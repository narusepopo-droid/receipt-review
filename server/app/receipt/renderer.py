"""
영수증 렌더러: 구조화된 영수증 데이터를 PNG 이미지로 변환

- 80mm 용지 = 576px, 58mm 용지 = 384px
- 고정폭 한글 폰트 사용
- ESC/POS 프린터 출력과 유사한 레이아웃 재현
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
import json
import unicodedata

from PIL import Image, ImageDraw, ImageFont, ImageOps

FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"
BUNDLED_FONT = FONT_DIR / "NanumGothicCoding-Regular.ttf"
BUNDLED_FONT_BOLD = FONT_DIR / "NanumGothicCoding-Bold.ttf"


class Alignment(Enum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


@dataclass
class TextStyle:
    bold: bool = False
    double_height: bool = False
    double_width: bool = False
    underline: bool = False


@dataclass
class ReceiptLine:
    """영수증 한 줄"""
    text: str
    alignment: Alignment = Alignment.LEFT
    style: TextStyle = field(default_factory=TextStyle)


@dataclass
class ReceiptData:
    """구조화된 영수증 데이터"""
    # 매장 정보
    store_name: str
    biz_no: Optional[str] = None  # 사업자번호
    owner_name: Optional[str] = None  # 대표자
    address: Optional[str] = None
    phone: Optional[str] = None

    # 거래 정보
    paid_at: Optional[str] = None  # 거래일시
    approval_no: Optional[str] = None  # 승인번호
    card_issuer: Optional[str] = None  # 카드사
    card_no: Optional[str] = None  # 카드번호 (마스킹)
    installment: Optional[str] = None  # 할부

    # 금액
    total_amount: int = 0
    vat: Optional[int] = None
    supply_amount: Optional[int] = None

    # 품목
    items: list = field(default_factory=list)  # [{"name": str, "qty": int, "price": int}]

    # 기타
    raw_lines: list = field(default_factory=list)  # ReceiptLine 목록 (직접 렌더링용)


class ReceiptRenderer:
    """영수증 PNG 렌더러"""

    # 기본 설정
    PAPER_WIDTH_80MM = 576  # 80mm 용지
    PAPER_WIDTH_58MM = 384  # 58mm 용지

    # 폰트 크기 (프린터 기본: 12x24 dot)
    FONT_SIZE_NORMAL = 24
    FONT_SIZE_DOUBLE = 48

    # 여백
    MARGIN_TOP = 20
    MARGIN_BOTTOM = 40
    MARGIN_SIDE = 16
    LINE_SPACING = 4

    def __init__(self, paper_width: int = PAPER_WIDTH_80MM, font_path: Optional[str] = None):
        self.paper_width = paper_width
        self.content_width = paper_width - (self.MARGIN_SIDE * 2)

        # 폰트 로드 (고정폭 한글 폰트)
        self.font_path = font_path
        self._load_fonts()

    def _load_fonts(self):
        """폰트 로드"""
        # 시스템 폰트 후보 (고정폭 우선)
        font_candidates = [
            self.font_path,
            str(BUNDLED_FONT),  # 저장소에 포함된 나눔고딕코딩 (서버에 한글 폰트가 없어도 동작)
            "D2Coding.ttf",
            "NanumGothicCoding.ttf",
            "NanumGothicCoding-Bold.ttf",
            "malgun.ttf",  # 맑은 고딕 (Windows)
            "NanumGothic.ttf",
            "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",  # Linux
        ]

        self.font_normal = None
        self.font_bold = None

        for font_name in font_candidates:
            if font_name is None:
                continue
            try:
                self.font_normal = ImageFont.truetype(font_name, self.FONT_SIZE_NORMAL)
                try:
                    # Bold 버전 시도
                    bold_name = font_name.replace(".ttf", "-Bold.ttf")
                    self.font_bold = ImageFont.truetype(bold_name, self.FONT_SIZE_NORMAL)
                except:
                    self.font_bold = self.font_normal
                break
            except:
                continue

        if self.font_normal is None:
            # 기본 폰트 사용 (한글 깨질 수 있음)
            self.font_normal = ImageFont.load_default()
            self.font_bold = self.font_normal

        # 2배 크기 폰트
        try:
            if self.font_path:
                self.font_double = ImageFont.truetype(self.font_path, self.FONT_SIZE_DOUBLE)
            else:
                for font_name in font_candidates:
                    if font_name is None:
                        continue
                    try:
                        self.font_double = ImageFont.truetype(font_name, self.FONT_SIZE_DOUBLE)
                        break
                    except:
                        continue
        except:
            self.font_double = self.font_normal

    def _get_font(self, style: TextStyle) -> ImageFont.FreeTypeFont:
        """스타일에 맞는 폰트 반환"""
        if style.double_height or style.double_width:
            return self.font_double
        if style.bold:
            return self.font_bold
        return self.font_normal

    def _get_text_width(self, text: str, font: ImageFont.FreeTypeFont) -> int:
        """텍스트 너비 계산"""
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0] if bbox else 0

    def _get_line_height(self, style: TextStyle) -> int:
        """줄 높이 계산"""
        if style.double_height:
            return self.FONT_SIZE_DOUBLE + self.LINE_SPACING
        return self.FONT_SIZE_NORMAL + self.LINE_SPACING

    def _draw_line(self, draw: ImageDraw.ImageDraw, y: int, line: ReceiptLine) -> int:
        """한 줄 그리기, 다음 y 위치 반환"""
        font = self._get_font(line.style)
        text_width = self._get_text_width(line.text, font)

        # 정렬에 따른 x 위치
        if line.alignment == Alignment.CENTER:
            x = self.MARGIN_SIDE + (self.content_width - text_width) // 2
        elif line.alignment == Alignment.RIGHT:
            x = self.MARGIN_SIDE + self.content_width - text_width
        else:
            x = self.MARGIN_SIDE

        # 텍스트 그리기
        draw.text((x, y), line.text, font=font, fill="black")

        # 밑줄
        if line.style.underline:
            line_y = y + self._get_line_height(line.style) - 4
            draw.line([(x, line_y), (x + text_width, line_y)], fill="black", width=1)

        return y + self._get_line_height(line.style)

    def _draw_separator(self, draw: ImageDraw.ImageDraw, y: int, char: str = "-") -> int:
        """구분선 그리기"""
        # 한 줄 가득 채우는 문자열
        font = self.font_normal
        char_width = self._get_text_width(char, font)
        if char_width > 0:
            count = self.content_width // char_width
            line = ReceiptLine(text=char * count, alignment=Alignment.CENTER)
            return self._draw_line(draw, y, line)
        return y

    def render_from_lines(self, lines: list[ReceiptLine]) -> Image.Image:
        """ReceiptLine 목록을 PNG로 렌더링"""
        # 높이 계산
        total_height = self.MARGIN_TOP + self.MARGIN_BOTTOM
        for line in lines:
            total_height += self._get_line_height(line.style)

        # 이미지 생성
        img = Image.new("RGB", (self.paper_width, total_height), "white")
        draw = ImageDraw.Draw(img)

        # 각 줄 그리기
        y = self.MARGIN_TOP
        for line in lines:
            y = self._draw_line(draw, y, line)

        return img

    def render_from_data(self, data: ReceiptData) -> Image.Image:
        """ReceiptData를 PNG로 렌더링 (실제 영수증 형태)"""
        width = self.paper_width
        line_height = 22
        padding = 20

        # 컬럼 위치 (픽셀)
        COL_NAME = 20
        COL_PRICE = int(width * 0.45)
        COL_QTY = int(width * 0.66)
        COL_TOTAL = width - 20

        # 높이 계산 (대략)
        height = 700
        img = Image.new("RGB", (width, height), "#FAFAFA")
        draw = ImageDraw.Draw(img)

        y = padding

        # [ 영 수 증 ] 타이틀
        draw.text((width // 2, y), "[ 영 수 증 ]", font=self.font_bold, fill="black", anchor="mm")
        y += line_height * 2

        # 매장명
        draw.text((width // 2, y), data.store_name, font=self.font_bold, fill="black", anchor="mm")
        y += line_height

        # 사업자 정보
        if data.biz_no:
            biz_line = f"사업자번호 : {data.biz_no}"
            if data.phone:
                biz_line = f"{data.biz_no} TEL: {data.phone}"
            draw.text((COL_NAME, y), biz_line, font=self.font_normal, fill="black")
            y += line_height

        if data.owner_name:
            draw.text((COL_NAME, y), f"대표자: {data.owner_name}", font=self.font_normal, fill="black")
            y += line_height

        if data.address:
            draw.text((COL_NAME, y), data.address, font=self.font_normal, fill="black")
            y += line_height

        y += line_height

        # 거래일시
        if data.paid_at:
            draw.text((COL_NAME, y), f"판매시간: {data.paid_at}", font=self.font_normal, fill="black")
            y += line_height

        y += 5
        draw.line([(COL_NAME, y), (width - COL_NAME, y)], fill="black", width=1)
        y += 10

        # 품목 헤더
        draw.text((COL_NAME, y), "상품", font=self.font_normal, fill="black")
        draw.text((COL_PRICE, y), "단가", font=self.font_normal, fill="black", anchor="rm")
        draw.text((COL_QTY, y), "수량", font=self.font_normal, fill="black", anchor="rm")
        draw.text((COL_TOTAL, y), "금액", font=self.font_normal, fill="black", anchor="rm")
        y += line_height

        draw.line([(COL_NAME, y), (width - COL_NAME, y)], fill="black", width=1)
        y += 10

        # 품목들
        for item in data.items:
            name = item.get("name", "")
            qty = item.get("qty", 1)
            price = item.get("price", 0)
            total = price  # qty가 이미 반영된 금액일 수 있음

            draw.text((COL_NAME, y), name, font=self.font_normal, fill="black")
            draw.text((COL_PRICE, y), f"{price:,}", font=self.font_normal, fill="black", anchor="rm")
            draw.text((COL_QTY, y), str(qty), font=self.font_normal, fill="black", anchor="rm")
            draw.text((COL_TOTAL, y), f"{total:,}", font=self.font_normal, fill="black", anchor="rm")
            y += line_height

        y += 5
        draw.line([(COL_NAME, y), (width - COL_NAME, y)], fill="black", width=1)
        y += 15

        # 합계
        draw.text((COL_NAME, y), "합    계::", font=self.font_bold, fill="black")
        draw.text((COL_TOTAL, y), f"{data.total_amount:,}", font=self.font_bold, fill="black", anchor="rm")
        y += line_height + 3

        draw.text((COL_NAME, y), "받은금액::", font=self.font_bold, fill="black")
        draw.text((COL_TOTAL, y), f"{data.total_amount:,}", font=self.font_bold, fill="black", anchor="rm")
        y += line_height + 3

        # 카드 정보
        if data.card_issuer:
            draw.text((COL_NAME, y), f"카드: {data.card_issuer}", font=self.font_normal, fill="black")
            y += line_height

        if data.card_no:
            draw.text((COL_NAME, y), f"카드번호: {data.card_no}", font=self.font_normal, fill="black")
            y += line_height

        if data.approval_no:
            draw.text((COL_NAME, y), f"승인번호: {data.approval_no}", font=self.font_bold, fill="black")
            y += line_height

        y += line_height

        # 발행일시
        if data.paid_at:
            draw.text((width // 2, y), f"발행일시 : {data.paid_at}", font=self.font_normal, fill="black", anchor="mm")

        # 이미지 크롭
        img = img.crop((0, 0, width, y + padding + 10))
        return img

    def render_from_json(self, json_path: str) -> Image.Image:
        """JSON 파일에서 영수증 렌더링"""
        with open(json_path, "r", encoding="utf-8") as f:
            data_dict = json.load(f)

        # JSON 형식에 따라 처리
        if "lines" in data_dict:
            # 직접 lines 지정
            lines = []
            for line_data in data_dict["lines"]:
                style = TextStyle(**line_data.get("style", {}))
                alignment = Alignment(line_data.get("alignment", "left"))
                lines.append(ReceiptLine(
                    text=line_data.get("text", ""),
                    alignment=alignment,
                    style=style
                ))
            return self.render_from_lines(lines)
        else:
            # ReceiptData 형식
            data = ReceiptData(
                store_name=data_dict.get("store_name", ""),
                biz_no=data_dict.get("biz_no"),
                owner_name=data_dict.get("owner_name"),
                address=data_dict.get("address"),
                phone=data_dict.get("phone"),
                paid_at=data_dict.get("paid_at"),
                approval_no=data_dict.get("approval_no"),
                card_issuer=data_dict.get("card_issuer"),
                card_no=data_dict.get("card_no"),
                installment=data_dict.get("installment"),
                total_amount=data_dict.get("total_amount", 0),
                vat=data_dict.get("vat"),
                supply_amount=data_dict.get("supply_amount"),
                items=data_dict.get("items", [])
            )
            return self.render_from_data(data)

    def save(self, image: Image.Image, output_path: str):
        """이미지 저장"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, "PNG")


class EscPosRenderer:
    """
    ESC/POS 파싱 결과(줄 목록)를 원래 프린터 출력 모양 그대로 그린다.
    - 글자 칸(셀) 단위로 배치: 영문·숫자 1칸, 한글 2칸 → 공백으로 맞춘 열 정렬이 그대로 유지됨
    - 정렬, 굵게, 밑줄, 가로/세로 2배, 로고(래스터 이미지), QR 위치까지 재현
    """

    CELL_W = 12          # 프린터 Font A: 12x24 dot
    CELL_H = 24
    LINE_GAP = 6
    MARGIN_X = 8
    MARGIN_TOP = 24
    MARGIN_BOTTOM = 32

    def __init__(self, paper_width: int = 576):
        self.paper_width = paper_width
        self._fonts: dict = {}

    def _font(self, size: int, bold: bool):
        key = (size, bold)
        if key not in self._fonts:
            path = BUNDLED_FONT_BOLD if bold else BUNDLED_FONT
            try:
                self._fonts[key] = ImageFont.truetype(str(path), size)
            except OSError:
                self._fonts[key] = ImageFont.load_default()
        return self._fonts[key]

    @staticmethod
    def _is_wide(ch: str) -> bool:
        return unicodedata.east_asian_width(ch) in ("W", "F")

    def _cols(self, text: str) -> int:
        return sum(2 if self._is_wide(c) else 1 for c in text)

    def render(self, lines: list) -> Image.Image:
        inner = self.paper_width - self.MARGIN_X * 2

        # 셀 폭: 가장 긴 줄이 용지에 들어가도록 (최대 12px)
        # (2배 폭 줄은 프린터에서도 넘치면 줄바꿈되므로 기준에서 제외)
        text_lines = [ln for ln in lines
                      if getattr(ln, "image", None) is None and not getattr(ln, "qr", None)]
        normal = [ln for ln in text_lines if not ln.style.double_width] or text_lines
        max_cols = max([self._cols(ln.text.rstrip()) for ln in normal] + [32])
        cell_w = min(self.CELL_W, max(6, inner // max_cols))
        cell_h = cell_w * 2

        blocks = []
        for ln in lines:
            if getattr(ln, "image", None) is not None:
                blocks.append((self._raster(ln.image, inner), ln.style.alignment))
            elif getattr(ln, "qr", None):
                blocks.append((self._qr(ln.qr, ln.qr_module), ln.style.alignment))
            else:
                for part in self._wrap(ln, max_cols):
                    blocks.append((self._text(part, cell_w, cell_h), ln.style.alignment))

        height = self.MARGIN_TOP + self.MARGIN_BOTTOM + sum(b.height for b, _ in blocks)
        img = Image.new("RGB", (self.paper_width, height), "white")
        y = self.MARGIN_TOP
        for block, align in blocks:
            a = int(align)
            if a == 1:
                x = self.MARGIN_X + (inner - block.width) // 2
            elif a == 2:
                x = self.MARGIN_X + inner - block.width
            else:
                x = self.MARGIN_X
            img.paste(block, (max(0, x), y))
            y += block.height
        return img

    def _wrap(self, ln, max_cols: int) -> list:
        """한 줄이 용지 폭을 넘으면 프린터처럼 다음 줄로 넘긴다"""
        scale = 2 if ln.style.double_width else 1
        text = ln.text.rstrip()
        if self._cols(text) * scale <= max_cols:
            return [ln]
        parts, cur, used = [], "", 0
        for ch in text:
            w = (2 if self._is_wide(ch) else 1) * scale
            if used + w > max_cols:
                parts.append(cur)
                cur, used = "", 0
            cur += ch
            used += w
        parts.append(cur)
        from dataclasses import replace as _replace
        return [_replace(ln, text=p) for p in parts]

    def _text(self, ln, cell_w: int, cell_h: int) -> Image.Image:
        text = ln.text.rstrip()
        st = ln.style
        sx = 2 if st.double_width else 1
        sy = 2 if st.double_height else 1
        # 가로·세로 같은 배율은 큰 글꼴로 직접 그려 선명하게 (OCR 인식률)
        k = min(sx, sy)
        cw, ch = cell_w * k, cell_h * k
        cols = max(1, self._cols(text))
        base = Image.new("L", (cols * cw, ch), 255)
        if text.strip():
            draw = ImageDraw.Draw(base)
            font = self._font(ch - 2 * k, st.bold)
            x = 0
            for c in text:
                w = cw * (2 if self._is_wide(c) else 1)
                if c != " ":
                    draw.text((x + w / 2, ch / 2), c, font=font, fill=0, anchor="mm")
                x += w
            if st.underline:
                draw.line([(0, ch - 1), (x, ch - 1)], fill=0, width=2 * k)

        # 한쪽만 2배인 경우 부드럽게 늘림
        if sx != k or sy != k:
            base = base.resize((base.width * sx // k, base.height * sy // k), Image.BICUBIC)

        out = Image.new("L", (base.width, base.height + self.LINE_GAP), 255)
        out.paste(base, (0, 0))
        return out.convert("RGB")

    def _raster(self, image_data, max_width: int) -> Image.Image:
        bmp = Image.frombytes("1", (image_data.width, image_data.height), bytes(image_data.data))
        bmp = ImageOps.invert(bmp.convert("L"))  # ESC/POS 는 1=검정, PIL 은 1=흰색
        if bmp.width > max_width:
            ratio = max_width / bmp.width
            bmp = bmp.resize((max_width, max(1, int(bmp.height * ratio))))
        out = Image.new("L", (bmp.width, bmp.height + self.LINE_GAP), 255)
        out.paste(bmp, (0, 0))
        return out.convert("RGB")

    def _qr(self, data: str, module: int) -> Image.Image:
        import qrcode
        qr = qrcode.QRCode(box_size=max(2, module), border=1)
        qr.add_data(data)
        qr.make(fit=True)
        q = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        out = Image.new("RGB", (q.width, q.height + self.LINE_GAP), "white")
        out.paste(q, (0, 0))
        return out


def render_receipt(parsed_data, output_path: str, paper_width: int = 576):
    """
    파싱된 영수증 데이터를 PNG로 렌더링하는 헬퍼 함수

    Args:
        parsed_data: ParsedReceipt 객체
        output_path: 저장할 파일 경로
        paper_width: 용지 폭 (576=80mm, 384=58mm)
    """
    # 실제 포스 원본(줄 목록)이 있으면 원래 모양 그대로 그린다
    lines = getattr(parsed_data, "lines", None) or []
    if any(getattr(l, "text", "").strip() for l in lines):
        image = EscPosRenderer(paper_width).render(lines)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path, "PNG")
        return

    renderer = ReceiptRenderer(paper_width=paper_width)

    # ParsedReceipt -> ReceiptData 변환 (줄 정보가 없는 경우의 대체 양식)
    data = ReceiptData(
        store_name=parsed_data.store_name or "매장명",
        biz_no=parsed_data.biz_no,
        owner_name=getattr(parsed_data, "owner_name", None),
        address=getattr(parsed_data, "address", None),
        phone=getattr(parsed_data, "phone", None),
        paid_at=parsed_data.paid_at,
        approval_no=parsed_data.approval_no,
        card_issuer=parsed_data.card_issuer,
        card_no=getattr(parsed_data, "card_no", None),
        installment=getattr(parsed_data, "installment", None),
        total_amount=parsed_data.amount or 0,
        vat=getattr(parsed_data, "vat", None),
        supply_amount=getattr(parsed_data, "supply_amount", None),
        items=parsed_data.items or []
    )

    image = renderer.render_from_data(data)
    renderer.save(image, output_path)

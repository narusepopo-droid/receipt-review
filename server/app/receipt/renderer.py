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

from PIL import Image, ImageDraw, ImageFont


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
        """ReceiptData를 PNG로 렌더링"""
        lines = []

        # 매장명 (크게, 중앙)
        lines.append(ReceiptLine(
            text=data.store_name,
            alignment=Alignment.CENTER,
            style=TextStyle(bold=True, double_height=True, double_width=True)
        ))
        lines.append(ReceiptLine(text=""))  # 빈 줄

        # 사업자 정보
        if data.biz_no:
            lines.append(ReceiptLine(
                text=f"사업자번호: {data.biz_no}",
                alignment=Alignment.CENTER
            ))
        if data.owner_name:
            lines.append(ReceiptLine(
                text=f"대표자: {data.owner_name}",
                alignment=Alignment.CENTER
            ))
        if data.address:
            lines.append(ReceiptLine(
                text=data.address,
                alignment=Alignment.CENTER
            ))
        if data.phone:
            lines.append(ReceiptLine(
                text=f"TEL: {data.phone}",
                alignment=Alignment.CENTER
            ))

        lines.append(ReceiptLine(text=""))
        lines.append(ReceiptLine(text="-" * 48, alignment=Alignment.CENTER))

        # 품목
        if data.items:
            lines.append(ReceiptLine(
                text="품목명              수량      금액",
                alignment=Alignment.LEFT,
                style=TextStyle(bold=True)
            ))
            lines.append(ReceiptLine(text="-" * 48, alignment=Alignment.CENTER))

            for item in data.items:
                name = item.get("name", "")[:16].ljust(16)
                qty = str(item.get("qty", 1)).rjust(4)
                price = f"{item.get('price', 0):,}".rjust(10)
                lines.append(ReceiptLine(text=f"{name}  {qty}  {price}"))

        lines.append(ReceiptLine(text="-" * 48, alignment=Alignment.CENTER))

        # 금액
        if data.supply_amount is not None:
            lines.append(ReceiptLine(
                text=f"공급가액:                {data.supply_amount:>12,}원",
                alignment=Alignment.LEFT
            ))
        if data.vat is not None:
            lines.append(ReceiptLine(
                text=f"부가세:                  {data.vat:>12,}원",
                alignment=Alignment.LEFT
            ))

        lines.append(ReceiptLine(
            text=f"합    계:                {data.total_amount:>12,}원",
            alignment=Alignment.LEFT,
            style=TextStyle(bold=True)
        ))

        lines.append(ReceiptLine(text="=" * 48, alignment=Alignment.CENTER))

        # 결제 정보
        if data.card_issuer:
            lines.append(ReceiptLine(text=f"카드사: {data.card_issuer}"))
        if data.card_no:
            lines.append(ReceiptLine(text=f"카드번호: {data.card_no}"))
        if data.installment:
            lines.append(ReceiptLine(text=f"할부: {data.installment}"))
        if data.approval_no:
            lines.append(ReceiptLine(
                text=f"승인번호: {data.approval_no}",
                style=TextStyle(bold=True)
            ))
        if data.paid_at:
            lines.append(ReceiptLine(text=f"거래일시: {data.paid_at}"))

        lines.append(ReceiptLine(text=""))
        lines.append(ReceiptLine(text="-" * 48, alignment=Alignment.CENTER))
        lines.append(ReceiptLine(text=""))
        lines.append(ReceiptLine(
            text="감사합니다",
            alignment=Alignment.CENTER,
            style=TextStyle(bold=True)
        ))
        lines.append(ReceiptLine(text=""))

        return self.render_from_lines(lines)

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

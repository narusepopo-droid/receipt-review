"""ESC/POS 명령어 파서 - 원본 바이트를 구조화된 데이터로 변환"""
import re
import struct
import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

logger = logging.getLogger(__name__)


class Alignment(IntEnum):
    LEFT = 0
    CENTER = 1
    RIGHT = 2


@dataclass
class TextStyle:
    bold: bool = False
    underline: bool = False
    double_width: bool = False
    double_height: bool = False
    alignment: Alignment = Alignment.LEFT

    def copy(self) -> "TextStyle":
        return TextStyle(
            bold=self.bold,
            underline=self.underline,
            double_width=self.double_width,
            double_height=self.double_height,
            alignment=self.alignment,
        )


@dataclass
class TextLine:
    text: str
    style: TextStyle
    # 텍스트 대신 그림 요소인 경우 (원래 위치 그대로 렌더링하기 위함)
    image: Optional["ImageData"] = None
    qr: Optional[str] = None
    qr_module: int = 6


@dataclass
class ImageData:
    width: int
    height: int
    data: bytes


@dataclass
class ParsedReceipt:
    lines: list[TextLine] = field(default_factory=list)
    images: list[ImageData] = field(default_factory=list)
    raw_text: str = ""

    store_name: Optional[str] = None
    biz_no: Optional[str] = None
    owner_name: Optional[str] = None
    address: Optional[str] = None
    phone: Optional[str] = None

    approval_no: Optional[str] = None
    card_issuer: Optional[str] = None
    paid_at: Optional[str] = None
    amount: Optional[int] = None
    vat: Optional[int] = None

    items: list[dict] = field(default_factory=list)
    table_no: Optional[str] = None


class ESCPOSParser:
    ESC = 0x1B
    GS = 0x1D
    FS = 0x1C
    LF = 0x0A
    CR = 0x0D

    def __init__(self):
        self.style = TextStyle()
        self.current_line = ""
        self.lines: list[TextLine] = []
        self.images: list[ImageData] = []
        self.korean_mode = True
        self._qr_data = ""
        self._qr_module = 6

    def parse(self, data: bytes) -> ParsedReceipt:
        self.style = TextStyle()
        self.current_line = ""
        self.lines = []
        self.images = []
        self._qr_data = ""
        self._qr_module = 6

        i = 0
        while i < len(data):
            byte = data[i]

            if byte == self.ESC:
                i = self._handle_esc(data, i)
            elif byte == self.GS:
                i = self._handle_gs(data, i)
            elif byte == self.FS:
                i = self._handle_fs(data, i)
            elif byte == self.LF:
                self._flush_line(keep_empty=True)
                i += 1
            elif byte == 0x10 and i + 1 < len(data) and data[i + 1] in (0x04, 0x05):
                i += 3  # DLE EOT/ENQ n (상태 조회)
            elif byte == 0x10 and i + 1 < len(data) and data[i + 1] == 0x14:
                i += 5  # DLE DC4 fn m t (실시간 명령)
            elif byte == self.CR:
                i += 1
            else:
                i = self._handle_text(data, i)

        self._flush_line()

        # 맨 끝 빈 줄 정리
        while self.lines and not self.lines[-1].text.strip() and not self.lines[-1].image and not self.lines[-1].qr:
            self.lines.pop()

        result = ParsedReceipt(
            lines=self.lines,
            images=self.images,
            raw_text="\n".join(line.text for line in self.lines if not line.image and not line.qr),
        )

        self._extract_fields(result)
        return result

    # 인자 개수가 고정인 명령 (명령 문자 → 인자 바이트 수)
    ESC_ARGS = {
        "@": 0, "2": 0, "<": 0, "L": 0, "S": 0, "i": 0, "m": 0,
        "!": 1, "E": 1, "a": 1, "-": 1, "d": 1, "J": 1, "t": 1, "3": 1, "M": 1,
        "G": 1, "R": 1, " ": 1, "{": 1, "V": 1, "r": 1, "U": 1, "e": 1, "K": 1,
        "=": 1, "T": 1, "$": 2, "B": 2, "\\": 2, "c": 2, "p": 3, "W": 8,
    }
    GS_ARGS = {
        ":": 0,
        "!": 1, "B": 1, "H": 1, "h": 1, "w": 1, "f": 1, "a": 1, "r": 1, "I": 1,
        "/": 1, "b": 1, "E": 1, "T": 1, "C": 1, "x": 1,
        "L": 2, "W": 2, "P": 2, "$": 2, "\\": 2, "^": 3,
    }
    FS_ARGS = {"&": 0, ".": 0, "!": 1, "-": 1, "C": 1, "W": 1, "p": 2, "S": 2, "?": 2}

    def _handle_esc(self, data: bytes, i: int) -> int:
        if i + 1 >= len(data):
            return i + 1

        cmd = chr(data[i + 1])
        arg = data[i + 2] if i + 2 < len(data) else 0

        if cmd == "@":
            self._flush_line()
            self.style = TextStyle()
        elif cmd == "!":
            self.style.bold = bool(arg & 0x08)
            self.style.double_height = bool(arg & 0x10)
            self.style.double_width = bool(arg & 0x20)
            self.style.underline = bool(arg & 0x80)
        elif cmd in ("E", "G"):
            self.style.bold = bool(arg & 0x01)
        elif cmd == "a":
            n = arg - 48 if arg >= 48 else arg
            self.style.alignment = Alignment(n if n in (0, 1, 2) else 0)
        elif cmd == "-":
            self.style.underline = (arg % 48) > 0
        elif cmd == "d":
            # n줄 이송: 현재 줄 마감 후 빈 줄 (n-1)개
            self._flush_line(keep_empty=True)
            for _ in range(max(0, min(arg, 10) - 1)):
                self._flush_line(keep_empty=True)
        elif cmd == "*":
            # 비트 이미지: ESC * m nL nH d1...dk (그림 복원은 생략, 데이터만 건너뜀)
            n = (data[i + 3] if i + 3 < len(data) else 0) + ((data[i + 4] if i + 4 < len(data) else 0) << 8)
            k = n * 3 if arg in (32, 33) else n
            return i + 5 + k
        elif cmd == "D":
            # 탭 위치: NUL 로 끝남
            j = i + 2
            while j < len(data) and data[j] != 0:
                j += 1
            return j + 1

        if cmd in self.ESC_ARGS:
            return i + 2 + self.ESC_ARGS[cmd]
        logger.debug("unsupported ESC %r", cmd)
        return i + 2

    def _handle_gs(self, data: bytes, i: int) -> int:
        if i + 1 >= len(data):
            return i + 1

        cmd = chr(data[i + 1])
        arg = data[i + 2] if i + 2 < len(data) else 0

        if cmd == "!":
            # 상위 4비트 = 가로 배율, 하위 4비트 = 세로 배율
            self.style.double_width = ((arg >> 4) & 0x0F) > 0
            self.style.double_height = (arg & 0x0F) > 0
            return i + 3
        elif cmd == "B":
            # 흑백 반전 → 굵게로 근사
            self.style.bold = self.style.bold or bool(arg & 0x01)
            return i + 3
        elif cmd == "V":
            self._flush_line()
            return i + (4 if arg in (65, 66, 97, 98, 103, 104) else 3)
        elif cmd == "v":
            return self._handle_raster_image(data, i)
        elif cmd == "(":
            return self._handle_gs_paren(data, i)
        elif cmd == "k":
            return self._handle_barcode(data, i)
        elif cmd == "*":
            # 다운로드 비트 이미지 정의: GS * x y d1...d(x*y*8)
            y = data[i + 3] if i + 3 < len(data) else 0
            return i + 4 + arg * y * 8
        elif cmd == "8":
            # GS 8 L p1 p2 p3 p4 ...: 큰 그래픽 데이터
            if i + 6 < len(data):
                ln = data[i + 3] | (data[i + 4] << 8) | (data[i + 5] << 16) | (data[i + 6] << 24)
                return i + 7 + ln
            return len(data)

        if cmd in self.GS_ARGS:
            return i + 2 + self.GS_ARGS[cmd]
        logger.debug("unsupported GS %r", cmd)
        return i + 2

    def _handle_fs(self, data: bytes, i: int) -> int:
        if i + 1 >= len(data):
            return i + 1

        cmd = chr(data[i + 1])

        if cmd == "&":
            self.korean_mode = True
        elif cmd == ".":
            self.korean_mode = False
        elif cmd == "!":
            arg = data[i + 2] if i + 2 < len(data) else 0
            # 한글 문자 모드: 0x04 가로 2배, 0x08 세로 2배
            if arg & 0x04:
                self.style.double_width = True
            if arg & 0x08:
                self.style.double_height = True

        if cmd in self.FS_ARGS:
            return i + 2 + self.FS_ARGS[cmd]
        return i + 3

    def _handle_raster_image(self, data: bytes, i: int) -> int:
        # GS v 0 m xL xH yL yH d1...dk
        if i + 7 >= len(data):
            return len(data)

        try:
            width_bytes = data[i + 4] + (data[i + 5] << 8)
            height = data[i + 6] + (data[i + 7] << 8)
            img_start = i + 8
            img_end = img_start + width_bytes * height

            if img_end <= len(data) and width_bytes > 0 and height > 0:
                img = ImageData(width=width_bytes * 8, height=height, data=data[img_start:img_end])
                self.images.append(img)
                self._flush_line()
                self.lines.append(TextLine(text="", style=self.style.copy(), image=img))

            return img_end
        except Exception as e:
            logger.warning(f"Raster image parsing error: {e}")
            return i + 2

    def _handle_gs_paren(self, data: bytes, i: int) -> int:
        # GS ( fn pL pH [params]
        if i + 4 >= len(data):
            return len(data)

        fn = chr(data[i + 2])
        param_len = data[i + 3] + (data[i + 4] << 8)
        params = data[i + 5:i + 5 + param_len]

        # QR 코드: GS ( k pL pH cn=49 fn ...
        if fn == "k" and len(params) >= 2 and params[0] == 49:
            sub = params[1]
            if sub == 67 and len(params) >= 3:          # 모듈 크기
                self._qr_module = max(1, min(params[2], 16))
            elif sub == 80 and len(params) >= 3:        # 데이터 저장 (params[2] = m)
                self._qr_data = params[3:].decode("cp949", errors="replace")
            elif sub == 81 and self._qr_data:           # 인쇄
                self._flush_line()
                self.lines.append(TextLine(text="", style=self.style.copy(),
                                           qr=self._qr_data, qr_module=self._qr_module))

        return i + 5 + param_len

    def _handle_barcode(self, data: bytes, i: int) -> int:
        if i + 2 >= len(data):
            return i + 2

        m = data[i + 2]

        if m <= 6:
            end = i + 3
            while end < len(data) and data[end] != 0x00:
                end += 1
            return end + 1
        else:
            if i + 3 < len(data):
                n = data[i + 3]
                return i + 4 + n
            return i + 3

    def _handle_text(self, data: bytes, i: int) -> int:
        byte = data[i]

        if byte < 0x20 and byte not in (self.LF, self.CR):
            return i + 1

        if self.korean_mode and byte >= 0x80:
            if i + 1 < len(data):
                try:
                    char = data[i:i+2].decode("cp949", errors="replace")
                    self.current_line += char
                    return i + 2
                except:
                    return i + 1
            return i + 1
        else:
            try:
                char = chr(byte)
                self.current_line += char
            except:
                pass
            return i + 1

    def _flush_line(self, keep_empty: bool = False):
        if self.current_line or keep_empty:
            self.lines.append(TextLine(
                text=self.current_line,
                style=self.style.copy()
            ))
        self.current_line = ""

    def _extract_fields(self, result: ParsedReceipt):
        text = result.raw_text

        biz_match = re.search(r"(\d{3})-?(\d{2})-?(\d{5})", text)
        if biz_match:
            result.biz_no = f"{biz_match.group(1)}-{biz_match.group(2)}-{biz_match.group(3)}"

        approval_match = re.search(r"승인번호[:\s]*(\d{6,12})", text)
        if approval_match:
            result.approval_no = approval_match.group(1)

        datetime_match = re.search(
            r"(\d{4}[-/.]\d{2}[-/.]\d{2}\s+\d{2}:\d{2}:\d{2})",
            text
        )
        if datetime_match:
            result.paid_at = datetime_match.group(1)

        amount_patterns = [
            r"(?:받을|결제|승인)\s*금\s*액[:\s]*(-?[0-9][0-9,]*)\s*원?",
            r"합\s*계(?:\s*금\s*액)?[:\s]*(-?[0-9][0-9,]*)\s*원?",
            r"총\s*(?:금\s*액|합\s*계)[:\s]*(-?[0-9][0-9,]*)\s*원?",
        ]
        for pattern in amount_patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    result.amount = int(match.group(1).replace(",", ""))
                except ValueError:
                    continue
                break

        card_patterns = [
            r"(신한|삼성|현대|롯데|국민|하나|우리|농협|기업|BC|비씨|NH)카드?",
            r"카드사[:\s]*([\w]+)",
        ]
        for pattern in card_patterns:
            match = re.search(pattern, text)
            if match:
                result.card_issuer = match.group(1)
                break

        vat_match = re.search(r"부가세[:\s]*([0-9,]+)", text)
        if vat_match:
            result.vat = int(vat_match.group(1).replace(",", ""))

        table_match = re.search(r"테이블[:\s#]*(\d+)", text)
        if table_match:
            result.table_no = table_match.group(1)


def parse_escpos(data: bytes) -> ParsedReceipt:
    parser = ESCPOSParser()
    return parser.parse(data)

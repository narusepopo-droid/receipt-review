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

    def parse(self, data: bytes) -> ParsedReceipt:
        self.style = TextStyle()
        self.current_line = ""
        self.lines = []
        self.images = []

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
                self._flush_line()
                i += 1
            elif byte == self.CR:
                i += 1
            else:
                i = self._handle_text(data, i)

        self._flush_line()

        result = ParsedReceipt(
            lines=self.lines,
            images=self.images,
            raw_text="\n".join(line.text for line in self.lines),
        )

        self._extract_fields(result)
        return result

    def _handle_esc(self, data: bytes, i: int) -> int:
        if i + 1 >= len(data):
            return i + 1

        cmd = data[i + 1]

        if cmd == ord("@"):
            self.style = TextStyle()
            return i + 2

        elif cmd == ord("!"):
            if i + 2 < len(data):
                n = data[i + 2]
                self.style.bold = bool(n & 0x08)
                self.style.double_height = bool(n & 0x10)
                self.style.double_width = bool(n & 0x20)
                return i + 3
            return i + 2

        elif cmd == ord("E"):
            if i + 2 < len(data):
                self.style.bold = bool(data[i + 2])
                return i + 3
            return i + 2

        elif cmd == ord("a"):
            if i + 2 < len(data):
                n = data[i + 2]
                self.style.alignment = Alignment(min(n, 2))
                return i + 3
            return i + 2

        elif cmd == ord("-"):
            if i + 2 < len(data):
                self.style.underline = bool(data[i + 2])
                return i + 3
            return i + 2

        elif cmd == ord("d"):
            if i + 2 < len(data):
                n = data[i + 2]
                for _ in range(n):
                    self._flush_line()
                return i + 3
            return i + 2

        elif cmd == ord("J"):
            if i + 2 < len(data):
                return i + 3
            return i + 2

        elif cmd == ord("t"):
            if i + 2 < len(data):
                return i + 3
            return i + 2

        return i + 2

    def _handle_gs(self, data: bytes, i: int) -> int:
        if i + 1 >= len(data):
            return i + 1

        cmd = data[i + 1]

        if cmd == ord("!"):
            if i + 2 < len(data):
                n = data[i + 2]
                self.style.double_width = bool(n & 0x10)
                self.style.double_height = bool(n & 0x01)
                return i + 3
            return i + 2

        elif cmd == ord("V"):
            if i + 2 < len(data):
                return i + 3
            return i + 2

        elif cmd == ord("v"):
            return self._handle_raster_image(data, i)

        elif cmd == ord("("):
            return self._handle_gs_paren(data, i)

        elif cmd == ord("k"):
            return self._handle_barcode(data, i)

        return i + 2

    def _handle_fs(self, data: bytes, i: int) -> int:
        if i + 1 >= len(data):
            return i + 1

        cmd = data[i + 1]

        if cmd == ord("&"):
            self.korean_mode = True
            return i + 2
        elif cmd == ord("."):
            self.korean_mode = False
            return i + 2

        return i + 2

    def _handle_raster_image(self, data: bytes, i: int) -> int:
        if i + 7 >= len(data):
            return i + 2

        try:
            m = data[i + 2]
            xL = data[i + 3]
            xH = data[i + 4]
            yL = data[i + 5]
            yH = data[i + 6]

            width_bytes = xL + (xH << 8)
            height = yL + (yH << 8)
            width = width_bytes * 8

            data_len = width_bytes * height
            img_start = i + 7
            img_end = img_start + data_len

            if img_end <= len(data):
                self.images.append(ImageData(
                    width=width,
                    height=height,
                    data=data[img_start:img_end]
                ))

            return img_end
        except Exception as e:
            logger.warning(f"Raster image parsing error: {e}")
            return i + 2

    def _handle_gs_paren(self, data: bytes, i: int) -> int:
        if i + 3 >= len(data):
            return i + 2

        fn = data[i + 2]
        pL = data[i + 3]
        pH = data[i + 4] if i + 4 < len(data) else 0
        param_len = pL + (pH << 8)

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

    def _flush_line(self):
        if self.current_line:
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
            r"합\s*계[:\s]*([0-9,]+)\s*원?",
            r"총\s*금\s*액[:\s]*([0-9,]+)\s*원?",
            r"결제금액[:\s]*([0-9,]+)\s*원?",
        ]
        for pattern in amount_patterns:
            match = re.search(pattern, text)
            if match:
                result.amount = int(match.group(1).replace(",", ""))
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

"""개인정보 마스킹 - 전화번호, 회원명, 카드번호 등"""
import re
from typing import Callable

from .escpos_parser import ParsedReceipt, TextLine


PHONE_PATTERNS = [
    r"01[016789][-\s]?\d{3,4}[-\s]?\d{4}",
    r"01[016789][-\s]?\d{3,4}[-\s]?\*{1,4}",
    r"01[016789][-\s]?\*{1,4}[-\s]?\d{4}",
    r"\*{2,4}[-\s]?\d{3,4}[-\s]?\d{4}",
]

MEMBER_LINE_PATTERNS = [
    r"회원\s*(번호|명|이름|ID)?[:\s]",
    r"고객\s*(번호|명|이름)?[:\s]",
    r"포인트\s*(적립|사용|잔액)",
    r"멤버십",
    r"적립\s*(금액|포인트)",
]

CARD_FULL_PATTERN = r"(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})[-\s]?(\d{4})"
CARD_PARTIAL_PATTERN = r"(\d{4})[-\s]?(\d{2})\*{2}[-\s]?\*{4}[-\s]?(\d{4})"
CARD_EXPOSED_PATTERN = r"\d{5,16}"


def mask_phone_numbers(text: str) -> str:
    result = text
    for pattern in PHONE_PATTERNS:
        result = re.sub(pattern, "***-****-****", result)
    return result


def mask_member_lines(text: str) -> str:
    lines = text.split("\n")
    masked_lines = []

    for line in lines:
        should_mask = False
        for pattern in MEMBER_LINE_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                should_mask = True
                break

        if should_mask:
            masked_line = re.sub(
                r"[가-힣]{2,5}(?=\s*(님|고객|회원|\s|$))",
                "***",
                line
            )
            masked_line = re.sub(r"\d{4,}", "****", masked_line)
            masked_lines.append(masked_line)
        else:
            masked_lines.append(line)

    return "\n".join(masked_lines)


def mask_card_numbers(text: str) -> str:
    result = re.sub(
        CARD_FULL_PATTERN,
        r"\1-**\*\*-****-\4",
        text
    )

    def check_exposed(match):
        num = match.group(0)
        if len(num) > 4:
            return num[:4] + "*" * (len(num) - 4)
        return num

    card_line_pattern = r"카드(번호)?[:\s]*(\d{5,})"
    result = re.sub(
        card_line_pattern,
        lambda m: m.group(0)[:6] + "*" * (len(m.group(2)) - 4) + m.group(2)[-4:] if len(m.group(2)) > 8 else m.group(0),
        result
    )

    return result


def mask_receipt_text(text: str) -> str:
    result = mask_phone_numbers(text)
    result = mask_member_lines(result)
    result = mask_card_numbers(result)
    return result


def mask_parsed_receipt(parsed: ParsedReceipt) -> ParsedReceipt:
    masked_lines = []
    for line in parsed.lines:
        masked_text = mask_receipt_text(line.text)
        masked_lines.append(TextLine(
            text=masked_text,
            style=line.style
        ))

    parsed.lines = masked_lines
    parsed.raw_text = mask_receipt_text(parsed.raw_text)

    return parsed


def create_safe_display_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) >= 10:
        return f"{digits[:3]}-****-{digits[-4:]}"
    return "***-****-****"

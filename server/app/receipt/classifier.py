"""영수증 분류기 - 정상/취소/주방/재출력/현금 판별"""
import re
from enum import Enum
from dataclasses import dataclass
from typing import Optional

from .escpos_parser import ParsedReceipt


class ReceiptType(str, Enum):
    NORMAL = "normal"
    CANCELLED = "cancelled"
    KITCHEN = "kitchen"
    REPRINT = "reprint"
    CASH = "cash"
    UNCLASSIFIED = "unclassified"


@dataclass
class ClassificationResult:
    type: ReceiptType
    reason: str
    should_store: bool
    should_dispose_existing: bool = False
    existing_approval_no: Optional[str] = None


# 취소 표기: 줄 전체가 "취소" 제목이거나 명확한 취소 거래 용어일 때만 인정
# ("교환/환불/취소 시 영수증 지참" 같은 안내 문구 때문에 정상 영수증이 버려지지 않도록)
CANCEL_PATTERNS = [
    r"승인취소",
    r"취소승인",
    r"거래취소",
    r"취소거래",
    r"취소영수증",
    r"취소전표",
    r"반품",
    r"CANCEL",
    r"VOID",
]
CANCEL_TITLE_PATTERN = r"^[\[\(<*=\-]*취소[\]\)>*=\-]*$"

KITCHEN_PATTERNS = [
    r"주방\s*용",
    r"주방\s*주문",
    r"주문서",
    r"주문\s*확인",
    r"KITCHEN",
    r"조리\s*지시",
]

REPRINT_PATTERNS = [
    r"재발행",
    r"재출력",
    r"복사본",
    r"REPRINT",
    r"COPY",
]


def classify_receipt(
    parsed: ParsedReceipt,
    existing_approval_nos: Optional[set[str]] = None
) -> ClassificationResult:
    text = parsed.raw_text
    text_upper = text.upper()

    # 띄어쓰기를 없앤 줄 단위로 검사 ("[ 취 소 ]", "승 인 취 소" 등 대응)
    compact_lines = [re.sub(r"\s+", "", l) for l in text.split("\n")]
    compact_text = "\n".join(compact_lines)

    cancel_hit = None
    for pattern in CANCEL_PATTERNS:
        if re.search(pattern, compact_text, re.IGNORECASE):
            cancel_hit = pattern
            break
    if not cancel_hit and any(re.match(CANCEL_TITLE_PATTERN, l) for l in compact_lines):
        cancel_hit = "취소 제목 줄"
    if cancel_hit:
        return ClassificationResult(
            type=ReceiptType.CANCELLED,
            reason=f"취소 패턴 감지: {cancel_hit}",
            should_store=False,
            should_dispose_existing=True,
            existing_approval_no=parsed.approval_no,
        )

    if parsed.amount is not None and parsed.amount < 0:
        return ClassificationResult(
            type=ReceiptType.CANCELLED,
            reason="음수 금액 감지",
            should_store=False,
            should_dispose_existing=True,
            existing_approval_no=parsed.approval_no,
        )

    for pattern in KITCHEN_PATTERNS:
        if re.search(pattern, compact_text, re.IGNORECASE) or re.search(pattern, text, re.IGNORECASE):
            return ClassificationResult(
                type=ReceiptType.KITCHEN,
                reason=f"주방용 패턴 감지: {pattern}",
                should_store=False,
            )

    if not parsed.approval_no and not parsed.amount:
        # 승인번호·결제금액이 모두 없으면 결제 영수증이 아님 (주문서·확인서 등)
        return ClassificationResult(
            type=ReceiptType.KITCHEN,
            reason="승인번호/금액 없음 (주문서 등)",
            should_store=False,
        )

    for pattern in REPRINT_PATTERNS:
        if re.search(pattern, compact_text, re.IGNORECASE):
            return ClassificationResult(
                type=ReceiptType.REPRINT,
                reason=f"재출력 패턴 감지: {pattern}",
                should_store=False,
            )

    if existing_approval_nos and parsed.approval_no:
        if parsed.approval_no in existing_approval_nos:
            return ClassificationResult(
                type=ReceiptType.REPRINT,
                reason="동일 승인번호 이미 존재",
                should_store=False,
            )

    if not parsed.approval_no:
        cash_patterns = [r"현금영수증", r"현금\s*결제", r"CASH"]
        for pattern in cash_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return ClassificationResult(
                    type=ReceiptType.CASH,
                    reason="승인번호 없는 현금 거래",
                    should_store=False,
                )

        if parsed.amount and parsed.amount > 0:
            return ClassificationResult(
                type=ReceiptType.UNCLASSIFIED,
                reason="금액은 있으나 승인번호 없음",
                should_store=True,
            )

    if parsed.approval_no and parsed.amount and parsed.amount > 0:
        return ClassificationResult(
            type=ReceiptType.NORMAL,
            reason="정상 카드 결제 영수증",
            should_store=True,
        )

    return ClassificationResult(
        type=ReceiptType.UNCLASSIFIED,
        reason="분류 기준에 맞지 않음",
        should_store=True,
    )

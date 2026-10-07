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


CANCEL_PATTERNS = [
    r"취\s*소",
    r"승인\s*취소",
    r"반\s*품",
    r"CANCEL",
    r"VOID",
    r"거래\s*취소",
]

KITCHEN_PATTERNS = [
    r"주방\s*용",
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

    for pattern in CANCEL_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return ClassificationResult(
                type=ReceiptType.CANCELLED,
                reason=f"취소 패턴 감지: {pattern}",
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
        if re.search(pattern, text, re.IGNORECASE):
            return ClassificationResult(
                type=ReceiptType.KITCHEN,
                reason=f"주방용 패턴 감지: {pattern}",
                should_store=False,
            )

    if not parsed.approval_no and not parsed.amount:
        for pattern in KITCHEN_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return ClassificationResult(
                    type=ReceiptType.KITCHEN,
                    reason="승인번호/금액 없음 + 주방 패턴",
                    should_store=False,
                )
        if len(parsed.lines) < 5:
            return ClassificationResult(
                type=ReceiptType.KITCHEN,
                reason="짧은 출력물 (라인 5개 미만)",
                should_store=False,
            )

    for pattern in REPRINT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
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

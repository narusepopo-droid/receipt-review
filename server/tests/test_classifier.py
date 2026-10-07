"""영수증 분류기 테스트"""
import pytest
from app.receipt.escpos_parser import ParsedReceipt
from app.receipt.classifier import classify_receipt, ReceiptType


def make_receipt(**kwargs) -> ParsedReceipt:
    defaults = {
        "lines": [],
        "images": [],
        "raw_text": "",
        "approval_no": None,
        "amount": None,
    }
    defaults.update(kwargs)
    return ParsedReceipt(**defaults)


class TestClassifier:
    def test_normal_receipt(self):
        receipt = make_receipt(
            raw_text="신한카드\n승인번호: 12345678\n합계: 28,000원",
            approval_no="12345678",
            amount=28000
        )

        result = classify_receipt(receipt)

        assert result.type == ReceiptType.NORMAL
        assert result.should_store is True

    def test_cancelled_receipt_by_text(self):
        receipt = make_receipt(
            raw_text="승인취소\n승인번호: 12345678",
            approval_no="12345678",
            amount=28000
        )

        result = classify_receipt(receipt)

        assert result.type == ReceiptType.CANCELLED
        assert result.should_store is False
        assert result.should_dispose_existing is True

    def test_cancelled_receipt_by_negative_amount(self):
        receipt = make_receipt(
            raw_text="신한카드",
            approval_no="12345678",
            amount=-28000
        )

        result = classify_receipt(receipt)

        assert result.type == ReceiptType.CANCELLED
        assert result.should_store is False

    def test_kitchen_order(self):
        receipt = make_receipt(
            raw_text="주방용\n돼지김치찌개 x2",
        )

        result = classify_receipt(receipt)

        assert result.type == ReceiptType.KITCHEN
        assert result.should_store is False

    def test_kitchen_order_short(self):
        receipt = make_receipt(
            raw_text="테이블 5\n물 2",
            lines=[None, None, None],
        )

        result = classify_receipt(receipt)

        assert result.type == ReceiptType.KITCHEN
        assert result.should_store is False

    def test_reprint_by_text(self):
        receipt = make_receipt(
            raw_text="재발행\n승인번호: 12345678",
            approval_no="12345678",
            amount=28000
        )

        result = classify_receipt(receipt)

        assert result.type == ReceiptType.REPRINT
        assert result.should_store is False

    def test_reprint_by_existing(self):
        receipt = make_receipt(
            raw_text="신한카드",
            approval_no="12345678",
            amount=28000
        )

        existing = {"12345678"}
        result = classify_receipt(receipt, existing)

        assert result.type == ReceiptType.REPRINT
        assert result.should_store is False

    def test_cash_receipt(self):
        receipt = make_receipt(
            raw_text="현금영수증\n합계: 28,000원",
            amount=28000
        )

        result = classify_receipt(receipt)

        assert result.type == ReceiptType.CASH
        assert result.should_store is False

    def test_unclassified_with_amount(self):
        receipt = make_receipt(
            raw_text="매장 영수증",
            amount=28000
        )

        result = classify_receipt(receipt)

        assert result.type == ReceiptType.UNCLASSIFIED
        assert result.should_store is True

    def test_cancel_patterns(self):
        patterns = ["취소", "승인취소", "반품", "CANCEL", "VOID", "거래취소"]

        for pattern in patterns:
            receipt = make_receipt(
                raw_text=f"{pattern}\n승인번호: 12345678",
                approval_no="12345678",
                amount=28000
            )

            result = classify_receipt(receipt)

            assert result.type == ReceiptType.CANCELLED, f"Pattern '{pattern}' should be cancelled"

    def test_kitchen_patterns(self):
        patterns = ["주방용", "주문서", "주문확인", "KITCHEN", "조리지시"]

        for pattern in patterns:
            receipt = make_receipt(
                raw_text=f"{pattern}\n메뉴 항목",
            )

            result = classify_receipt(receipt)

            assert result.type == ReceiptType.KITCHEN, f"Pattern '{pattern}' should be kitchen"

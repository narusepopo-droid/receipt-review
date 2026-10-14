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

    def test_reprint_first_time_recent_is_stored(self):
        """프로그램 설치 전 결제를 다시 뽑은 영수증: 승인번호 처음 + 24시간 안 → 받음, 이미 받은 승인번호·오래된 건 거름"""
        from datetime import datetime, timedelta, timezone
        kst = timezone(timedelta(hours=9))
        recent = (datetime.now(kst) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        old = (datetime.now(kst) - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        r = make_receipt(raw_text="[영 수 증]-재발행 승인번호: 30014958", approval_no="30014958", amount=39000)
        r.paid_at = recent
        assert classify_receipt(r).should_store is True
        assert classify_receipt(r, {"30014958"}).type == ReceiptType.REPRINT
        r.paid_at = old
        assert classify_receipt(r).should_store is False

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


def test_parser_reads_spaced_approval_label():
    """'승 인 번 호' 처럼 글자 사이를 띄어 찍는 포스 (수작나베 실제 영수증)"""
    from app.receipt.escpos_parser import parse_escpos
    raw = ("[영 수 증]-재발행\n승 인 금 액:      39,000\n승 인 번 호: 30014958\n"
           "승 인 일 시: 2026-10-14 14:04:10\n").encode("cp949") + b"\x1dV\x00"
    p = parse_escpos(raw)
    assert p.approval_no == "30014958" and p.amount == 39000
    empty = "승 인 번 호: \n승 인 일 시: 2026-10-14 16:51:05\n".encode("cp949")
    assert parse_escpos(empty).approval_no is None


@pytest.mark.parametrize("label", [
    "승인번호", "승 인 번 호", "승인 번호", "승  인  번  호", "승인NO", "승인 No.", "승인No:", "승인#",
    "카드승인번호", "APPROVAL NO", "Approval No.", "AUTH NO", "승인코드",
])
def test_parser_approval_label_variants(label):
    """포스마다 다른 '승인번호' 표기·띄어쓰기를 모두 읽음"""
    from app.receipt.escpos_parser import parse_escpos
    for sep in (": ", ":", " : ", "   ", "："):
        raw = f"합 계 금 액   12,000\n{label}{sep}30014958\n".encode("cp949", "replace")
        assert parse_escpos(raw).approval_no == "30014958", (label, sep)


@pytest.mark.parametrize("line,expected", [
    ("승인일시: 2026-10-14 14:04:10", "2026-10-14 14:04:10"),
    ("승 인 일 시 : 2026/10/14 14:04", "2026-10-14 14:04:00"),
    ("거래일시 26.10.14 09:05:33", "2026-10-14 09:05:33"),
    ("2026년 10월 14일(화) 14:04", "2026-10-14 14:04:00"),
    ("판매일자 2026-10-1 4:05:09", "2026-10-01 04:05:09"),
])
def test_parser_datetime_variants(line, expected):
    from app.receipt.escpos_parser import parse_escpos
    assert parse_escpos(f"상호 테스트\n{line}\n".encode("cp949")).paid_at == expected


@pytest.mark.parametrize("line,amount", [
    ("승 인 금 액:      39,000", 39000), ("결제금액 15,000원", 15000), ("받을금액   8,500", 8500),
    ("합 계 금 액                         5,000", 5000), ("총 금액: 22,000", 22000), ("TOTAL 7,000", 7000),
])
def test_parser_amount_variants(line, amount):
    from app.receipt.escpos_parser import parse_escpos
    assert parse_escpos(f"{line}\n".encode("cp949")).amount == amount


def test_parser_real_sujaknabe_receipt():
    """실제 매장(수작나베) 영수증 전체: 승인번호·금액·일시·사업자번호"""
    from app.receipt.escpos_parser import parse_escpos
    t = """[ 영 수 증]-재발행
수작나베(석촌호수직영점) / 846-87-03229 / 신재준
02-423-3767
2026-10-14 14:04:10
합 계  금 액                         39,000
         부       가      세         3,545
카 드 종 류:                     KB국민카드
판 매 금 액:                         35,455
승 인 금 액:                         39,000
승 인 번 호: 30014958
승 인 일 시: 2026-10-14 14:04:10
가맹점 번호: 00117000089
"""
    p = parse_escpos(t.encode("cp949"))
    assert (p.approval_no, p.amount, p.paid_at, p.biz_no) == ("30014958", 39000, "2026-10-14 14:04:10", "846-87-03229")
    assert p.vat == 3545 and p.card_issuer
    t2 = t.replace("승 인 번 호: 30014958", "승 인 번 호: ").replace("가맹점 번호: 00117000089", "가맹점 번호: ")
    assert parse_escpos(t2.encode("cp949")).approval_no is None     # 임의등록(승인번호 빈칸)은 다음 줄 숫자를 가져오지 않음

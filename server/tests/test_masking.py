"""마스킹 테스트"""
import pytest
from app.receipt.masking import (
    mask_phone_numbers,
    mask_member_lines,
    mask_card_numbers,
    mask_receipt_text,
    create_safe_display_phone,
)


class TestPhoneMasking:
    def test_standard_phone(self):
        text = "연락처: 010-1234-5678"
        result = mask_phone_numbers(text)

        assert "1234-5678" not in result
        assert "***" in result

    def test_phone_no_dash(self):
        text = "01012345678"
        result = mask_phone_numbers(text)

        assert "12345678" not in result

    def test_phone_with_space(self):
        text = "010 1234 5678"
        result = mask_phone_numbers(text)

        assert "1234" not in result

    def test_partially_masked_phone(self):
        text = "010-****-5678"
        result = mask_phone_numbers(text)

        assert "5678" not in result

    def test_multiple_phones(self):
        text = "발신: 010-1111-2222\n수신: 010-3333-4444"
        result = mask_phone_numbers(text)

        assert "1111-2222" not in result
        assert "3333-4444" not in result

    def test_various_prefixes(self):
        prefixes = ["010", "011", "016", "017", "018", "019"]

        for prefix in prefixes:
            text = f"{prefix}-1234-5678"
            result = mask_phone_numbers(text)

            assert "1234-5678" not in result, f"Prefix {prefix} not masked"


class TestMemberLineMasking:
    def test_member_name(self):
        text = "회원명: 홍길동"
        result = mask_member_lines(text)

        assert "홍길동" not in result

    def test_customer_name(self):
        text = "고객명: 김철수님"
        result = mask_member_lines(text)

        assert "김철수" not in result

    def test_points(self):
        text = "포인트 적립: 280P\n회원: 박영희"
        result = mask_member_lines(text)

        assert "박영희" not in result

    def test_member_id(self):
        text = "회원번호: 12345678"
        result = mask_member_lines(text)

        assert "12345678" not in result

    def test_non_member_line_unchanged(self):
        text = "돼지김치찌개 x2   18,000원"
        result = mask_member_lines(text)

        assert result == text


class TestCardMasking:
    def test_full_card_number(self):
        text = "카드번호: 1234-5678-9012-3456"
        result = mask_card_numbers(text)

        assert "5678-9012" not in result

    def test_card_no_dash(self):
        text = "1234567890123456"
        result = mask_card_numbers(text)

        assert "56789012" not in result


class TestFullMasking:
    def test_combined_masking(self):
        text = """맛있는 식당
사업자번호: 123-45-67890
연락처: 010-1234-5678
회원명: 홍길동
카드번호: 1234-5678-9012-3456
합계: 28,000원"""

        result = mask_receipt_text(text)

        assert "123-45-67890" in result
        assert "28,000원" in result
        assert "010-1234-5678" not in result
        assert "홍길동" not in result


class TestDisplayPhone:
    def test_standard_format(self):
        result = create_safe_display_phone("01012345678")

        assert result == "010-****-5678"

    def test_with_dashes(self):
        result = create_safe_display_phone("010-1234-5678")

        assert result == "010-****-5678"

    def test_short_number(self):
        result = create_safe_display_phone("12345")

        assert result == "***-****-****"

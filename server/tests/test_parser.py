"""ESC/POS 파서 테스트"""
import pytest
from app.receipt.escpos_parser import ESCPOSParser, parse_escpos, Alignment


class TestESCPOSParser:
    def test_parse_simple_text(self):
        data = b"Hello World\n"
        result = parse_escpos(data)

        assert len(result.lines) == 1
        assert result.lines[0].text == "Hello World"

    def test_parse_korean_text(self):
        korean = "맛있는 식당"
        data = korean.encode("cp949") + b"\n"
        result = parse_escpos(data)

        assert len(result.lines) == 1
        assert result.lines[0].text == "맛있는 식당"

    def test_parse_esc_init(self):
        data = b"\x1b@Hello\n"
        result = parse_escpos(data)

        assert len(result.lines) == 1
        assert result.lines[0].text == "Hello"

    def test_parse_bold(self):
        data = b"\x1bE\x01Bold Text\n"
        result = parse_escpos(data)

        assert result.lines[0].style.bold is True

    def test_parse_alignment_center(self):
        data = b"\x1ba\x01Centered\n"
        result = parse_escpos(data)

        assert result.lines[0].style.alignment == Alignment.CENTER

    def test_parse_alignment_right(self):
        data = b"\x1ba\x02Right\n"
        result = parse_escpos(data)

        assert result.lines[0].style.alignment == Alignment.RIGHT

    def test_extract_biz_no(self):
        text = "사업자번호: 123-45-67890"
        data = text.encode("cp949") + b"\n"
        result = parse_escpos(data)

        assert result.biz_no == "123-45-67890"

    def test_extract_approval_no(self):
        text = "승인번호: 12345678"
        data = text.encode("cp949") + b"\n"
        result = parse_escpos(data)

        assert result.approval_no == "12345678"

    def test_extract_amount(self):
        text = "합계: 28,000원"
        data = text.encode("cp949") + b"\n"
        result = parse_escpos(data)

        assert result.amount == 28000

    def test_extract_card_issuer(self):
        text = "신한카드"
        data = text.encode("cp949") + b"\n"
        result = parse_escpos(data)

        assert result.card_issuer == "신한"

    def test_extract_datetime(self):
        text = "거래일시: 2026-10-07 12:34:56"
        data = text.encode("cp949") + b"\n"
        result = parse_escpos(data)

        assert result.paid_at == "2026-10-07 12:34:56"

    def test_multiple_lines(self):
        lines = ["맛있는 식당", "서울시 강남구", "합계: 28,000원"]
        data = b"\n".join(line.encode("cp949") for line in lines) + b"\n"
        result = parse_escpos(data)

        assert len(result.lines) == 3
        assert result.raw_text == "\n".join(lines)

    def test_gs_cut_command(self):
        data = b"Text\n\x1dV\x00More\n"
        result = parse_escpos(data)

        assert len(result.lines) == 2

    def test_unknown_commands_ignored(self):
        data = b"\x1b\xffUnknown\n"
        result = parse_escpos(data)

        assert "Unknown" in result.raw_text

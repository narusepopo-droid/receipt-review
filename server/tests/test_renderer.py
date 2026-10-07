"""
영수증 렌더러 테스트
"""
import pytest
from PIL import Image
import io
from app.receipt.renderer import ReceiptRenderer, ReceiptData


class TestReceiptRenderer:
    """렌더러 테스트"""

    @pytest.fixture
    def renderer(self):
        return ReceiptRenderer(paper_width=380)

    @pytest.fixture
    def sample_receipt_data(self):
        return ReceiptData(
            store_name="다산식육식당",
            biz_no="607-19-41861",
            owner_name="강미선",
            address="부산광역시 동래구 명장로20번길 23",
            phone="051-525-7737",
            paid_at="2026-10-07 15:00:00",
            approval_no="12345678",
            card_issuer="NH농협",
            card_no="9441-16**-****-546*",
            total_amount=130000,
            items=[
                {"name": "모듬6", "qty": 1, "price": 60000},
                {"name": "모듬3", "qty": 1, "price": 30000},
                {"name": "양념갈비(1인)", "qty": 3, "price": 3000},
                {"name": "된장+밥", "qty": 1, "price": 3000},
            ]
        )

    def test_render_creates_image(self, renderer, sample_receipt_data):
        """렌더링 결과가 이미지인지"""
        img = renderer.render_from_data(sample_receipt_data)

        assert isinstance(img, Image.Image)
        assert img.mode == "RGB"

    def test_render_correct_width(self, renderer, sample_receipt_data):
        """렌더링 결과 폭이 정확한지"""
        img = renderer.render_from_data(sample_receipt_data)

        assert img.width == 380

    def test_render_height_varies_with_items(self, renderer):
        """품목 수에 따라 높이가 달라지는지"""
        data_few = ReceiptData(
            store_name="테스트",
            total_amount=10000,
            items=[{"name": "Item1", "qty": 1, "price": 10000}]
        )

        data_many = ReceiptData(
            store_name="테스트",
            total_amount=100000,
            items=[{"name": f"Item{i}", "qty": 1, "price": 10000} for i in range(10)]
        )

        img_few = renderer.render_from_data(data_few)
        img_many = renderer.render_from_data(data_many)

        assert img_many.height > img_few.height

    def test_render_contains_store_name(self, renderer, sample_receipt_data):
        """매장명이 포함되는지 (이미지 텍스트 검증은 어려우므로 에러 없이 완료되는지만)"""
        img = renderer.render_from_data(sample_receipt_data)

        # 이미지가 생성되면 성공
        assert img is not None

    def test_render_empty_items(self, renderer):
        """품목이 없어도 렌더링되는지"""
        data = ReceiptData(
            store_name="테스트 매장",
            total_amount=0,
            items=[]
        )

        img = renderer.render_from_data(data)
        assert img is not None

    def test_render_long_item_names(self, renderer):
        """긴 품목명 처리"""
        data = ReceiptData(
            store_name="테스트",
            total_amount=50000,
            items=[
                {"name": "아주아주아주긴메뉴이름입니다", "qty": 1, "price": 50000}
            ]
        )

        img = renderer.render_from_data(data)
        assert img is not None

    def test_render_large_amounts(self, renderer):
        """큰 금액 처리"""
        data = ReceiptData(
            store_name="테스트",
            total_amount=9999999,
            items=[
                {"name": "고가품목", "qty": 1, "price": 9999999}
            ]
        )

        img = renderer.render_from_data(data)
        assert img is not None

    def test_render_special_characters(self, renderer):
        """특수문자 처리"""
        data = ReceiptData(
            store_name="테스트 & 매장 (본점)",
            total_amount=10000,
            items=[
                {"name": "메뉴 #1 [특별]", "qty": 1, "price": 10000}
            ]
        )

        img = renderer.render_from_data(data)
        assert img is not None

    def test_save_as_png(self, renderer, sample_receipt_data, tmp_path):
        """PNG로 저장되는지"""
        img = renderer.render_from_data(sample_receipt_data)
        output_path = tmp_path / "test_receipt.png"

        renderer.save(img, str(output_path))

        assert output_path.exists()

        # 저장된 파일이 유효한 PNG인지
        loaded = Image.open(output_path)
        assert loaded.format == "PNG"


class TestReceiptRendererPaperWidths:
    """용지 폭 별 테스트"""

    @pytest.mark.parametrize("width", [576, 384])
    def test_render_different_widths(self, width):
        """다양한 용지 폭에서 렌더링"""
        renderer = ReceiptRenderer(paper_width=width)
        data = ReceiptData(
            store_name="테스트",
            total_amount=10000,
            items=[{"name": "Item", "qty": 1, "price": 10000}]
        )

        img = renderer.render_from_data(data)

        assert img.width == width

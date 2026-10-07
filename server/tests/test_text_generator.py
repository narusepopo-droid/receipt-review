"""문구 생성기 테스트"""
import pytest
from app.review.text_generator import TextGenerator
from app.models.store import Store


class TestTextGenerator:
    @pytest.mark.asyncio
    async def test_generate_basic(self, db_session):
        store = Store(name="테스트매장", store_code="gen001")
        db_session.add(store)
        await db_session.flush()

        generator = TextGenerator(db_session)
        text = await generator.generate(
            store.id,
            ["맛있어요", "친절해요"]
        )

        assert text is not None
        assert len(text) >= 30
        assert len(text) <= 150

    @pytest.mark.asyncio
    async def test_generate_without_keywords(self, db_session):
        store = Store(name="테스트매장", store_code="gen002")
        db_session.add(store)
        await db_session.flush()

        generator = TextGenerator(db_session)
        text = await generator.generate(store.id, [])

        assert text is not None

    @pytest.mark.asyncio
    async def test_duplicate_detection(self, db_session):
        store = Store(name="테스트매장", store_code="gen003")
        db_session.add(store)
        await db_session.flush()

        generator = TextGenerator(db_session)

        await generator.record_text(store.id, "테스트 문구입니다")

        is_dup = await generator.is_duplicate(store.id, "테스트 문구입니다")
        assert is_dup is True

        is_dup2 = await generator.is_duplicate(store.id, "다른 문구입니다")
        assert is_dup2 is False

    @pytest.mark.asyncio
    async def test_regenerate_limit(self, db_session):
        store = Store(name="테스트매장", store_code="gen004")
        db_session.add(store)
        await db_session.flush()

        generator = TextGenerator(db_session)

        current_text = "현재 문구입니다"
        _, count = await generator.regenerate(
            store.id,
            ["맛있어요"],
            current_text,
            regenerate_count=10
        )

        assert count == 10

    @pytest.mark.asyncio
    async def test_hash_consistency(self, db_session):
        generator = TextGenerator(db_session)

        h1 = generator._hash_text("동일한 문구")
        h2 = generator._hash_text("동일한 문구")
        h3 = generator._hash_text("다른 문구")

        assert h1 == h2
        assert h1 != h3

    @pytest.mark.asyncio
    async def test_keyword_to_phrase(self, db_session):
        generator = TextGenerator(db_session)

        phrase = generator._keyword_to_phrase("맛있어요")
        assert phrase in [
            "정말 맛있었어요.",
            "맛이 일품이에요.",
            "입맛에 딱 맞았어요.",
        ]

        unknown = generator._keyword_to_phrase("알수없는키워드")
        assert unknown == "알수없는키워드"

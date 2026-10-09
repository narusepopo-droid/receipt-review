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
    async def test_bank_sentence_per_keyword(self, db_session):
        """고른 키워드마다 그 키워드 문장이 하나씩 들어감"""
        from app.review.phrase_bank import BANK
        store = Store(name="테스트매장", store_code="gen005")
        db_session.add(store)
        await db_session.flush()
        gen = TextGenerator(db_session)
        kws = ["친절해요", "주차하기 편해요", "포장 상태가 좋아요"]
        text, picked = await gen.compose(store.id, kws, [], {}, 300, mark=False)
        for kw in kws:
            assert any(p in picked for p in BANK[kw]), kw
        assert all(p in text for p in picked)

    @pytest.mark.asyncio
    async def test_no_repeat_until_full_cycle(self, db_session):
        """한 매장에서 같은 문장은 한 바퀴(25문장) 다 쓰기 전에는 다시 안 나옴"""
        from app.review.phrase_bank import BANK
        store = Store(name="테스트매장", store_code="gen006")
        db_session.add(store)
        await db_session.flush()
        gen = TextGenerator(db_session)
        bank = [p for p in BANK["주차하기 편해요"]]
        seen = []
        for _ in range(len(bank)):
            _, picked = await gen.compose(store.id, ["주차하기 편해요"], [], {}, 300, mark=True)
            seen.append(picked[0])
        assert sorted(seen) == sorted(bank)          # 25번 동안 25문장 모두 한 번씩
        _, picked = await gen.compose(store.id, ["주차하기 편해요"], [], {}, 300, mark=True)
        assert picked[0] in bank                       # 26번째부터 다시 순환

    @pytest.mark.asyncio
    async def test_cycle_is_per_store(self, db_session):
        from app.review.phrase_bank import BANK
        a = Store(name="A", store_code="gen007")
        b = Store(name="B", store_code="gen008")
        db_session.add_all([a, b])
        await db_session.flush()
        gen = TextGenerator(db_session)
        for _ in range(24):
            await gen.compose(a.id, ["맛있어요"], [], {}, 300, mark=True)
        # B 매장은 A 사용 기록과 무관하게 아무 문장이나 가능 (첫 바퀴)
        _, picked = await gen.compose(b.id, ["맛있어요"], [], {}, 300, mark=True)
        assert picked[0] in BANK["맛있어요"]

    @pytest.mark.asyncio
    async def test_custom_phrases_added_and_menu(self, db_session):
        from app.review.text_generator import candidates_for
        c = candidates_for("맛있어요", {"맛있어요": ["국물이 진했어요."]}, ["갈비탕"])
        assert "국물이 진했어요." in c and len(c) == 26
        assert all("{메뉴}" not in p for p in candidates_for("맛있어요", {}, []))


@pytest.mark.asyncio
async def test_flow_order_and_connectors(db_session):
    """음식 → 서비스 → 매장 순서, 이어주는 말 최대 2개"""
    import re
    from app.review.phrase_bank import BANK
    store = Store(name="흐름", store_code="gen009")
    db_session.add(store)
    await db_session.flush()
    gen = TextGenerator(db_session)
    for _ in range(30):
        text, picked = await gen.compose(store.id, ["주차하기 편해요", "친절해요", "맛있어요"], [], {}, 400, mark=True)
        kinds = [next(k for k, v in BANK.items() if p in v) for p in picked]
        assert kinds == ["맛있어요", "친절해요", "주차하기 편해요"]
        assert len(re.findall(r"(특히|참,|그리고|게다가) ", text)) <= 2
        assert "무엇보다" not in text

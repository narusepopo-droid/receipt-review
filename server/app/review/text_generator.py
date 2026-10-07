"""리뷰 문구 생성기"""
import re
import random
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.session import TextHistory
from ..models.store import StoreSettings


DEFAULT_TEMPLATES = [
    "{메뉴} 정말 맛있었어요! {키워드1} 다음에 또 올게요.",
    "오늘 {메뉴} 먹었는데 {키워드1} {키워드2} 추천합니다.",
    "{키워드1} 분위기도 좋고 {메뉴}도 최고였어요.",
    "{메뉴} 강추해요! {키워드1} 또 방문할게요.",
    "역시 {메뉴}! {키워드1} {키워드2} 만족스러웠습니다.",
]

DEFAULT_MENUS = ["대표메뉴"]

DEFAULT_KEYWORD_PHRASES = {
    "맛있어요": [
        "정말 맛있었어요.",
        "맛이 일품이에요.",
        "입맛에 딱 맞았어요.",
    ],
    "친절해요": [
        "직원분들이 정말 친절하셨어요.",
        "응대가 친절해서 기분 좋았어요.",
        "서비스가 훌륭했어요.",
    ],
    "깔끔해요": [
        "매장이 깔끔하고 청결해요.",
        "위생적이고 정돈되어 있어요.",
        "깔끔한 분위기가 좋았어요.",
    ],
    "가성비좋아요": [
        "가격 대비 만족스러웠어요.",
        "가성비 최고예요!",
        "합리적인 가격이에요.",
    ],
    "분위기좋아요": [
        "분위기가 아늑하고 좋아요.",
        "편안한 분위기에서 식사했어요.",
        "인테리어가 예뻐요.",
    ],
}


class TextGenerator:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _hash_text(self, text: str) -> str:
        """문장 해시 생성"""
        return hashlib.sha256(text.encode()).hexdigest()

    def _keyword_to_phrase(
        self,
        keyword: str,
        keyword_phrases: Optional[dict] = None
    ) -> str:
        """키워드를 문장형으로 변환"""
        phrases = keyword_phrases or DEFAULT_KEYWORD_PHRASES
        if keyword in phrases:
            return random.choice(phrases[keyword])
        return keyword

    def _fill_template(
        self,
        template: str,
        menus: list[str],
        keywords: list[str],
        keyword_phrases: Optional[dict] = None
    ) -> str:
        """템플릿 빈칸 채우기"""
        result = template

        if menus:
            result = result.replace("{메뉴}", random.choice(menus))
        else:
            result = result.replace("{메뉴}", "")

        for i in range(1, 6):
            placeholder = f"{{키워드{i}}}"
            if placeholder in result:
                if i <= len(keywords):
                    phrase = self._keyword_to_phrase(keywords[i-1], keyword_phrases)
                    result = result.replace(placeholder, phrase)
                else:
                    result = result.replace(placeholder, "")

        result = re.sub(r"\s+", " ", result).strip()
        return result

    async def is_duplicate(
        self,
        store_id: int,
        text: str,
        days: int = 30
    ) -> bool:
        """최근 N일 내 중복 문구인지 확인"""
        text_hash = self._hash_text(text)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        result = await self.db.execute(
            select(TextHistory).where(
                TextHistory.store_id == store_id,
                TextHistory.text_hash == text_hash,
                TextHistory.used_at >= cutoff
            )
        )
        return result.scalar_one_or_none() is not None

    async def record_text(self, store_id: int, text: str) -> None:
        """사용된 문구 기록"""
        history = TextHistory(
            store_id=store_id,
            text_hash=self._hash_text(text),
            used_at=datetime.now(timezone.utc)
        )
        self.db.add(history)
        await self.db.flush()

    async def cleanup_old_history(self, store_id: int, days: int = 30) -> int:
        """오래된 문구 기록 정리"""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.db.execute(
            delete(TextHistory).where(
                TextHistory.store_id == store_id,
                TextHistory.used_at < cutoff
            )
        )
        return result.rowcount

    async def generate(
        self,
        store_id: int,
        selected_keywords: list[str],
        settings: Optional[StoreSettings] = None,
        max_attempts: int = 20
    ) -> str:
        """
        문구 생성
        - 템플릿 랜덤 선택 → 빈칸 채움
        - 글자수 범위 체크
        - 중복 방지 (30일 내)
        """
        templates = DEFAULT_TEMPLATES
        menus = DEFAULT_MENUS
        keyword_phrases = DEFAULT_KEYWORD_PHRASES
        min_len = 30
        max_len = 150

        if settings:
            if settings.templates:
                templates = settings.templates
            if settings.signature_menus:
                menus = settings.signature_menus
            if settings.keywords:
                kw_phrases = {}
                for kw in settings.keywords:
                    if isinstance(kw, dict) and "label" in kw:
                        label = kw["label"]
                        phrases = kw.get("phrases", [label])
                        kw_phrases[label] = phrases if phrases else [label]
                if kw_phrases:
                    keyword_phrases = kw_phrases
            min_len = settings.text_min_len
            max_len = settings.text_max_len

        for _ in range(max_attempts):
            template = random.choice(templates)
            text = self._fill_template(
                template,
                menus,
                selected_keywords,
                keyword_phrases
            )

            if len(text) < min_len or len(text) > max_len:
                continue

            if await self.is_duplicate(store_id, text):
                continue

            await self.record_text(store_id, text)
            return text

        fallback = self._fill_template(
            random.choice(templates),
            menus,
            selected_keywords,
            keyword_phrases
        )
        await self.record_text(store_id, fallback)
        return fallback

    async def regenerate(
        self,
        store_id: int,
        selected_keywords: list[str],
        current_text: str,
        regenerate_count: int,
        settings: Optional[StoreSettings] = None,
        max_regenerate: int = 10
    ) -> tuple[str, int]:
        """
        다른 문구 생성 (세션당 최대 10회)
        Returns: (새 문구, 새 재생성 카운트)
        """
        if regenerate_count >= max_regenerate:
            return current_text, regenerate_count

        for attempt in range(5):
            new_text = await self.generate(store_id, selected_keywords, settings)
            if new_text != current_text:
                return new_text, regenerate_count + 1

        return current_text, regenerate_count

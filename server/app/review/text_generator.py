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

DEFAULT_MENUS: list[str] = []

# 점주가 템플릿을 등록하지 않았을 때 쓰는 조합형 문장 재료
# (시작 × 메뉴/본문 × 키워드 문장 순서 × 마무리 → 수천 가지 조합, 같은 문장 반복 방지)
OPENINGS = [
    "", "", "오늘 방문했어요.", "점심 먹으러 왔어요.", "저녁 식사하러 들렀어요.",
    "지인 추천으로 와봤어요.", "근처에 볼일이 있어서 들렀어요.", "오랜만에 다시 왔어요.",
    "가족이랑 같이 왔어요.", "친구랑 왔는데 좋았어요.",
]
MENU_SENTENCES = [
    "{메뉴} 정말 맛있었어요.", "{메뉴} 먹었는데 기대 이상이었어요.", "{메뉴} 추천합니다!",
    "{메뉴}가 특히 맛있었어요.", "{메뉴} 양도 넉넉하고 좋았어요.", "역시 {메뉴}가 최고네요.",
    "{메뉴} 또 먹고 싶어요.", "{메뉴} 맛집 인정합니다.",
]
NO_MENU_SENTENCES = [
    "음식이 전체적으로 맛있었어요.", "메뉴가 다 맛있었어요.", "음식이 정갈하고 맛있었어요.",
    "먹는 내내 만족스러웠어요.", "음식이 빨리 나와서 좋았어요.", "기대 이상이었어요.",
]
CLOSINGS = [
    "다음에 또 올게요!", "재방문 의사 있어요.", "또 방문할게요.", "추천합니다!",
    "잘 먹고 갑니다.", "만족스러운 식사였어요.", "주변에도 추천할게요.", "자주 올 것 같아요.", "",
]

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


def _josa_iga(word: str) -> str:
    """받침 있으면 '이', 없으면 '가' (갈비탕이 / 김치찌개가)"""
    if not word:
        return "가"
    ch = word[-1]
    if "가" <= ch <= "힣":
        return "이" if (ord(ch) - 0xAC00) % 28 else "가"
    return "가"


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

        custom_templates = bool(settings and settings.templates)

        def make() -> str:
            if custom_templates:
                tpl = random.choice(templates)
                if not menus:
                    # 메뉴가 없으면 {메뉴}가 없는 템플릿 우선
                    no_menu = [t for t in templates if "{메뉴}" not in t]
                    tpl = random.choice(no_menu) if no_menu else tpl
                return self._fill_template(tpl, menus, selected_keywords, keyword_phrases)
            return self._compose(menus, selected_keywords, keyword_phrases)

        for _ in range(max_attempts):
            text = make()

            if len(text) < min_len or len(text) > max_len:
                continue

            if await self.is_duplicate(store_id, text):
                continue

            await self.record_text(store_id, text)
            return text

        fallback = make()
        await self.record_text(store_id, fallback)
        return fallback

    def _compose(self, menus: list[str], keywords: list[str], keyword_phrases: Optional[dict]) -> str:
        """조합형 기본 문장: 시작 + 메뉴 문장 + 키워드 문장들(섞음) + 마무리"""
        parts = [random.choice(OPENINGS)]
        if menus:
            menu = random.choice(menus)
            sentence = random.choice(MENU_SENTENCES).replace("{메뉴}가", menu + _josa_iga(menu))
            parts.append(sentence.replace("{메뉴}", menu))
        else:
            parts.append(random.choice(NO_MENU_SENTENCES))

        kws = list(keywords)[:3]
        random.shuffle(kws)
        for kw in kws:
            phrase = self._keyword_to_phrase(kw, keyword_phrases).strip()
            if phrase and phrase[-1] not in ".!?~":
                phrase += "."
            parts.append(phrase)

        parts.append(random.choice(CLOSINGS))
        text = " ".join(p for p in parts if p)
        return re.sub(r"\s+", " ", text).strip()

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

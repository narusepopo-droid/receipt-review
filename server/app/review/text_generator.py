"""
리뷰 문구 생성기

손님이 고른 키워드(최소 3개)마다 문장 묶음(phrase_bank: 12키워드 × 25문장 = 300문장 + 점주 추가 문장)에서
1문장씩 골라 이어 붙인다. 앞뒤로 시작·마무리 문장을 무작위로 붙임.

- 한 매장 안에서 같은 문장은 그 키워드 문장을 한 바퀴 다 쓸 때까지 다시 쓰지 않음 (phrase_usage)
- 완성 문구도 30일 안에 같은 것이 나가지 않게 한 번 더 확인
"""
import hashlib
import random
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.session import TextHistory
from ..models.store import StoreSettings
from .phrase_bank import BANK, OPENINGS, CLOSINGS

MAX_KEYWORD_SENTENCES = 4   # 키워드를 많이 골라도 글이 너무 길어지지 않게 최대 4문장


def _norm(t: str) -> str:
    return re.sub(r"\s+", "", t or "")


def _josa_iga(word: str) -> str:
    """받침 있으면 '이', 없으면 '가' (갈비탕이 / 김치찌개가)"""
    if not word:
        return "가"
    ch = word[-1]
    if "가" <= ch <= "힣":
        return "이" if (ord(ch) - 0xAC00) % 28 else "가"
    return "가"


def _phrase_hash(phrase: str) -> str:
    return hashlib.sha256(phrase.encode()).hexdigest()


def candidates_for(keyword: str, custom: Optional[dict], menus: list[str]) -> list[str]:
    """키워드의 후보 문장: 기본 25문장 + 점주가 추가한 문장 (메뉴가 없으면 {메뉴} 문장 제외)"""
    out = []
    for label, phrases in BANK.items():
        if _norm(label) == _norm(keyword):
            out.extend(phrases)
    for label, phrases in (custom or {}).items():
        if _norm(label) == _norm(keyword):
            out.extend(p for p in phrases if p)
    if not out:
        out = [keyword if keyword.endswith((".", "!", "요")) else keyword]   # 점주가 만든 새 키워드 (문장 미등록)
    if not menus:
        out = [p for p in out if "{메뉴}" not in p] or out
    return list(dict.fromkeys(out))


def fill_menu(phrase: str, menus: list[str]) -> str:
    if "{메뉴}" not in phrase:
        return phrase
    menu = random.choice(menus) if menus else "음식"
    phrase = phrase.replace("{메뉴}가", menu + _josa_iga(menu)).replace("{메뉴}는", menu + ("은" if _josa_iga(menu) == "이" else "는"))
    return phrase.replace("{메뉴}", menu)


class TextGenerator:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _hash_text(self, text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    # ---------- 완성 문구 30일 중복 확인 ----------
    async def is_duplicate(self, store_id: int, text: str, days: int = 30) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.db.execute(select(TextHistory).where(
            TextHistory.store_id == store_id,
            TextHistory.text_hash == self._hash_text(text),
            TextHistory.used_at >= cutoff))
        return result.scalars().first() is not None

    async def record_text(self, store_id: int, text: str) -> None:
        self.db.add(TextHistory(store_id=store_id, text_hash=self._hash_text(text), used_at=datetime.now(timezone.utc)))
        await self.db.flush()

    async def cleanup_old_history(self, store_id: int, days: int = 30) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await self.db.execute(delete(TextHistory).where(
            TextHistory.store_id == store_id, TextHistory.used_at < cutoff))
        return result.rowcount

    # ---------- 문장 순환 (한 바퀴 돌면 다시) ----------
    async def _usage(self, store_id: int, phrases: list[str]) -> dict:
        from ..models.options import PhraseUsage
        hashes = {_phrase_hash(p): p for p in phrases}
        rows = (await self.db.execute(select(PhraseUsage).where(
            PhraseUsage.store_id == store_id, PhraseUsage.phrase_hash.in_(list(hashes))))).scalars().all()
        counts = {p: 0 for p in phrases}
        for r in rows:
            counts[hashes[r.phrase_hash]] = r.count
        return counts

    async def _pick(self, store_id: int, phrases: list[str], exclude: set) -> str:
        """가장 덜 쓴 문장 중 하나 (같은 바퀴 안에서는 중복 없음)"""
        counts = await self._usage(store_id, phrases)
        pool = [p for p in phrases if p not in exclude] or phrases
        least = min(counts[p] for p in pool)
        return random.choice([p for p in pool if counts[p] == least])

    async def _mark_used(self, store_id: int, phrases: list[str]) -> None:
        from ..models.options import PhraseUsage
        for p in phrases:
            h = _phrase_hash(p)
            row = (await self.db.execute(select(PhraseUsage).where(
                PhraseUsage.store_id == store_id, PhraseUsage.phrase_hash == h))).scalar_one_or_none()
            if row:
                row.count += 1
            else:
                self.db.add(PhraseUsage(store_id=store_id, phrase_hash=h, count=1))
        await self.db.flush()

    # ---------- 생성 ----------
    @staticmethod
    def _store_material(settings: Optional[StoreSettings]):
        menus = [m for m in (settings.signature_menus or []) if m and m.strip()] if settings else []
        custom = {}
        if settings and settings.keywords:
            for kw in settings.keywords:
                if isinstance(kw, dict) and kw.get("label") and kw.get("phrases"):
                    custom[kw["label"]] = [p for p in kw["phrases"] if p]
        min_len = settings.text_min_len if settings and settings.text_min_len else 30
        max_len = settings.text_max_len if settings and settings.text_max_len else 150
        return menus, custom, min_len, max_len

    async def compose(self, store_id: int, keywords: list[str], menus: list[str], custom: dict,
                      max_len: int = 150, mark: bool = True) -> tuple[str, list[str]]:
        """(완성 문구, 고른 원문 문장들)"""
        chosen = list(dict.fromkeys(k for k in keywords if k))
        random.shuffle(chosen)
        chosen = chosen[:MAX_KEYWORD_SENTENCES] or ["맛있어요"]

        picked_raw = []
        for kw in chosen:
            phrases = candidates_for(kw, custom, menus)
            picked_raw.append(await self._pick(store_id, phrases, set(picked_raw)))

        opening = random.choice(OPENINGS)
        closing = random.choice(CLOSINGS)
        body = [fill_menu(p, menus) for p in picked_raw]
        text = " ".join(x for x in [opening, *body, closing] if x)
        # 너무 길면 시작·마무리부터 뺌
        if len(text) > max_len:
            text = " ".join(x for x in [*body, closing] if x)
        if len(text) > max_len:
            text = " ".join(body)
        if mark:
            await self._mark_used(store_id, picked_raw)
        return re.sub(r"\s+", " ", text).strip(), picked_raw

    async def generate(
        self,
        store_id: int,
        selected_keywords: list[str],
        settings: Optional[StoreSettings] = None,
        max_attempts: int = 10
    ) -> str:
        menus, custom, min_len, max_len = self._store_material(settings)
        text, picked = "", []
        for _ in range(max_attempts):
            text, picked = await self.compose(store_id, selected_keywords, menus, custom, max_len, mark=False)
            if len(text) < min_len or await self.is_duplicate(store_id, text):
                continue
            break
        # 확정한 문장만 사용 처리 (한 바퀴 순환 기록)
        await self._mark_used(store_id, picked)
        await self.record_text(store_id, text)
        return text

    async def regenerate(
        self,
        store_id: int,
        selected_keywords: list[str],
        current_text: str,
        regenerate_count: int,
        settings: Optional[StoreSettings] = None,
        max_regenerate: int = 10
    ) -> tuple[str, int]:
        """다른 문구 (세션당 최대 10회)"""
        if regenerate_count >= max_regenerate:
            return current_text, regenerate_count
        for _ in range(5):
            new_text = await self.generate(store_id, selected_keywords, settings)
            if new_text != current_text:
                return new_text, regenerate_count + 1
        return current_text, regenerate_count

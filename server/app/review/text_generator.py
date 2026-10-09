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

# 이야기 순서: 음식 → 가격 → 직원·속도 → 매장 → 포장 (점주가 만든 키워드는 음식 뒤)
FLOW_ORDER = [
    "맛있어요", "재료가 신선해요", "특별한 메뉴가 있어요", "양이 많아요", "메뉴가 다양해요",
    "가성비 좋아요", "음식이 빨리 나와요", "친절해요",
    "분위기 좋아요", "매장이 청결해요", "주차하기 편해요", "포장 상태가 좋아요",
]
# 이어주는 말 (한 리뷰에 최대 2개, 문맥에 맞을 때만)
FOOD_DETAIL = {"재료가 신선해요", "양이 많아요", "특별한 메뉴가 있어요"}       # 맛 이야기 뒤 "특히"
SIDE_TOPICS = {"주차하기 편해요", "포장 상태가 좋아요"}  # 마지막이면 "참,"
MAX_CONNECTORS = 2
# 이미 이런 말로 시작하면 이어주는 말을 붙이지 않음
NO_CONNECTOR_START = ("그리고", "또", "게다가", "특히", "무엇보다", "참", "다음", "처음", "생각", "오랜만", "같이", "{메뉴}")
# 시작 문장과 내용이 부딪히는 표현
OPENING_CONFLICTS = {
    "처음 와봤어요.": ("또 ", "다시", "오랜만", "두 번째", "단골", "올 때마다", "여러 번"),
    "오랜만에 다시 왔어요.": ("처음",),
    "지인 추천으로 와봤어요.": ("올 때마다", "여러 번", "단골"),
}
# 마무리 문장과 겹치는 말 (본문에 이미 있으면 그 마무리는 안 씀)
CLOSING_STEMS = {"다음에 또 올게요!": ("또 오", "또 올", "다시 오", "재방문"),
                 "재방문 의사 있어요.": ("재방문", "또 오", "또 올"),
                 "또 방문할게요.": ("재방문", "또 오", "또 올", "방문할"),
                 "추천합니다!": ("추천",),
                 "주변에도 추천할게요.": ("추천",),
                 "자주 올 것 같아요.": ("자주", "단골", "또 오", "또 올"),
                 "잘 먹고 갑니다.": (),
                 "만족스러운 식사였어요.": ("만족",)}


def _ending(sentence: str) -> str:
    """문장 끝맺음 (예: '좋았어요', '맛있어요') — 같은 끝맺음 연속 방지용"""
    core = sentence.rstrip(".!~ ")
    return core[-4:]


def _flow_key(keyword: str) -> int:
    for i, k in enumerate(FLOW_ORDER):
        if _norm(k) == _norm(keyword):
            return i
    return 1  # 점주가 만든 키워드는 음식 이야기 바로 뒤


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

    async def _pick(self, store_id: int, phrases: list[str], exclude: set, avoid_endings: set = frozenset()) -> str:
        """가장 덜 쓴 문장 중 하나 (같은 바퀴 안에서는 중복 없음). 앞 문장과 끝맺음이 같은 문장은 가능하면 피함"""
        counts = await self._usage(store_id, phrases)
        pool = [p for p in phrases if p not in exclude] or phrases
        least = min(counts[p] for p in pool)
        best = [p for p in pool if counts[p] == least]
        varied = [p for p in best if _ending(p) not in avoid_endings]
        return random.choice(varied or best)

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
        """(완성 문구, 고른 원문 문장들) — 이야기 순서로 배치하고 자연스럽게 이어 붙임"""
        chosen = list(dict.fromkeys(k for k in keywords if k))
        random.shuffle(chosen)
        chosen = chosen[:MAX_KEYWORD_SENTENCES] or ["맛있어요"]
        chosen.sort(key=_flow_key)

        picked_raw, endings = [], set()
        for kw in chosen:
            phrases = candidates_for(kw, custom, menus)
            p = await self._pick(store_id, phrases, set(picked_raw), endings)
            picked_raw.append(p)
            endings.add(_ending(p))

        body = [fill_menu(p, menus) for p in picked_raw]
        joined = " ".join(body)

        # 이어주는 말: 문맥에 맞을 때만, 한 리뷰에 최대 2개, 같은 말 반복 없음
        used_conn = []
        norm_kw = [_norm(k) for k in chosen]
        for i in range(1, len(body)):
            if len(used_conn) >= MAX_CONNECTORS or body[i].startswith(NO_CONNECTOR_START) or body[i].startswith("다른"):
                continue
            prev_kw, kw = chosen[i - 1], chosen[i]
            conn = ""
            if _norm(prev_kw) == _norm("맛있어요") and kw in FOOD_DETAIL and random.random() < 0.7:
                conn = "특히 "
            elif i == len(body) - 1 and kw in SIDE_TOPICS and random.random() < 0.5:
                conn = "참, "
            elif random.random() < 0.35:
                conn = random.choice(["그리고 ", "게다가 "])
            if conn and conn not in used_conn:
                used_conn.append(conn)
                body[i] = conn + body[i]

        # 시작 문장: 본문과 부딪히지 않는 것만
        openings = [o for o in OPENINGS if not any(w in joined for w in OPENING_CONFLICTS.get(o, ()))]
        opening = random.choice(openings or [""])
        # 마무리: 본문에 이미 같은 말이 있으면 다른 것
        closings = [c for c in CLOSINGS if not any(w in joined for w in CLOSING_STEMS.get(c, ()))]
        closing = random.choice(closings or [""])

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

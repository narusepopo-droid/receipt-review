"""
리뷰 등록 자동 확인 (Phase 9, 매장별 선택)
네이버 플레이스 공개 방문자 리뷰(최근순 20개)를 읽어, 최근 7일 손님에게 드린 문구와 비슷한 리뷰가 있으면 '확인됨'으로 기록.
- 매장당 6시간에 1번, 매장 사이 간격을 둬서 요청 (네이버 부담 최소화)
- 손님이 문구를 조금 고쳐 써도 잡히도록 띄어쓰기·문장부호를 뺀 뒤 유사도로 비교
"""
import asyncio
import difflib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.options import ReviewCheck, StoreOptions
from app.models.session import ReviewSession

logger = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
MATCH_THRESHOLD = 0.6
LOOKBACK = timedelta(days=7)
DELAY_BETWEEN_STORES = 5.0


def parse_reviews(html: str) -> list[dict]:
    """플레이스 리뷰 페이지 HTML → [{id, body, created}]"""
    m = re.search(r"window\.__APOLLO_STATE__\s*=\s*(\{.*?\})\s*;\s*\n", html, re.S) or \
        re.search(r"window\.__APOLLO_STATE__\s*=\s*(\{.*\})\s*;", html, re.S)
    if not m:
        return []
    try:
        state = json.loads(m.group(1))
    except ValueError:
        return []
    out = []
    for key, v in state.items():
        if key.startswith("VisitorReview:") and isinstance(v, dict) and v.get("body"):
            out.append({"id": v.get("id") or key, "body": v["body"], "created": v.get("created")})
    return out


async def fetch_reviews(place_id: str, client: Optional[httpx.AsyncClient] = None) -> list[dict]:
    own = client is None
    client = client or httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": UA})
    try:
        for kind in ("restaurant", "place"):
            r = await client.get(f"https://m.place.naver.com/{kind}/{place_id}/review/visitor",
                                 params={"reviewSort": "recent"})
            if r.status_code == 200:
                reviews = parse_reviews(r.text)
                if reviews:
                    return reviews
        return []
    finally:
        if own:
            await client.aclose()


def _norm(text: str) -> str:
    return re.sub(r"[\s\.,!?~'\"…·\-]+", "", text or "")


def similarity(given: str, posted: str) -> float:
    a, b = _norm(given), _norm(posted)
    if not a or not b:
        return 0.0
    if a in b:          # 손님이 앞뒤에 말을 덧붙인 경우
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


async def check_store(db: AsyncSession, store_id: int, place_id: str, reviews: list[dict]) -> int:
    since = datetime.now(timezone.utc) - LOOKBACK
    done = {r.session_id for r in (await db.execute(
        select(ReviewCheck).where(ReviewCheck.store_id == store_id))).scalars()}
    sessions = (await db.execute(select(ReviewSession).where(
        ReviewSession.store_id == store_id,
        ReviewSession.generated_text.isnot(None),
        ReviewSession.assigned_at >= since))).scalars().all()
    found = 0
    used_reviews = set()
    for s in sessions:
        if str(s.id) in done:
            continue
        best, best_rev = 0.0, None
        for rev in reviews:
            if rev["id"] in used_reviews:
                continue
            sc = similarity(s.generated_text, rev["body"])
            if sc > best:
                best, best_rev = sc, rev
        if best_rev and best >= MATCH_THRESHOLD:
            used_reviews.add(best_rev["id"])
            db.add(ReviewCheck(session_id=str(s.id), store_id=store_id, similarity=int(best * 100),
                               review_excerpt=best_rev["body"][:200]))
            found += 1
    await db.commit()
    return found


async def run_all(db: AsyncSession) -> int:
    opts = (await db.execute(select(StoreOptions).where(
        StoreOptions.review_check.is_(True), StoreOptions.naver_place_id.isnot(None)))).scalars().all()
    total = 0
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": UA}) as client:
        for i, o in enumerate(opts):
            if i:
                await asyncio.sleep(DELAY_BETWEEN_STORES)
            try:
                reviews = await fetch_reviews(o.naver_place_id, client)
                n = await check_store(db, o.store_id, o.naver_place_id, reviews)
                total += n
                logger.info("review check store=%s reviews=%s matched=%s", o.store_id, len(reviews), n)
            except Exception as e:
                logger.warning("review check failed store=%s: %s", o.store_id, e)
    return total


async def verified_count(db: AsyncSession, store_id: int, days: int = 7) -> int:
    from sqlalchemy import func
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return (await db.execute(select(func.count()).select_from(ReviewCheck).where(
        ReviewCheck.store_id == store_id, ReviewCheck.created_at >= since))).scalar() or 0

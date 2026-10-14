"""네이버 플레이스 매장 검색 (매장 추가 화면 드롭다운용)

플마(플레이스 마스터) 매장 검색과 같은 방식: 네이버 공개 검색 페이지 HTML 안의
window.__APOLLO_STATE__ JSON 에서 매장 목록을 읽음. 로그인·API 키 없음.
1) pcmap.place.naver.com/place/list  2) 없으면 search.naver.com  3) 그래도 없으면 끝의 '점/지점' 떼고 다시
"""
import json
import logging
import re
import time
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}
_CACHE: dict = {}          # query -> (시각, 결과)
_CACHE_SEC = 600
_TAG = re.compile(r"<[^>]+>")


def _item(pid, val: dict, address_keys) -> dict:
    thumb = val.get("imageUrl") or val.get("thumUrl") or ""
    if thumb.startswith("//"):
        thumb = "https:" + thumb
    return {
        "place_id": str(pid),
        "name": _TAG.sub("", val.get("name") or "").strip(),
        "category": (val.get("category") or "").split(",")[0].strip(),
        "address": next((val[k] for k in address_keys if val.get(k)), ""),
        "thumbnail": thumb if thumb.startswith("https://") else "",
    }


def _from_state(state: dict, address_keys) -> list:
    out = []
    for key, val in state.items():
        if key.startswith("PlaceListBusinessesItem:") and isinstance(val, dict):
            it = _item(val.get("id") or key.split(":")[-1], val, address_keys)
            if it["name"] and it["place_id"].isdigit():
                out.append(it)
    return out


def _apollo(html: str) -> dict:
    """페이지 안의 __APOLLO_STATE__ = {...} JSON (뒤에 무엇이 오든 JSON 끝까지만 읽음)"""
    m = re.search(r"__APOLLO_STATE__\s*=\s*", html)
    if not m:
        return {}
    try:
        state, _ = json.JSONDecoder().raw_decode(html, m.end())
    except ValueError:
        return {}
    return state if isinstance(state, dict) else {}


async def _pcmap(c: httpx.AsyncClient, q: str) -> list:
    r = await c.get(f"https://pcmap.place.naver.com/place/list?query={quote(q)}")
    if r.status_code != 200:
        return []
    return _from_state(_apollo(r.text), ("fullAddress", "roadAddress", "commonAddress", "address"))


async def _search(c: httpx.AsyncClient, q: str) -> list:
    r = await c.get(f"https://search.naver.com/search.naver?where=nexearch&query={quote(q)}")
    if r.status_code != 200:
        return []
    return _from_state(_apollo(r.text), ("fullAddress", "roadAddress", "commonAddress", "address"))


def _filter(results: list, q: str) -> list:
    """입력한 이름으로 시작하는 매장 우선 (다 걸러지면 원래 목록)"""
    qq = re.sub(r"\s+", "", q).lower()
    keep = [r for r in results
            if (n := re.sub(r"\s+", "", r["name"]).lower()).startswith(qq) or qq.startswith(n)]
    return keep or results


async def search(query: str) -> list:
    q = (query or "").strip()[:50]
    if len(q) < 2:
        return []
    hit = _CACHE.get(q)
    if hit and time.time() - hit[0] < _CACHE_SEC:
        return hit[1]
    results: list = []
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=_HEADERS) as c:
            tries = [q]
            short = re.sub(r"(지점|점)$", "", q).strip()
            if short != q and len(short) >= 2:
                tries.append(short)
            for t in tries:
                results = await _pcmap(c, t) or await _search(c, t)
                if results:
                    break
    except httpx.HTTPError as e:
        logger.warning("place search failed for %r: %s", q, e)
        return []
    seen, uniq = set(), []
    for r in _filter(results, q):
        if r["place_id"] not in seen:
            seen.add(r["place_id"])
            uniq.append(r)
    uniq = uniq[:20]
    _CACHE[q] = (time.time(), uniq)
    if len(_CACHE) > 500:
        _CACHE.clear()
    return uniq

"""
AI 리뷰 문장 (Phase 9, 매장별 선택)
- Claude 로 대표메뉴·키워드 기반의 자연스러운 손님 리뷰 문장 1개 생성
- 키(ANTHROPIC_API_KEY)가 없거나, 8초 안에 응답이 없거나, 오류·거부면 None → 호출 쪽이 기존 조합 방식 사용
"""
import logging
import os
import random
import re
from typing import Optional

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5-5"
TIMEOUT_SECONDS = 8.0

SYSTEM = (
    "당신은 식당을 방문한 실제 손님처럼 네이버 영수증 리뷰 문장을 씁니다. "
    "규칙: 한국어 존댓말 구어체, 1~3문장, 과장·광고 문구·이모지·해시태그·따옴표 금지, "
    "가격이나 사실관계를 지어내지 않음, 주어진 메뉴와 느낌만 사용. 리뷰 문장만 출력하세요."
)

STYLES = ["담백하게", "친근하게", "짧고 간결하게", "구체적으로", "다정하게", "솔직하게"]
SITUATIONS = ["", "점심에", "저녁에", "가족과", "친구와", "동료들과", "혼자"]


def is_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or _settings_key())


def _settings_key() -> str:
    try:
        from app.config import get_settings
        return getattr(get_settings(), "ANTHROPIC_API_KEY", "") or ""
    except Exception:
        return ""


def _clean(text: str) -> str:
    text = text.strip().strip('"“”\'')
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"#\S+", "", text).strip()
    return text


async def generate(menus: list[str], keyword_phrases: list[str], min_len: int, max_len: int) -> Optional[str]:
    """성공 시 문장, 실패 시 None"""
    if not is_available():
        return None
    try:
        import anthropic
    except ImportError:
        logger.warning("anthropic SDK 미설치 - AI 문장 사용 불가")
        return None

    menu = random.choice(menus) if menus else None
    points = ", ".join(keyword_phrases) if keyword_phrases else "전반적으로 만족"
    prompt = (
        f"대표 메뉴: {menu or '(언급하지 않음)'}\n"
        f"손님이 고른 느낌: {points}\n"
        f"상황: {random.choice(SITUATIONS) or '특별히 없음'}\n"
        f"말투: {random.choice(STYLES)}\n"
        f"길이: 공백 포함 {min_len}~{max_len}자"
    )

    key = os.environ.get("ANTHROPIC_API_KEY") or _settings_key()
    client = anthropic.AsyncAnthropic(api_key=key, timeout=TIMEOUT_SECONDS, max_retries=0)
    try:
        response = await client.beta.messages.create(
            model=MODEL,
            max_tokens=2000,
            system=SYSTEM,
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIConnectionError as e:
        logger.warning("AI 문장 연결 오류/시간 초과: %s", e)
        return None
    except anthropic.RateLimitError:
        logger.warning("AI 문장 요청 한도 초과")
        return None
    except anthropic.APIStatusError as e:
        logger.warning("AI 문장 API 오류 %s: %s", e.status_code, e.message)
        return None
    finally:
        await client.close()

    if response.stop_reason == "refusal":
        return None
    text = _clean("".join(b.text for b in response.content if b.type == "text"))
    if not text or not (min_len <= len(text) <= max_len):
        return None
    return text

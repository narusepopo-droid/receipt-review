"""문자 알림 (알리고). 키가 없으면 모의 발송 (로그만)"""
import logging
import re

import httpx

from app.config import settings

logger = logging.getLogger("notify")


async def send_sms(phone: str, message: str) -> bool:
    digits = re.sub(r"\D", "", phone or "")
    if not re.fullmatch(r"01[016789]\d{7,8}", digits):
        return False
    if not (settings.ALIGO_KEY and settings.ALIGO_USER_ID and settings.ALIGO_SENDER):
        logger.warning("[모의 문자] ***-%s %s", digits[-4:], message)
        return False
    msg_type = "LMS" if len(message.encode("cp949", errors="replace")) > 90 else "SMS"
    data = {"key": settings.ALIGO_KEY, "user_id": settings.ALIGO_USER_ID, "sender": settings.ALIGO_SENDER,
            "receiver": digits, "msg": message, "msg_type": msg_type}
    if msg_type == "LMS":
        data["title"] = "플레이스마스터 안내"
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post("https://apis.aligo.in/send/", data=data)
        ok = str(r.json().get("result_code")) == "1"
        if not ok:
            logger.warning("문자 발송 실패: %s", r.text[:200])
        return ok
    except Exception as e:
        logger.warning("문자 발송 오류: %s", e)
        return False

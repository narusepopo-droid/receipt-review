"""
운영자 알림 (Phase 6-4)
- 매장 에이전트가 30분 넘게 끊기면 1번 알림, 복구되면 1번 알림
- 영업 시간대(10~23시, 한국 시간)에만 보냄 (밤에 매장 포스를 끄는 건 정상)
- 받는 곳: OPS_ALERT_PHONE + 알리고 키가 있으면 문자, 없으면 서버 로그만
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.store import Store, StoreStatus, Agent

logger = logging.getLogger("alerts")
KST = timezone(timedelta(hours=9))
OFFLINE_AFTER = timedelta(minutes=30)
ALERT_HOURS = range(10, 23)

# store_id → 끊김 알림을 보낸 시점의 마지막 하트비트 (재시작하면 비워짐 → 최대 1번 중복)
_alerted: dict[int, datetime] = {}


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


async def notify(message: str) -> bool:
    """운영자에게 알림. 보냈으면 True"""
    s = get_settings()
    logger.warning("[운영 알림] %s", message)
    if not (s.OPS_ALERT_PHONE and s.ALIGO_KEY and s.ALIGO_USER_ID and s.ALIGO_SENDER):
        return False
    try:
        from app.services.sms import _aligo_send
        ok, _, _ = await _aligo_send([s.OPS_ALERT_PHONE], f"[영수증리뷰] {message}", "LMS", "영수증리뷰 알림")
        return ok > 0
    except Exception as e:
        logger.error("alert send failed: %s", e)
        return False


async def check_agents(db: AsyncSession, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    sent = []
    stores = {s.id: s for s in (await db.execute(select(Store).where(Store.status == StoreStatus.ACTIVE))).scalars()}
    latest: dict[int, datetime] = {}
    for a in (await db.execute(select(Agent).where(Agent.last_heartbeat_at.isnot(None)))).scalars():
        hb = _aware(a.last_heartbeat_at)
        if a.store_id in stores and (a.store_id not in latest or hb > latest[a.store_id]):
            latest[a.store_id] = hb

    in_hours = now.astimezone(KST).hour in ALERT_HOURS
    for store_id, hb in latest.items():
        name = stores[store_id].name
        gap = now - hb
        if gap > OFFLINE_AFTER:
            # 최근 24시간 안에 살아 있었던 매장만 (오래 꺼진 매장은 반복 알림 안 함)
            if store_id not in _alerted and gap < timedelta(hours=24) and in_hours:
                _alerted[store_id] = hb
                msg = f"{name} 포스 프로그램 연결 끊김 ({int(gap.total_seconds() // 60)}분째). 포스 전원·인터넷 확인 필요"
                await notify(msg)
                sent.append(msg)
        elif store_id in _alerted:
            del _alerted[store_id]
            msg = f"{name} 포스 프로그램 연결 복구됨"
            await notify(msg)
            sent.append(msg)
    return sent

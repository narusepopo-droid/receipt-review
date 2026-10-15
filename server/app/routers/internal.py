"""서버끼리 쓰는 API (계정 서버 ↔ 영수증리뷰). 공유 비밀 헤더 필수, 외부에는 nginx 로 막음"""
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models.store import Store
from app.security import verify_password

router = APIRouter(prefix="/internal", tags=["internal"])


def _check(secret: str):
    if not settings.INTERNAL_SECRET or not secret or not hmac.compare_digest(secret, settings.INTERNAL_SECRET):
        raise HTTPException(status_code=403)


class LegacyLogin(BaseModel):
    email: str
    password: str


@router.post("/legacy-login")
async def legacy_login(req: LegacyLogin, x_internal_secret: str = Header(""), db: AsyncSession = Depends(get_db)):
    """예전 점주 계정(매장 아이디·비밀번호) 확인 → 계정 서버가 자동 이전에 사용"""
    _check(x_internal_secret)
    store = (await db.execute(select(Store).where(Store.admin_login_id == req.email.strip()))).scalar_one_or_none()
    if not store or not verify_password(req.password, store.admin_password_hash or ""):
        return {"ok": False}
    return {"ok": True, "store_name": store.name, "biz_no": store.biz_no or "",
            "stores": [{"id": store.id, "name": store.name, "biz_no": store.biz_no or "",
                        "store_code": store.store_code}]}


@router.get("/ops-summary")
async def ops_summary(x_internal_secret: str = Header(""), db: AsyncSession = Depends(get_db)):
    """마스터 관리자 페이지용 영수증리뷰 현황 숫자"""
    _check(x_internal_secret)
    from sqlalchemy import func
    from app.models.receipt import Receipt, ReceiptClassification, ReceiptStatus
    from app.models.session import ReviewSession
    from app.models.store import StoreStatus
    from app.routers.ops import _kst_day_start, _latest_agents, agent_health
    stores = (await db.execute(select(Store))).scalars().all()
    agents = await _latest_agents(db)
    active = [s for s in stores if s.status == StoreStatus.ACTIVE]
    offline = [s.name for s in active if agent_health(agents.get(s.id))[0] == "offline"]
    today = _kst_day_start()
    return {
        "stores": len(stores), "active_stores": len(active), "offline_stores": offline,
        "today_sessions": (await db.execute(select(func.count(ReviewSession.id)).where(
            ReviewSession.started_at >= today))).scalar() or 0,
        "today_completed": (await db.execute(select(func.count(ReviewSession.id)).where(
            ReviewSession.started_at >= today, ReviewSession.completed_at.isnot(None)))).scalar() or 0,
        "unclassified": (await db.execute(select(func.count(Receipt.id)).where(
            Receipt.classification == ReceiptClassification.UNCLASSIFIED,
            Receipt.status != ReceiptStatus.DISPOSED))).scalar() or 0,
    }


@router.get("/ops-stores")
async def ops_stores(x_internal_secret: str = Header(""), db: AsyncSession = Depends(get_db)):
    """마스터 '전체 회원' 화면용 매장 목록 (예전 매장 계정 포함)"""
    _check(x_internal_secret)
    from app.models.store import StoreStatus
    from app.routers.ops import _latest_agents, agent_health
    agents = await _latest_agents(db)
    out = []
    for s in (await db.execute(select(Store).order_by(Store.id))).scalars():
        out.append({"id": s.id, "name": s.name, "store_code": s.store_code, "login": s.admin_login_id or "",
                    "active": s.status == StoreStatus.ACTIVE, "pos": agent_health(agents.get(s.id))[0],
                    "created_at": s.created_at.isoformat() if s.created_at else ""})
    return {"stores": out}


# ───────────── 마스터 '매장 목록' (실시간 사용 여부 + 매장별 핵심 데이터) ─────────────
# 포스 프로그램은 켜져 있고 로그인돼 있으면 1분마다 신호(하트비트)를 보냄 → 3분 안에 신호가 왔으면 '사용 중'
LIVE_MINUTES = 3


def _iso(dt):
    from app.routers.ops import KST, _aware
    return _aware(dt).astimezone(KST).isoformat(timespec="seconds") if dt else None


def _live(agent) -> str:
    """live: 지금 사용 중 / idle: 잠깐 끊김(3~30분) / off: 꺼짐·로그아웃 / never: 설치 기록 없음"""
    from datetime import datetime, timedelta, timezone
    from app.routers.ops import _aware
    if not agent or not agent.last_heartbeat_at:
        return "never"
    gap = datetime.now(timezone.utc) - _aware(agent.last_heartbeat_at)
    if gap <= timedelta(minutes=LIVE_MINUTES):
        return "live"
    return "idle" if gap <= timedelta(minutes=30) else "off"


def _agent_info(agent) -> dict:
    from app.routers.ops import agent_health
    health, warn = agent_health(agent)
    return {"live": _live(agent), "health": health, "warning": warn,
            "version": agent.version if agent else None, "capture_mode": agent.capture_mode if agent else None,
            "last_heartbeat_at": _iso(agent.last_heartbeat_at) if agent else None,
            "last_capture_at": _iso(agent.last_capture_at) if agent else None,
            "queue_length": (agent.queue_length or 0) if agent else 0}


@router.get("/master-stores")
async def master_stores(x_internal_secret: str = Header(""), db: AsyncSession = Depends(get_db)):
    """매장 목록: 포스 프로그램 사용 여부 + 오늘 숫자"""
    _check(x_internal_secret)
    from sqlalchemy import func
    from app.models.receipt import Receipt, ReceiptClassification, ReceiptStatus
    from app.models.session import ReviewSession
    from app.models.store import StoreStatus
    from app.routers.ops import _kst_day_start, _latest_agents
    today = _kst_day_start()
    agents = await _latest_agents(db)

    async def grouped(q):
        return {sid: n for sid, n in (await db.execute(q)).all()}

    R, S = Receipt, ReviewSession
    rc_today = await grouped(select(R.store_id, func.count(R.id)).where(R.created_at >= today).group_by(R.store_id))
    amt_today = await grouped(select(R.store_id, func.coalesce(func.sum(R.amount), 0)).where(
        R.created_at >= today).group_by(R.store_id))
    avail = await grouped(select(R.store_id, func.count(R.id)).where(
        R.status == ReceiptStatus.AVAILABLE, R.classification == ReceiptClassification.NORMAL).group_by(R.store_id))
    ss_today = await grouped(select(S.store_id, func.count(S.id)).where(S.started_at >= today).group_by(S.store_id))
    done_today = await grouped(select(S.store_id, func.count(S.id)).where(
        S.started_at >= today, S.completed_at.isnot(None)).group_by(S.store_id))
    last_rc = await grouped(select(R.store_id, func.max(R.created_at)).group_by(R.store_id))
    last_ss = await grouped(select(S.store_id, func.max(S.started_at)).group_by(S.store_id))

    out = []
    for s in (await db.execute(select(Store).order_by(Store.id))).scalars():
        out.append({"id": s.id, "name": s.name, "store_code": s.store_code, "login": s.admin_login_id or "",
                    "active": s.status == StoreStatus.ACTIVE, "created_at": _iso(s.created_at),
                    "agent": _agent_info(agents.get(s.id)),
                    "today": {"receipts": rc_today.get(s.id, 0), "amount": int(amt_today.get(s.id, 0) or 0),
                              "sessions": ss_today.get(s.id, 0), "completed": done_today.get(s.id, 0)},
                    "available": avail.get(s.id, 0),
                    "last_receipt_at": _iso(last_rc.get(s.id)), "last_session_at": _iso(last_ss.get(s.id))})
    return {"stores": out, "live_minutes": LIVE_MINUTES}


@router.get("/master-stores/{store_id}")
async def master_store_detail(store_id: int, x_internal_secret: str = Header(""), db: AsyncSession = Depends(get_db)):
    """매장 한 곳 요약: 포스 연결, 오늘·7일·30일 숫자, 단계별 이탈, 고객, 설정, 최근 기록"""
    _check(x_internal_secret)
    from datetime import timedelta
    from sqlalchemy import func
    from app.models.customer import Customer, StoreCustomer
    from app.models.options import BenefitOption, ReviewCheck, StoreOptions
    from app.models.receipt import Receipt, ReceiptClassification, ReceiptStatus
    from app.models.session import ReviewSession
    from app.models.sms import SmsCampaign, SmsWallet
    from app.models.store import StoreSettings, StoreStatus
    from app.routers.ops import KST, _aware, _kst_day_start, _latest_agents

    s = await db.get(Store, store_id)
    if not s:
        raise HTTPException(status_code=404)
    today = _kst_day_start()
    d7, d30 = today - timedelta(days=6), today - timedelta(days=29)
    agent = (await _latest_agents(db)).get(s.id)
    R, S, SC = Receipt, ReviewSession, StoreCustomer

    async def scalar(q):
        return (await db.execute(q)).scalar() or 0

    async def funnel(since):
        base = [S.store_id == s.id, S.started_at >= since]
        n = lambda *extra: scalar(select(func.count(S.id)).where(*base, *extra))  # noqa: E731
        return {"started": await n(), "assigned": await n(S.assigned_at.isnot(None)),
                "downloaded": await n(S.downloaded_at.isnot(None)), "redirected": await n(S.redirected_at.isnot(None)),
                "completed": await n(S.completed_at.isnot(None)), "benefit": await n(S.benefit_given_at.isnot(None))}

    async def receipts(since):
        return {"count": await scalar(select(func.count(R.id)).where(R.store_id == s.id, R.created_at >= since)),
                "amount": int(await scalar(select(func.coalesce(func.sum(R.amount), 0)).where(
                    R.store_id == s.id, R.created_at >= since)))}

    # 최근 7일 날짜별
    rows_r = (await db.execute(select(R.created_at).where(R.store_id == s.id, R.created_at >= d7))).scalars().all()
    rows_s = (await db.execute(select(S.started_at, S.completed_at).where(S.store_id == s.id, S.started_at >= d7))).all()
    kd = lambda t: _aware(t).astimezone(KST).date()  # noqa: E731
    days = []
    for i in range(7):
        d = (d7 + timedelta(days=i)).date()
        days.append({"date": d.isoformat(), "receipts": sum(1 for t in rows_r if kd(t) == d),
                     "sessions": sum(1 for a, _ in rows_s if kd(a) == d),
                     "completed": sum(1 for a, c in rows_s if c and kd(a) == d)})

    cnt = lambda *w: scalar(select(func.count()).select_from(SC).where(SC.store_id == s.id, *w))  # noqa: E731
    customers = {"total": await cnt(), "new_30d": await cnt(SC.first_visit_at >= d30),
                 "returning": await cnt(SC.visit_count >= 2), "opt_in": await cnt(SC.marketing_opt_in.is_(True))}

    st = await db.get(StoreSettings, s.id)
    opt = await db.get(StoreOptions, s.id)
    ben = await db.get(BenefitOption, s.id)
    wallet = await db.get(SmsWallet, s.id)
    last_sms = (await db.execute(select(SmsCampaign).where(SmsCampaign.store_id == s.id)
                                 .order_by(SmsCampaign.scheduled_at.desc()).limit(1))).scalar_one_or_none()
    settings_info = {
        "benefit_text": (st.benefit_text if st else None) or "",
        "keywords": len((st.keywords or []) if st else []),
        "signature_menus": list((st.signature_menus or []) if st else [])[:10],
        "pin_required": bool(ben and ben.pin_required),
        "phone_verify": bool(opt and opt.phone_verify),
        "review_check": bool(opt and opt.review_check),
        "naver_place_id": (opt.naver_place_id if opt else None) or "",
        "paper_width": s.paper_width,
        "sms_balance": wallet.balance if wallet else 0,
        "last_sms": {"at": _iso(last_sms.scheduled_at), "status": last_sms.status.value,
                     "target": last_sms.target_count} if last_sms else None,
    }

    STEP = {"started": "번호 입력", "assigned": "영수증 받음", "downloaded": "영수증 저장", "redirected": "네이버 이동",
            "completed": "리뷰 완료", "benefit_given": "혜택 지급", "expired": "만료"}
    # 마스터(광고토대왕)는 동의서의 '수집·이용 주체'라 전체 번호를 봄 (점주 화면은 계속 가린 번호)
    from app.services.customers import decrypt_phone

    def full_phone(enc, last4):
        try:
            n = decrypt_phone(enc) if enc else ""
        except Exception:
            n = ""
        n = "".join(ch for ch in n if ch.isdigit())
        if len(n) == 11:
            return f"{n[:3]}-{n[3:7]}-{n[7:]}"
        if len(n) == 10:
            return f"{n[:3]}-{n[3:6]}-{n[6:]}"
        return n or (f"***-{last4}" if last4 else "****")

    recent_s = []
    q = (select(S, Customer.phone_enc, Customer.phone_last4).join(Customer, Customer.id == S.customer_id, isouter=True)
         .where(S.store_id == s.id).order_by(S.started_at.desc()).limit(10))
    for ss, enc, last4 in (await db.execute(q)).all():
        recent_s.append({"at": _iso(ss.started_at), "table": ss.table_no if ss.table_no not in (None, "", "0") else "",
                         "phone": full_phone(enc, last4),
                         "status": STEP.get(ss.status.value, ss.status.value), "completed": ss.completed_at is not None})
    customer_list = []
    q = (select(SC, Customer.phone_enc, Customer.phone_last4).join(Customer, Customer.id == SC.customer_id)
         .where(SC.store_id == s.id).order_by(SC.last_visit_at.desc()).limit(100))
    for sc_, enc, last4 in (await db.execute(q)).all():
        customer_list.append({"phone": full_phone(enc, last4), "visits": sc_.visit_count or 0,
                              "first": _iso(sc_.first_visit_at), "last": _iso(sc_.last_visit_at),
                              "opt_in": bool(sc_.marketing_opt_in)})
    recent_r = []
    for r in (await db.execute(select(R).where(R.store_id == s.id).order_by(R.created_at.desc()).limit(10))).scalars():
        recent_r.append({"at": _iso(r.created_at), "paid_at": _iso(r.paid_at), "amount": r.amount,
                         "card": r.card_issuer or "", "status": r.status.value,
                         "unclassified": r.classification == ReceiptClassification.UNCLASSIFIED})

    return {
        "store": {"id": s.id, "name": s.name, "store_code": s.store_code, "biz_no": s.biz_no or "",
                  "login": s.admin_login_id or "", "active": s.status == StoreStatus.ACTIVE,
                  "created_at": _iso(s.created_at)},
        "agent": _agent_info(agent),
        "receipts": {"today": await receipts(today), "d7": await receipts(d7), "d30": await receipts(d30),
                     "available": await scalar(select(func.count(R.id)).where(
                         R.store_id == s.id, R.status == ReceiptStatus.AVAILABLE,
                         R.classification == ReceiptClassification.NORMAL)),
                     "unclassified": await scalar(select(func.count(R.id)).where(
                         R.store_id == s.id, R.classification == ReceiptClassification.UNCLASSIFIED,
                         R.status != ReceiptStatus.DISPOSED))},
        "funnel": {"today": await funnel(today), "d7": await funnel(d7), "d30": await funnel(d30)},
        "days": days,
        "customers": customers,
        "reviews_verified": await scalar(select(func.count()).select_from(ReviewCheck).where(ReviewCheck.store_id == s.id)),
        "settings": settings_info,
        "recent_sessions": recent_s,
        "recent_receipts": recent_r,
        "customer_list": customer_list,
        "live_minutes": LIVE_MINUTES,
    }

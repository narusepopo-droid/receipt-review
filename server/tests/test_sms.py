"""홍보 문자 (Phase 8) 테스트: 수신동의자만, (광고)·수신거부 자동, 야간 차단, 모의/실발송, 잔액"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import settings
from app.services import sms as sms_service
from tests.test_web_pages import web  # noqa: F401  (fixture 재사용)

KST = timezone(timedelta(hours=9))


@pytest.fixture(autouse=True)
def daytime(monkeypatch):
    """테스트 시각과 관계없이 낮 시간으로"""
    monkeypatch.setattr(sms_service, "is_night", lambda dt: False)


async def join(web, phone, opt_in):
    r = await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": phone, "marketing_opt_in": opt_in})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_sms_only_opted_in_and_compliance_text(web, monkeypatch):
    await join(web, "010-1000-0001", True)
    await join(web, "010-1000-0002", False)
    await join(web, "010-1000-0003", True)
    await web.post("/api/v1/consent/withdraw", json={"phone": "010-1000-0003", "store_code": "WEB01"})

    await web.post("/admin/login", data={"login_id": "owner@test.com", "password": "pw1234!"})
    p = (await web.post("/admin/sms/preview", json={"body": "금요일 사리 무료!"})).json()
    assert p["targets"] == 1                                   # 동의 1명만 (거부·미동의 제외)
    assert p["final_text"].startswith("(광고)테스트매장")
    assert "/optout/WEB01" in p["final_text"]

    # 모의 발송 (알리고 키 없음)
    r = (await web.post("/admin/sms/send", json={"body": "금요일 사리 무료!"})).json()
    assert r["success"] and r["test_mode"] and r["success_count"] == 1
    assert (await web.get("/admin/sms")).status_code == 200


@pytest.mark.asyncio
async def test_sms_real_send_uses_balance_and_only_consented_numbers(web, monkeypatch):
    await join(web, "010-2000-0001", True)
    await join(web, "010-2000-0002", False)
    monkeypatch.setattr(settings, "ALIGO_KEY", "k")
    monkeypatch.setattr(settings, "ALIGO_USER_ID", "u")
    monkeypatch.setattr(settings, "ALIGO_SENDER", "0212345678")
    sent = {}

    async def fake_send(numbers, text, msg_type, title):
        sent["numbers"] = numbers
        return len(numbers), 0, "ok"
    monkeypatch.setattr(sms_service, "_aligo_send", fake_send)

    await web.post("/admin/login", data={"login_id": "owner@test.com", "password": "pw1234!"})
    r = await web.post("/admin/sms/send", json={"body": "이벤트"})
    assert r.status_code == 400 and "잔액" in r.json()["error"]

    await web.post("/ops/login", data={"username": settings.OPS_USERNAME, "password": settings.OPS_PASSWORD})
    assert (await web.post("/ops/stores/1/sms-charge", data={"amount": "1000"})).json()["balance"] == 1000

    r = (await web.post("/admin/sms/send", json={"body": "이벤트"})).json()
    assert r["success"] and not r["test_mode"]
    assert sent["numbers"] == ["01020000001"]                   # 미동의 번호는 절대 포함 안 됨
    page = (await web.get("/admin/sms")).text
    assert "980원" in page or "950원" in page                   # 잔액 차감


@pytest.mark.asyncio
async def test_sms_night_blocked_and_schedule(web, monkeypatch):
    await join(web, "010-3000-0001", True)
    await web.post("/admin/login", data={"login_id": "owner@test.com", "password": "pw1234!"})
    monkeypatch.setattr(sms_service, "is_night", lambda dt: dt.astimezone(KST).hour >= 21 or dt.astimezone(KST).hour < 8)
    tomorrow = (datetime.now(KST) + timedelta(days=1)).date()
    r = await web.post("/admin/sms/send", json={"body": "야간", "scheduled_at": f"{tomorrow}T22:00"})
    assert r.status_code == 400 and "야간" in r.json()["error"]
    r = (await web.post("/admin/sms/send", json={"body": "예약", "scheduled_at": f"{tomorrow}T11:00"})).json()
    assert r["success"] and r["status"] == "scheduled"
    page = (await web.get("/admin/sms")).text
    assert "예약" in page

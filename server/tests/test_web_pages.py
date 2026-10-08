"""
점주 관리자 웹 / 운영자 웹 화면 점검
- 사이트 가입(예전 PBKDF2 방식 비밀번호) 점주가 관리자 웹에 로그인 가능
- 로그인 5회 실패 시 잠금
- 모든 화면이 오류(500) 없이 열림
- 에이전트 토큰 갱신
"""
import hashlib
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.models.base import Base
from app.models.store import Store, StoreSettings
from app.config import settings
from app.security import login_limiter


def legacy_hash(pw: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), settings.SECRET_KEY[:16].encode(), 100000).hex()


@pytest_asyncio.fixture
async def web():
    from app.main import app
    from app.db import get_db

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as s:
        store = Store(name="테스트매장", store_code="WEB01", admin_login_id="owner@test.com",
                      admin_password_hash=legacy_hash("pw1234!"))
        s.add(store)
        await s.flush()
        s.add(StoreSettings(store_id=store.id))
        await s.commit()

    async def _get_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    login_limiter._fails.clear()
    login_limiter._locked_until.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    await engine.dispose()


ADMIN_PAGES = ["/admin/dashboard", "/admin/customers", "/admin/receipts", "/admin/phrases",
               "/admin/settings", "/admin/tables"]
OPS_PAGES = ["/ops/dashboard", "/ops/stores", "/ops/stores/new", "/ops/agents", "/ops/receipts/unclassified",
             "/ops/stats", "/ops/installer", "/ops/signups", "/ops/api/agents/status"]


@pytest.mark.asyncio
async def test_signup_owner_can_login_to_admin_and_open_all_pages(web):
    r = await web.post("/admin/login", data={"login_id": "owner@test.com", "password": "pw1234!"})
    assert r.status_code == 302, r.text[:300]
    for page in ADMIN_PAGES:
        r = await web.get(page)
        assert r.status_code == 200, f"{page}: {r.status_code} {r.text[:300]}"


@pytest.mark.asyncio
async def test_agent_login_with_legacy_password(web):
    r = await web.post("/auth/login", json={"email": "owner@test.com", "password": "pw1234!"})
    assert r.json()["success"] is True and r.json()["token"]


@pytest.mark.asyncio
async def test_admin_lockout_after_5_failures(web):
    for _ in range(5):
        await web.post("/admin/login", data={"login_id": "owner@test.com", "password": "wrong"})
    r = await web.post("/admin/login", data={"login_id": "owner@test.com", "password": "pw1234!"})
    assert r.status_code == 200 and "너무 많습니다" in r.text


@pytest.mark.asyncio
async def test_ops_login_and_pages(web):
    r = await web.post("/ops/login", data={"username": settings.OPS_USERNAME, "password": settings.OPS_PASSWORD})
    assert r.status_code == 303
    for page in OPS_PAGES:
        r = await web.get(page)
        assert r.status_code == 200, f"{page}: {r.status_code} {r.text[:300]}"


@pytest.mark.asyncio
async def test_heartbeat_refreshes_old_token(web, monkeypatch):
    from app.routers import auth
    old_time = datetime.now() - timedelta(days=3)

    class OldDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return old_time

    monkeypatch.setattr(auth, "datetime", OldDatetime)
    old_token = auth.generate_token(1)
    monkeypatch.setattr(auth, "datetime", datetime)

    r = await web.post("/agent/v1/heartbeat", headers={"Authorization": f"Bearer {old_token}"},
                       json={"version": "1.1.1", "capture_mode": "serial", "last_capture_at": None, "queue_length": 0})
    assert r.status_code == 200, r.text
    new = r.json()["new_token"]
    assert new and new != old_token and auth.verify_token(new) == 1


@pytest.mark.asyncio
async def test_pages_with_real_data(web, tmp_path, monkeypatch):
    """영수증 업로드 → 손님 참여 → 배정 데이터가 있는 상태에서도 모든 화면 정상"""
    import sys
    from pathlib import Path
    from datetime import timezone
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import make_sample_escpos as samples
    from app.routers.auth import generate_token

    monkeypatch.setattr(settings, "RECEIPT_IMAGE_DIR", str(tmp_path / "img"))
    monkeypatch.setattr(settings, "RECEIPT_RAW_DIR", str(tmp_path / "raw"))
    auth = {"Authorization": f"Bearer {generate_token(1)}"}

    for data in (samples.card_receipt(), samples.card_receipt().replace(b"30012345", b"30099999")):
        r = await web.post("/agent/v1/receipts", headers=auth,
                           files={"file": ("r.bin", data, "application/octet-stream")},
                           data={"captured_at": datetime.now(timezone.utc).isoformat()})
        assert r.json()["classification"] == "normal", r.text
    r = await web.post("/agent/v1/heartbeat", headers=auth,
                       json={"version": "1.1.1", "capture_mode": "serial", "last_capture_at": None, "queue_length": 0})
    assert r.status_code == 200

    r = await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": "010-1111-2222", "marketing_opt_in": True})
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    assert (await web.post(f"/api/v1/session/{sid}/assign")).status_code == 200

    # 손님 화면
    for page in ["/t/WEB01/1", "/t/WEB01/1/keywords", "/t/WEB01/1/result", "/t/WEB01/1/complete"]:
        r = await web.get(page)
        assert r.status_code in (200, 302, 307), f"{page}: {r.status_code} {r.text[:300]}"

    await web.post("/admin/login", data={"login_id": "owner@test.com", "password": "pw1234!"})
    for page in ADMIN_PAGES + ["/admin/receipts?status=available", "/admin/receipts?status=assigned"]:
        r = await web.get(page)
        assert r.status_code == 200, f"{page}: {r.status_code} {r.text[:300]}"
    assert "010-1111-2222" not in (await web.get("/admin/customers")).text  # 원본 번호 노출 금지

    await web.post("/ops/login", data={"username": settings.OPS_USERNAME, "password": settings.OPS_PASSWORD})
    for page in OPS_PAGES + ["/ops/stores/1", "/ops/api/stats/1"]:
        r = await web.get(page)
        assert r.status_code == 200, f"{page}: {r.status_code} {r.text[:300]}"


@pytest.mark.asyncio
async def test_customer_flow_uses_real_assigned_receipt(web, tmp_path, monkeypatch):
    """손님 흐름: 결과 화면이 샘플이 아닌 실제 배정 영수증·문구를 보여주고, 쿠키로 복귀"""
    import re
    import sys
    from pathlib import Path
    from datetime import timezone
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import make_sample_escpos as samples
    from app.routers.auth import generate_token

    monkeypatch.setattr(settings, "RECEIPT_IMAGE_DIR", str(tmp_path / "img"))
    monkeypatch.setattr(settings, "RECEIPT_RAW_DIR", str(tmp_path / "raw"))
    await web.post("/agent/v1/receipts", headers={"Authorization": f"Bearer {generate_token(1)}"},
                   files={"file": ("r.bin", samples.card_receipt(), "application/octet-stream")},
                   data={"captured_at": datetime.now(timezone.utc).isoformat()})

    # 영수증 받기 전엔 결과 화면 → 번호 입력으로
    r = await web.get("/t/WEB01/3/result")
    assert r.status_code == 302 and r.headers["location"].endswith("/t/WEB01/3")

    r = await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": "010-3333-4444"})
    sid = r.json()["session_id"]
    assert "rr_sid" in r.headers.get("set-cookie", "")

    assert (await web.post(f"/api/v1/session/{sid}/keywords", json={"keywords": ["맛있어요"]})).status_code == 200
    r = await web.get("/t/WEB01/3/result")
    assert r.status_code == 200
    assert "sample_receipt" not in r.text
    m = re.search(r'src="(/api/v1/receipt-image/[^"]+)"', r.text)
    assert m, r.text[:500]
    img = await web.get(m.group(1).replace("&amp;", "&"))
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"

    # 문구 수정 저장, 다른 문구, 이벤트
    assert (await web.post(f"/api/v1/session/{sid}/text", json={"text": "직접 쓴 문구입니다"})).status_code == 200
    assert "직접 쓴 문구입니다" in (await web.get("/t/WEB01/3/result")).text
    r = await web.post(f"/api/v1/session/{sid}/regenerate")
    assert r.status_code == 200 and r.json()["generated_text"]
    assert (await web.post(f"/api/v1/session/{sid}/event", json={"event": "downloaded"})).status_code == 200
    assert (await web.post(f"/api/v1/session/{sid}/event", json={"event_type": "redirected"})).status_code == 200

    # 완료 화면 → completed, 이후 downloaded 이벤트가 와도 상태가 뒤로 가지 않음
    assert (await web.get("/t/WEB01/3/complete")).status_code == 200
    await web.post(f"/api/v1/session/{sid}/event", json={"event": "downloaded"})
    from app.db import get_db
    from app.main import app
    from app.models.session import ReviewSession, SessionStatus
    from sqlalchemy import select
    from uuid import UUID
    async for s in app.dependency_overrides[get_db]():
        sess = (await s.execute(select(ReviewSession).where(ReviewSession.id == UUID(sid)))).scalar_one()
        assert sess.status == SessionStatus.COMPLETED and sess.completed_at and sess.downloaded_at

    # QR 다시 찍으면 결과 화면으로 복귀
    r = await web.get("/t/WEB01/3")
    assert r.status_code == 302 and r.headers["location"].endswith("/result")


@pytest.mark.asyncio
async def test_no_receipt_shows_retry(web):
    r = await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": "010-5555-6666"})
    assert r.status_code == 200
    r = await web.get("/t/WEB01/1/result")
    assert r.status_code == 200 and "다시 시도" in r.text


@pytest.mark.asyncio
async def test_pin_bruteforce_limited(web):
    r = await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": "010-7777-8888"})
    sid = r.json()["session_id"]
    codes = [(await web.post(f"/api/v1/session/{sid}/benefit", json={"pin": f"{i:04d}"})).status_code for i in range(7)]
    assert 429 in codes

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

    assert (await web.post(f"/api/v1/session/{sid}/keywords", json={"keywords": ["맛있어요"]})).status_code == 400   # 3개 미만 거부
    assert (await web.post(f"/api/v1/session/{sid}/keywords", json={"keywords": ["맛있어요", "친절해요", "양이 많아요"]})).status_code == 200
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


@pytest.mark.asyncio
async def test_ops_store_management_and_agent_status(web, tmp_path, monkeypatch):
    """운영자: 매장 등록·수정·정지, 에이전트 상태, 판별불가 분류, 통계, 설치파일"""
    import json
    from datetime import timezone
    from app.services import release as rel
    from app.routers.auth import generate_token

    await web.post("/ops/login", data={"username": settings.OPS_USERNAME, "password": settings.OPS_PASSWORD})

    r = await web.post("/ops/stores/new", data={
        "name": "새매장", "biz_no": "111-22-33333", "naver_review_url": "https://m.place.naver.com/x",
        "paper_width": "576", "admin_login_id": "new@test.com", "admin_password": "pw!", "staff_pin": "1234"})
    assert r.status_code == 303
    page = (await web.get("/ops/stores")).text
    assert "새매장" in page

    # 새 매장 점주가 바로 로그인 가능
    r = await web.post("/auth/login", json={"email": "new@test.com", "password": "pw!"})
    assert r.json()["success"], r.text
    new_id = r.json()["store_id"]

    r = await web.post(f"/ops/stores/{new_id}", data={"name": "새매장2", "status": "paused"})
    assert r.status_code == 303
    assert "새매장2" in (await web.get(f"/ops/stores/{new_id}")).text
    assert (await web.post(f"/ops/stores/{new_id}/activate")).json()["status"] == "active"

    # 에이전트 상태: 하트비트 전 offline → 후 warning(수신 0건)
    agents = (await web.get("/ops/api/agents/status")).json()["agents"]
    me = next(a for a in agents if a["store_id"] == new_id)
    assert me["status"] == "offline"
    await web.post("/agent/v1/heartbeat", headers={"Authorization": f"Bearer {generate_token(new_id)}"},
                   json={"version": "1.1.2", "capture_mode": "serial", "last_capture_at": None, "queue_length": 0})
    me = next(a for a in (await web.get("/ops/api/agents/status")).json()["agents"] if a["store_id"] == new_id)
    assert me["status"] == "warning" and "0건" in me["warning_message"]
    assert (await web.get("/ops/agents")).status_code == 200

    # 판별 불가 영수증 (금액 있음 + 승인번호 없음) → 수동 정상 분류
    monkeypatch.setattr(settings, "RECEIPT_IMAGE_DIR", str(tmp_path / "img"))
    monkeypatch.setattr(settings, "RECEIPT_RAW_DIR", str(tmp_path / "raw"))
    data = ("맛집\n" + "\n".join(f"품목{i}  1,000" for i in range(5)) + "\n합계 5,000\n").encode("cp949")
    up = await web.post("/agent/v1/receipts", headers={"Authorization": f"Bearer {generate_token(new_id)}"},
                        files={"file": ("r.bin", data, "application/octet-stream")},
                        data={"captured_at": datetime.now(timezone.utc).isoformat()})
    assert up.json()["classification"] == "unclassified", up.text
    rid = up.json()["receipt_id"]
    assert rid in (await web.get("/ops/receipts/unclassified")).text
    assert (await web.post(f"/ops/receipts/{rid}/classify", data={"classification": "normal"})).json()["success"]
    assert rid not in (await web.get("/ops/receipts/unclassified")).text

    # 통계
    st = (await web.get(f"/ops/api/stats/{new_id}")).json()
    assert st["store_name"] == "새매장2" and len(st["hourly_distribution"]) == 24
    assert (await web.get("/ops/stats")).status_code == 200
    assert (await web.get("/ops/dashboard")).status_code == 200

    # 설치 파일 업로드 → 최신 지정
    monkeypatch.setattr(rel, "INSTALLER_DIR", str(tmp_path / "dl"))
    monkeypatch.setattr(rel, "LATEST_JSON", str(tmp_path / "dl" / "latest.json"))
    r = await web.post("/ops/installer/upload", data={"version": "9.0.0"},
                       files={"file": ("x.zip", b"PKzip", "application/zip")})
    assert r.json()["filename"] == "ReceiptTap_v9.0.0.zip", r.text
    assert (await web.post("/ops/installer/9.0.0/set-latest")).json()["success"]
    assert json.loads((tmp_path / "dl" / "latest.json").read_text(encoding="utf-8"))["version"] == "9.0.0"
    assert "9.0.0" in (await web.get("/ops/installer")).text


@pytest.mark.asyncio
async def test_owner_phrases_apply_to_next_customer(web, tmp_path, monkeypatch):
    """점주가 문구 설정을 바꾸면 다음 손님부터 바로 반영 (Phase 4 완료 기준)"""
    import sys
    from pathlib import Path
    from datetime import timezone
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import make_sample_escpos as samples
    from app.routers.auth import generate_token

    await web.post("/admin/login", data={"login_id": "owner@test.com", "password": "pw1234!"})
    payload = {
        "keywords": [{"label": "국물맛집", "default": True, "phrases": ["국물이 정말 진하고 깊었어요."]},
                     {"label": "친절해요", "default": True}, {"label": "양이 많아요", "default": False}],
        "signature_menus": ["얼큰나베"], "text_min_len": 10, "text_max_len": 300,
    }
    prev = (await web.post("/admin/phrases/preview", json=payload)).json()["texts"]
    assert len(prev) == 5 and all(p["text"] for p in prev)
    assert (await web.post("/admin/phrases/save", json=payload)).json()["success"]
    assert "국물이 정말 진하고 깊었어요." in (await web.get("/admin/phrases")).text

    monkeypatch.setattr(settings, "RECEIPT_IMAGE_DIR", str(tmp_path / "img"))
    monkeypatch.setattr(settings, "RECEIPT_RAW_DIR", str(tmp_path / "raw"))
    await web.post("/agent/v1/receipts", headers={"Authorization": f"Bearer {generate_token(1)}"},
                   files={"file": ("r.bin", samples.card_receipt(), "application/octet-stream")},
                   data={"captured_at": datetime.now(timezone.utc).isoformat()})
    sid = (await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": "010-9999-0000"})).json()["session_id"]
    assert (await web.post(f"/api/v1/session/{sid}/keywords", json={"keywords": ["국물맛집", "친절해요", "양이 많아요"]})).status_code == 200
    text = (await web.post(f"/api/v1/session/{sid}/assign")).json()["generated_text"]
    assert "국물이 정말 진하고 깊었어요." in text, text      # 점주가 등록한 문장이 바로 반영


@pytest.mark.asyncio
async def test_table_sign_pdf_and_png(web):
    await web.post("/admin/login", data={"login_id": "owner@test.com", "password": "pw1234!"})
    r = await web.get("/admin/tables/download?format=pdf&count=3&start=2")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    r = await web.get("/admin/tables/download?format=png&count=2")
    assert r.status_code == 200 and r.content[:2] == b"PK"


@pytest.mark.asyncio
async def test_phone_validation_withdraw_and_assign_limit(web, tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    from datetime import timezone
    from sqlalchemy import select
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import make_sample_escpos as samples
    from app.routers.auth import generate_token
    from app.db import get_db
    from app.main import app
    from app.models.store import StoreSettings
    from app.models.customer import StoreCustomer, ConsentLog

    # 번호 형식
    assert (await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": "abc"})).status_code == 422
    assert (await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": "02-123-4567"})).status_code == 422

    # 수신동의 → 수신거부
    r = await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": "010-2222-3333", "marketing_opt_in": True})
    assert r.status_code == 200
    assert (await web.get("/optout/WEB01")).status_code == 200
    r = await web.post("/api/v1/consent/withdraw", json={"phone": "01022223333", "store_code": "WEB01"})
    assert r.status_code == 200
    async for s in app.dependency_overrides[get_db]():
        sc = (await s.execute(select(StoreCustomer))).scalars().all()
        assert sc and not sc[0].marketing_opt_in and sc[0].opt_out_at
        logs = (await s.execute(select(ConsentLog))).scalars().all()
        assert any(l.action.value == "withdraw" for l in logs)
        # 시간당 상한 1
        st = (await s.execute(select(StoreSettings))).scalar_one()
        st.hourly_assign_limit = 1
        await s.commit()

    monkeypatch.setattr(settings, "RECEIPT_IMAGE_DIR", str(tmp_path / "img"))
    monkeypatch.setattr(settings, "RECEIPT_RAW_DIR", str(tmp_path / "raw"))
    auth = {"Authorization": f"Bearer {generate_token(1)}"}
    for no in (b"30012345", b"30012346"):
        await web.post("/agent/v1/receipts", headers=auth,
                       files={"file": ("r.bin", samples.card_receipt().replace(b"30012345", no), "application/octet-stream")},
                       data={"captured_at": datetime.now(timezone.utc).isoformat()})
    s1 = (await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": "010-4444-0001"})).json()["session_id"]
    s2 = (await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": "010-4444-0002"})).json()["session_id"]
    assert (await web.post(f"/api/v1/session/{s1}/assign")).status_code == 200
    assert (await web.post(f"/api/v1/session/{s2}/assign")).status_code == 503   # 상한 도달

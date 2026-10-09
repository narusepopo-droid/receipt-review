"""통합 계정 서버 연동 (계정 서버 응답은 가짜)"""
import pytest

from app.config import settings
from app.services import account_link
from tests.test_web_pages import web  # noqa: F401  (fixture)


class FakeResp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def json(self):
        return self._d


@pytest.fixture
def linked(monkeypatch):
    monkeypatch.setattr(settings, "ACCOUNT_API_URL", "http://acct")
    monkeypatch.setattr(settings, "INTERNAL_SECRET", "s")
    account_link.clear_cache()
    calls = []
    state = {"login": None, "owner": None, "usable": True}

    async def fake_post(path, body, internal=False):
        calls.append((path, body))
        if path == "/api/v1/license/login":
            return state["login"]
        if path == "/internal/owner-login":
            return state["owner"]
        if path == "/internal/review-store":
            return FakeResp({"usable": state["usable"]})
        if path == "/internal/link-store":
            return FakeResp({"ok": True})
        return None

    monkeypatch.setattr(account_link, "_post", fake_post)
    yield state, calls
    account_link.clear_cache()


@pytest.mark.asyncio
async def test_agent_login_via_account_creates_and_links_store(web, linked):
    state, calls = linked
    state["login"] = FakeResp({"ok": True, "store": {"id": 5, "name": "새 매장", "review_store_id": None},
                               "expires_at": None})
    r = (await web.post("/auth/login", json={"email": "a@b.com", "password": "pw", "device_id": "PC1"})).json()
    assert r["success"] and r["store_name"] == "새 매장" and r["token"]
    assert any(p == "/internal/link-store" and b["store_id"] == 5 for p, b in calls)


@pytest.mark.asyncio
async def test_agent_login_choose_store_and_device_mismatch(web, linked):
    state, _ = linked
    state["login"] = FakeResp({"ok": False, "code": "choose_store", "stores": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]})
    r = (await web.post("/auth/login", json={"email": "a@b.com", "password": "pw", "device_id": "PC1"})).json()
    assert not r["success"] and r["code"] == "choose_store" and len(r["stores"]) == 2
    state["login"] = FakeResp({"ok": False, "code": "device_mismatch", "message": "다른 PC"}, 403)
    r = (await web.post("/auth/login", json={"email": "a@b.com", "password": "pw", "device_id": "PC2", "store_id": 1})).json()
    assert not r["success"] and r["code"] == "device_mismatch"


@pytest.mark.asyncio
async def test_account_down_falls_back_to_legacy(web, linked):
    state, _ = linked
    state["login"] = None      # 계정 서버 연결 실패
    r = (await web.post("/auth/login", json={"email": "owner@test.com", "password": "pw1234!", "device_id": "PC1"})).json()
    assert r["success"]


@pytest.mark.asyncio
async def test_expired_store_blocked(web, linked):
    state, _ = linked
    state["usable"] = False
    state["login"] = None
    r = (await web.post("/auth/login", json={"email": "owner@test.com", "password": "pw1234!"})).json()
    assert not r["success"] and r["code"] == "expired"
    r = await web.post("/api/v1/session/start?store_code=WEB01",
                       json={"phone": "01012345678", "privacy_agreed": True, "marketing_opt_in": False})
    assert r.status_code == 403 and "쉬는 중" in r.text


@pytest.mark.asyncio
async def test_owner_web_multi_store_choose(web, linked):
    state, _ = linked
    state["owner"] = FakeResp({"ok": True, "stores": [
        {"id": 1, "name": "1호점", "review_store_id": None, "usable": True},
        {"id": 2, "name": "2호점", "review_store_id": None, "usable": True},
        {"id": 3, "name": "만료점", "review_store_id": None, "usable": False}]})
    r = await web.post("/admin/login", data={"login_id": "a@b.com", "password": "pw"})
    assert r.status_code == 302 and r.headers["location"] == "/admin/choose-store"
    page = (await web.get("/admin/choose-store")).text
    assert "1호점" in page and "2호점" in page and "만료점" not in page
    r = await web.get("/admin/dashboard")
    assert r.status_code == 200 and "매장 바꾸기" in r.text


@pytest.mark.asyncio
async def test_owner_web_no_usable_store(web, linked):
    state, _ = linked
    state["owner"] = FakeResp({"ok": True, "stores": [{"id": 3, "name": "만료점", "usable": False}]})
    r = await web.post("/admin/login", data={"login_id": "a@b.com", "password": "pw"})
    assert r.status_code == 200 and "이용 중인 영수증리뷰 매장이 없습니다" in r.text


@pytest.mark.asyncio
async def test_internal_legacy_login(web, linked):
    r = await web.post("/internal/legacy-login", json={"email": "owner@test.com", "password": "pw1234!"})
    assert r.status_code == 403
    h = {"X-Internal-Secret": "s"}
    r = (await web.post("/internal/legacy-login", json={"email": "owner@test.com", "password": "pw1234!"}, headers=h)).json()
    assert r["ok"] and r["stores"][0]["store_code"] == "WEB01"
    r = (await web.post("/internal/legacy-login", json={"email": "owner@test.com", "password": "x"}, headers=h)).json()
    assert not r["ok"]


@pytest.mark.asyncio
async def test_heartbeat_reports_license(web, linked):
    state, _ = linked
    state["login"] = None
    tok = (await web.post("/auth/login", json={"email": "owner@test.com", "password": "pw1234!"})).json()["token"]
    state["usable"] = False
    account_link.clear_cache()
    r = (await web.post("/agent/v1/heartbeat", headers={"Authorization": f"Bearer {tok}"},
                        json={"version": "1.2.0", "capture_mode": "spmc", "queue_length": 0})).json()
    assert r["success"] and r["license_ok"] is False


@pytest.mark.asyncio
async def test_sso_from_account_mypage(web, linked):
    from itsdangerous import URLSafeTimedSerializer
    tok = URLSafeTimedSerializer("s", salt="review-sso").dumps(
        {"email": "a@b.com", "pick": 9, "stores": [{"id": 8, "name": "1호점", "review_store_id": None},
                                                    {"id": 9, "name": "2호점", "review_store_id": None}]})
    r = await web.get(f"/admin/sso?t={tok}")
    assert r.status_code == 302 and r.headers["location"] == "/admin/dashboard"
    page = (await web.get("/admin/dashboard")).text
    assert "2호점" in page and "매장 바꾸기" in page
    r = await web.get("/admin/sso?t=bad")
    assert "만료" in r.text

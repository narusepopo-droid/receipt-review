"""화면·API 흐름 테스트 (Firebase·토스는 가짜로 대체)"""
import re  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import firebase  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base, License, Order, Plan, PlanKind, Product  # noqa: E402
from app.seed import seed  # noqa: E402

USERS: dict = {}


async def fake_sign_up(email, password):
    if email in USERS:
        raise firebase.FirebaseError("EMAIL_EXISTS")
    USERS[email] = password
    return {"localId": "uid_" + re.sub(r"\W", "", email), "email": email}


async def fake_sign_in(email, password):
    if USERS.get(email) != password:
        raise firebase.FirebaseError("INVALID_LOGIN_CREDENTIALS")
    return {"localId": "uid_" + re.sub(r"\W", "", email), "email": email}


@pytest_asyncio.fixture
async def client(monkeypatch):
    USERS.clear()
    monkeypatch.setattr(firebase, "sign_up", fake_sign_up)
    monkeypatch.setattr(firebase, "sign_in", fake_sign_in)

    async def no_legacy(db, email, pw, acc=None):
        return None
    from app import legacy as legacy_mod
    monkeypatch.setattr(legacy_mod, "try_migrate_review_owner", no_legacy)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.drop_all)
        await c.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        await seed(db)
    from app.routers import auth
    auth._hits.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t",
                                 follow_redirects=True) as c:
        yield c


async def signup(c, email="owner@test.com", products=("receipt_review",), store="테스트 매장"):
    data = {"name": "홍길동", "phone": "010-1234-5678", "email": email, "password": "password1",
            "password2": "password1", "agree": "1", "store_name": store}
    for p in products:
        data[f"p_{p}"] = "1"
    return await c.post("/signup", data=data)


async def login(c, email, pw="password1"):
    return await c.post("/login", data={"email": email, "password": pw})


@pytest.mark.asyncio
async def test_signup_login_dashboard(client):
    r = await signup(client, products=("receipt_review",))
    assert r.status_code == 200 and "담당자 승인 후" in r.text
    assert "테스트 매장" in r.text and "승인 대기" in r.text
    r = await client.get("/my/orders")
    assert "결제 내역" in r.text
    r = await client.get("/my/profile")
    assert "010-1234-5678" in r.text
    await client.get("/logout")
    r = await client.get("/my")
    assert "로그인" in r.text and str(r.url).endswith("/login?next=/my")
    r = await login(client, "owner@test.com", "wrong")
    assert "올바르지 않습니다" in r.text
    r = await login(client, "owner@test.com")
    assert "안녕하세요" in r.text


@pytest.mark.asyncio
async def test_signup_validation(client):
    r = await client.post("/signup", data={"email": "bad", "password": "1", "password2": "2"})
    assert "이름을 입력" in r.text and "이메일을 정확히" in r.text and "상품을 하나 이상" in r.text
    await signup(client)
    await client.get("/logout")
    r = await signup(client)
    assert "이미 가입된 이메일" in r.text


@pytest.mark.asyncio
async def test_non_operator_blocked(client):
    await signup(client)
    r = await client.get("/ops")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_operator_full_flow(client):
    # 점주 가입 + 매장 2개
    await signup(client)
    r = await client.post("/my/stores", data={"name": "2호점"})
    assert "2호점" in r.text
    await client.get("/logout")
    # 운영자
    await signup(client, email="ops@test.com", products=("receipt_review",))
    for path in ("/ops", "/ops/accounts", "/ops/products", "/ops/promotions", "/ops/orders", "/ops/notifications"):
        r = await client.get(path)
        assert r.status_code == 200, path
    r = await client.get("/ops/accounts?q=홍길동")
    assert "owner@test.com" in r.text
    async with SessionLocal() as db:
        lics = (await db.execute(select(License).order_by(License.id))).scalars().all()
        owner_lic = lics[0]
        y1 = (await db.execute(select(Plan).where(Plan.product_id == owner_lic.product_id,
                                                  Plan.kind == PlanKind.PREPAID, Plan.months == 12))).scalar_one()
    # 승인 → 무제한
    r = await client.post(f"/ops/licenses/{owner_lic.id}", data={"action": "approve"})
    assert "승인했습니다" in r.text
    # 만료일 지정 → 연장 → 정지 → 해제 → PC 해제
    r = await client.post(f"/ops/licenses/{owner_lic.id}", data={"action": "set_expiry", "expires_at": "2030-01-31"})
    assert "2030.01.31" in r.text
    r = await client.post(f"/ops/licenses/{owner_lic.id}", data={"action": "extend", "months": "1", "days": "0"})
    assert "2030.02.28" in r.text
    r = await client.post(f"/ops/licenses/{owner_lic.id}", data={"action": "grant", "plan_id": str(y1.id)})
    assert "2031.02.28" in r.text
    r = await client.post(f"/ops/licenses/{owner_lic.id}", data={"action": "suspend"})
    assert "정지했습니다" in r.text
    r = await client.post(f"/ops/licenses/{owner_lic.id}", data={"action": "resume"})
    assert "정지를 풀었습니다" in r.text
    # 요금제·프로모션 수정
    r = await client.post("/ops/plans", data={"product_id": str(owner_lic.product_id), "name": "3년 일시불",
                                              "kind": "prepaid", "months": "36", "discount_pct": "35", "public": "1",
                                              "sort": "22", "lifetime_months": "36"})
    assert "3년 일시불" in r.text
    r = await client.post("/ops/promotions", data={"name": "오픈 기념", "code": "open10", "kind": "percent",
                                                   "value": "10", "active": "1"})
    assert "OPEN10" in r.text
    async with SessionLocal() as db:
        prod = await db.get(Product, owner_lic.product_id)
    r = await client.post(f"/ops/products/{prod.id}", data={"name": prod.name, "monthly_price": "45000",
                                                            "signup_policy": "payment", "active": "1", "tagline": "t",
                                                            "download_url": ""})
    assert "45000" in r.text or "45,000" in r.text


@pytest.mark.asyncio
async def test_purchase_manual_then_operator_confirms(client):
    await signup(client)
    async with SessionLocal() as db:
        lic = (await db.execute(select(License))).scalars().first()
        y1 = (await db.execute(select(Plan).where(Plan.product_id == lic.product_id, Plan.kind == PlanKind.PREPAID,
                                                  Plan.months == 12))).scalar_one()
    r = await client.get(f"/my/buy/{lic.id}")
    assert "1년 일시불" in r.text and "영구 이용권" in r.text
    q = (await client.post("/my/quote", json={"items": [{"license_id": lic.id, "plan_id": y1.id}]})).json()
    assert q["amount"] == 397800
    q = (await client.post("/my/quote", json={"items": [{"license_id": lic.id, "plan_id": y1.id}],
                                               "promo_code": "NOPE"})).json()
    assert q["promo_error"]
    r = (await client.post("/my/checkout", json={"items": [{"license_id": lic.id, "plan_id": y1.id}]})).json()
    assert r["manual"]       # 토스 키 없음 → 입금 신청
    await client.get("/logout")
    await signup(client, email="ops@test.com", products=("receipt_review",))
    async with SessionLocal() as db:
        order = (await db.execute(select(Order))).scalars().first()
    r = await client.post(f"/ops/orders/{order.id}", data={"action": "mark_paid"})
    assert "입금 확인 처리했습니다" in r.text
    async with SessionLocal() as db:
        lic = await db.get(License, lic.id)
        from app import licensing
        assert licensing.state(lic) == "active" and 360 <= licensing.days_left(lic) <= 366


@pytest.mark.asyncio
async def test_other_owner_cannot_touch_license(client):
    await signup(client)
    async with SessionLocal() as db:
        lic = (await db.execute(select(License))).scalars().first()
    await client.get("/logout")
    await signup(client, email="other@test.com")
    r = await client.get(f"/my/buy/{lic.id}")
    assert r.status_code == 404
    r = await client.post(f"/my/licenses/{lic.id}/device-reset")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_license_api_device_lock_and_store_choice(client):
    await signup(client)
    await client.post("/my/stores", data={"name": "2호점"})
    body = {"email": "owner@test.com", "password": "password1", "product": "receipt_review",
            "device_id": "PC-1", "device_name": "카운터"}
    r = (await client.post("/api/v1/license/login", json=body)).json()
    assert r["code"] == "choose_store" and len(r["stores"]) == 2
    sid = r["stores"][0]["id"]
    r = (await client.post("/api/v1/license/login", json={**body, "store_id": sid})).json()
    assert r["code"] == "pending"       # 승인 전
    async with SessionLocal() as db:
        from app import licensing
        lic = (await db.execute(select(License).where(License.store_id == sid))).scalar_one()
        free = (await db.execute(select(Plan).where(Plan.product_id == lic.product_id,
                                                    Plan.kind == PlanKind.FREE))).scalar_one()
        await licensing.apply_plan(db, lic, free, "test")
        await db.commit()
    r = (await client.post("/api/v1/license/login", json={**body, "store_id": sid})).json()
    assert r["ok"] and r["unlimited"] and r["store"]["name"] == "테스트 매장"
    token = r["token"]
    r = (await client.post("/api/v1/license/check", json={"token": token, "device_id": "PC-1"})).json()
    assert r["ok"]
    # 다른 PC
    r = (await client.post("/api/v1/license/login", json={**body, "store_id": sid, "device_id": "PC-2"})).json()
    assert r["code"] == "device_mismatch"
    r = (await client.post("/api/v1/license/check", json={"token": token, "device_id": "PC-2"})).json()
    assert r["code"] == "device_mismatch"
    # 이 PC가 등록된 매장은 선택 없이 자동
    r = (await client.post("/api/v1/license/login", json=body)).json()
    assert r["ok"] and r["store"]["id"] == sid
    # 잘못된 토큰·비밀번호
    r = await client.post("/api/v1/license/check", json={"token": "x", "device_id": "PC-1"})
    assert r.status_code == 401
    r = await client.post("/api/v1/license/login", json={**body, "password": "nope"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_internal_requires_secret(client):
    r = await client.post("/internal/review-store", json={"review_store_id": 1})
    assert r.status_code == 403
    r = await client.post("/internal/review-store", json={"review_store_id": 1},
                          headers={"X-Internal-Secret": "internal-test"})
    assert r.json()["state"] == "unknown"


@pytest.mark.asyncio
async def test_internal_owner_login(client):
    await signup(client)
    h = {"X-Internal-Secret": "internal-test"}
    r = (await client.post("/internal/owner-login", json={"email": "owner@test.com", "password": "password1"},
                           headers=h)).json()
    assert r["ok"] and r["stores"][0]["name"] == "테스트 매장" and r["stores"][0]["state"] == "pending"
    r = (await client.post("/internal/owner-login", json={"email": "owner@test.com", "password": "x"},
                           headers=h)).json()
    assert not r["ok"]
    # 매장 연결
    sid = (await client.post("/internal/owner-login", json={"email": "owner@test.com", "password": "password1"},
                             headers=h)).json()["stores"][0]["id"]
    r = await client.post("/internal/link-store", json={"store_id": sid, "review_store_id": 77,
                                                         "review_store_code": "ABC"}, headers=h)
    assert r.json()["ok"]
    r = (await client.post("/internal/review-store", json={"review_store_id": 77}, headers=h)).json()
    assert r["state"] == "pending" and r["usable"] is False



@pytest.mark.asyncio
async def test_plma_signup_goes_to_plma_site_until_key(client):
    r = await client.get("/signup?product=plma,receipt_review")
    assert "signup.html" in r.text and 'name="p_plma"' not in r.text
    r = await signup(client, products=("receipt_review", "plma"))
    assert "따로 신청" in r.text
    r = await client.get("/api/v1/pricing", headers={"Origin": "https://placemaster.co.kr"})
    d = r.json()
    assert r.headers.get("access-control-allow-origin") == "https://placemaster.co.kr"
    assert all(not p["enabled"] and p["plans"] == [] for p in d["products"]) and d["bundle_pct"] == 10


@pytest.mark.asyncio
async def test_master_api(client, monkeypatch):
    """마스터 전용 API: 마스터 토큰만 통과, 관리 키 없으면 안내, 운영 화면 바로 열기"""
    from app.config import settings

    async def fake_verify(tok):
        return {"uid": settings.MASTER_UID if tok == "master" else "someone", "email": "boss@test.com"}
    monkeypatch.setattr(firebase, "verify_id_token", fake_verify)
    monkeypatch.setattr(settings, "MASTER_SA_FILE", "")
    h = {"Authorization": "Bearer master", "Origin": "https://placemaster.co.kr"}

    r = await client.options("/api/v1/master/summary", headers={"Origin": "https://placemaster.co.kr"})
    assert r.status_code == 204 and r.headers["access-control-allow-origin"] == "https://placemaster.co.kr"
    assert (await client.get("/api/v1/master/summary")).status_code == 403
    assert (await client.get("/api/v1/master/summary", headers={"Authorization": "Bearer other"})).status_code == 403
    r = await client.get("/api/v1/master/summary", headers=h)
    assert r.status_code == 200 and r.json()["ok"] and "licenses" in r.json()
    assert r.headers["access-control-allow-origin"] == "https://placemaster.co.kr"

    # 관리 키 없으면 삭제·비밀번호는 안내 (503)
    r = await client.post("/api/v1/master/plma/delete", headers=h, json={"uid": "abc"})
    assert r.status_code == 503 and not r.json()["ok"]
    # 마스터 자신은 삭제 불가
    r = await client.post("/api/v1/master/plma/delete", headers=h, json={"uid": settings.MASTER_UID})
    assert r.status_code == 400
    r = await client.post("/api/v1/master/plma/password", headers=h, json={"uid": "abc", "password": "12"})
    assert r.status_code == 400
    # 남의 토큰으로는 삭제 불가
    r = await client.post("/api/v1/master/plma/delete", headers={"Authorization": "Bearer other"}, json={"uid": "abc"})
    assert r.status_code == 403

    # 운영 화면 바로 열기 → 운영자 로그인 상태로 /ops
    r = await client.post("/api/v1/master/sso", headers=h)
    link = r.json()["account_ops"]
    assert "/ops/sso?t=" in link and "/ops/sso?t=" in r.json()["review_ops"]
    r = await client.get("/ops/sso?t=" + link.split("t=")[1])
    assert r.status_code == 200 and str(r.url).endswith("/ops")
    r = await client.get("/ops/sso?t=bad", follow_redirects=False)
    assert r.status_code == 303 and "/login" in r.headers["location"]


@pytest.mark.asyncio
async def test_master_customers(client, monkeypatch):
    """전체 회원: 통합 계정 회원·이용권이 합쳐져 나오고, 운영 화면 바로 열기는 /ops 안쪽 주소로만 이동"""
    from app.config import settings

    async def fake_verify(tok):
        return {"uid": settings.MASTER_UID, "email": "boss@test.com"}
    monkeypatch.setattr(firebase, "verify_id_token", fake_verify)
    monkeypatch.setattr(settings, "MASTER_SA_FILE", "")
    await signup(client, email="shop@test.com", products=("receipt_review",), store="가게A")
    await client.get("/logout")
    h = {"Authorization": "Bearer master"}
    r = await client.get("/api/v1/master/customers", headers=h)
    j = r.json()
    assert r.status_code == 200 and j["ok"] and j["plma_ok"] is False
    row = [x for x in j["rows"] if x["email"] == "shop@test.com"][0]
    assert row["account_id"] and row["rr"] and row["rr"][0]["store"] == "가게A"

    r = await client.post("/api/v1/master/sso", headers=h, json={"account_next": f"/ops/accounts/{row['account_id']}"})
    t = r.json()["account_ops"].split("t=")[1]
    r = await client.get("/ops/sso?t=" + t, follow_redirects=False)
    assert r.headers["location"].endswith(f"/ops/accounts/{row['account_id']}")
    r = await client.post("/api/v1/master/sso", headers=h, json={"account_next": "https://evil.com"})
    r = await client.get("/ops/sso?t=" + r.json()["account_ops"].split("t=")[1], follow_redirects=False)
    assert r.headers["location"].endswith("/ops")


async def _ops_login(client):
    await client.get("/logout")
    await signup(client, email="ops@test.com", products=("receipt_review",))


async def _set_policy(code, policy):
    from app.models import SignupPolicy
    async with SessionLocal() as db:
        p = (await db.execute(select(Product).where(Product.code == code))).scalar_one()
        p.signup_policy = SignupPolicy(policy)
        await db.commit()


@pytest.mark.asyncio
async def test_paid_mode_blocks_free_paths(client):
    """결제제: 무료 승인 막힘, 연결 안 된 영수증 매장 사용 불가, 무료 무제한 → 기한 일괄 전환"""
    from app import licensing
    await signup(client)
    async with SessionLocal() as db:
        lic = (await db.execute(select(License))).scalars().first()
    h = {"X-Internal-Secret": "internal-test"}
    assert (await client.post("/internal/review-store", json={"review_store_id": 999}, headers=h)).json()["usable"]
    await _ops_login(client)
    await _set_policy("receipt_review", "payment")
    r = await client.post(f"/ops/licenses/{lic.id}", data={"action": "approve"})
    assert "무료 승인은 막혀" in r.text
    assert (await client.post("/internal/review-store", json={"review_store_id": 999}, headers=h)).json()["usable"] is False
    # 무료로 쓰던 이용권은 일괄로 기한 지정
    await _set_policy("receipt_review", "approval")
    await client.post(f"/ops/licenses/{lic.id}", data={"action": "approve"})
    async with SessionLocal() as db:
        assert (await db.get(License, lic.id)).expires_at is None
        pid = (await db.get(License, lic.id)).product_id
    r = await client.post(f"/ops/products/{pid}/free-until", data={"until": "2099-01-31"})
    assert "1개를 2099-01-31까지로" in r.text
    async with SessionLocal() as db:
        l2 = await db.get(License, lic.id)
        assert l2.expires_at is not None and licensing.state(l2) == "active"


@pytest.mark.asyncio
async def test_monthly_hidden_without_toss_and_blocked_purchases(client):
    from app.models import LicenseStatus
    await signup(client)
    async with SessionLocal() as db:
        lic = (await db.execute(select(License))).scalars().first()
        m12 = (await db.execute(select(Plan).where(Plan.product_id == lic.product_id, Plan.kind == PlanKind.MONTHLY,
                                                   Plan.months == 12))).scalar_one()
        y1 = (await db.execute(select(Plan).where(Plan.product_id == lic.product_id, Plan.kind == PlanKind.PREPAID,
                                                  Plan.months == 12))).scalar_one()
    r = await client.get(f"/my/buy/{lic.id}")
    assert "월 결제 · 12개월 약정" not in r.text and "1년 일시불" in r.text
    r = await client.post("/my/checkout", json={"items": [{"license_id": lic.id, "plan_id": m12.id}]})
    assert r.status_code == 400
    async with SessionLocal() as db:
        l = await db.get(License, lic.id)
        l.status = LicenseStatus.SUSPENDED
        await db.commit()
    r = await client.post("/my/checkout", json={"items": [{"license_id": lic.id, "plan_id": y1.id}]})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_login_redirect_keeps_payment_query(client):
    r = await client.get("/my/pay/success?paymentKey=pk1&orderId=o1&amount=100", follow_redirects=False)
    loc = r.headers["location"]
    assert "paymentKey" in loc and "orderId" in loc and "amount" in loc


@pytest.mark.asyncio
async def test_plma_payment_syncs_to_program(client, monkeypatch):
    """플마 결제(입금 확인) → 플마 프로그램이 보는 Firestore 에 기간 반영"""
    calls = []

    async def fake_sync(uid, **kw):
        calls.append((uid, kw))
        return True
    monkeypatch.setattr(firebase, "sa_available", lambda: True)
    monkeypatch.setattr(firebase, "sync_plma_user", fake_sync)
    await signup(client, email="pm@test.com")
    from app import licensing
    from app.models import Account
    async with SessionLocal() as db:
        acc = (await db.execute(select(Account).where(Account.email == "pm@test.com"))).scalar_one()
        prod = (await db.execute(select(Product).where(Product.code == "plma"))).scalar_one()
        lic = await licensing.get_or_create(db, acc, prod, None)
        await db.commit()
        y1 = (await db.execute(select(Plan).where(Plan.product_id == prod.id, Plan.kind == PlanKind.PREPAID,
                                                  Plan.months == 12))).scalar_one()
    r = (await client.post("/my/checkout", json={"items": [{"license_id": lic.id, "plan_id": y1.id}]})).json()
    assert r["manual"] and not calls
    await _ops_login(client)
    async with SessionLocal() as db:
        order = (await db.execute(select(Order))).scalars().first()
    await client.post(f"/ops/orders/{order.id}", data={"action": "mark_paid"})
    await client.post(f"/ops/orders/{order.id}", data={"action": "mark_paid"})     # 두 번 눌러도 한 번만
    assert len(calls) == 1
    uid, kw = calls[0]
    assert uid == acc.firebase_uid and kw["active"] is True and kw["expires_at"] >= "2027-"
    assert kw.get("device_id") is None        # PC 기록은 건드리지 않음
    async with SessionLocal() as db:
        l = await db.get(License, lic.id)
        assert 360 <= licensing.days_left(l) <= 367
    # PC 변경 → 프로그램 쪽 PC 기록도 지움
    await client.post(f"/ops/licenses/{lic.id}", data={"action": "device_reset"})
    assert calls[-1][1].get("device_id") == ""

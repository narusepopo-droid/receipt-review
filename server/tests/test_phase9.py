"""Phase 9: 휴대폰 인증번호, 선택 기능 설정"""
import pytest

from app.config import settings
from tests.test_web_pages import web  # noqa: F401


async def owner(web):
    await web.post("/admin/login", data={"login_id": "owner@test.com", "password": "pw1234!"})


@pytest.mark.asyncio
async def test_phone_verify_flow(web, monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", True)          # 모의 발송 코드를 응답으로 받기
    await owner(web)
    assert (await web.post("/admin/options/save", json={"phone_verify": True})).json()["success"]
    assert "인증번호 받기" in (await web.get("/t/WEB01/1")).text

    # 인증 없이 참여 불가
    r = await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": "010-1212-3434"})
    assert r.status_code == 403

    code = (await web.post("/api/v1/otp/send", json={"phone": "010-1212-3434", "store_code": "WEB01"})).json()["dev_code"]
    wrong = "000000" if code != "000000" else "111111"
    assert (await web.post("/api/v1/otp/verify", json={"phone": "01012123434", "code": wrong})).status_code == 400
    assert (await web.post("/api/v1/otp/verify", json={"phone": "01012123434", "code": code})).status_code == 200
    assert (await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": "010-1212-3434"})).status_code == 200

    # 다른 번호는 여전히 막힘, 같은 코드 재사용 불가
    assert (await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": "010-5656-7878"})).status_code == 403
    assert (await web.post("/api/v1/otp/verify", json={"phone": "01012123434", "code": code})).status_code == 400


@pytest.mark.asyncio
async def test_otp_bruteforce_and_rate_limit(web, monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", True)
    code = (await web.post("/api/v1/otp/send", json={"phone": "010-9090-1010", "store_code": "WEB01"})).json()["dev_code"]
    for i in range(5):
        await web.post("/api/v1/otp/verify", json={"phone": "01090901010", "code": f"{(int(code) + 1 + i) % 1000000:06d}"})
    # 5번 틀린 뒤엔 맞는 코드도 무효
    assert (await web.post("/api/v1/otp/verify", json={"phone": "01090901010", "code": code})).status_code == 400
    statuses = [(await web.post("/api/v1/otp/send", json={"phone": "010-9090-1010", "store_code": "WEB01"})).status_code for _ in range(3)]
    assert 429 in statuses


@pytest.mark.asyncio
async def test_options_require_place_for_review_check(web):
    await owner(web)
    r = await web.post("/admin/options/save", json={"review_check": True})
    assert r.status_code == 400
    r = await web.post("/admin/options/save", json={"review_check": True,
                                                     "naver_place_id": "https://m.place.naver.com/restaurant/1234567890/home"})
    assert r.json()["naver_place_id"] == "1234567890"
    assert "1234567890" in (await web.get("/admin/settings")).text


@pytest.mark.asyncio
async def test_ai_text_used_when_enabled_and_fallback_when_fails(web, tmp_path, monkeypatch):
    import sys
    from pathlib import Path
    from datetime import datetime, timezone
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import make_sample_escpos as samples
    from app.routers.auth import generate_token
    from app.review import ai_text

    monkeypatch.setattr(settings, "RECEIPT_IMAGE_DIR", str(tmp_path / "img"))
    monkeypatch.setattr(settings, "RECEIPT_RAW_DIR", str(tmp_path / "raw"))
    for no in (b"30012345", b"30012399"):
        await web.post("/agent/v1/receipts", headers={"Authorization": f"Bearer {generate_token(1)}"},
                       files={"file": ("r.bin", samples.card_receipt().replace(b"30012345", no), "application/octet-stream")},
                       data={"captured_at": datetime.now(timezone.utc).isoformat()})
    await owner(web)
    await web.post("/admin/options/save", json={"ai_text": True})

    calls = {}

    async def fake_generate(menus, phrases, mn, mx):
        calls["phrases"] = phrases
        return "점심에 왔는데 국물이 정말 진하고 직원분들도 친절하셨어요. 또 올게요."
    monkeypatch.setattr(ai_text, "is_available", lambda: True)
    monkeypatch.setattr(ai_text, "generate", fake_generate)
    sid = (await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": "010-3131-4141"})).json()["session_id"]
    await web.post(f"/api/v1/session/{sid}/keywords", json={"keywords": ["친절해요"]})
    text = (await web.post(f"/api/v1/session/{sid}/assign")).json()["generated_text"]
    assert text.startswith("점심에 왔는데") and calls["phrases"]

    # AI 실패 → 기존 조합 방식
    async def failing(*a):
        return None
    monkeypatch.setattr(ai_text, "generate", failing)
    sid2 = (await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": "010-3131-5151"})).json()["session_id"]
    text2 = (await web.post(f"/api/v1/session/{sid2}/assign")).json()["generated_text"]
    assert text2 and not text2.startswith("점심에 왔는데")


@pytest.mark.asyncio
async def test_ai_text_bad_key_returns_none(monkeypatch):
    """잘못된 키 → 오류를 삼키고 None (손님 흐름은 기존 방식으로 계속)"""
    from app.review import ai_text
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-invalid-test-key")
    assert await ai_text.generate(["김치찌개"], ["정말 맛있었어요."], 20, 150) is None


@pytest.mark.asyncio
async def test_review_check_matches_posted_review(web, tmp_path, monkeypatch):
    """손님에게 준 문구가 네이버 리뷰에 (조금 고쳐서라도) 올라오면 확인됨으로 집계"""
    import sys
    from pathlib import Path
    from datetime import datetime, timezone
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import make_sample_escpos as samples
    from app.routers.auth import generate_token
    from app.services import review_check
    from app.db import get_db
    from app.main import app

    monkeypatch.setattr(settings, "RECEIPT_IMAGE_DIR", str(tmp_path / "img"))
    monkeypatch.setattr(settings, "RECEIPT_RAW_DIR", str(tmp_path / "raw"))
    for no in (b"30012345", b"30012388"):
        await web.post("/agent/v1/receipts", headers={"Authorization": f"Bearer {generate_token(1)}"},
                       files={"file": ("r.bin", samples.card_receipt().replace(b"30012345", no), "application/octet-stream")},
                       data={"captured_at": datetime.now(timezone.utc).isoformat()})
    await owner(web)
    await web.post("/admin/options/save", json={"review_check": True, "naver_place_id": "1234567890"})
    texts = []
    for phone in ("010-6161-0001", "010-6161-0002"):
        sid = (await web.post("/api/v1/session/start?store_code=WEB01", json={"phone": phone})).json()["session_id"]
        texts.append((await web.post(f"/api/v1/session/{sid}/assign")).json()["generated_text"])

    fake = [{"id": "r1", "body": texts[0].replace(".", "!") + " 사장님 최고예요", "created": "10.9.목"},
            {"id": "r2", "body": "전혀 다른 손님의 리뷰입니다. 분위기가 좋네요.", "created": "10.9.목"}]

    async def fake_fetch(place_id, client=None):
        assert place_id == "1234567890"
        return fake
    monkeypatch.setattr(review_check, "fetch_reviews", fake_fetch)
    async for s in app.dependency_overrides[get_db]():
        assert await review_check.run_all(s) == 1        # 첫 손님만 확인됨
        assert await review_check.run_all(s) == 0        # 중복 집계 없음
    assert "네이버에서 확인된 리뷰" in (await web.get("/admin/dashboard")).text


def test_parse_reviews_from_apollo_state():
    from app.services.review_check import parse_reviews
    html = ('<script>window.__APOLLO_STATE__ = {"VisitorReview:abc:true": {"id": "abc", "body": "맛있어요", '
            '"created": "10.9.목"}, "Other:1": {}};\nwindow.x=1;</script>')
    assert parse_reviews(html) == [{"id": "abc", "body": "맛있어요", "created": "10.9.목"}]

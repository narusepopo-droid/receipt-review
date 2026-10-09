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

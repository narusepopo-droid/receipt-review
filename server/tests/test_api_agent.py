"""
에이전트 API 테스트 (실제 흐름)
- 로그인 토큰(Bearer)으로 인증
- 샘플 ESC/POS 바이트 업로드 → 분류 → 마스킹 → PNG 생성 → DB 저장
- 취소 영수증 업로드 시 기존 영수증 폐기
- 주방 주문서·재출력은 저장 안 함
- 하트비트
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.models.base import Base
from app.models.store import Store, Agent
from app.models.receipt import Receipt, ReceiptStatus
from app.routers.auth import generate_token

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import make_sample_escpos as samples  # noqa: E402


@pytest_asyncio.fixture
async def api(tmp_path, monkeypatch):
    from app.main import app
    from app.db import get_db
    from app.config import settings

    monkeypatch.setattr(settings, "RECEIPT_IMAGE_DIR", str(tmp_path / "img"))
    monkeypatch.setattr(settings, "RECEIPT_RAW_DIR", str(tmp_path / "raw"))

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as s:
        store = Store(name="맛있는김치찌개", store_code="TEST01", paper_width=576)
        s.add(store)
        await s.commit()
        store_id = store.id

    async def _get_db():
        async with factory() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.headers["Authorization"] = f"Bearer {generate_token(store_id)}"
        yield client, factory, store_id
    app.dependency_overrides.clear()
    await engine.dispose()


async def upload(client, data: bytes):
    return await client.post(
        "/agent/v1/receipts",
        files={"file": ("r.bin", data, "application/octet-stream")},
        data={"captured_at": datetime.now(timezone.utc).isoformat(), "capture_mode": "serial",
              "agent_version": "1.1.0"},
    )


async def receipts(factory):
    async with factory() as s:
        return (await s.execute(select(Receipt))).scalars().all()


@pytest.mark.asyncio
async def test_upload_card_receipt_creates_masked_png(api):
    client, factory, _ = api
    r = await upload(client, samples.card_receipt())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] and body["classification"] == "normal"

    rows = await receipts(factory)
    assert len(rows) == 1
    rec = rows[0]
    assert rec.status == ReceiptStatus.AVAILABLE
    assert rec.approval_no == "30012345"
    assert rec.amount == 30000
    assert os.path.exists(rec.image_path) and os.path.exists(rec.raw_bytes_path)
    # 마스킹: 저장된 텍스트에 휴대폰 번호가 남지 않음
    assert "010-1234-5678" not in (rec.raw_text or "")


@pytest.mark.asyncio
async def test_cancel_disposes_existing(api):
    client, factory, _ = api
    await upload(client, samples.card_receipt())
    img = (await receipts(factory))[0].image_path
    assert os.path.exists(img)

    r = await upload(client, samples.card_receipt(cancel=True))
    assert r.json()["classification"] == "cancelled"

    rows = await receipts(factory)
    assert len(rows) == 1
    assert rows[0].status == ReceiptStatus.DISPOSED
    assert not os.path.exists(img)          # 폐기 = 이미지 파일 삭제
    assert rows[0].image_path is None


@pytest.mark.asyncio
async def test_footer_cancel_notice_is_still_normal(api):
    """'교환/환불/취소 시 영수증 지참' 안내 문구가 있어도 정상 영수증"""
    client, factory, _ = api
    data = samples.card_receipt().replace(
        "이용해 주셔서 감사합니다".encode("cp949"), "교환/환불/취소 시 영수증 지참".encode("cp949"))
    r = await upload(client, data)
    assert r.json()["classification"] == "normal"


@pytest.mark.asyncio
async def test_kitchen_and_reprint_not_stored(api):
    client, factory, _ = api
    r = await upload(client, samples.kitchen_order())
    assert r.json()["classification"] == "kitchen"
    await upload(client, samples.card_receipt())
    r = await upload(client, samples.card_receipt())
    assert r.json()["classification"] == "reprint"
    assert len(await receipts(factory)) == 1


@pytest.mark.asyncio
async def test_upload_requires_auth(api):
    client, _, _ = api
    r = await client.post(
        "/agent/v1/receipts",
        files={"file": ("r.bin", b"x", "application/octet-stream")},
        data={"captured_at": datetime.now(timezone.utc).isoformat()},
        headers={"Authorization": "Bearer invalid"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_heartbeat_updates_agent(api):
    client, factory, store_id = api
    r = await client.post("/agent/v1/heartbeat", json={
        "version": "1.1.0", "capture_mode": "serial", "last_capture_at": None, "queue_length": 3,
    })
    assert r.status_code == 200, r.text
    async with factory() as s:
        agent = (await s.execute(select(Agent).where(Agent.store_id == store_id))).scalar_one()
        assert agent.version == "1.1.0" and agent.queue_length == 3

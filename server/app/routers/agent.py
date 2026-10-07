"""포스 에이전트 API - 활성화, 영수증 업로드, 하트비트"""
import os
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.config import get_settings
from app.models import Store, Agent, Receipt
from app.models.receipt import ReceiptClassification, ReceiptStatus
from app.receipt.escpos_parser import parse_escpos
from app.receipt.classifier import classify_receipt, ReceiptType
from app.receipt.masking import mask_parsed_receipt
from app.receipt.renderer import render_receipt

router = APIRouter(prefix="/agent/v1", tags=["agent"])
settings = get_settings()


class ActivateRequest(BaseModel):
    activation_code: str


class ActivateResponse(BaseModel):
    success: bool
    agent_key: Optional[str] = None
    store_name: Optional[str] = None
    message: str


class HeartbeatRequest(BaseModel):
    version: str
    capture_mode: str
    last_capture_at: Optional[datetime] = None
    queue_length: int = 0


class HeartbeatResponse(BaseModel):
    success: bool
    server_time: datetime


class ReceiptUploadResponse(BaseModel):
    success: bool
    receipt_id: Optional[str] = None
    classification: Optional[str] = None
    message: str


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def verify_agent_key(
    x_agent_key: str = Header(...),
    db: AsyncSession = Depends(get_db)
) -> Agent:
    key_hash = hash_key(x_agent_key)

    stmt = select(Agent).where(Agent.agent_key_hash == key_hash)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(status_code=401, detail="Invalid agent key")

    return agent


@router.post("/activate", response_model=ActivateResponse)
async def activate_agent(
    request: ActivateRequest,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Agent).where(
        Agent.activation_code == request.activation_code,
        Agent.activation_expires_at > datetime.now(timezone.utc)
    )
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()

    if not agent:
        return ActivateResponse(
            success=False,
            message="유효하지 않거나 만료된 활성화 코드입니다."
        )

    stmt = select(Store).where(Store.id == agent.store_id)
    result = await db.execute(stmt)
    store = result.scalar_one_or_none()

    agent_key = secrets.token_urlsafe(32)
    agent.agent_key_hash = hash_key(agent_key)
    agent.activation_code = None
    agent.activation_expires_at = None

    await db.commit()

    return ActivateResponse(
        success=True,
        agent_key=agent_key,
        store_name=store.name if store else None,
        message="활성화 성공"
    )


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    request: HeartbeatRequest,
    agent: Agent = Depends(verify_agent_key),
    db: AsyncSession = Depends(get_db)
):
    agent.version = request.version
    agent.capture_mode = request.capture_mode
    agent.last_heartbeat_at = datetime.now(timezone.utc)
    agent.last_capture_at = request.last_capture_at
    agent.queue_length = request.queue_length

    await db.commit()

    return HeartbeatResponse(
        success=True,
        server_time=datetime.now(timezone.utc)
    )


@router.post("/receipts", response_model=ReceiptUploadResponse)
async def upload_receipt(
    file: UploadFile = File(...),
    captured_at: datetime = Form(...),
    capture_mode: str = Form("serial"),
    agent_version: str = Form("1.0.0"),
    agent: Agent = Depends(verify_agent_key),
    db: AsyncSession = Depends(get_db)
):
    raw_bytes = await file.read()

    if not raw_bytes:
        return ReceiptUploadResponse(
            success=False,
            message="빈 파일"
        )

    agent.last_capture_at = captured_at
    agent.version = agent_version
    agent.capture_mode = capture_mode

    parsed = parse_escpos(raw_bytes)

    if parsed.approval_no:
        stmt = select(Receipt.approval_no).where(
            Receipt.store_id == agent.store_id,
            Receipt.status != ReceiptStatus.DISPOSED
        )
        result = await db.execute(stmt)
        existing_approval_nos = {r[0] for r in result.fetchall() if r[0]}
    else:
        existing_approval_nos = set()

    classification = classify_receipt(parsed, existing_approval_nos)

    if classification.should_dispose_existing and classification.existing_approval_no:
        stmt = select(Receipt).where(
            Receipt.store_id == agent.store_id,
            Receipt.approval_no == classification.existing_approval_no,
            Receipt.status != ReceiptStatus.DISPOSED
        )
        result = await db.execute(stmt)
        existing_receipts = result.scalars().all()

        for receipt in existing_receipts:
            receipt.status = ReceiptStatus.DISPOSED
            receipt.disposed_at = datetime.now(timezone.utc)
            receipt.dispose_reason = "cancelled"

    if not classification.should_store:
        await db.commit()
        return ReceiptUploadResponse(
            success=True,
            classification=classification.type.value,
            message=f"저장하지 않음: {classification.reason}"
        )

    masked = mask_parsed_receipt(parsed)

    receipt_id = uuid4()

    raw_dir = settings.RECEIPT_RAW_DIR
    img_dir = settings.RECEIPT_IMAGE_DIR
    os.makedirs(raw_dir, exist_ok=True)
    os.makedirs(img_dir, exist_ok=True)

    raw_path = os.path.join(raw_dir, f"{receipt_id}.bin")
    img_path = os.path.join(img_dir, f"{receipt_id}.png")

    with open(raw_path, "wb") as f:
        f.write(raw_bytes)

    stmt = select(Store.paper_width).where(Store.id == agent.store_id)
    result = await db.execute(stmt)
    paper_width = result.scalar() or 576

    render_receipt(masked, img_path, paper_width)

    paid_at = None
    if parsed.paid_at:
        try:
            paid_at = datetime.strptime(parsed.paid_at, "%Y-%m-%d %H:%M:%S")
            paid_at = paid_at.replace(tzinfo=timezone.utc)
        except:
            paid_at = captured_at

    receipt = Receipt(
        id=receipt_id,
        store_id=agent.store_id,
        approval_no=parsed.approval_no,
        paid_at=paid_at or captured_at,
        amount=parsed.amount,
        card_issuer=parsed.card_issuer,
        items=[{"name": item.get("name"), "qty": item.get("qty"), "price": item.get("price")}
               for item in parsed.items] if parsed.items else None,
        raw_text=masked.raw_text,
        raw_bytes_path=raw_path,
        image_path=img_path,
        classification=ReceiptClassification.NORMAL if classification.type == ReceiptType.NORMAL else ReceiptClassification.UNCLASSIFIED,
        status=ReceiptStatus.AVAILABLE,
    )

    db.add(receipt)
    await db.commit()

    return ReceiptUploadResponse(
        success=True,
        receipt_id=str(receipt_id),
        classification=classification.type.value,
        message="업로드 성공"
    )


@router.get("/latest")
async def get_latest_version():
    return {
        "version": "1.0.0",
        "download_url": "/download/ReceiptTap_Setup.exe",
        "release_notes": "초기 버전",
    }

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
from app.routers.auth import verify_token

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


async def verify_auth_token(
    authorization: str = Header(None),
    x_agent_key: str = Header(None),
    db: AsyncSession = Depends(get_db)
) -> Store:
    """Bearer 토큰 또는 기존 Agent Key로 인증"""

    # Bearer 토큰 방식 (신규)
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "")
        store_id = verify_token(token)

        if not store_id:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        stmt = select(Store).where(Store.id == store_id)
        result = await db.execute(stmt)
        store = result.scalar_one_or_none()

        if not store:
            raise HTTPException(status_code=401, detail="Store not found")

        return store

    # 기존 Agent Key 방식 (호환성)
    if x_agent_key:
        key_hash = hash_key(x_agent_key)
        stmt = select(Agent).where(Agent.agent_key_hash == key_hash)
        result = await db.execute(stmt)
        agent = result.scalar_one_or_none()

        if not agent:
            raise HTTPException(status_code=401, detail="Invalid agent key")

        stmt = select(Store).where(Store.id == agent.store_id)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    raise HTTPException(status_code=401, detail="Authentication required")


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
    store: Store = Depends(verify_auth_token),
    db: AsyncSession = Depends(get_db)
):
    # 해당 매장의 에이전트 찾기 또는 생성
    stmt = select(Agent).where(Agent.store_id == store.id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()

    if not agent:
        agent = Agent(store_id=store.id)
        db.add(agent)

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
    store: Store = Depends(verify_auth_token),
    db: AsyncSession = Depends(get_db)
):
    raw_bytes = await file.read()

    if not raw_bytes:
        return ReceiptUploadResponse(
            success=False,
            message="빈 파일"
        )

    parsed = parse_escpos(raw_bytes)

    if parsed.approval_no:
        stmt = select(Receipt.approval_no).where(
            Receipt.store_id == store.id,
            Receipt.status != ReceiptStatus.DISPOSED
        )
        result = await db.execute(stmt)
        existing_approval_nos = {r[0] for r in result.fetchall() if r[0]}
    else:
        existing_approval_nos = set()

    classification = classify_receipt(parsed, existing_approval_nos)

    if classification.should_dispose_existing and classification.existing_approval_no:
        stmt = select(Receipt).where(
            Receipt.store_id == store.id,
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

    paper_width = store.paper_width or 576

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
        store_id=store.id,
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


class VersionInfo(BaseModel):
    version: str
    download_url: str
    checksum: str  # SHA256
    file_size: int
    release_notes: str
    mandatory: bool = False  # 필수 업데이트 여부


@router.get("/latest", response_model=VersionInfo)
async def get_latest_version():
    """최신 버전 정보 반환 - 에이전트가 6시간마다 확인"""

    # 설치 파일 경로
    installer_path = os.path.join(settings.UPLOAD_DIR, "ReceiptTap_Setup.exe")

    # 버전 정보 파일
    version_file = os.path.join(settings.UPLOAD_DIR, "version.json")

    # 기본값
    version_info = {
        "version": "1.0.0",
        "download_url": f"{settings.SERVER_URL}/download/agent/ReceiptTap_Setup.exe",
        "checksum": "",
        "file_size": 0,
        "release_notes": "초기 버전",
        "mandatory": False
    }

    # 버전 파일이 있으면 읽기
    if os.path.exists(version_file):
        import json
        with open(version_file, "r", encoding="utf-8") as f:
            version_info.update(json.load(f))

    # 설치 파일이 있으면 체크섬 계산
    if os.path.exists(installer_path):
        version_info["file_size"] = os.path.getsize(installer_path)

        # 체크섬이 없으면 계산
        if not version_info.get("checksum"):
            with open(installer_path, "rb") as f:
                version_info["checksum"] = hashlib.sha256(f.read()).hexdigest()

    return VersionInfo(**version_info)


@router.get("/download/agent/{filename}")
async def download_agent(filename: str):
    """에이전트 설치 파일 다운로드"""
    from fastapi.responses import FileResponse

    # 보안: 파일명 검증
    if not filename.endswith(".exe") or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = os.path.join(settings.UPLOAD_DIR, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        file_path,
        media_type="application/octet-stream",
        filename=filename
    )

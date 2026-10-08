"""영수증 배정 엔진 - 동시성 처리 포함"""
from datetime import datetime, timezone, timedelta, time
from typing import Optional
from uuid import UUID, uuid4
import random
import string
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.receipt import Receipt, ReceiptStatus, ReceiptClassification
from ..models.session import ReviewSession, SessionStatus
from ..models.store import Store, StoreSettings


KST = timezone(timedelta(hours=9))


class NoReceiptAvailableError(Exception):
    """사용 가능한 영수증이 없음"""
    pass


class AlreadyParticipatedError(Exception):
    """오늘 이미 참여함"""
    def __init__(self, session: ReviewSession):
        self.session = session


class AssignmentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def get_business_day_start(self, cutoff: str = "05:00") -> datetime:
        """영업일 시작 시각 계산 (한국 시간 기준, 예: 새벽 5시)"""
        now = datetime.now(KST)
        h, m = map(int, cutoff.split(":"))
        today_cutoff = datetime.combine(now.date(), time(h, m), tzinfo=KST)

        if now < today_cutoff:
            return today_cutoff - timedelta(days=1)
        return today_cutoff

    async def create_session(
        self,
        store_id: int,
        customer_id: int,
        table_no: Optional[str] = None,
        device_id: Optional[str] = None
    ) -> ReviewSession:
        """새 세션 생성"""
        session = ReviewSession(
            id=uuid4(),
            store_id=store_id,
            customer_id=customer_id,
            table_no=table_no,
            device_id=device_id,
            started_at=datetime.now(timezone.utc),
            status=SessionStatus.STARTED
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def assign_receipt(
        self,
        session: ReviewSession,
        store_settings: Optional[StoreSettings] = None
    ) -> Receipt:
        """
        영수증 배정 (FOR UPDATE SKIP LOCKED)
        동시 요청에서 같은 영수증이 두 번 배정되지 않음
        """
        now = datetime.now(timezone.utc)
        cutoff = store_settings.business_day_cutoff if store_settings else "05:00"
        business_day_start = self.get_business_day_start(cutoff)

        policy = store_settings.assignment_policy if store_settings else "latest_same_day"

        order_col = Receipt.paid_at.desc() if policy == "latest_same_day" else Receipt.paid_at.asc()
        # 영업일 시작 이후 + 생성 후 24시간 이내(폐기 기준과 동일)인 미배정 정상 영수증
        query = (
            select(Receipt.id)
            .where(
                Receipt.store_id == session.store_id,
                Receipt.status == ReceiptStatus.AVAILABLE,
                Receipt.classification == ReceiptClassification.NORMAL,
                Receipt.paid_at >= business_day_start,
                Receipt.created_at >= now - timedelta(hours=24),
            )
            .order_by(order_col)
            .limit(1)
            .with_for_update(skip_locked=True)   # PostgreSQL: 동시 요청 시 같은 영수증 중복 배정 방지
        )

        result = await self.db.execute(query)
        row = result.first()

        if not row:
            raise NoReceiptAvailableError("사용 가능한 영수증이 없습니다")

        receipt_id = row[0]

        receipt_result = await self.db.execute(
            select(Receipt).where(Receipt.id == receipt_id)
        )
        receipt = receipt_result.scalar_one()

        receipt.status = ReceiptStatus.ASSIGNED
        receipt.assigned_session_id = session.id
        receipt.assigned_at = now

        session.receipt_id = receipt.id
        session.assigned_at = now
        session.status = SessionStatus.ASSIGNED
        session.completion_code = ''.join(random.choices(string.digits, k=6))

        await self.db.flush()
        return receipt

    async def get_session_with_receipt(
        self,
        session_id: UUID
    ) -> tuple[ReviewSession, Optional[Receipt]]:
        """세션과 배정된 영수증 조회"""
        result = await self.db.execute(
            select(ReviewSession).where(ReviewSession.id == session_id)
        )
        session = result.scalar_one_or_none()

        if not session:
            return None, None

        receipt = None
        if session.receipt_id:
            receipt_result = await self.db.execute(
                select(Receipt).where(Receipt.id == session.receipt_id)
            )
            receipt = receipt_result.scalar_one_or_none()

        return session, receipt

    async def update_session_status(
        self,
        session: ReviewSession,
        status: SessionStatus
    ) -> ReviewSession:
        """세션 상태 업데이트 (단계는 앞으로만 진행, 각 단계 시각은 처음 1번만 기록)"""
        now = datetime.now(timezone.utc)
        order = [SessionStatus.STARTED, SessionStatus.ASSIGNED, SessionStatus.DOWNLOADED,
                 SessionStatus.REDIRECTED, SessionStatus.COMPLETED, SessionStatus.BENEFIT_GIVEN]
        if session.status in order and status in order and order.index(status) < order.index(session.status):
            # 이미 더 진행된 상태 → 상태는 유지, 해당 단계 시각만 비어 있으면 기록
            status_to_set = session.status
        else:
            status_to_set = status
        session.status = status_to_set

        if status == SessionStatus.DOWNLOADED and not session.downloaded_at:
            session.downloaded_at = now
        elif status == SessionStatus.REDIRECTED and not session.redirected_at:
            session.redirected_at = now
        elif status == SessionStatus.COMPLETED and not session.completed_at:
            session.completed_at = now
        elif status == SessionStatus.BENEFIT_GIVEN and not session.benefit_given_at:
            session.benefit_given_at = now

        await self.db.flush()
        return session

    async def verify_staff_pin(
        self,
        store_id: int,
        pin: str
    ) -> bool:
        """직원 PIN 확인"""
        result = await self.db.execute(
            select(Store).where(Store.id == store_id)
        )
        store = result.scalar_one_or_none()

        if not store or not store.staff_pin:
            return False

        return store.staff_pin == pin

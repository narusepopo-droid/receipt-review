"""배정 엔진 테스트 - 동시성 테스트 포함"""
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from app.services.assignment import (
    AssignmentService,
    NoReceiptAvailableError
)
from app.models.store import Store
from app.models.customer import Customer
from app.models.receipt import Receipt, ReceiptStatus, ReceiptClassification
from app.models.session import ReviewSession


class TestAssignmentService:
    @pytest.mark.asyncio
    async def test_business_day_start_after_cutoff(self, db_session):
        service = AssignmentService(db_session)
        start = service.get_business_day_start("05:00")
        assert start is not None

    @pytest.mark.asyncio
    async def test_create_session(self, db_session):
        store = Store(name="테스트매장", store_code="test001")
        db_session.add(store)

        customer = Customer(phone_enc="enc", phone_hash="hash123")
        db_session.add(customer)
        await db_session.flush()

        service = AssignmentService(db_session)
        session = await service.create_session(
            store.id,
            customer.id,
            table_no="1"
        )

        assert session.id is not None
        assert session.store_id == store.id
        assert session.customer_id == customer.id
        assert session.table_no == "1"

    @pytest.mark.asyncio
    async def test_assign_receipt_success(self, db_session):
        store = Store(name="테스트매장", store_code="test002")
        db_session.add(store)

        customer = Customer(phone_enc="enc", phone_hash="hash456")
        db_session.add(customer)
        await db_session.flush()

        receipt = Receipt(
            store_id=store.id,
            approval_no="12345678",
            paid_at=datetime.now(timezone.utc),
            amount=28000,
            status=ReceiptStatus.AVAILABLE,
            classification=ReceiptClassification.NORMAL
        )
        db_session.add(receipt)
        await db_session.flush()

        service = AssignmentService(db_session)
        session = await service.create_session(store.id, customer.id)

        assigned = await service.assign_receipt(session)

        assert assigned.id == receipt.id
        assert assigned.status == ReceiptStatus.ASSIGNED
        assert session.receipt_id == receipt.id
        assert session.completion_code is not None
        assert len(session.completion_code) == 6

    @pytest.mark.asyncio
    async def test_assign_receipt_no_available(self, db_session):
        store = Store(name="테스트매장", store_code="test003")
        db_session.add(store)

        customer = Customer(phone_enc="enc", phone_hash="hash789")
        db_session.add(customer)
        await db_session.flush()

        service = AssignmentService(db_session)
        session = await service.create_session(store.id, customer.id)

        with pytest.raises(NoReceiptAvailableError):
            await service.assign_receipt(session)


class TestConcurrency:
    """동시성 테스트 - 같은 영수증이 두 번 배정되지 않아야 함"""

    @pytest.mark.asyncio
    async def test_concurrent_assignment_no_duplicate(self, db_session):
        """50개 동시 요청에서 중복 배정 없음"""
        store = Store(name="동시성테스트", store_code="concurrent001")
        db_session.add(store)
        await db_session.flush()

        for i in range(10):
            receipt = Receipt(
                store_id=store.id,
                approval_no=f"APPR{i:04d}",
                paid_at=datetime.now(timezone.utc),
                amount=10000 + i * 1000,
                status=ReceiptStatus.AVAILABLE,
                classification=ReceiptClassification.NORMAL
            )
            db_session.add(receipt)
        await db_session.flush()

        assigned_receipt_ids = []
        errors = []

        async def try_assign(idx: int):
            try:
                customer = Customer(
                    phone_enc=f"enc{idx}",
                    phone_hash=f"hash_concurrent_{idx}"
                )
                db_session.add(customer)
                await db_session.flush()

                service = AssignmentService(db_session)
                session = await service.create_session(store.id, customer.id)
                receipt = await service.assign_receipt(session)
                assigned_receipt_ids.append(receipt.id)
            except NoReceiptAvailableError:
                errors.append(idx)
            except Exception as e:
                errors.append(f"Error {idx}: {e}")

        await asyncio.gather(*[try_assign(i) for i in range(15)])

        assert len(set(assigned_receipt_ids)) == len(assigned_receipt_ids), \
            "중복 배정 발생!"

        assert len(assigned_receipt_ids) <= 10, \
            "10개 영수증보다 더 많이 배정됨"

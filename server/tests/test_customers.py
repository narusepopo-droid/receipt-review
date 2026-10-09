"""고객 서비스 테스트"""
import pytest
from app.services.customers import (
    normalize_phone,
    hash_phone,
    encrypt_phone,
    decrypt_phone,
    mask_phone,
    CustomerService
)


class TestPhoneUtils:
    def test_normalize_phone_with_hyphens(self):
        assert normalize_phone("010-1234-5678") == "01012345678"

    def test_normalize_phone_with_spaces(self):
        assert normalize_phone("010 1234 5678") == "01012345678"

    def test_normalize_phone_already_clean(self):
        assert normalize_phone("01012345678") == "01012345678"

    def test_hash_phone_consistent(self):
        h1 = hash_phone("010-1234-5678")
        h2 = hash_phone("01012345678")
        assert h1 == h2

    def test_hash_phone_different_numbers(self):
        h1 = hash_phone("01012345678")
        h2 = hash_phone("01087654321")
        assert h1 != h2

    def test_encrypt_decrypt_roundtrip(self):
        original = "01012345678"
        encrypted = encrypt_phone(original)
        decrypted = decrypt_phone(encrypted)
        assert decrypted == original

    def test_encrypt_different_each_time(self):
        phone = "01012345678"
        e1 = encrypt_phone(phone)
        e2 = encrypt_phone(phone)
        assert e1 != e2

    def test_mask_phone_11_digits(self):
        assert mask_phone("01012345678") == "010-****-5678"

    def test_mask_phone_10_digits(self):
        assert mask_phone("0212345678") == "021-***-5678"

    def test_mask_phone_with_hyphens(self):
        assert mask_phone("010-1234-5678") == "010-****-5678"


class TestCustomerService:
    @pytest.mark.asyncio
    async def test_get_or_create_customer_new(self, db_session):
        service = CustomerService(db_session)
        customer = await service.get_or_create_customer("01012345678")

        assert customer.id is not None
        assert customer.phone_hash == hash_phone("01012345678")

    @pytest.mark.asyncio
    async def test_get_or_create_customer_existing(self, db_session):
        service = CustomerService(db_session)

        c1 = await service.get_or_create_customer("01012345678")
        c2 = await service.get_or_create_customer("010-1234-5678")

        assert c1.id == c2.id


@pytest.mark.asyncio
async def test_purge_inactive_customers_after_one_year(db_session):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from app.models.store import Store
    from app.models.customer import Customer, StoreCustomer
    from app.services.disposal import purge_inactive_customers
    from app.services.customers import hash_phone, encrypt_phone

    db_session.add(Store(id=1, name="s", store_code="S1"))
    old = datetime.now(timezone.utc) - timedelta(days=400)
    new = datetime.now(timezone.utc) - timedelta(days=10)
    for i, last in ((1, old), (2, new)):
        db_session.add(Customer(id=i, phone_enc=encrypt_phone(f"0101111000{i}"), phone_hash=hash_phone(f"0101111000{i}")))
        db_session.add(StoreCustomer(store_id=1, customer_id=i, first_visit_at=last, last_visit_at=last))
    await db_session.commit()

    assert await purge_inactive_customers(db_session) == 1
    c1 = (await db_session.execute(select(Customer).where(Customer.id == 1))).scalar_one()
    c2 = (await db_session.execute(select(Customer).where(Customer.id == 2))).scalar_one()
    assert c1.phone_enc == "" and c1.phone_hash.startswith("deleted-")
    assert c2.phone_enc != ""

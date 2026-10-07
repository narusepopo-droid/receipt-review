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

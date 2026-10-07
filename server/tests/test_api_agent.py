"""
에이전트 API 테스트
- POST /agent/v1/activate
- POST /agent/v1/receipts
- POST /agent/v1/heartbeat
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
import json


class TestActivateAPI:
    """활성화 API 테스트"""

    def test_activate_with_valid_code(self, client, test_store):
        """유효한 활성화 코드로 활성화 성공"""
        # Given: 테스트 매장에 활성화 코드 생성
        activation_code = "TEST1234"

        with patch('app.routers.agent.verify_activation_code') as mock_verify:
            mock_verify.return_value = {
                "store_id": test_store.id,
                "agent_key": "generated_agent_key_123"
            }

            # When
            response = client.post("/agent/v1/activate", json={
                "activation_code": activation_code
            })

            # Then
            assert response.status_code == 200
            data = response.json()
            assert "agent_key" in data
            assert data["agent_key"] == "generated_agent_key_123"

    def test_activate_with_invalid_code(self, client):
        """유효하지 않은 활성화 코드로 404"""
        with patch('app.routers.agent.verify_activation_code') as mock_verify:
            mock_verify.return_value = None

            response = client.post("/agent/v1/activate", json={
                "activation_code": "INVALID1"
            })

            assert response.status_code == 404

    def test_activate_code_format_validation(self, client):
        """활성화 코드 형식 검증"""
        # 8자리가 아닌 코드
        response = client.post("/agent/v1/activate", json={
            "activation_code": "SHORT"
        })

        assert response.status_code == 422


class TestReceiptUploadAPI:
    """영수증 업로드 API 테스트"""

    def test_upload_receipt_success(self, client, test_store, test_agent_key):
        """영수증 업로드 성공"""
        # Given: ESC/POS 샘플 데이터
        raw_data = b'\x1b@\x1ba\x01Test Receipt\n\x1dV\x00'

        with patch('app.routers.agent.process_receipt') as mock_process:
            mock_process.return_value = {"id": "receipt-uuid-123", "status": "available"}

            # When
            response = client.post(
                "/agent/v1/receipts",
                headers={"X-Agent-Key": test_agent_key},
                files={"raw_data": ("receipt.bin", raw_data, "application/octet-stream")},
                data={
                    "captured_at": "2026-10-07T15:00:00",
                    "capture_mode": "serial",
                    "version": "1.0.0"
                }
            )

            # Then
            assert response.status_code == 201
            data = response.json()
            assert data["status"] == "available"

    def test_upload_without_agent_key(self, client):
        """에이전트 키 없이 업로드 시 401"""
        raw_data = b'\x1b@Test\n'

        response = client.post(
            "/agent/v1/receipts",
            files={"raw_data": ("receipt.bin", raw_data, "application/octet-stream")},
            data={"captured_at": "2026-10-07T15:00:00"}
        )

        assert response.status_code == 401

    def test_upload_with_invalid_agent_key(self, client):
        """잘못된 에이전트 키로 업로드 시 401"""
        raw_data = b'\x1b@Test\n'

        response = client.post(
            "/agent/v1/receipts",
            headers={"X-Agent-Key": "invalid_key"},
            files={"raw_data": ("receipt.bin", raw_data, "application/octet-stream")},
            data={"captured_at": "2026-10-07T15:00:00"}
        )

        assert response.status_code == 401


class TestHeartbeatAPI:
    """하트비트 API 테스트"""

    def test_heartbeat_success(self, client, test_agent_key):
        """하트비트 전송 성공"""
        with patch('app.routers.agent.update_agent_status') as mock_update:
            mock_update.return_value = True

            response = client.post(
                "/agent/v1/heartbeat",
                headers={"X-Agent-Key": test_agent_key},
                json={
                    "version": "1.0.0",
                    "capture_mode": "serial",
                    "last_capture_at": "2026-10-07T15:00:00",
                    "queue_length": 0
                }
            )

            assert response.status_code == 200

    def test_heartbeat_updates_agent_status(self, client, test_agent_key, db_session):
        """하트비트가 에이전트 상태를 업데이트하는지"""
        # This would test the actual database update
        pass


class TestLatestVersionAPI:
    """최신 버전 확인 API 테스트"""

    def test_get_latest_version(self, client, test_agent_key):
        """최신 버전 확인"""
        response = client.get(
            "/agent/v1/latest",
            headers={"X-Agent-Key": test_agent_key}
        )

        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "download_url" in data


# Fixtures
@pytest.fixture
def test_agent_key():
    """테스트용 에이전트 키"""
    return "test_agent_key_abc123"


@pytest.fixture
def test_store():
    """테스트용 매장"""
    class MockStore:
        id = 1
        name = "테스트 매장"
        store_code = "TEST01"
    return MockStore()

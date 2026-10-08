"""배포 버전 정보 / 자동 업데이트 API 테스트"""
import json

import pytest
from httpx import AsyncClient, ASGITransport

from app.services import release as rel


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    monkeypatch.setattr(rel, "INSTALLER_DIR", str(tmp_path))
    monkeypatch.setattr(rel, "LATEST_JSON", str(tmp_path / "latest.json"))
    (tmp_path / "ReceiptTap_v9.9.9.zip").write_bytes(b"PK-package")
    (tmp_path / "ReceiptTap_Setup_9.9.9.exe").write_bytes(b"MZ-setup")
    (tmp_path / "latest.json").write_text(json.dumps({
        "version": "9.9.9", "setup": "ReceiptTap_Setup_9.9.9.exe",
        "package": "ReceiptTap_v9.9.9.zip", "notes": "테스트", "date": "2026-10-09",
    }), encoding="utf-8")
    return tmp_path


async def get(path, ua="ReceiptTap/1.1.1"):
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.get(path, headers={"User-Agent": ua})


@pytest.mark.asyncio
async def test_latest_for_new_agent(downloads):
    r = await get("/agent/v1/latest")
    body = r.json()
    assert body["version"] == "9.9.9"
    assert body["download_url"].endswith("/download/package/9.9.9")
    assert body["checksum"] == rel.sha256_of(str(downloads / "ReceiptTap_v9.9.9.zip"))


@pytest.mark.asyncio
async def test_old_agent_not_offered_update(downloads):
    r = await get("/agent/v1/latest", ua="ReceiptTap/1.0.3")
    assert r.json()["version"] == "1.0.3"
    assert r.json()["download_url"] == ""


@pytest.mark.asyncio
async def test_download_latest_prefers_setup(downloads):
    r = await get("/download/latest")
    assert r.status_code == 200 and r.content == b"MZ-setup"


@pytest.mark.asyncio
async def test_download_latest_zip_when_no_setup(downloads):
    data = json.loads((downloads / "latest.json").read_text(encoding="utf-8"))
    data["setup"] = None
    (downloads / "latest.json").write_text(json.dumps(data), encoding="utf-8")
    r = await get("/download/latest")
    assert r.content == b"PK-package"


@pytest.mark.asyncio
async def test_package_download(downloads):
    assert (await get("/download/package/9.9.9")).content == b"PK-package"
    assert (await get("/download/package/1.0.0")).status_code == 404


def test_parse_version():
    assert rel.parse_version("1.10.0") > rel.parse_version("1.9.9")
    assert rel.parse_version("1.1") == (1, 1, 0)

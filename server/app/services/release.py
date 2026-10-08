"""
에이전트 배포 버전 관리

다운로드 폴더(INSTALLER_DIR)의 latest.json 이 기준:
{
  "version": "1.1.1",
  "setup": "ReceiptTap_Setup_1.1.1.exe",   # 처음 설치용 (없으면 package 를 내려줌)
  "package": "ReceiptTap_v1.1.1.zip",       # 자동 업데이트용 (프로그램 파일 묶음)
  "notes": "변경 내용",
  "date": "2026-10-09"
}
latest.json 이 없으면 아래 기본값을 쓴다.
"""
import hashlib
import json
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

INSTALLER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "downloads")
LATEST_JSON = os.path.join(INSTALLER_DIR, "latest.json")

DEFAULT = {
    "version": "1.1.0",
    "setup": None,
    "package": "ReceiptTap_v1.1.0.zip",
    "notes": "SPMC 캡처 수정, 프린터 자동 연결, 상태판",
    "date": "2026-10-09",
}

# 이 버전 미만은 업데이트 방식(설치파일 무인 실행)이 달라 자동 업데이트 대상에서 제외 (1.1.0 이하는 수동 재설치)
MIN_AUTO_UPDATE_VERSION = "1.1.1"


@dataclass
class Release:
    version: str
    setup: Optional[str]
    package: Optional[str]
    notes: str
    date: str

    def path(self, name: Optional[str]) -> Optional[str]:
        if not name:
            return None
        p = os.path.join(INSTALLER_DIR, os.path.basename(name))
        return p if os.path.exists(p) else None

    @property
    def setup_path(self) -> Optional[str]:
        return self.path(self.setup)

    @property
    def package_path(self) -> Optional[str]:
        return self.path(self.package)

    @property
    def first_install_path(self) -> Optional[str]:
        """다운로드 버튼용: 설치 파일이 있으면 설치 파일, 없으면 zip"""
        return self.setup_path or self.package_path


def get_release() -> Release:
    data = dict(DEFAULT)
    try:
        with open(LATEST_JSON, encoding="utf-8") as f:
            data.update(json.load(f))
    except (OSError, ValueError):
        pass
    return Release(
        version=str(data["version"]),
        setup=data.get("setup"),
        package=data.get("package"),
        notes=data.get("notes") or "",
        date=data.get("date") or "",
    )


def save_release(version: str, setup: Optional[str], package: Optional[str], notes: str, date: str) -> None:
    os.makedirs(INSTALLER_DIR, exist_ok=True)
    tmp = LATEST_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": version, "setup": setup, "package": package, "notes": notes, "date": date},
                  f, ensure_ascii=False, indent=2)
    os.replace(tmp, LATEST_JSON)


def sha256_of(path: Optional[str]) -> str:
    if not path or not os.path.exists(path):
        return ""
    st = os.stat(path)
    return _sha256_cached(path, st.st_mtime, st.st_size)


@lru_cache(maxsize=16)
def _sha256_cached(path: str, mtime: float, size: int) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_version(v: str) -> tuple:
    parts = []
    for p in (v or "0").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])

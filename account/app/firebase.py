"""
Firebase 연동 (플마와 같은 프로젝트)
- 가입·로그인·비밀번호 재설정: Identity Toolkit REST + 공개 웹 API 키
- ID 토큰 검증: 구글 공개 인증서 (비밀키 불필요)
- (선택) 플마 Firestore users/{uid} 동기화: 서비스 계정 키가 있을 때만
"""
import base64
import json
import time
from typing import Optional

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.config import settings

ID_TOOLKIT = "https://identitytoolkit.googleapis.com/v1/accounts:{}?key={}"
CERTS_URL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"

ERRORS = {
    "EMAIL_EXISTS": "이미 가입된 이메일입니다. 로그인해 주세요.",
    "EMAIL_NOT_FOUND": "이메일 또는 비밀번호가 올바르지 않습니다.",
    "INVALID_PASSWORD": "이메일 또는 비밀번호가 올바르지 않습니다.",
    "INVALID_LOGIN_CREDENTIALS": "이메일 또는 비밀번호가 올바르지 않습니다.",
    "USER_DISABLED": "사용이 중지된 계정입니다. 고객센터로 문의해 주세요.",
    "TOO_MANY_ATTEMPTS_TRY_LATER": "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.",
    "WEAK_PASSWORD": "비밀번호는 6자 이상이어야 합니다.",
    "INVALID_EMAIL": "이메일 형식이 올바르지 않습니다.",
}


class FirebaseError(Exception):
    def __init__(self, code: str):
        self.code = code
        key = code.split(" ")[0].split(":")[0].strip()
        super().__init__(ERRORS.get(key, "로그인 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."))


async def _call(action: str, body: dict) -> dict:
    if not settings.FIREBASE_API_KEY:
        raise FirebaseError("NOT_CONFIGURED")
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(ID_TOOLKIT.format(action, settings.FIREBASE_API_KEY), json=body)
    data = r.json() if r.content else {}
    if r.status_code != 200:
        raise FirebaseError((data.get("error") or {}).get("message", f"HTTP_{r.status_code}"))
    return data


async def sign_up(email: str, password: str) -> dict:
    """{'localId': uid, 'email': ..., 'idToken': ...}"""
    return await _call("signUp", {"email": email, "password": password, "returnSecureToken": True})


async def sign_in(email: str, password: str) -> dict:
    return await _call("signInWithPassword", {"email": email, "password": password, "returnSecureToken": True})


async def send_password_reset(email: str) -> None:
    await _call("sendOobCode", {"requestType": "PASSWORD_RESET", "email": email})


async def change_password(id_token: str, new_password: str) -> None:
    await _call("update", {"idToken": id_token, "password": new_password, "returnSecureToken": False})


# ───────────── ID 토큰 검증 (플마 프로그램 → 계정 서버) ─────────────

_certs: dict = {"exp": 0, "keys": {}}


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


async def _google_certs() -> dict:
    if _certs["exp"] > time.time():
        return _certs["keys"]
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(CERTS_URL)
    _certs["keys"] = r.json()
    _certs["exp"] = time.time() + 3600
    return _certs["keys"]


async def verify_id_token(token: str) -> Optional[dict]:
    """유효하면 {'uid','email'} 아니면 None"""
    try:
        h64, p64, s64 = token.split(".")
        header = json.loads(_b64d(h64))
        payload = json.loads(_b64d(p64))
        certs = await _google_certs()
        pem = certs.get(header.get("kid"))
        if not pem or header.get("alg") != "RS256":
            return None
        pub = x509.load_pem_x509_certificate(pem.encode()).public_key()
        pub.verify(_b64d(s64), f"{h64}.{p64}".encode(), padding.PKCS1v15(), hashes.SHA256())
        proj = settings.FIREBASE_PROJECT_ID
        now = time.time()
        if payload.get("aud") != proj or payload.get("iss") != f"https://securetoken.google.com/{proj}":
            return None
        if payload.get("exp", 0) < now or payload.get("iat", now + 1) > now + 60:
            return None
        return {"uid": payload.get("sub"), "email": payload.get("email", "")}
    except Exception:
        return None


# ───────────── (선택) 플마 Firestore 동기화 ─────────────

_sa_token: dict = {"exp": 0, "token": ""}


def sa_available() -> bool:
    try:
        return bool(settings.FIREBASE_SA_FILE) and bool(json.load(open(settings.FIREBASE_SA_FILE)))
    except Exception:
        return False


async def _sa_access_token() -> str:
    if _sa_token["exp"] > time.time() + 60:
        return _sa_token["token"]
    sa = json.load(open(settings.FIREBASE_SA_FILE))
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    claims = {"iss": sa["client_email"], "scope": "https://www.googleapis.com/auth/datastore",
              "aud": "https://oauth2.googleapis.com/token", "iat": now, "exp": now + 3600}
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    unsigned = f"{enc(header)}.{enc(claims)}"
    key = serialization.load_pem_private_key(sa["private_key"].encode(), password=None)
    sig = key.sign(unsigned.encode(), padding.PKCS1v15(), hashes.SHA256())
    jwt = unsigned + "." + base64.urlsafe_b64encode(sig).rstrip(b"=").decode()
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post("https://oauth2.googleapis.com/token",
                         data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": jwt})
    tok = r.json()
    _sa_token.update(token=tok["access_token"], exp=now + int(tok.get("expires_in", 3600)))
    return _sa_token["token"]


async def sync_plma_user(uid: str, *, active: bool, expires_at: str, email: str = "", name: str = "",
                         device_id: Optional[str] = None) -> bool:
    """플마 프로그램이 보는 Firestore users/{uid} 갱신 (active, expires_at, device_id)"""
    if not sa_available() or not uid:
        return False
    fields = {"active": {"booleanValue": active}, "expires_at": {"stringValue": expires_at}}
    if email:
        fields["email"] = {"stringValue": email}
    if name:
        fields["name"] = {"stringValue": name}
    if device_id is not None:
        fields["device_id"] = {"stringValue": device_id}
    mask = "&".join(f"updateMask.fieldPaths={k}" for k in fields)
    url = (f"https://firestore.googleapis.com/v1/projects/{settings.FIREBASE_PROJECT_ID}"
           f"/databases/(default)/documents/users/{uid}?{mask}")
    token = await _sa_access_token()
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.patch(url, headers={"Authorization": f"Bearer {token}"}, json={"fields": fields})
    return r.status_code == 200


async def list_plma_users() -> list[dict]:
    """플마 기존 회원 목록 (Firestore users) — 이전용"""
    if not sa_available():
        return []
    token = await _sa_access_token()
    out, page = [], None
    async with httpx.AsyncClient(timeout=30) as c:
        while True:
            url = (f"https://firestore.googleapis.com/v1/projects/{settings.FIREBASE_PROJECT_ID}"
                   f"/databases/(default)/documents/users?pageSize=300" + (f"&pageToken={page}" if page else ""))
            r = await c.get(url, headers={"Authorization": f"Bearer {token}"})
            data = r.json()
            for d in data.get("documents", []):
                f = d.get("fields", {})
                out.append({
                    "uid": d["name"].rsplit("/", 1)[-1],
                    "email": f.get("email", {}).get("stringValue", ""),
                    "name": f.get("name", {}).get("stringValue", ""),
                    "active": f.get("active", {}).get("booleanValue", False),
                    "expires_at": f.get("expires_at", {}).get("stringValue", ""),
                    "device_id": f.get("device_id", {}).get("stringValue", ""),
                    "role": f.get("role", {}).get("stringValue", "member"),
                })
            page = data.get("nextPageToken")
            if not page:
                break
    return out


async def get_own_user_doc(uid: str, id_token: str) -> Optional[dict]:
    """플마 회원 본인 문서 users/{uid} (본인 로그인 토큰으로 읽기 — 서비스 계정 키 불필요). 없으면 None"""
    if not uid or not id_token or not settings.FIREBASE_PROJECT_ID:
        return None
    url = (f"https://firestore.googleapis.com/v1/projects/{settings.FIREBASE_PROJECT_ID}"
           f"/databases/(default)/documents/users/{uid}")
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(url, headers={"Authorization": f"Bearer {id_token}"})
    if r.status_code != 200:
        return None
    f = r.json().get("fields", {})
    return {
        "active": f.get("active", {}).get("booleanValue", False),
        "expires_at": f.get("expires_at", {}).get("stringValue", ""),
        "device_id": f.get("device_id", {}).get("stringValue", ""),
        "name": f.get("name", {}).get("stringValue", ""),
        "role": f.get("role", {}).get("stringValue", "member"),
    }

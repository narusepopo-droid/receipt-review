"""
로그인 실패 잠금 + 간단한 요청 횟수 제한 (서버 1대 기준, 메모리 보관)

- 로그인: 같은 IP·아이디로 5회 실패 시 10분 잠금 (지시서 5.12)
- 요청 제한: 키(IP, 전화번호 등)별로 기간 내 최대 횟수
"""
import time
from collections import defaultdict, deque
from threading import Lock

MAX_FAILURES = 5
LOCK_SECONDS = 600


class LoginLimiter:
    def __init__(self, max_failures: int = MAX_FAILURES, lock_seconds: int = LOCK_SECONDS):
        self.max_failures = max_failures
        self.lock_seconds = lock_seconds
        self._fails: dict[str, list[float]] = defaultdict(list)
        self._locked_until: dict[str, float] = {}
        self._lock = Lock()

    @staticmethod
    def key(scope: str, ip: str, login_id: str) -> str:
        return f"{scope}:{ip}:{(login_id or '').lower()}"

    def remaining_lock(self, key: str) -> int:
        """잠겨 있으면 남은 초, 아니면 0"""
        with self._lock:
            until = self._locked_until.get(key, 0)
            left = int(until - time.time())
            if left <= 0:
                self._locked_until.pop(key, None)
                return 0
            return left

    def fail(self, key: str) -> int:
        """실패 기록. 잠기면 잠금 초를 반환"""
        now = time.time()
        with self._lock:
            fails = [t for t in self._fails[key] if now - t < self.lock_seconds]
            fails.append(now)
            self._fails[key] = fails
            if len(fails) >= self.max_failures:
                self._locked_until[key] = now + self.lock_seconds
                self._fails[key] = []
                return self.lock_seconds
            return 0

    def success(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)
            self._locked_until.pop(key, None)


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            if len(self._hits) > 50000:  # 메모리 보호
                for k in list(self._hits.keys())[:10000]:
                    if not self._hits[k] or now - self._hits[k][-1] > 3600:
                        del self._hits[k]
            return True


login_limiter = LoginLimiter()
rate_limiter = RateLimiter()


def client_ip(request) -> str:
    """nginx 뒤에서 실제 접속 IP"""
    # nginx 가 덮어쓰는 X-Real-IP 우선 (X-Forwarded-For 앞부분은 손님이 위조 가능)
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


# ============ 비밀번호 (가입·관리자 웹·에이전트 로그인 공용) ============

def hash_password(password: str) -> str:
    """새 비밀번호는 bcrypt 로 저장"""
    import bcrypt
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """bcrypt 와 예전 가입 방식(PBKDF2, SECRET_KEY 솔트) 둘 다 확인"""
    import hashlib
    import hmac as _hmac
    if not password_hash:
        return False
    if password_hash.startswith("$2"):
        import bcrypt
        try:
            return bcrypt.checkpw(password.encode(), password_hash.encode())
        except ValueError:
            return False
    from app.config import settings
    legacy = hashlib.pbkdf2_hmac("sha256", password.encode(), settings.SECRET_KEY[:16].encode(), 100000).hex()
    return _hmac.compare_digest(legacy, password_hash)

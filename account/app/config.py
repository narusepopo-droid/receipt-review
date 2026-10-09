"""계정 서버 설정 (.env)"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./account.db"
    SECRET_KEY: str = "change-me"
    DEBUG: bool = False

    # 공개 주소 (메일·문자 링크용). 하위 경로로 서비스할 때 BASE_PATH 예: /account
    BASE_URL: str = "https://review.placemaster.co.kr/account"
    BASE_PATH: str = ""

    # Firebase (플마와 같은 프로젝트) — 웹 API 키는 공개 키
    FIREBASE_API_KEY: str = ""
    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_SA_FILE: str = ""          # 서비스 계정 키 (있으면 플마 Firestore 동기화)

    # 운영자: 이 이메일로 로그인하면 운영자 권한
    OPS_EMAILS: str = ""

    # 토스페이먼츠 (비어 있으면 결제 대신 '운영자 승인' 흐름)
    TOSS_CLIENT_KEY: str = ""
    TOSS_SECRET_KEY: str = ""

    # 문자 (알리고) — 비어 있으면 모의 발송(로그)
    ALIGO_KEY: str = ""
    ALIGO_USER_ID: str = ""
    ALIGO_SENDER: str = ""

    # 영수증리뷰 서버 연동 (서버끼리 공유 비밀)
    REVIEW_API_URL: str = "http://127.0.0.1:8000"
    REVIEW_PUBLIC_URL: str = "https://review.placemaster.co.kr"
    SUPPORT_PHONE: str = ""         # 고객센터 번호 (화면 안내용)
    SITE_URL: str = "https://placemaster.co.kr/"
    PLMA_SIGNUP_URL: str = "https://placemaster.co.kr/signup.html"   # 서비스 계정 키 연결 전 플마 가입 경로
    INTERNAL_SECRET: str = "change-me-internal"

    SESSION_HTTPS_ONLY: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def ops_emails(self) -> set:
        return {e.strip().lower() for e in self.OPS_EMAILS.split(",") if e.strip()}

    @property
    def toss_enabled(self) -> bool:
        return bool(self.TOSS_CLIENT_KEY and self.TOSS_SECRET_KEY)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

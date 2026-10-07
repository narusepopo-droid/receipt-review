# 영수증리뷰 (receipt-review)

손님이 QR을 찍고 휴대폰 번호를 입력하면, 미사용 영수증 이미지가 폰에 저장되고 리뷰 문구가 복사된 상태로 네이버 영수증 리뷰 작성 페이지가 열리는 서비스.

## 프로젝트 구조

```
receipt-review/
├── server/              # FastAPI 서버
│   ├── app/
│   │   ├── main.py      # FastAPI 진입점
│   │   ├── config.py    # 환경변수 설정
│   │   ├── db.py        # DB 연결
│   │   ├── models/      # SQLAlchemy 모델
│   │   ├── receipt/     # 파서, 렌더러, 마스킹
│   │   ├── review/      # 문구 생성기
│   │   ├── services/    # 비즈니스 로직
│   │   ├── routers/     # API 라우터
│   │   ├── templates/   # Jinja2 템플릿
│   │   └── static/      # CSS, JS, 이미지
│   ├── alembic/         # DB 마이그레이션
│   └── tests/           # pytest 테스트
├── agent/               # 포스 캡처 에이전트 (C#/.NET)
├── tools/               # 테스트 도구
├── samples/             # 샘플 데이터
├── docs/                # 문서
└── deploy/              # 배포 설정
```

## 개발 환경 설정

### 서버 (Python)

**요구사항**
- Python 3.11+
- PostgreSQL 15+

**설치**

```bash
# 1. 저장소 클론
git clone https://github.com/narusepopo-droid/receipt-review.git
cd receipt-review/server

# 2. 가상환경 생성 및 활성화
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

# 3. 의존성 설치
pip install -r requirements.txt
# 또는
pip install -e .

# 4. 환경변수 설정
cp .env.example .env
# .env 파일 편집 (아래 환경변수 설명 참고)

# 5. DB 마이그레이션
alembic upgrade head

# 6. 개발 서버 실행
uvicorn app.main:app --reload --port 8000
```

### 에이전트 (C#)

**요구사항**
- .NET Framework 4.6.2+
- Visual Studio 2019+ 또는 dotnet CLI

**빌드**

```bash
cd agent
dotnet build -c Release
```

## 환경변수 (.env)

```bash
# 필수
DATABASE_URL=postgresql://user:password@localhost:5432/receipt_review
SECRET_KEY=your-secret-key-at-least-32-characters

# 휴대폰 번호 암호화 키 (32바이트 base64)
PHONE_ENC_KEY=your-32-byte-base64-encoded-key
PHONE_HMAC_KEY=your-hmac-secret-key

# 선택
DEBUG=false
LOG_LEVEL=INFO

# 알리고 문자 발송 (Phase 8)
ALIGO_API_KEY=
ALIGO_SENDER=

# AWS S3 백업 (Phase 6)
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_DEFAULT_REGION=ap-northeast-2
```

## 서버 배포 (Ubuntu 24.04)

### 1. 서버 준비

```bash
# 시스템 업데이트
sudo apt update && sudo apt upgrade -y

# 필수 패키지 설치
sudo apt install -y python3.11 python3.11-venv python3-pip nginx postgresql

# 앱 디렉토리 생성
sudo mkdir -p /var/www/receipt-review
sudo chown www-data:www-data /var/www/receipt-review
```

### 2. 코드 배포

```bash
cd /var/www/receipt-review
sudo -u www-data git clone https://github.com/narusepopo-droid/receipt-review.git .

# 가상환경 설정
cd server
sudo -u www-data python3.11 -m venv .venv
sudo -u www-data .venv/bin/pip install -r requirements.txt

# 환경변수 설정
sudo cp .env.example .env
sudo nano .env  # 실제 값으로 편집
sudo chown www-data:www-data .env
sudo chmod 600 .env

# DB 마이그레이션
sudo -u www-data .venv/bin/alembic upgrade head
```

### 3. Nginx 설정

```bash
# Nginx 설정 복사
sudo cp deploy/nginx.conf /etc/nginx/sites-available/receipt-review
sudo ln -s /etc/nginx/sites-available/receipt-review /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 4. SSL 인증서 (Let's Encrypt)

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d review.placemaster.co.kr
```

### 5. Systemd 서비스

```bash
# 서비스 파일 복사
sudo cp deploy/receipt-review.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable receipt-review
sudo systemctl start receipt-review

# 상태 확인
sudo systemctl status receipt-review
```

### 6. 백업 설정 (Cron)

```bash
# 백업 스크립트 권한
sudo chmod +x deploy/backup.sh

# 매일 새벽 3시 백업
sudo crontab -e
# 추가: 0 3 * * * /var/www/receipt-review/deploy/backup.sh
```

## 배포 업데이트

```bash
cd /var/www/receipt-review
sudo -u www-data git pull
cd server
sudo -u www-data .venv/bin/pip install -r requirements.txt
sudo -u www-data .venv/bin/alembic upgrade head
sudo systemctl restart receipt-review
```

## API 문서

서버 실행 후 접속:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 테스트

```bash
cd server
pytest
```

## 라이선스

Private - All Rights Reserved

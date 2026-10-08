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
- HHD SPMC (Serial Port Monitoring Control) 라이선스

**빌드**

```bash
cd agent
dotnet restore
dotnet build -c Release
```

**설치 파일 생성 (Inno Setup)**

```bash
# Inno Setup 6 설치 후
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer/ReceiptTap.iss
```

**프로젝트 구조**

```
agent/
├── ReceiptTap.sln           # 솔루션 파일
├── ReceiptTap.Core/         # 핵심 라이브러리 (카솔 연동 대비)
│   ├── IReceiptCapture.cs   # 캡처 인터페이스
│   ├── ReceiptUploader.cs   # 서버 업로드
│   ├── LocalQueue.cs        # 로컬 큐 (실패 시 재시도)
│   └── AgentConfig.cs       # 설정 (DPAPI 암호화)
├── ReceiptTap.App/          # 트레이 앱
│   ├── Program.cs           # 진입점
│   ├── TrayApplicationContext.cs
│   ├── ActivationForm.cs    # 활성화 코드 입력
│   └── SettingsForm.cs      # 프린터 설정
└── installer/
    └── ReceiptTap.iss       # Inno Setup 스크립트
```

## 환경변수 (.env)

```bash
# 필수
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/receiptreview
SECRET_KEY=32자 이상 무작위 문자열        # 바꾸면 기존 로그인 토큰·가입 비밀번호(예전 방식) 무효
PHONE_ENC_KEY=32바이트 키                 # 바꾸면 기존 고객 번호 복호화 불가 — 절대 변경 금지
PHONE_HMAC_KEY=무작위 문자열              # 바꾸면 기존 고객 조회 불가 — 절대 변경 금지

# 운영 서버
SESSION_HTTPS_ONLY=true
OPS_USERNAME=admin
OPS_PASSWORD=운영자 비밀번호              # 기본값 사용 중이면 반드시 변경

# 홍보 문자·운영 알림 (알리고) — 비어 있으면 모의 발송
ALIGO_KEY=
ALIGO_USER_ID=
ALIGO_SENDER=                              # 알리고에 등록된 발신번호
ALIGO_OPTOUT_080=                          # 080 무료수신거부 번호
SMS_COST_SMS=20
SMS_COST_LMS=50
OPS_ALERT_PHONE=                           # 에이전트 끊김 알림 받을 번호
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

## 배포 업데이트 (운영 서버)

```bash
# 이 PC에서 (열쇠: ~/.ssh/receipt-review)
ssh -i ~/.ssh/receipt-review ubuntu@13.124.130.55
cd ~/receipt-review && git pull origin main
sudo systemctl restart receipt-review
cd server && venv/bin/python scripts/e2e_smoke.py      # 10개 항목 점검 (임시 매장 만들고 지움)
```
- 새 테이블은 서버 시작 시 자동 생성. 기존 테이블 칼럼이 모델과 다르면 로그에 "DB 칼럼 누락" 경고
- DB 백업: 매일 04:30 (KST) `/home/ubuntu/backups`, 14일 보관 (`deploy/backup.sh`)

## 에이전트 빌드·배포

```powershell
# 버전: agent\ReceiptTap.App\ReceiptTap.App.csproj 의 <Version>
.\scripts\release.ps1                                   # dist\ 에 Setup.exe + zip
.\scripts\release.ps1 -Publish -ZipOnly -Notes "내용"     # 서버 업로드 + 최신 지정 (자동 업데이트 반영)
```
설치·문제 해결: `docs/pos-install-guide.md`

## API 문서

서버 실행 후 접속:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 테스트

```bash
cd server
pytest                                     # 서버 전체 (SQLite 메모리 DB)
python scripts/make_sample_escpos.py -o out/sample.bin   # 샘플 ESC/POS 영수증
```

## 라이선스

Private - All Rights Reserved

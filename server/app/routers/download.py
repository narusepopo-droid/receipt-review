"""
다운로드 라우터
설치 파일 다운로드 및 버전 정보 제공
"""
import os
import hashlib
from datetime import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel
from typing import Optional

router = APIRouter(tags=["download"])


# ============ Pydantic Models ============

class VersionInfo(BaseModel):
    version: str
    filename: str
    sha256: str
    release_date: str
    download_url: str
    release_notes: Optional[str] = None


# ============ 설정 ============

INSTALLER_DIR = "uploads/installers"
CURRENT_VERSION = "1.0.0"  # TODO: DB에서 조회


# ============ 다운로드 페이지 ============

@router.get("/download", response_class=HTMLResponse)
async def download_page():
    """설치 파일 다운로드 페이지 (placemaster.co.kr에서 링크)"""

    # TODO: DB에서 최신 버전 정보 조회
    version_info = {
        "version": CURRENT_VERSION,
        "release_date": "2026-10-07",
        "sha256": "확인 후 표시됩니다",
        "requirements": [
            "Windows 7 SP1 이상 (Windows 10/11 권장)",
            ".NET Framework 4.6.2 이상",
            "영수증 프린터 연결 필요"
        ]
    }

    html = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>영수증리뷰 - 포스 에이전트 다운로드</title>
        <link rel="preconnect" href="https://cdn.jsdelivr.net">
        <link href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css" rel="stylesheet">
        <style>
            :root {{
                --primary: #03C75A;
                --primary-dark: #00a648;
                --text: #1a1a1a;
                --text-secondary: #666;
                --bg: #f8f9fa;
                --card: #ffffff;
                --border: #e9ecef;
            }}

            * {{ box-sizing: border-box; margin: 0; padding: 0; }}

            body {{
                font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, sans-serif;
                background: var(--bg);
                color: var(--text);
                line-height: 1.6;
            }}

            .container {{
                max-width: 800px;
                margin: 0 auto;
                padding: 60px 20px;
            }}

            .header {{
                text-align: center;
                margin-bottom: 48px;
            }}

            .logo {{
                font-size: 32px;
                font-weight: 700;
                color: var(--primary);
                margin-bottom: 8px;
            }}

            .subtitle {{
                color: var(--text-secondary);
                font-size: 18px;
            }}

            .card {{
                background: var(--card);
                border-radius: 16px;
                padding: 32px;
                margin-bottom: 24px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            }}

            .card-title {{
                font-size: 20px;
                font-weight: 600;
                margin-bottom: 20px;
                display: flex;
                align-items: center;
                gap: 8px;
            }}

            .download-btn {{
                display: block;
                width: 100%;
                padding: 20px;
                background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
                color: white;
                font-size: 18px;
                font-weight: 600;
                border: none;
                border-radius: 12px;
                cursor: pointer;
                text-align: center;
                text-decoration: none;
                transition: transform 0.2s, box-shadow 0.2s;
            }}

            .download-btn:hover {{
                transform: translateY(-2px);
                box-shadow: 0 4px 16px rgba(3, 199, 90, 0.3);
            }}

            .version-info {{
                display: grid;
                grid-template-columns: repeat(2, 1fr);
                gap: 16px;
                margin-top: 20px;
            }}

            .info-item {{
                padding: 16px;
                background: var(--bg);
                border-radius: 8px;
            }}

            .info-label {{
                font-size: 13px;
                color: var(--text-secondary);
                margin-bottom: 4px;
            }}

            .info-value {{
                font-size: 15px;
                font-weight: 500;
            }}

            .steps {{
                counter-reset: step;
            }}

            .step {{
                display: flex;
                gap: 16px;
                margin-bottom: 20px;
            }}

            .step-number {{
                width: 32px;
                height: 32px;
                background: var(--primary);
                color: white;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: 600;
                flex-shrink: 0;
            }}

            .step-content h4 {{
                font-size: 16px;
                margin-bottom: 4px;
            }}

            .step-content p {{
                font-size: 14px;
                color: var(--text-secondary);
            }}

            .requirements {{
                list-style: none;
            }}

            .requirements li {{
                padding: 8px 0;
                padding-left: 24px;
                position: relative;
                color: var(--text-secondary);
            }}

            .requirements li::before {{
                content: "✓";
                position: absolute;
                left: 0;
                color: var(--primary);
                font-weight: 600;
            }}

            .hash {{
                font-family: monospace;
                font-size: 12px;
                word-break: break-all;
                background: var(--bg);
                padding: 12px;
                border-radius: 8px;
                margin-top: 16px;
            }}

            .contact {{
                text-align: center;
                margin-top: 40px;
                color: var(--text-secondary);
            }}

            .contact a {{
                color: var(--primary);
                text-decoration: none;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="logo">영수증리뷰</div>
                <p class="subtitle">포스 에이전트 설치 프로그램</p>
            </div>

            <div class="card">
                <a href="/download/latest" class="download-btn">
                    📥 최신 버전 다운로드 (v{version_info['version']})
                </a>

                <div class="version-info">
                    <div class="info-item">
                        <div class="info-label">버전</div>
                        <div class="info-value">{version_info['version']}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">배포일</div>
                        <div class="info-value">{version_info['release_date']}</div>
                    </div>
                </div>

                <div class="hash">
                    <strong>SHA-256:</strong> {version_info['sha256']}
                </div>
            </div>

            <div class="card">
                <div class="card-title">📋 설치 방법</div>
                <div class="steps">
                    <div class="step">
                        <div class="step-number">1</div>
                        <div class="step-content">
                            <h4>다운로드</h4>
                            <p>위 버튼을 클릭하여 설치 파일을 다운로드합니다.</p>
                        </div>
                    </div>
                    <div class="step">
                        <div class="step-number">2</div>
                        <div class="step-content">
                            <h4>설치 실행</h4>
                            <p>다운로드한 파일을 실행하고 안내에 따라 설치합니다.</p>
                        </div>
                    </div>
                    <div class="step">
                        <div class="step-number">3</div>
                        <div class="step-content">
                            <h4>활성화 코드 입력</h4>
                            <p>광고토대왕 담당자에게 받은 8자리 활성화 코드를 입력합니다.</p>
                        </div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-title">💻 시스템 요구사항</div>
                <ul class="requirements">
                    {"".join(f'<li>{req}</li>' for req in version_info['requirements'])}
                </ul>
            </div>

            <div class="contact">
                문의: 광고토대왕 | <a href="mailto:support@placemaster.co.kr">support@placemaster.co.kr</a>
            </div>
        </div>
    </body>
    </html>
    """

    return HTMLResponse(content=html)


@router.get("/download/latest")
async def download_latest():
    """최신 설치 파일 다운로드"""

    # TODO: DB에서 최신 버전 파일명 조회
    filename = f"ReceiptTap_{CURRENT_VERSION}.exe"
    filepath = os.path.join(INSTALLER_DIR, filename)

    if not os.path.exists(filepath):
        raise HTTPException(
            status_code=404,
            detail="설치 파일을 찾을 수 없습니다. 관리자에게 문의하세요."
        )

    # TODO: 다운로드 카운트 증가

    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="application/octet-stream"
    )


@router.get("/agent/v1/latest")
async def get_latest_version():
    """에이전트 최신 버전 정보 (자동 업데이트용)"""

    # TODO: DB에서 조회
    filename = f"ReceiptTap_{CURRENT_VERSION}.exe"
    filepath = os.path.join(INSTALLER_DIR, filename)

    sha256 = ""
    if os.path.exists(filepath):
        with open(filepath, "rb") as f:
            sha256 = hashlib.sha256(f.read()).hexdigest()

    return JSONResponse({
        "version": CURRENT_VERSION,
        "download_url": "/download/latest",
        "sha256": sha256,
        "release_date": "2026-10-07",
        "mandatory": False,  # 필수 업데이트 여부
        "release_notes": "초기 버전"
    })


@router.get("/download/version/{version}")
async def download_specific_version(version: str):
    """특정 버전 다운로드"""

    filename = f"ReceiptTap_{version}.exe"
    filepath = os.path.join(INSTALLER_DIR, filename)

    if not os.path.exists(filepath):
        raise HTTPException(
            status_code=404,
            detail=f"버전 {version}을 찾을 수 없습니다."
        )

    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="application/octet-stream"
    )

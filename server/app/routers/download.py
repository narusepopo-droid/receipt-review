"""
?ㅼ슫濡쒕뱶 ?쇱슦???ㅼ튂 ?뚯씪 ?ㅼ슫濡쒕뱶 諛?踰꾩쟾 ?뺣낫 ?쒓났
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


# ============ ?ㅼ젙 ============

INSTALLER_DIR = "app/static/downloads"
CURRENT_VERSION = "1.0.3"
CURRENT_FILENAME = "ReceiptTap_v1.0.3.zip"


# ============ ?ㅼ슫濡쒕뱶 ?섏씠吏 ============

@router.get("/download", response_class=HTMLResponse)
async def download_page():
    """?ㅼ튂 ?뚯씪 ?ㅼ슫濡쒕뱶 ?섏씠吏 - 濡쒓렇???꾩닔"""

    version_info = {
        "version": CURRENT_VERSION,
        "release_date": "2026-10-08",
        "sha256": "?뚯씪 ?ㅼ슫濡쒕뱶 ???뺤씤",
    }

    html = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>?곸닔利앸━酉?- ?ъ뒪 ?먯씠?꾪듃 ?ㅼ슫濡쒕뱶</title>
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
                content: "??;
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
                <div class="logo">?곸닔利앸━酉?/div>
                <p class="subtitle">?ъ뒪 ?먯씠?꾪듃 ?ㅼ튂 ?꾨줈洹몃옩</p>
            </div>

            <div class="card">
                <a href="/download/latest" class="download-btn">
                    ?뱿 理쒖떊 踰꾩쟾 ?ㅼ슫濡쒕뱶 (v{version_info['version']})
                </a>

                <div class="version-info">
                    <div class="info-item">
                        <div class="info-label">踰꾩쟾</div>
                        <div class="info-value">{version_info['version']}</div>
                    </div>
                    <div class="info-item">
                        <div class="info-label">諛고룷??/div>
                        <div class="info-value">{version_info['release_date']}</div>
                    </div>
                </div>

                <div class="hash">
                    <strong>SHA-256:</strong> {version_info['sha256']}
                </div>
            </div>

            <div class="card">
                <div class="card-title">?뱥 ?ㅼ튂 諛⑸쾿</div>
                <div class="steps">
                    <div class="step">
                        <div class="step-number">1</div>
                        <div class="step-content">
                            <h4>?ㅼ슫濡쒕뱶</h4>
                            <p>??踰꾪듉???대┃?섏뿬 ?ㅼ튂 ?뚯씪???ㅼ슫濡쒕뱶?⑸땲??</p>
                        </div>
                    </div>
                    <div class="step">
                        <div class="step-number">2</div>
                        <div class="step-content">
                            <h4>?뺤텞 ?湲?/h4>
                            <p>?ㅼ슫濡쒕뱶??ZIP ?뚯씪???뺤텞???됰땲??</p>
                        </div>
                    </div>
                    <div class="step">
                        <div class="step-number">3</div>
                        <div class="step-content">
                            <h4>?ㅽ뻾 諛?濡쒓렇??/h4>
                            <p>ReceiptTap.exe瑜??ㅽ뻾?섍퀬 諛쒓툒諛쏆? 怨꾩젙?쇰줈 濡쒓렇?명빀?덈떎.</p>
                        </div>
                    </div>
                </div>
            </div>

            <div class="card">
                <div class="card-title">?뮲 ?쒖뒪???붽뎄?ы빆</div>
                <ul class="requirements">
                    {"".join(f'<li>{req}</li>' for req in version_info['requirements'])}
                </ul>
            </div>

            <div class="contact">
                臾몄쓽: 愿묎퀬?좊???| <a href="mailto:support@placemaster.co.kr">support@placemaster.co.kr</a>
            </div>
        </div>
    </body>
    </html>
    """

    return HTMLResponse(content=html)


@router.get("/download/latest")
async def download_latest():
    """理쒖떊 ?ㅼ튂 ?뚯씪 ?ㅼ슫濡쒕뱶"""

    filepath = os.path.join(INSTALLER_DIR, CURRENT_FILENAME)

    if not os.path.exists(filepath):
        raise HTTPException(
            status_code=404,
            detail="?ㅼ튂 ?뚯씪??李얠쓣 ???놁뒿?덈떎. 愿由ъ옄?먭쾶 臾몄쓽?섏꽭??"
        )

    return FileResponse(
        path=filepath,
        filename=CURRENT_FILENAME,
        media_type="application/zip"
    )


@router.get("/agent/v1/latest")
async def get_latest_version():
    """?먯씠?꾪듃 理쒖떊 踰꾩쟾 ?뺣낫 (?먮룞 ?낅뜲?댄듃??"""

    # TODO: DB?먯꽌 議고쉶
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
        "mandatory": False,  # ?꾩닔 ?낅뜲?댄듃 ?щ?
        "release_notes": "珥덇린 踰꾩쟾"
    })


@router.get("/download/version/{version}")
async def download_specific_version(version: str):
    """?뱀젙 踰꾩쟾 ?ㅼ슫濡쒕뱶"""

    filename = f"ReceiptTap_{version}.exe"
    filepath = os.path.join(INSTALLER_DIR, filename)

    if not os.path.exists(filepath):
        raise HTTPException(
            status_code=404,
            detail=f"踰꾩쟾 {version}??李얠쓣 ???놁뒿?덈떎."
        )

    return FileResponse(
        path=filepath,
        filename=filename,
        media_type="application/octet-stream"
    )

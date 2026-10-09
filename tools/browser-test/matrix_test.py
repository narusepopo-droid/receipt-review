"""
실행: pip install playwright && python -m playwright install chromium webkit
      python tools/browser-test/matrix_test.py   (server 의존성 설치된 파이썬으로)

손님 화면 기기·브라우저 매트릭스 시뮬레이션 (지시서 5.6 테스트 매트릭스)
아이폰: WebKit(사파리 엔진) + iOS 공유창(navigator.share) 흉내 → 탭 순간에 파일과 함께 호출되는지 확인
갤럭시: Chromium + 실제 다운로드·클립보드
인앱(카톡·네이버·인스타그램)은 User-Agent 로 흉내
"""
import asyncio
import os
import random
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SERVER = Path(__file__).resolve().parents[2] / "server"
import tempfile
WORK = Path(tempfile.gettempdir()) / "receipt_review_matrix"
WORK.mkdir(exist_ok=True)
DB = WORK / "bm.db"
if DB.exists():
    DB.unlink()
PORT = 18902
BASE = f"http://127.0.0.1:{PORT}"
NAVER = f"{BASE}/static/css/customer.css?naver"
env = dict(os.environ, DATABASE_URL=f"sqlite+aiosqlite:///{DB.as_posix()}",
           RECEIPT_IMAGE_DIR=str(WORK / "img"), RECEIPT_RAW_DIR=str(WORK / "raw"), PYTHONIOENCODING="utf-8")

IOS_SAFARI = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
              "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1")
IOS_KAKAO = IOS_SAFARI.replace(" Safari/604.1", " KAKAOTALK 10.8.5")
IOS_NAVER = IOS_SAFARI.replace(" Safari/604.1", " NAVER(inapp; search; 2000; 12.5.3; 13PRO)")
AND_CHROME = ("Mozilla/5.0 (Linux; Android 14; SM-S918N) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Mobile Safari/537.36")
AND_SAMSUNG = AND_CHROME.replace("Chrome/126.0.0.0 Mobile", "SamsungBrowser/25.0 Chrome/121.0.0.0 Mobile")
AND_KAKAO = AND_CHROME + " KAKAOTALK 10.8.5"
AND_NAVER = AND_CHROME + " NAVER(inapp; search; 2000; 12.5.3)"
AND_INSTA = AND_CHROME + " Instagram 330.0.0.0 Android"

CASES = [
    ("아이폰 사파리", "webkit", IOS_SAFARI, "ios"),
    ("아이폰 카톡 인앱", "webkit", IOS_KAKAO, "ios"),
    ("아이폰 네이버앱", "webkit", IOS_NAVER, "ios"),
    ("갤럭시 크롬", "chromium", AND_CHROME, "android"),
    ("갤럭시 삼성인터넷", "chromium", AND_SAMSUNG, "android"),
    ("갤럭시 카톡 인앱", "chromium", AND_KAKAO, "android"),
    ("갤럭시 네이버앱", "chromium", AND_NAVER, "android"),
    ("갤럭시 인스타그램", "chromium", AND_INSTA, "android"),
]

# iOS 공유창 흉내: 호출 시점·파일 정보를 기록 (실제 기기에서는 "이미지 저장" 선택)
SHARE_MOCK = """
window.__share = null; window.__copied = null;
navigator.canShare = (d) => !!(d && d.files && d.files.length);
navigator.share = (d) => { window.__share = { n: d.files.length, type: d.files[0].type, size: d.files[0].size,
  sync: !!window.__inClick }; return new Promise(r => setTimeout(r, 300)); };
document.addEventListener('click', () => { window.__inClick = true; setTimeout(() => window.__inClick = false, 0); }, true);
const _ec = document.execCommand.bind(document);
document.execCommand = (c, ...a) => { if (c === 'copy') { window.__copied = String(window.getSelection() || '') ||
  (document.activeElement && document.activeElement.value) || '__copy__'; } return _ec(c, ...a); };
"""


async def prepare():
    os.environ.update(env)
    sys.path.insert(0, str(SERVER))
    sys.path.insert(0, str(SERVER / "scripts"))
    os.chdir(SERVER)
    from app.db import engine, async_session_factory
    from app.models.base import Base
    from app.models.store import Store, StoreSettings
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_factory() as s:
        st = Store(name="매트릭스 매장", store_code="BM01", naver_review_url=NAVER)
        s.add(st)
        await s.flush()
        s.add(StoreSettings(store_id=st.id, signature_menus=["돼지김치찌개"]))
        await s.commit()
    await engine.dispose()


def run_server():
    log = open(WORK / "server.log", "w", encoding="utf-8")
    p = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT)],
                         cwd=SERVER, env=env, stdout=log, stderr=subprocess.STDOUT)
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", PORT), 0.5).close()
            return p
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("server did not start")


def upload_receipts(n):
    import httpx
    import make_sample_escpos as samples
    from app.routers.auth import generate_token
    for i in range(n):
        data = samples.card_receipt().replace(b"30012345", str(31000000 + i).encode())
        httpx.post(f"{BASE}/agent/v1/receipts", headers={"Authorization": f"Bearer {generate_token(1)}"},
                   files={"file": ("r.bin", data, "application/octet-stream")},
                   data={"captured_at": datetime.now(timezone.utc).isoformat()})


async def run_case(pw, name, engine_name, ua, kind, idx):
    res = {}
    browser = await getattr(pw, engine_name).launch()
    vp = {"width": 390, "height": 844} if kind == "ios" else {"width": 412, "height": 915}
    ctx = await browser.new_context(user_agent=ua, viewport=vp, is_mobile=(engine_name == "chromium"),
                                    has_touch=True, accept_downloads=True, locale="ko-KR")
    if engine_name == "chromium":
        await ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE)
    if kind == "ios":
        await ctx.add_init_script(SHARE_MOCK)
    page = await ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        if "KAKAOTALK" in ua:
            # 1) 첫 접속 시 외부 브라우저 열기 시도 확인
            try:
                await page.goto(f"{BASE}/t/BM01/{idx}", wait_until="domcontentloaded", timeout=5000)
            except Exception:
                pass
            await page.wait_for_timeout(800)
            try:
                tried = await page.evaluate("sessionStorage.getItem('kakaoExternalTried')")
            except Exception:
                tried = None
            res["외부브라우저 시도"] = tried == "1"
            # 2) 외부 열기가 안 된 경우 → 카톡 안에서 계속 진행 (같은 탭이라 재시도 안 함)
            if not tried:
                await ctx.add_init_script("sessionStorage.setItem('kakaoExternalTried','1')")
        await page.goto(f"{BASE}/t/BM01/{idx}")
        await page.wait_for_timeout(600)
        guide = await page.locator(".inapp-guide").count()
        if guide:
            res["인앱 안내"] = "표시"
            await page.click(".inapp-guide__continue")
        if page.url.startswith(BASE) is False:
            await page.goto(f"{BASE}/t/BM01/{idx}")
        await page.fill("#phoneInput", f"010{random.randint(10000000, 99999999)}")
        if not await page.locator("#privacyAgree").is_checked():
            await page.check("#privacyAgree")
        await page.click("#submitPhone")
        await page.wait_for_url("**/keywords", timeout=8000)
        await page.click("#submitKeywords")
        await page.wait_for_url("**/result", timeout=8000)
        await page.wait_for_function("document.getElementById('receiptImage') && document.getElementById('receiptImage').naturalWidth > 0", timeout=8000)
        res["번호 입력·키워드"] = True
        text = (await page.inner_text("#reviewText")).strip()
        await page.wait_for_timeout(500)  # 이미지 미리 받기

        if kind == "ios":
            await page.click("#mainAction")
            await page.wait_for_timeout(700)
            share = await page.evaluate("window.__share")
            res["영수증 저장"] = bool(share and share["n"] == 1 and share["type"] == "image/png" and share["size"] > 1000 and share["sync"])
            copied = await page.evaluate("window.__copied")
            res["문구 복사"] = bool(copied)
            btn = await page.inner_text("#mainAction")
            await page.click("#mainAction")       # 두 번째 탭: 네이버로
            await page.wait_for_url("**/customer.css?naver", timeout=5000)
            res["네이버 이동"] = "네이버로 이동" in btn
        else:
            async with page.expect_download(timeout=5000) as dl:
                await page.click("#mainAction")
            d = await dl.value
            p = WORK / f"dl_{idx}.png"
            await d.save_as(p)
            res["영수증 저장"] = p.read_bytes()[:4] == b"\x89PNG"
            clip = await page.evaluate("navigator.clipboard.readText()")
            res["문구 복사"] = clip.strip() == text
            await page.wait_for_url("**/customer.css?naver", timeout=5000)
            res["네이버 이동"] = True

        await page.go_back()
        await page.wait_for_url("**/result", timeout=5000)
        await page.click("#doneButton")
        await page.wait_for_url("**/complete", timeout=5000)
        res["완료 화면"] = "리뷰 등록 완료" in await page.content()
        res["스크립트 오류 없음"] = not errors
        if errors:
            res["오류"] = "; ".join(errors)[:150]
        try:
            await page.screenshot(path=str(WORK / f"case_{idx}.png"), timeout=5000)
        except Exception:
            pass
    except Exception as e:
        res["실패"] = f"{type(e).__name__}: {str(e)[:150]}"
        res["url"] = page.url
        try:
            await page.screenshot(path=str(WORK / f"case_{idx}_fail.png"), timeout=5000)
        except Exception:
            pass
    finally:
        await browser.close()
    return res


async def main():
    from playwright.async_api import async_playwright
    all_ok = True
    async with async_playwright() as pw:
        for i, (name, eng, ua, kind) in enumerate(CASES, start=1):
            r = await run_case(pw, name, eng, ua, kind, i)
            ok = "실패" not in r and all(v is True or v == "표시" for k, v in r.items() if k != "오류")
            all_ok &= ok
            print(f"{'OK  ' if ok else 'FAIL'} {name}: " + ", ".join(f"{k}={v}" for k, v in r.items()))
    print("\n전체:", "통과" if all_ok else "실패 있음")


if __name__ == "__main__":
    asyncio.run(prepare())
    proc = run_server()
    try:
        upload_receipts(len(CASES) + 2)
        asyncio.run(main())
    finally:
        proc.terminate()

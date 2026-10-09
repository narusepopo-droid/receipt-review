"""
운영 서버 전체 흐름 점검 (배포 후 실행)

임시 테스트 매장을 만들어 실제 API로 다음을 확인하고, 끝나면 그 매장 데이터를 모두 지운다.
  1. 포스 업로드: 샘플 카드 영수증 → normal 저장, PNG 생성
  2. 주방 주문서 → 저장 안 함
  3. 손님: 번호 입력 → 키워드 → 영수증 배정 → 영수증 PNG 받기
  4. 같은 번호 재입장 → 기존 세션 재사용
  5. 취소 영수증 → 기존 영수증 폐기 + 파일 삭제

사용법 (서버에서):
    cd ~/receipt-review/server && venv/bin/python scripts/e2e_smoke.py
    venv/bin/python scripts/e2e_smoke.py --base https://review.placemaster.co.kr   (쿠키 화면까지 확인하려면 HTTPS)
"""
import argparse
import asyncio
import os
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.db import async_session_factory  # noqa: E402
from app.models.store import Store, StoreSettings, Agent  # noqa: E402
from app.models.receipt import Receipt, ReceiptStatus  # noqa: E402
from app.models.customer import Customer, StoreCustomer, ConsentLog  # noqa: E402
from app.models.session import ReviewSession, TextHistory, EventLog  # noqa: E402
from app.routers.auth import generate_token  # noqa: E402
import make_sample_escpos as samples  # noqa: E402

OK, FAIL = "✅", "❌"
results = []


def check(name, cond, detail=""):
    results.append(cond)
    print(f"{OK if cond else FAIL} {name}" + (f"  ({detail})" if detail else ""))
    return cond


async def create_store():
    code = "E2E" + "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=5))
    async with async_session_factory() as s:
        store = Store(name="E2E 점검 매장", store_code=code, paper_width=576)
        s.add(store)
        await s.commit()
        return store.id, code


async def cleanup(store_id):
    async with async_session_factory() as s:
        recs = (await s.execute(select(Receipt).where(Receipt.store_id == store_id))).scalars().all()
        for r in recs:
            for p in (r.image_path, r.raw_bytes_path):
                if p and os.path.exists(p):
                    os.remove(p)
        cust_ids = [c for (c,) in (await s.execute(
            select(StoreCustomer.customer_id).where(StoreCustomer.store_id == store_id))).all()]
        for model in (EventLog, TextHistory, ReviewSession, Receipt, ConsentLog, StoreCustomer, Agent, StoreSettings):
            await s.execute(delete(model).where(model.store_id == store_id))
        # 다른 매장에 기록이 없는 테스트 고객만 삭제
        for cid in cust_ids:
            other = (await s.execute(select(StoreCustomer).where(StoreCustomer.customer_id == cid))).first()
            if not other:
                await s.execute(delete(ConsentLog).where(ConsentLog.customer_id == cid))
                await s.execute(delete(Customer).where(Customer.id == cid))
        await s.execute(delete(Store).where(Store.id == store_id))
        await s.commit()


async def receipt_rows(store_id):
    async with async_session_factory() as s:
        return (await s.execute(select(Receipt).where(Receipt.store_id == store_id))).scalars().all()


async def run(base: str, keep: bool):
    store_id, code = await create_store()
    print(f"임시 매장 생성: id={store_id} code={code}")
    token = generate_token(store_id)
    try:
        async with httpx.AsyncClient(base_url=base, timeout=30, verify=True) as c:
            auth = {"Authorization": f"Bearer {token}"}

            async def upload(data):
                return await c.post("/agent/v1/receipts", headers=auth,
                                    files={"file": ("r.bin", data, "application/octet-stream")},
                                    data={"captured_at": datetime.now(timezone.utc).isoformat(),
                                          "capture_mode": "serial", "agent_version": "e2e"})

            r = await upload(samples.card_receipt())
            check("포스 업로드 (카드 영수증)", r.status_code == 200 and r.json().get("classification") == "normal", r.text[:120])
            rows = await receipt_rows(store_id)
            check("영수증 PNG 생성", bool(rows) and rows[0].image_path and os.path.exists(rows[0].image_path))

            r = await upload(samples.kitchen_order())
            check("주방 주문서 걸러냄", r.json().get("classification") == "kitchen", r.text[:120])

            r = await c.post("/agent/v1/heartbeat", headers=auth, json={
                "version": "e2e", "capture_mode": "serial", "last_capture_at": None, "queue_length": 0})
            check("하트비트", r.status_code == 200, r.text[:120])

            phone = "010-0000-" + "".join(random.choices("0123456789", k=4))
            r = await c.post(f"/api/v1/session/start?store_code={code}", json={"phone": phone, "marketing_opt_in": False})
            check("손님 번호 입력 → 세션 시작", r.status_code == 200, r.text[:160])
            sid = r.json().get("session_id")

            r = await c.post(f"/api/v1/session/{sid}/keywords", json={"keywords": ["맛있어요"]})
            check("키워드 저장", r.status_code == 200, r.text[:120])

            r = await c.post(f"/api/v1/session/{sid}/assign")
            ok = check("영수증 배정 + 문구 생성", r.status_code == 200, r.text[:200])
            if ok:
                a = r.json()
                print("   문구:", a.get("generated_text"))
                img = await c.get(f"/api/v1/receipt-image/{a['image_token']}",
                                  params={"session_id": sid, "receipt_id": a["receipt_id"]})
                check("영수증 이미지 받기 (PNG)", img.status_code == 200 and img.content[:8] == b"\x89PNG\r\n\x1a\n",
                      f"{len(img.content)} bytes")

            # 손님 화면 (쿠키): 결과 화면에 실제 영수증 이미지 주소, QR 재접속 시 결과 화면 복귀
            pc = httpx.AsyncClient(base_url=base, timeout=30)
            await pc.post(f"/api/v1/session/start?store_code={code}", json={"phone": phone, "marketing_opt_in": False})
            page = await pc.get(f"/t/{code}/1/result")
            check("결과 화면 (쿠키 세션, 실제 영수증)", page.status_code == 200 and "/api/v1/receipt-image/" in page.text,
                  f"{page.status_code} {'쿠키 미전달 - HTTPS 주소로 실행 필요' if page.status_code in (302, 307) or 'receipt-image' not in page.text else ''}")
            back = await pc.get(f"/t/{code}/1", follow_redirects=False)
            check("QR 재접속 → 결과 화면", back.status_code == 302 and back.headers.get("location", "").endswith("/result"))
            await pc.aclose()

            r = await c.post(f"/api/v1/session/start?store_code={code}", json={"phone": phone, "marketing_opt_in": False})
            check("같은 번호 재입장 → 기존 세션", r.status_code == 200 and r.json().get("is_returning") is True, r.text[:160])

            r = await upload(samples.card_receipt(cancel=True))
            rows = await receipt_rows(store_id)
            check("취소 영수증 → 기존 영수증 폐기",
                  r.json().get("classification") == "cancelled"
                  and all(x.status == ReceiptStatus.DISPOSED and not x.image_path for x in rows), r.text[:120])
    finally:
        if keep:
            print(f"(--keep) 테스트 매장 유지: {code}")
        else:
            await cleanup(store_id)
            print("임시 매장 데이터 삭제 완료")

    print(f"\n결과: {sum(results)}/{len(results)} 통과")
    return all(results)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    sys.exit(0 if asyncio.run(run(a.base, a.keep)) else 1)

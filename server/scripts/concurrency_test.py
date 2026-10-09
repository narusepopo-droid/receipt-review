"""
운영 DB(PostgreSQL) 동시성 백테스트 — 지시서 5.4: 동시 50요청에서 같은 영수증 중복 배정 0건

임시 매장에 영수증 N장 업로드 → 손님 M명이 '동시에' 결과 화면 진입(배정) →
  · 같은 영수증이 두 손님에게 가지 않았는지
  · 배정 수 = min(N, M), 나머지는 '잠시 후 다시' 화면
  · 같은 손님 재요청은 같은 영수증
끝나면 임시 매장 데이터 삭제.

사용법 (서버에서): cd ~/receipt-review/server && venv/bin/python scripts/concurrency_test.py
"""
import asyncio
import random
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.db import async_session_factory  # noqa: E402
from app.models.receipt import Receipt  # noqa: E402
from app.routers.auth import generate_token  # noqa: E402
from e2e_smoke import create_store, cleanup  # noqa: E402
import make_sample_escpos as samples  # noqa: E402

BASE = "http://127.0.0.1:8000"
RECEIPTS, CUSTOMERS = 30, 50


async def main():
    store_id, code = await create_store()
    print(f"임시 매장 {code}: 영수증 {RECEIPTS}장, 손님 {CUSTOMERS}명 동시")
    ok = True
    try:
        async with httpx.AsyncClient(base_url=BASE, timeout=60) as c:
            auth = {"Authorization": f"Bearer {generate_token(store_id)}"}
            for i in range(RECEIPTS):
                data = samples.card_receipt().replace(b"30012345", str(40000000 + i).encode())
                r = await c.post("/agent/v1/receipts", headers=auth,
                                 files={"file": ("r.bin", data, "application/octet-stream")},
                                 data={"captured_at": datetime.now(timezone.utc).isoformat()})
                assert r.json()["classification"] == "normal", r.text

            # 손님마다 별도 쿠키(세션)로 번호 입력
            clients = []
            for i in range(CUSTOMERS):
                # 손님마다 다른 접속 IP (nginx 가 넣는 X-Real-IP 흉내, 요청 제한은 IP별)
                cc = httpx.AsyncClient(base_url=BASE, timeout=60, headers={"X-Real-IP": f"10.77.{i // 200}.{i % 200 + 1}"})
                r = await cc.post(f"/api/v1/session/start?store_code={code}",
                                  json={"phone": f"0109{random.randint(1000000, 9999999)}"})
                assert r.status_code == 200, r.text
                clients.append(cc)

            # 동시에 결과 화면 진입 → 배정
            async def enter(cc):
                r = await cc.get(f"/t/{code}/1/result")
                m = re.search(r"receipt_id=([0-9a-f-]{36})", r.text)
                return m.group(1) if m else None

            results = await asyncio.gather(*(enter(cc) for cc in clients))
            assigned = [r for r in results if r]
            dup = [rid for rid, n in Counter(assigned).items() if n > 1]
            print(f"배정 {len(assigned)}명 / 대기 화면 {results.count(None)}명 / 중복 {len(dup)}건")
            ok &= not dup and len(assigned) == min(RECEIPTS, CUSTOMERS)

            # 같은 손님이 다시 들어오면 같은 영수증
            again = await asyncio.gather(*(enter(cc) for cc in clients[:10]))
            same = sum(1 for a, b in zip(results[:10], again) if a and a == b)
            print(f"재진입 같은 영수증: {same}/{sum(1 for a in results[:10] if a)}")
            ok &= same == sum(1 for a in results[:10] if a)

            for cc in clients:
                await cc.aclose()

        async with async_session_factory() as s:
            rows = (await s.execute(select(Receipt).where(Receipt.store_id == store_id))).scalars().all()
            sess_ids = [r.assigned_session_id for r in rows if r.assigned_session_id]
            print(f"DB: 배정된 영수증 {len(sess_ids)}장, 세션 중복 {len(sess_ids) - len(set(sess_ids))}")
            ok &= len(sess_ids) == len(set(sess_ids))
    finally:
        await cleanup(store_id)
        print("임시 매장 삭제 완료")
    print("결과:", "통과" if ok else "실패")
    return ok


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) else 1)

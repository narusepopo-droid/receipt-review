"""영수증 품목(메뉴) 읽기 + 대시보드 기간(일·주·월)·메뉴별 판매량"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.receipt.escpos_parser import extract_items
from app.routers.admin import dashboard_range, menu_ranking
from tests.test_web_pages import web  # noqa: F401  (fixture)

KASOL = """수작나베(석촌호수직영점) / 846-87-03229 / 신재준
2026-10-14 12:57:27
------------------------------------------
    상  품  명       단 가  수량     금 액
------------------------------------------
스키야키(관동-국    17,500    2     35,000
▶호주청정우등심         0    2          0
▶계란소스           1,400    2      1,400
------------------------------------------
합 계  금 액                        36,400
승 인 번 호: 01158408"""

CAFE = """메뉴            수량      금액
--------------------------------
아메리카노
                   2     9,000
카페라떼           1     5,000
--------------------------------
합계                    14,000"""


def test_extract_items_kasol_and_wrapped_name():
    it = extract_items(KASOL.split("\n"))
    assert [(x["name"], x["qty"], x["price"], x["option"]) for x in it] == [
        ("스키야키(관동-국", 2, 35000, False), ("호주청정우등심", 2, 0, True), ("계란소스", 2, 1400, True)]
    assert it[0]["unit"] == 17500
    it = extract_items(CAFE.split("\n"))
    assert [(x["name"], x["qty"], x["price"]) for x in it] == [("아메리카노", 2, 9000), ("카페라떼", 1, 5000)]
    assert extract_items("영수증\n합계 1,000".split("\n")) == []


def test_menu_ranking_order():
    menus, opts = menu_ranking([
        [{"name": "A", "qty": 1, "price": 1000}, {"name": "B", "qty": 3, "price": 900}],
        [{"name": "A", "qty": 1, "price": 1000}, {"name": "옵션", "qty": 2, "price": 0, "option": True}],
        None])
    assert [(m["name"], m["qty"], m["rank"]) for m in menus] == [("B", 3, 1), ("A", 2, 2)]
    assert menus[0]["pct"] == 100 and opts[0]["name"] == "옵션"


def test_dashboard_range_day_week_month():
    r = dashboard_range("day", "2026-10-13")
    assert r["start"].isoformat() == "2026-10-13T05:00:00+09:00" and r["end"].isoformat() == "2026-10-14T05:00:00+09:00"
    assert r["prev"] == "2026-10-12" and r["next"] == "2026-10-14" and r["prev_start"].day == 12
    w = dashboard_range("week", "2026-10-15")       # 목요일 → 월~일
    assert w["start"].date() == date(2026, 10, 12) and w["end"].date() == date(2026, 10, 19) and w["prev"] == "2026-10-05"
    m = dashboard_range("month", "2026-10")
    assert m["start"].date() == date(2026, 10, 1) and m["end"].date() == date(2026, 11, 1) and m["prev"] == "2026-09-01"
    assert dashboard_range("day", "2999-01-01")["is_current"]       # 미래 → 오늘
    assert dashboard_range("bad", "x")["p"] == "day"


@pytest.mark.asyncio
async def test_dashboard_menu_sales_and_periods(web):
    from app.main import app
    from app.db import get_db
    from app.models.receipt import Receipt, ReceiptStatus, ReceiptClassification
    now = datetime.now(timezone.utc)
    gen = app.dependency_overrides[get_db]()
    db = await gen.__anext__()
    db.add(Receipt(store_id=1, approval_no="11110000", amount=36400, paid_at=now,
                   items=extract_items(KASOL.split("\n")), status=ReceiptStatus.AVAILABLE,
                   classification=ReceiptClassification.NORMAL))
    db.add(Receipt(store_id=1, approval_no="22220000", amount=9000, paid_at=now, dispose_reason="cancelled",
                   items=[{"name": "취소된메뉴", "qty": 5, "price": 9000}], status=ReceiptStatus.DISPOSED,
                   classification=ReceiptClassification.NORMAL))
    await db.commit()
    await gen.aclose()

    await web.post("/admin/login", data={"login_id": "owner@test.com", "password": "pw1234!"})
    page = (await web.get("/admin/dashboard")).text
    assert "메뉴별 판매량" in page and "스키야키(관동-국" in page and "36,400원" in page
    assert "취소된메뉴" not in page and "단계별 전환율" not in page and "일별" in page and "주별" in page
    for q in ("?p=week", "?p=month", "?p=month&d=2026-09", "?p=day&d=2020-01-01", "?p=day&d=bad"):
        r = await web.get("/admin/dashboard" + q)
        assert r.status_code == 200, q
    old = (await web.get("/admin/dashboard?p=day&d=2020-01-01")).text
    assert "메뉴가 읽힌 영수증이 없어요" in old and "location.reload" not in old

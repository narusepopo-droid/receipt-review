"""기본 상품·요금제·프로모션 (처음 한 번만 생성, 이후는 운영자 화면에서 수정)"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Plan, PlanKind, Product, Promotion, SignupPolicy, Unit

# 가격은 임시값 — 운영자 화면 > 상품·요금제에서 설정
PRODUCTS = [
    {"code": "plma", "name": "플레이스마스터 PRO", "tagline": "네이버 플레이스 순위 분석기",
     "unit": Unit.ACCOUNT, "monthly_price": 29000, "sort": 1, "download_url": ""},
    {"code": "receipt_review", "name": "영수증리뷰", "tagline": "포스 영수증으로 네이버 영수증 리뷰 자동화",
     "unit": Unit.STORE, "monthly_price": 39000, "sort": 2,
     "download_url": "https://review.placemaster.co.kr/download/latest"},
]

PLANS = [
    # name, kind, months, discount, badge, public, sort
    ("무료 (무제한)", PlanKind.FREE, None, 0, "", False, 0),
    ("월 결제 · 12개월 약정", PlanKind.MONTHLY, 12, 0, "", True, 10),
    ("월 결제 · 24개월 약정", PlanKind.MONTHLY, 24, 5, "", True, 11),
    ("1년 일시불", PlanKind.PREPAID, 12, 15, "인기", True, 20),
    ("2년 일시불", PlanKind.PREPAID, 24, 25, "", True, 21),
    ("영구 이용권", PlanKind.LIFETIME, None, 40, "최대 할인", True, 30),
]


async def seed(db: AsyncSession) -> None:
    for p in PRODUCTS:
        prod = (await db.execute(select(Product).where(Product.code == p["code"]))).scalar_one_or_none()
        if prod:
            continue
        prod = Product(signup_policy=SignupPolicy.APPROVAL, **p)
        db.add(prod)
        await db.flush()
        for name, kind, months, disc, badge, public, sort in PLANS:
            db.add(Plan(product_id=prod.id, name=name, kind=kind, months=months, discount_pct=disc,
                        badge=badge, public=public, sort=sort, lifetime_months=36))
    if not (await db.execute(select(Promotion).where(Promotion.kind == "bundle"))).first():
        db.add(Promotion(name="두 상품 함께 구매 할인", code=None, kind="bundle", value=10, min_products=2))
    await db.commit()

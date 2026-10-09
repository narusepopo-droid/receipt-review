"""
가격 계산

요금제 가격 = 정가(월) × 개월 × (1 − 요금제 할인율)          (직접 가격 지정이 있으면 그 값)
  · 월 자동결제: 매달 청구액 = 정가(월) × (1 − 할인율)    (약정이 길수록 할인율 ↑)
  · 일시불 N개월: 정가 × N × (1 − 할인율)                  (기간이 길수록 할인율 ↑)
  · 영구: 정가 × 기준개월(기본 36) × (1 − 할인율)          (할인율 가장 큼)
  · 무료: 0원
주문 할인 = 묶음 할인(서로 다른 상품 N개 이상) + 프로모션(쿠폰/자동)
전체 할인은 설정의 최대 할인율을 넘지 않음. 금액은 100원 단위.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.models import Plan, PlanKind, Product, Promotion

DEFAULT_MAX_DISCOUNT_PCT = 60


def round100(x: float) -> int:
    return int(round(x / 100.0)) * 100


def list_price(product: Product, plan: Plan) -> int:
    """정가 (할인 전)"""
    if plan.kind == PlanKind.FREE:
        return 0
    if plan.kind == PlanKind.MONTHLY:
        return product.monthly_price
    if plan.kind == PlanKind.LIFETIME:
        return product.monthly_price * (plan.lifetime_months or 36)
    return product.monthly_price * (plan.months or 1)


def plan_price(product: Product, plan: Plan) -> int:
    """요금제 가격 (월 자동결제는 1회 청구액)"""
    if plan.kind == PlanKind.FREE:
        return 0
    if plan.price_override is not None:
        return plan.price_override
    return round100(list_price(product, plan) * (1 - (plan.discount_pct or 0) / 100))


def effective_monthly(product: Product, plan: Plan) -> Optional[int]:
    """월 환산 가격 (비교용). 영구는 기준개월로 나눔"""
    if plan.kind == PlanKind.FREE:
        return 0
    p = plan_price(product, plan)
    if plan.kind == PlanKind.MONTHLY:
        return p
    months = plan.lifetime_months if plan.kind == PlanKind.LIFETIME else plan.months
    return round(p / max(1, months or 1))


def plan_rule_warnings(product: Product, plans: list[Plan]) -> list[str]:
    """'기간 길수록·일시불일수록 싸고, 영구가 가장 싸야 함' 규칙 점검 (운영자 화면 경고)"""
    warns = []
    paid = [p for p in plans if p.kind != PlanKind.FREE and p.public]
    monthly = sorted([p for p in paid if p.kind == PlanKind.MONTHLY], key=lambda p: p.months or 0)
    prepaid = sorted([p for p in paid if p.kind == PlanKind.PREPAID], key=lambda p: p.months or 0)
    lifetime = [p for p in paid if p.kind == PlanKind.LIFETIME]

    def chk(seq, label):
        for a, b in zip(seq, seq[1:]):
            if effective_monthly(product, b) > effective_monthly(product, a):
                warns.append(f"{label}: '{b.name}'(월 {effective_monthly(product, b):,}원)이 "
                             f"'{a.name}'(월 {effective_monthly(product, a):,}원)보다 비쌉니다")
    chk(monthly, "월결제 약정")
    chk(prepaid, "일시불")
    if monthly and prepaid:
        best_monthly = min(effective_monthly(product, p) for p in monthly)
        for p in prepaid:
            if effective_monthly(product, p) > best_monthly:
                warns.append(f"일시불 '{p.name}'이 월결제보다 비쌉니다 (일시불이 더 싸야 함)")
    for lp in lifetime:
        others = [effective_monthly(product, p) for p in monthly + prepaid]
        if others and effective_monthly(product, lp) > min(others):
            warns.append(f"영구권 '{lp.name}'의 할인이 가장 크지 않습니다")
    return warns


@dataclass
class Line:
    product: Product
    plan: Plan
    store_id: Optional[int] = None
    list_amount: int = 0
    amount: int = 0


@dataclass
class Quote:
    lines: list
    list_amount: int
    discounts: list = field(default_factory=list)   # [{"label", "amount"}]
    amount: int = 0
    promo_code: Optional[str] = None
    promo_error: str = ""
    promotion_ids: list = field(default_factory=list)


def _promo_applies(promo: Promotion, lines: list[Line], now: datetime) -> bool:
    if promo.active is False:
        return False
    if promo.starts_at and now < _aware(promo.starts_at):
        return False
    if promo.ends_at and now > _aware(promo.ends_at):
        return False
    if promo.max_uses is not None and (promo.used_count or 0) >= promo.max_uses:
        return False
    target = [l for l in lines
              if (not promo.product_codes or l.product.code in promo.product_codes)
              and (not promo.plan_kinds or l.plan.kind.value in promo.plan_kinds)]
    if not target:
        return False
    if promo.kind == "bundle":
        return len({l.product.code for l in lines}) >= max(2, promo.min_products or 2)
    return True


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt


def build_quote(lines: list[Line], promotions: list[Promotion], promo_code: Optional[str] = None,
                max_discount_pct: int = DEFAULT_MAX_DISCOUNT_PCT, now: Optional[datetime] = None) -> Quote:
    now = now or datetime.now(timezone.utc)
    for l in lines:
        l.list_amount = list_price(l.product, l.plan)
        l.amount = plan_price(l.product, l.plan)

    list_total = sum(l.list_amount for l in lines)
    q = Quote(lines=lines, list_amount=list_total, promo_code=(promo_code or "").strip().upper() or None)
    plan_disc = list_total - sum(l.amount for l in lines)
    if plan_disc > 0:
        q.discounts.append({"label": "요금제 할인 (기간·일시불)", "amount": plan_disc})

    subtotal = sum(l.amount for l in lines)
    extra = 0
    code_found = False
    for promo in promotions:
        is_code = bool(promo.code)
        if is_code and (promo.code or "").upper() != q.promo_code:
            continue
        if is_code:
            code_found = True
        if not _promo_applies(promo, lines, now):
            if is_code:
                q.promo_error = "사용할 수 없는 쿠폰입니다 (기간·대상·사용 횟수 확인)"
            continue
        base = sum(l.amount for l in lines
                   if (not promo.product_codes or l.product.code in promo.product_codes)
                   and (not promo.plan_kinds or l.plan.kind.value in promo.plan_kinds))
        if (promo.kind or "percent") == "amount":
            d = min(promo.value, base)
        else:  # percent / bundle
            d = round100(base * promo.value / 100)
        if d > 0:
            extra += d
            q.discounts.append({"label": promo.name, "amount": d})
            q.promotion_ids.append(promo.id)
    if q.promo_code and not code_found:
        q.promo_error = "없는 쿠폰 코드입니다"

    # 전체 할인 한도
    max_total_disc = round100(list_total * max_discount_pct / 100)
    total_disc = plan_disc + extra
    if total_disc > max_total_disc and extra > 0:
        # 요금제 자체 할인은 운영자가 정한 값이라 유지, 추가 할인(묶음·쿠폰)만 한도까지 줄임
        cut = min(extra, total_disc - max_total_disc)
        extra -= cut
        q.discounts.append({"label": f"최대 할인 한도({max_discount_pct}%) 적용", "amount": -cut})
    q.amount = max(0, subtotal - extra)
    return q

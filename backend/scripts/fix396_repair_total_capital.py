"""🚨 Fix 396 보정 — 「포지션 추가」 이중 가산으로 부풀어 있는 total_capital 을 되돌린다.

기본은 **미리보기만** 한다 (DB 변경 없음). 실제로 고칠 때만 인자 `--apply` 를 준다.
사장님 승인 없이는 절대 --apply 를 쓰지 않는다 (프로젝트 규칙 2: DB UPDATE 는 보고·승인 뒤).

맞는 값의 정의
    total_capital = 사다리 계획(템플릿 total_capital)
                  + 「포지션 추가」 중 **체결된** 금액 (체결수량 × 평단 ÷ 레버리지)
                  + 「증거금 추가」 기록 (알림 본문 「추가 금액」)
  · 미체결·취소된 추가는 넣지 않는다 (그게 이번 결함의 절반이다).
  · 부분 익절로 이미 줄어든 값(tp_sl_orchestrator)은 그대로 존중한다
    → 계산값이 기록값보다 **크면** 건드리지 않는다 (줄이는 방향만 보정).

왜 중요한가
    SL 한도 = total_capital / 레버리지 × sl_pct  → 부풀면 강제손절이 늦게 걸린다.
    노출(calc_reserved_for_account)·화면 자본도 같이 과대가 된다.

쓰는 법 (VPS)
    미리보기: cd ~/binance-auto-trader/backend && docker compose exec -T api python - < scripts/fix396_repair_total_capital.py
    실제보정: … python - --apply < scripts/fix396_repair_total_capital.py   (사장님 승인 뒤)
"""
from __future__ import annotations

import re
import sys

sys.path.insert(0, "/app")

from decimal import Decimal  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.core.strategy_status import TERMINAL_STATUSES  # noqa: E402
from app.models.notification import Notification  # noqa: E402
from app.models.order import Order  # noqa: E402
from app.models.strategy_instance import StrategyInstance  # noqa: E402
from app.models.strategy_template import StrategyTemplate  # noqa: E402

AMOUNT_RE = re.compile(r"추가 (?:금액|증거금|자본)\s*:?\s*([0-9,]+(?:\.[0-9]+)?)")
MIN_DIFF = Decimal("1")          # 1 USDT 미만 차이는 건드리지 않는다


def _margin_added(db, strategy_id: int) -> Decimal:
    total = Decimal("0")
    rows = db.execute(
        select(Notification.body).where(
            Notification.strategy_instance_id == strategy_id,
            Notification.title.like("%증거금 추가%"),
        )
    ).all()
    for (body,) in rows:
        m = AMOUNT_RE.search((body or "").replace("\n", " "))
        if m:
            total += Decimal(m.group(1).replace(",", ""))
    return total


def _filled_adds_margin(db, strategy_id: int, leverage: Decimal) -> Decimal:
    rows = db.execute(
        select(Order.executed_qty, Order.avg_price).where(
            Order.strategy_instance_id == strategy_id,
            Order.purpose == "ENTRY",
            Order.stage_no.is_(None),              # 단계 진입이 아닌 = 「포지션 추가」
            Order.status == "FILLED",
        )
    ).all()
    total = Decimal("0")
    for qty, px in rows:
        if qty and px:
            total += Decimal(str(qty)) * Decimal(str(px)) / leverage
    return total


def main(apply: bool) -> None:
    db = SessionLocal()
    try:
        rows = db.execute(
            select(StrategyInstance, StrategyTemplate)
            .join(StrategyTemplate, StrategyTemplate.id == StrategyInstance.strategy_template_id)
            .where(~StrategyInstance.status.in_(tuple(TERMINAL_STATUSES)))
        ).all()
        print(f"{'전략':>7} {'종목':13s} {'기록':>9} {'계획':>7} {'추가체결':>9} {'증거금추가':>10} {'보정값':>9} {'차이':>9}")
        print("-" * 86)
        changed = 0
        total_diff = Decimal("0")
        for s, t in rows:
            lev = Decimal(str(s.leverage or 1)) or Decimal("1")
            plan = Decimal(str(t.total_capital or 0))
            adds = _filled_adds_margin(db, s.id, lev)
            margin = _margin_added(db, s.id)
            correct = (plan + adds + margin).quantize(Decimal("0.01"))
            recorded = Decimal(str(s.total_capital or 0))
            diff = recorded - correct
            if diff <= MIN_DIFF:            # 같거나 기록이 더 작으면 그대로 둔다
                continue
            changed += 1
            total_diff += diff
            print(f"#{s.id:>6} {s.symbol:13s} {float(recorded):9.2f} {float(plan):7.0f} "
                  f"{float(adds):9.2f} {float(margin):10.2f} {float(correct):9.2f} {float(diff):+9.2f}")
            if apply:
                s.total_capital = correct
        print("-" * 86)
        print(f"대상 {changed}건 · 되돌릴 과대 합계 {float(total_diff):+.2f} USDT")
        if apply:
            db.commit()
            print("✅ 적용 완료 (DB 반영). SL 한도·노출이 즉시 실제 자본 기준으로 바뀐다.")
        else:
            print("ℹ️ 미리보기만 했다 (DB 변경 없음). 실제 보정은 사장님 승인 뒤 `--apply`.")
    finally:
        db.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)

"""#92 BABYUSDT — DB current_position_qty -574 → -860 보정.

원인: 이전 stream_service idempotent gate 가 prev_status="FILLED" 만 검사.
  → TP3 의 PARTIALLY_FILLED → FILLED 흐름에서 같은 286 qty 가 두 번 차감.
  → DB -574 (== -860 - 286). 거래소 = -860 (Order 누적과 일치).

새 코드 (delta_executed 기반) 는 더 이상 이 버그 발생 안 함.
하지만 기존 DB 의 잘못된 -574 값은 수동 보정 필요.

사용:
  docker compose exec -e PYTHONPATH=/app api python /tmp/fix_baby_92.py            # dry-run
  docker compose exec -e PYTHONPATH=/app api python /tmp/fix_baby_92.py --apply
"""
import sys
from datetime import datetime, timezone
from decimal import Decimal

from app.core.database import SessionLocal
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance


def main(apply: bool) -> None:
    db = SessionLocal()
    try:
        s = db.get(StrategyInstance, 92)
        if not s:
            print("#92 NOT FOUND")
            return
        old_qty = s.current_position_qty
        new_qty = Decimal("-860")
        print(f"#{s.id} {s.symbol} {s.side} {s.status}")
        print(f"  current_position_qty: {old_qty} → {new_qty}")
        if str(old_qty) == str(new_qty):
            print("  (이미 보정됨 — skip)")
            return
        if not apply:
            print("\n(dry-run — 실제 변경 없음. --apply 로 다시 실행)")
            return
        s.current_position_qty = new_qty
        db.add(RiskEvent(
            strategy_instance_id=s.id,
            event_type="MANUAL_QTY_CORRECTION",
            severity="INFO",
            title="🔧 수동 qty 보정 (TP3 double-decrement bug fix)",
            message=(
                f"#{s.id} BABYUSDT: current_position_qty {old_qty} → {new_qty}. "
                "원인: stream_service 의 PARTIALLY_FILLED → FILLED 흐름에서 같은 trade settlement 이 "
                "두 번 차감 (TP3 close 286 이 중복). 새 코드 (delta_executed 기반) 적용 + "
                "기존 잘못된 DB 값 거래소 일치값 (-860) 으로 수동 보정."
            ),
            event_payload={
                "strategy_id": s.id,
                "old_qty": str(old_qty),
                "new_qty": str(new_qty),
                "exchange_qty": "-860",
            },
        ))
        db.commit()
        print("\nCOMMIT 완료.")
    finally:
        db.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)

"""
좀비 strategy 정리 (2026-05-03 testnet 검증 직전):

처리 대상:
  - #89 LABUSDT STOPPING + qty=-35.90  → STOPPED + qty=0
    이유: 같은 LABUSDT SHORT 포지션을 #90 STAGE1_OPEN 이 점유 중. #89 는 이미
    사용자가 「수동 정지」 했는데 거래소 청산 완료 시점에 #90 이 진입하여
    reconcile 이 정리 못하는 좀비 상태.

  - #83 XNYUSDT STOPPED + qty=-60842  → qty=0 (status 는 이미 STOPPED)
    이유: STOPPED 인데 qty 잔재 — UI 혼동 + 이후 통계에 잘못 들어갈 수 있음.

거래소 측은 손대지 않음 (LABUSDT -35.9 는 #90 이 정상 점유 중).

dry-run 기본값. 진행은 --apply 플래그.
사용:
  docker compose exec -e PYTHONPATH=/app api python /tmp/cleanup_zombie_strategies.py            # dry-run
  docker compose exec -e PYTHONPATH=/app api python /tmp/cleanup_zombie_strategies.py --apply    # 실제 적용
"""
import sys
from datetime import datetime, timezone
from decimal import Decimal

from app.core.database import SessionLocal
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance


PLAN = [
    {
        "id": 89,
        "expected_status": "STOPPING",
        "expected_symbol": "LABUSDT",
        "new_status": "STOPPED",
        "reset_qty": True,
        "reason": "좀비 STOPPING — #90 이 같은 LABUSDT SHORT 점유 중이라 reconcile 자동 정리 불가",
    },
    {
        "id": 83,
        "expected_status": "STOPPED",
        "expected_symbol": "XNYUSDT",
        "new_status": "STOPPED",          # 그대로
        "reset_qty": True,
        "reason": "STOPPED 인데 qty=-60842 잔재 — UI 혼동 방지 위해 qty=0 으로 정리",
    },
]


def main(apply: bool) -> None:
    db = SessionLocal()
    try:
        print("=" * 80)
        print(f"좀비 strategy 정리 — {'APPLY' if apply else 'DRY-RUN'}")
        print("=" * 80)
        for plan in PLAN:
            s = db.get(StrategyInstance, plan["id"])
            if not s:
                print(f"  [#{plan['id']}] NOT FOUND — skip")
                continue
            if s.symbol != plan["expected_symbol"] or s.status != plan["expected_status"]:
                print(
                    f"  [#{plan['id']}] expected {plan['expected_symbol']}/{plan['expected_status']} "
                    f"but got {s.symbol}/{s.status} — skip (안전)"
                )
                continue
            print(f"  [#{plan['id']}] {s.symbol} {s.side} {s.status} qty={s.current_position_qty}")
            print(f"      → status={plan['new_status']}, qty=0  ({plan['reason']})")
            if apply:
                old_status = s.status
                old_qty = s.current_position_qty
                s.status = plan["new_status"]
                if plan["reset_qty"]:
                    s.current_position_qty = Decimal("0")
                if plan["new_status"] == "STOPPED" and not s.stopped_at:
                    s.stopped_at = datetime.now(timezone.utc)
                db.add(RiskEvent(
                    strategy_instance_id=s.id,
                    event_type="ZOMBIE_STRATEGY_MANUAL_CLEANUP",
                    severity="INFO",
                    title="🧹 좀비 strategy 수동 정리",
                    message=(
                        f"#{s.id} {s.symbol} {s.side}: status {old_status} → {plan['new_status']}, "
                        f"qty {old_qty} → 0. {plan['reason']}"
                    ),
                    event_payload={
                        "strategy_id": s.id,
                        "old_status": old_status,
                        "new_status": plan["new_status"],
                        "old_qty": str(old_qty),
                    },
                ))
        if apply:
            db.commit()
            print("\nCOMMIT 완료.")
        else:
            print("\n(dry-run — 실제 변경 없음. --apply 로 다시 실행하세요.)")
    finally:
        db.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)

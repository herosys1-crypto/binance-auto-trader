"""#90 LABUSDT — STOPPING 좀비 정리 (COMPLETED 였는데 사용자가 우연히 stop 클릭한 케이스).

진단 + 정리:
  - 거래소에 LABUSDT SHORT 포지션 0 인지 재확인
  - status=STOPPING & 거래소 0 → STOPPED 강등 + qty=0
  - 사용자가 새 LABUSDT SHORT strategy 진입 가능하게 unblock

사용:
  docker compose exec -e PYTHONPATH=/app api python /tmp/fix_lab_90.py            # dry-run
  docker compose exec -e PYTHONPATH=/app api python /tmp/fix_lab_90.py --apply
"""
import sys
from datetime import datetime, timezone
from decimal import Decimal

from app.core.crypto import decrypt_text
from app.core.database import SessionLocal
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from sqlalchemy import select


def main(apply: bool) -> None:
    db = SessionLocal()
    try:
        s = db.get(StrategyInstance, 90)
        if not s:
            print("#90 NOT FOUND")
            return
        print(f"#{s.id} {s.symbol} {s.side} status={s.status} qty={s.current_position_qty}")

        # 거래소 확인
        acc = db.get(ExchangeAccount, s.exchange_account_id)
        client = BinanceClient(
            api_key=decrypt_text(acc.api_key_enc),
            api_secret=decrypt_text(acc.api_secret_enc),
            is_testnet=acc.is_testnet,
        )
        pr = client.get_position_risk(symbol=s.symbol)
        if isinstance(pr, dict):
            pr = [pr]
        ex_amt = Decimal("0")
        for p in pr:
            if p.get("symbol") == s.symbol and p.get("positionSide") == s.side:
                ex_amt = Decimal(str(p.get("positionAmt", "0")))
                break
        print(f"거래소 {s.symbol} {s.side} positionAmt = {ex_amt}")

        if ex_amt != 0:
            print(f"\n⚠️ 거래소에 포지션이 살아있음! 자동 정리 위험. 거래소에서 직접 청산 후 다시 시도하세요.")
            return

        if s.status not in ("STOPPING",) and s.current_position_qty == 0:
            print(f"\n이미 깨끗한 상태 (status={s.status}, qty=0). skip.")
            return

        old_status = s.status
        old_qty = s.current_position_qty

        if not apply:
            print(f"\n[DRY-RUN] 변경 예정:")
            print(f"  status: {old_status} → STOPPED")
            print(f"  qty   : {old_qty} → 0")
            print(f"\n  --apply 로 다시 실행")
            return

        s.status = "STOPPED"
        s.current_position_qty = Decimal("0")
        if not s.stopped_at:
            s.stopped_at = datetime.now(timezone.utc)
        db.add(RiskEvent(
            strategy_instance_id=s.id,
            event_type="ZOMBIE_STOPPING_MANUAL_CLEANUP",
            severity="INFO",
            title="🧹 #90 LABUSDT STOPPING 좀비 수동 정리",
            message=(
                f"status {old_status} → STOPPED, qty {old_qty} → 0. "
                "원인: 사용자가 COMPLETED 인 #90 에 「수동 정지」 클릭 → STOPPING 으로 덮어쓴 후 "
                "거래소엔 포지션 없어 reconcile 좀비 정리 대상. 사용자 신규 진입 unblock."
            ),
            event_payload={
                "strategy_id": s.id,
                "old_status": old_status,
                "old_qty": str(old_qty),
                "exchange_amt": str(ex_amt),
            },
        ))
        db.commit()
        print(f"\n✅ COMMIT 완료 — #{s.id} 정리됨. 이제 LABUSDT SHORT 신규 진입 가능.")
    finally:
        db.close()


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)

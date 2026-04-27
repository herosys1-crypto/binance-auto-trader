"""
Testnet 전략 일괄 정리 스크립트.

처리 순서:
1) 모든 active testnet 전략 나열 (mainnet은 건드리지 않음)
2) 각 전략마다 상황별 처리:
   - current_position_qty != 0  -> emergency_close_position (거래소 청산)
   - status == STAGE1_OPEN_PENDING (미체결 진입 주문) -> 거래소 주문 취소 + DB STOPPED
   - status == STOPPING 등 -> 거래소 주문 취소 + DB STOPPED
3) testnet 거래소에 남은 모든 미체결 주문도 일괄 취소 (안전망)
4) 결과 요약 출력

사용법:
    docker compose exec api python /app/cleanup_testnet_strategies.py
"""
from decimal import Decimal
from app.core.database import SessionLocal
from app.core.crypto import decrypt_text
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.order import Order
from app.services.execution_service import ExecutionService


ACTIVE_STATUSES = {
    "STAGE1_OPEN_PENDING", "STAGE1_OPEN",
    "STAGE2_OPEN_PENDING", "STAGE2_OPEN",
    "STAGE3_OPEN_PENDING", "STAGE3_OPEN",
    "STAGE4_OPEN_PENDING", "STAGE4_OPEN",
    "STOPPING",
}


def main():
    db = SessionLocal()
    try:
        # 1) testnet 계정 + active 전략 조회
        testnet_accounts = db.query(ExchangeAccount).filter_by(is_testnet=True, is_active=True).all()
        if not testnet_accounts:
            print("No active testnet accounts. Nothing to do.")
            return

        results = []
        for acc in testnet_accounts:
            print(f"\n=== Account #{acc.id} ({acc.exchange_name} testnet) ===")
            api_key = decrypt_text(acc.api_key_enc)
            api_secret = decrypt_text(acc.api_secret_enc)
            exec_svc = ExecutionService(db, api_key=api_key, api_secret=api_secret, is_testnet=True)

            strategies = (
                db.query(StrategyInstance)
                .filter(StrategyInstance.exchange_account_id == acc.id)
                .filter(StrategyInstance.status.in_(ACTIVE_STATUSES))
                .order_by(StrategyInstance.id)
                .all()
            )
            print(f"Found {len(strategies)} active strategies.")

            for s in strategies:
                action = "skip"
                detail = ""
                try:
                    qty = abs(s.current_position_qty or Decimal("0"))
                    # 1-A) 실제 포지션 보유 -> 시장가 청산
                    if qty > 0:
                        try:
                            exec_svc.emergency_close_position(s.id, quantity=qty)
                            action = "emergency_close + STOPPED"
                        except Exception as e:
                            action = f"close failed: {e}"
                    # 1-B) 미체결 limit 주문 취소 (있으면)
                    open_orders = (
                        db.query(Order)
                        .filter(Order.strategy_instance_id == s.id)
                        .filter(Order.status.in_(["NEW", "PARTIALLY_FILLED"]))
                        .all()
                    )
                    for o in open_orders:
                        try:
                            exec_svc.cancel_exchange_order(
                                symbol=o.symbol,
                                order_id=int(o.exchange_order_id) if o.exchange_order_id else None,
                                orig_client_order_id=o.client_order_id,
                            )
                            o.status = "CANCELED"
                            db.add(o)
                        except Exception as e:
                            detail += f"cancel({o.client_order_id}) fail: {e}; "
                    # 1-C) 최종적으로 DB status STOPPED
                    s.status = "STOPPED"
                    db.add(s)
                    db.commit()
                    if action == "skip":
                        action = "STOPPED (no position)"
                except Exception as e:
                    db.rollback()
                    action = f"FAILED: {e}"

                results.append((s.id, s.symbol, s.side, action, detail))
                print(f"  - Strategy #{s.id} {s.symbol} {s.side}: {action} {detail}")

        # 2) 안전망: 거래소에 남은 모든 미체결 주문 취소 (계정별)
        for acc in testnet_accounts:
            try:
                api_key = decrypt_text(acc.api_key_enc)
                api_secret = decrypt_text(acc.api_secret_enc)
                exec_svc = ExecutionService(db, api_key=api_key, api_secret=api_secret, is_testnet=True)
                # 사용 중인 심볼들에 대해 cancel-all 시도
                symbols = {s.symbol for s in db.query(StrategyInstance).filter_by(exchange_account_id=acc.id).all()}
                for sym in symbols:
                    try:
                        exec_svc.client.cancel_all_orders(symbol=sym)
                        print(f"\n[safety net] Cancelled all open orders for {sym} on testnet account #{acc.id}")
                    except AttributeError:
                        # cancel_all_orders 없으면 무시
                        pass
                    except Exception as e:
                        print(f"[safety net] Cancel-all on {sym} failed (ignored): {e}")
            except Exception as e:
                print(f"[safety net] account #{acc.id}: {e}")

        # 3) 요약
        print("\n=== SUMMARY ===")
        for r in results:
            print(f"#{r[0]} {r[1]} {r[2]}: {r[3]} {r[4]}")
        print(f"\nTotal processed: {len(results)}")

    finally:
        db.close()


if __name__ == "__main__":
    main()

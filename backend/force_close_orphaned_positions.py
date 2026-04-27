"""
거래소엔 살아있지만 DB는 STOPPED인 고아 포지션을 강제 청산.

상황:
- 이전 cleanup이 reduce_only 파라미터 호환 문제로 close 실패
- DB는 STOPPED로 마킹되었지만 실제 포지션은 testnet 거래소에 그대로

처리:
- testnet 계정의 모든 열린 포지션을 거래소에서 직접 조회
- 각 포지션을 시장가로 close (reduce_only 없이, hedge mode 호환)

사용법:
    docker compose exec api python /app/force_close_orphaned_positions.py
"""
from decimal import Decimal
from app.core.database import SessionLocal
from app.core.crypto import decrypt_text
from app.models.exchange_account import ExchangeAccount
from app.integrations.binance.client import BinanceClient
from app.integrations.binance.futures_trade import BinanceFuturesTradeClient


def main():
    db = SessionLocal()
    try:
        accounts = db.query(ExchangeAccount).filter_by(is_testnet=True, is_active=True).all()
        if not accounts:
            print("No testnet accounts.")
            return

        for acc in accounts:
            print(f"\n=== Account #{acc.id} ({acc.exchange_name} testnet) ===")
            api_key = decrypt_text(acc.api_key_enc)
            api_secret = decrypt_text(acc.api_secret_enc)
            client = BinanceClient(api_key=api_key, api_secret=api_secret, is_testnet=True)
            trade_client = BinanceFuturesTradeClient(client)

            # 1) 모든 열린 미체결 주문 취소 (안전 첫 단계)
            try:
                # symbol별로 cancel_all
                positions = client.get_position_risk()  # /fapi/v2/positionRisk
                symbols = {p["symbol"] for p in positions if Decimal(str(p.get("positionAmt", "0"))) != 0}
                # positionAmt 0이어도 미체결 주문이 있을 수 있으니 BTCUSDT 같은 활성 심볼도 추가
                from app.models.symbol import Symbol
                active = {s.symbol for s in db.query(Symbol).filter_by(status="TRADING").all()}
                symbols = symbols | active
                for sym in symbols:
                    try:
                        client.cancel_all_orders(symbol=sym)
                        print(f"  cancelled all open orders on {sym}")
                    except Exception as e:
                        if "no need" not in str(e).lower():
                            print(f"  cancel-all {sym} skipped: {e}")
            except Exception as e:
                print(f"  cancel-all phase failed: {e}")

            # 2) 모든 열린 포지션 시장가 청산 (hedge mode 호환)
            try:
                positions = client.get_position_risk()
            except Exception as e:
                print(f"  position read failed: {e}")
                continue

            closed = 0
            for p in positions:
                amt = Decimal(str(p.get("positionAmt", "0")))
                if amt == 0:
                    continue
                symbol = p["symbol"]
                position_side = p.get("positionSide", "BOTH")
                # LONG 포지션이면 SELL로 청산, SHORT면 BUY로 청산
                if position_side == "LONG" or (position_side == "BOTH" and amt > 0):
                    side = "SELL"
                else:
                    side = "BUY"
                quantity = abs(amt)
                client_order_id = f"FORCE-CLOSE-{symbol}-{position_side}-{int(closed):03d}"
                try:
                    resp = trade_client.place_market_order(
                        symbol=symbol,
                        side=side,
                        position_side=position_side,
                        quantity=quantity,
                        new_client_order_id=client_order_id,
                    )
                    print(f"  CLOSED: {symbol} {position_side} qty={quantity} -> orderId={resp.get('orderId')}")
                    closed += 1
                except Exception as e:
                    print(f"  CLOSE FAILED: {symbol} {position_side} qty={quantity} err={e}")

            print(f"\n  Total closed: {closed}")

            # 3) 검증: 다시 조회해서 0인지 확인
            try:
                positions2 = client.get_position_risk()
                still_open = [p for p in positions2 if Decimal(str(p.get("positionAmt", "0"))) != 0]
                if still_open:
                    print("  ⚠️ Still open after close attempt:")
                    for p in still_open:
                        print(f"     {p['symbol']} {p.get('positionSide')} amt={p['positionAmt']}")
                else:
                    print("  ✅ All positions closed.")
            except Exception as e:
                print(f"  verify failed: {e}")

    finally:
        db.close()


if __name__ == "__main__":
    main()

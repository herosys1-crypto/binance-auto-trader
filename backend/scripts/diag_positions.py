"""
testnet 잔존 포지션 진단:
  - DB 의 strategy_instance vs 거래소 실제 position 비교
  - 최근 risk_event dump

사용:
  docker compose exec api python scripts/diag_positions.py
"""
from app.core.database import SessionLocal
from app.core.crypto import decrypt_text as dec
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from sqlalchemy import select

SYMS = ["BIOUSDT", "SKYAIUSDT", "XNYUSDT", "LABUSDT"]


def dump_strategies(db) -> None:
    rows = db.execute(
        select(StrategyInstance)
        .where(StrategyInstance.symbol.in_(SYMS))
        .order_by(StrategyInstance.id.desc())
        .limit(50)
    ).scalars().all()
    print("=" * 110)
    print("[1] DB strategy_instance (해당 4개 심볼, 최근 50개)")
    print("=" * 110)
    print(f"{'id':>4} {'symbol':<10} {'side':<6} {'status':<24} {'qty':>14} {'avg':>14} {'realized':>12}")
    print("-" * 110)
    for s in rows:
        print(
            f"{s.id:>4} {s.symbol:<10} {s.side:<6} {s.status:<24} "
            f"{str(s.current_position_qty or 0):>14} "
            f"{str(s.avg_entry_price or 0):>14} "
            f"{str(s.realized_pnl or 0):>12}"
        )


def dump_exchange(db) -> None:
    acc = db.execute(
        select(ExchangeAccount).where(
            ExchangeAccount.is_testnet.is_(True),
            ExchangeAccount.is_active.is_(True),
        ).limit(1)
    ).scalars().first()
    if not acc:
        print("\nNO TESTNET ACCOUNT")
        return
    client = BinanceClient(
        api_key=dec(acc.api_key_enc),
        api_secret=dec(acc.api_secret_enc),
        is_testnet=True,
    )
    print()
    print("=" * 110)
    print("[2] 거래소 (testnet) 실제 포지션")
    print("=" * 110)
    print(f"{'symbol':<10} {'side':<6} {'posAmt':>14} {'entry':>14} {'mark':>14} {'uPnL':>12} {'liq':>14}")
    print("-" * 110)
    for sym in SYMS:
        try:
            pr = client.get_position_risk(symbol=sym)
            if isinstance(pr, dict):
                pr = [pr]
            for p in pr:
                amt = float(p.get("positionAmt", 0) or 0)
                if abs(amt) <= 0:
                    continue
                print(
                    f"{p['symbol']:<10} {p['positionSide']:<6} "
                    f"{p.get('positionAmt', ''):>14} "
                    f"{p.get('entryPrice', ''):>14} "
                    f"{p.get('markPrice', ''):>14} "
                    f"{p.get('unRealizedProfit', ''):>12} "
                    f"{p.get('liquidationPrice', ''):>14}"
                )
        except Exception as e:
            print(f"{sym:<10} ERROR: {e}")


def dump_recent_events(db) -> None:
    rows = db.execute(
        select(RiskEvent).order_by(RiskEvent.id.desc()).limit(20)
    ).scalars().all()
    print()
    print("=" * 110)
    print("[3] 최근 risk_event 20개")
    print("=" * 110)
    for r in rows:
        title = (r.title or "")[:60]
        print(f"{r.id:>5} | sid={r.strategy_instance_id} | {r.event_type:<35} | {r.severity:<8} | {title}")


def main() -> None:
    db = SessionLocal()
    try:
        dump_strategies(db)
        dump_exchange(db)
        dump_recent_events(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()

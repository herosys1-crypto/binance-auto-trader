"""특정 strategy 의 전체 history 분석 — DB ↔ 거래소 mismatch 원인 추적.

  - 모든 order 시계열 (ENTRY/EXIT, status, executed_qty, avg_price)
  - 모든 risk_event
  - 현재 DB state vs 거래소 실제 포지션
  - notification 발송 history
  - 추정 누적 qty (order 기준) vs DB current_position_qty vs 거래소

사용:
  docker compose exec -e PYTHONPATH=/app api python /tmp/investigate_strategy.py 92 84 90 87 93
"""
import sys
from decimal import Decimal

from app.core.crypto import decrypt_text
from app.core.database import SessionLocal
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.models.notification import Notification
from app.models.order import Order
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from sqlalchemy import select


def investigate(db, strategy_id: int) -> None:
    print()
    print("#" * 110)
    print(f"#  STRATEGY {strategy_id} 정밀 진단")
    print("#" * 110)
    s = db.get(StrategyInstance, strategy_id)
    if not s:
        print(f"  NOT FOUND")
        return

    print(f"\n[기본]")
    print(f"  symbol={s.symbol}  side={s.side}  status={s.status}")
    print(f"  current_stage={s.current_stage}  current_position_qty={s.current_position_qty}")
    print(f"  avg_entry_price={s.avg_entry_price}  realized_pnl={s.realized_pnl}")
    print(f"  reentry_ready={s.reentry_ready}  stopped_at={s.stopped_at}")
    print(f"  created_at={s.created_at}")

    # 모든 orders
    orders = db.execute(
        select(Order)
        .where(Order.strategy_instance_id == strategy_id)
        .order_by(Order.id.asc())
    ).scalars().all()
    print(f"\n[Orders] 총 {len(orders)}건")
    print(f"  {'id':>5} {'created':<19} {'purpose':<8} {'st#':<4} {'side':<5} {'type':<7} "
          f"{'orig_qty':>14} {'exec_qty':>14} {'avg_px':>14} {'status':<10}")
    print("  " + "-" * 120)
    cum_buy = Decimal("0")
    cum_sell = Decimal("0")
    cum_realized = Decimal("0")
    for o in orders:
        c = (o.created_at.isoformat() if o.created_at else "")[:19]
        eq = Decimal(str(o.executed_qty or 0))
        if o.side == "BUY":
            cum_buy += eq
        else:
            cum_sell += eq
        # Realized PnL 추정 (EXIT 만)
        if o.purpose == "EXIT" and o.avg_price and s.avg_entry_price:
            try:
                entry = Decimal(str(s.avg_entry_price))
                exitp = Decimal(str(o.avg_price))
                if s.side == "SHORT":
                    cum_realized += eq * (entry - exitp)
                else:
                    cum_realized += eq * (exitp - entry)
            except Exception:
                pass
        print(f"  {o.id:>5} {c:<19} {o.purpose:<8} {str(o.stage_no or '-'):<4} "
              f"{o.side:<5} {o.order_type:<7} "
              f"{str(o.orig_qty or 0):>14} {str(o.executed_qty or 0):>14} "
              f"{str(o.avg_price or 0):>14} {o.status:<10}")

    # SHORT: net = sell - buy. LONG: net = buy - sell.
    if s.side == "SHORT":
        net_qty = -(cum_sell - cum_buy)  # SHORT 은 음수 표기
    else:
        net_qty = (cum_buy - cum_sell)
    print(f"\n  Order 누적 검증:")
    print(f"    cum_buy  = {cum_buy}")
    print(f"    cum_sell = {cum_sell}")
    print(f"    net_qty  = {net_qty}    (이게 거래소 positionAmt 와 일치해야 함)")
    print(f"    DB current_position_qty = {s.current_position_qty}")

    # Risk events
    events = db.execute(
        select(RiskEvent)
        .where(RiskEvent.strategy_instance_id == strategy_id)
        .order_by(RiskEvent.id.asc())
    ).scalars().all()
    print(f"\n[Risk Events] 총 {len(events)}건")
    for e in events[-20:]:  # 최근 20개만
        c = (e.created_at.isoformat() if e.created_at else "")[:19]
        title = (e.title or "")[:55]
        print(f"  {e.id:>5} {c:<19} {e.severity:<8} {e.event_type:<32} {title}")

    # Notifications
    notes = db.execute(
        select(Notification)
        .where(Notification.strategy_instance_id == strategy_id)
        .order_by(Notification.id.asc())
    ).scalars().all()
    print(f"\n[Notifications] 총 {len(notes)}건")
    for n in notes[-15:]:
        c = (n.created_at.isoformat() if n.created_at else "")[:19]
        title = (n.title or "")[:60]
        print(f"  {n.id:>5} {c:<19} {n.send_status:<8} {title}")

    # 거래소 실제 포지션
    print(f"\n[거래소 실제 포지션]")
    try:
        acc = db.get(ExchangeAccount, s.exchange_account_id)
        if not acc:
            print(f"  exchange_account #{s.exchange_account_id} 없음")
            return
        client = BinanceClient(
            api_key=decrypt_text(acc.api_key_enc),
            api_secret=decrypt_text(acc.api_secret_enc),
            is_testnet=acc.is_testnet,
        )
        pr = client.get_position_risk(symbol=s.symbol)
        if isinstance(pr, dict):
            pr = [pr]
        found = False
        for p in pr:
            amt = Decimal(str(p.get("positionAmt", "0")))
            if abs(amt) <= 0:
                continue
            if p.get("symbol") == s.symbol and p.get("positionSide") == s.side:
                found = True
                print(f"  symbol={p['symbol']} side={p['positionSide']}")
                print(f"  positionAmt = {p.get('positionAmt')}    "
                      f"vs DB={s.current_position_qty}    "
                      f"match? {Decimal(str(p['positionAmt'])) == Decimal(str(s.current_position_qty or 0))}")
                print(f"  entryPrice  = {p.get('entryPrice')}    vs DB avg={s.avg_entry_price}")
                print(f"  markPrice   = {p.get('markPrice')}")
                print(f"  uPnL        = {p.get('unRealizedProfit')}")
                print(f"  liq         = {p.get('liquidationPrice')}")
        if not found:
            print(f"  거래소에 {s.symbol} {s.side} 포지션 없음")
    except Exception as e:
        print(f"  ERROR: {e}")


def main(args):
    db = SessionLocal()
    try:
        for arg in args:
            try:
                sid = int(arg)
            except ValueError:
                print(f"skip arg: {arg}")
                continue
            investigate(db, sid)
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: investigate_strategy.py <id1> [id2 ...]")
        sys.exit(1)
    main(sys.argv[1:])

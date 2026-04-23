from decimal import Decimal
from sqlalchemy import select
from app.core.database import SessionLocal
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.models.position import Position
from app.models.risk_event import RiskEvent
from app.models.strategy_instance import StrategyInstance
from app.observability.metrics import position_reconcile_total, position_qty_mismatch_total

def run_position_reconcile_once(decrypt_func) -> None:
    db = SessionLocal()
    try:
        rows = db.execute(
            select(StrategyInstance, ExchangeAccount)
            .join(ExchangeAccount, StrategyInstance.exchange_account_id == ExchangeAccount.id)
            .where(StrategyInstance.status.in_(["STAGE1_OPEN","STAGE2_OPEN","STAGE3_OPEN","STAGE4_OPEN","TP1_DONE_PARTIAL","TP2_DONE_PARTIAL"]))
            .where(ExchangeAccount.is_active.is_(True))
        ).all()
        for strategy, account in rows:
            try:
                client = BinanceClient(api_key=decrypt_func(account.api_key_enc), api_secret=decrypt_func(account.api_secret_enc), is_testnet=account.is_testnet)
                position_risk = client.get_position_risk(symbol=strategy.symbol)
                if isinstance(position_risk, dict):
                    position_risk = [position_risk]
                matched = None
                for item in position_risk:
                    if item.get("symbol") == strategy.symbol and item.get("positionSide") == strategy.side:
                        matched = item
                        break
                if not matched:
                    db.add(RiskEvent(strategy_instance_id=strategy.id, event_type="POSITION_RECONCILE_MISS", severity="WARN", title="No matching position found on exchange", message=f"symbol={strategy.symbol}, side={strategy.side}", event_payload={"strategy_id": strategy.id}))
                    position_reconcile_total.labels(status="miss").inc()
                    continue
                exchange_position_amt = Decimal(str(matched.get("positionAmt", "0")))
                exchange_entry_price = Decimal(str(matched.get("entryPrice", "0")))
                exchange_mark_price = Decimal(str(matched.get("markPrice", "0")))
                exchange_unrealized_pnl = Decimal(str(matched.get("unRealizedProfit", "0")))
                exchange_liquidation_price = Decimal(str(matched.get("liquidationPrice", "0")))
                db.add(Position(strategy_instance_id=strategy.id, symbol=strategy.symbol, side=strategy.side, position_side=strategy.side, entry_price=exchange_entry_price if exchange_entry_price > 0 else None, break_even_price=Decimal(str(matched.get("breakEvenPrice", "0"))) or None, mark_price=exchange_mark_price if exchange_mark_price > 0 else None, liquidation_price=exchange_liquidation_price if exchange_liquidation_price > 0 else None, position_amt=exchange_position_amt, isolated_margin=Decimal(str(matched.get("isolatedMargin", "0"))), unrealized_pnl=exchange_unrealized_pnl, margin_type=matched.get("marginType"), leverage=int(matched.get("leverage", strategy.leverage)) if matched.get("leverage") else strategy.leverage, source="POSITION_RISK_SYNC"))
                local_qty = Decimal(str(strategy.current_position_qty or 0))
                if local_qty != exchange_position_amt:
                    db.add(RiskEvent(strategy_instance_id=strategy.id, event_type="POSITION_QTY_MISMATCH", severity="WARN", title="Local/exchange position quantity mismatch", message=f"local={local_qty}, exchange={exchange_position_amt}", event_payload={"local_qty": str(local_qty), "exchange_qty": str(exchange_position_amt)}))
                    position_qty_mismatch_total.labels(symbol=strategy.symbol, side=strategy.side).inc()
                strategy.avg_entry_price = exchange_entry_price if exchange_entry_price > 0 else strategy.avg_entry_price
                strategy.current_position_qty = exchange_position_amt
                strategy.unrealized_pnl = exchange_unrealized_pnl
                strategy.liquidation_price = exchange_liquidation_price if exchange_liquidation_price > 0 else strategy.liquidation_price
                position_reconcile_total.labels(status="success").inc()
            except Exception as e:
                db.add(RiskEvent(strategy_instance_id=strategy.id, event_type="POSITION_RECONCILE_ERROR", severity="ERROR", title="Position reconcile failed", message=str(e), event_payload={"strategy_id": strategy.id}))
                position_reconcile_total.labels(status="error").inc()
        db.commit()
    finally:
        db.close()

"""🎯 v220 (2026-08-22 사장님!): 자동 증거금 추가 워커!

사장님 verbatim (2026-08-22):
"자동 증거금 추가 = 이건 2단계 진입후 손실이 추가로 발생해서 전체손실이 30% 넘어가면
 초기금액으로 증거금을 추가해줘 3단계 진입전에 청산가를 높이고
 심볼차트가 하락이 시작하면 3단계 진입을 해줘
 최종청산가는 -80% 손실일때 청산하는걸로 해줘"

로직:
1. 매 15초 실행!
2. 활성 심볼 스캔:
   - current_stage >= 2 (2단계 진입 완료!)
   - 자동 진입 소스만 (auto_bb_break% / sajangnim_top% 등!)
   - 심볼:side 24h dedup!
3. ROI 계산 (unrealized_pnl / margin!):
   - ROI < -30% 감지!
4. 액션:
   - ExecutionService.add_position_margin(strategy_id, amount=300) 자동 호출!
   - Redis add_margin_done:{symbol}:{side} = TTL 24h!
   - 텔레그램 알림!

효과:
- 청산가 상승 = 유지!
- 3단계 진입 조건 대기 (stage_trigger가 감지!)
- 최종 -80% ROI = evaluate_stop_loss 자동 청산 (사장님 완성!)

안전:
- ISOLATED 모드만 (CROSS = 실패!)
- 여유 잔액 부족 = 실패 로그!
- 심볼:side 24h dedup = 중복 방지!
- MAX 1건/사이클 (남발 방지!)
"""
from __future__ import annotations

import logging
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

DEFAULT_ADD_MARGIN_USDT = Decimal("300.0")  # 사장님 default!
ROI_TRIGGER = -30.0  # 사장님 verbatim: 전체 손실 30%!
DEDUP_TTL_SEC = 86400  # 24h dedup!

# 자동 진입 소스만 (사장님 사상 = 자동만!)
AUTO_ENTRY_TYPES = (
    "auto_bb_break",
    "sajangnim_top",
    "realtime_reentry",
    "chart_pattern",
)


def _get_add_margin_amount(db) -> Decimal:
    """SystemSetting `auto_add_margin_usdt` (default 300!)"""
    try:
        row = db.get(SystemSetting, "auto_add_margin_usdt")
        if row and row.value:
            val = Decimal(str(row.value))
            if val > 0:
                return val
    except Exception:
        pass
    return DEFAULT_ADD_MARGIN_USDT


def _redis():
    from app.core.redis_client import get_redis_client
    return get_redis_client()


def _already_done(symbol: str, side: str) -> bool:
    """심볼:side 24h dedup 확인!"""
    try:
        v = _redis().get(f"add_margin_done:{symbol}:{side}")
        return v is not None
    except Exception:
        return False


def _mark_done(symbol: str, side: str) -> None:
    """dedup 마크!"""
    try:
        _redis().setex(
            f"add_margin_done:{symbol}:{side}",
            DEDUP_TTL_SEC, "1",
        )
    except Exception:
        pass


def _calc_roi_pct(si: StrategyInstance) -> float | None:
    """ROI % 계산 (unrealized_pnl / margin × 100)"""
    try:
        pnl = float(si.unrealized_pnl or 0)
        margin = float(si.total_capital or 0)
        if margin <= 0:
            return None
        return (pnl / margin) * 100.0
    except Exception:
        return None


def run_auto_add_margin() -> dict:
    """매 15초 = 자동 증거금 추가 감지!"""
    db = SessionLocal()
    added = 0
    skipped = 0
    results: list[dict] = []
    try:
        # 1. mainnet 계정
        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            return {"note": "mainnet 계정 없음!", "added": 0}

        # 2. 증거금 금액
        add_amount = _get_add_margin_amount(db)

        # 3. 활성 심볼 스캔
        rows = db.execute(
            select(StrategyInstance, StrategyTemplate)
            .join(StrategyTemplate, StrategyInstance.strategy_template_id == StrategyTemplate.id)
            .where(StrategyInstance.status.in_(list(ACTIVE_LIKE)))
            .where(StrategyInstance.is_archived.is_(False))   # Fix 158
            .where(StrategyInstance.current_stage >= 2)  # 2단계 이상!
        ).all()

        if not rows:
            return {"note": "2단계 이상 활성 없음!", "added": 0}

        # 4. ExecutionService 준비
        from app.services.execution_service import ExecutionService
        from app.core.crypto import decrypt_text
        _exec = ExecutionService(
            db,
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=account.is_testnet,
        )

        # 5. 대상 심볼 처리
        for si, tpl in rows:
            if added >= 1:  # MAX 1건/사이클 (남발 방지!)
                break

            # 자동 진입 소스만!
            stype = tpl.strategy_type or ""
            if not any(stype.startswith(t) for t in AUTO_ENTRY_TYPES):
                skipped += 1
                continue

            # 24h dedup 확인!
            if _already_done(si.symbol, si.side):
                skipped += 1
                continue

            # ROI 계산!
            roi = _calc_roi_pct(si)
            if roi is None:
                skipped += 1
                continue

            # ROI < -30% 감지!
            if roi > ROI_TRIGGER:  # -30보다 크면 (-20, -10 등!) skip
                skipped += 1
                continue

            # 실 증거금 추가!
            try:
                logger.warning(
                    "[auto_add_margin] 🚨 v220 트리거! %s %s stage=%d ROI=%.2f%% (<%.0f%%) → 증거금 +%.0f USDT!",
                    si.symbol, si.side, si.current_stage, roi, ROI_TRIGGER, float(add_amount),
                )
                result = _exec.add_position_margin(si.id, amount=add_amount)
                _mark_done(si.symbol, si.side)
                added += 1
                results.append({
                    "symbol": si.symbol,
                    "side": si.side,
                    "stage": si.current_stage,
                    "roi_pct": roi,
                    "added_usdt": float(add_amount),
                    "strategy_id": si.id,
                })
                logger.info(
                    "[auto_add_margin] ✅ v220 증거금 추가 성공: %s %s +%.0f USDT (청산가 상승!)",
                    si.symbol, si.side, float(add_amount),
                )
            except ValueError as _ve:
                # 검증 실패 (CROSS 모드 등!) = 명확한 에러!
                logger.warning(
                    "[auto_add_margin] ❌ v220 %s %s 검증 실패: %s",
                    si.symbol, si.side, _ve,
                )
                skipped += 1
                # CROSS 모드 등 = dedup 마크 (반복 API 절약!)
                _mark_done(si.symbol, si.side)
            except Exception as _e:
                logger.warning(
                    "[auto_add_margin] ❌ v220 %s %s 실패: %s",
                    si.symbol, si.side, _e,
                )
                skipped += 1

        logger.info(
            "[auto_add_margin] 완료: added=%d skipped=%d",
            added, skipped,
        )
        return {
            "added": added,
            "skipped": skipped,
            "results": results,
        }
    except Exception as e:
        logger.exception("[auto_add_margin] 실행 실패: %s", e)
        return {"error": str(e), "added": 0}
    finally:
        db.close()

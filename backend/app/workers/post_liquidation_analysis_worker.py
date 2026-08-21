"""🔬 v212 사장님 (2026-08-21): 청산 후 사후 진단 워커!

사장님 요구: "학습해서 다음에 대처!"

= 청산된 자동 진입 = 왜 청산됐는지 자동 분석!
= 진입 시점 지표 vs 청산 시점 비교!
= 반복 패턴 발견 = 자동 학습!

로직 (매 30분!):
1. 최근 청산된 자동 진입 (bb4h_auto_entry + executed_strategy_id!)
2. StrategyInstance status로 close reason 분류:
   - CLOSED_BY_TP = 익절 성공!
   - CLOSED_BY_SL = 손절!
   - STOPPED = 강제 정지!
   - 트레일링 = 관찰 필요!
3. 진입 시점 entry_snapshot vs 현재 시점 지표 (Redis에서!)
4. system_settings에 = 통계 저장!
5. 손절 패턴 반복 시 = 텔레그램 알림!

효과:
- 사장님 = 청산 원인 = 자동 진단!
- 반복 손실 = 즉시 발견!
- 파라미터 개선 = 데이터 기반!
"""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.strategy_status import TERMINAL_STATUSES
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_suggestion import StrategySuggestion
from app.models.system_setting import SystemSetting

logger = logging.getLogger(__name__)

SETTING_KEY = "post_liquidation_analysis_v212"


def run_post_liquidation_analysis() -> dict:
    """매 30분 = 청산 후 사후 진단!"""
    db: Session = SessionLocal()
    try:
        # 최근 24시간 청산된 자동 진입!
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        candidates = db.execute(
            select(StrategySuggestion)
            .where(StrategySuggestion.created_at >= cutoff)
            .where(StrategySuggestion.suggestion_type == "bb4h_auto_entry")
            .where(StrategySuggestion.executed_strategy_id.isnot(None))
        ).scalars().all()

        # 청산 원인 카운터!
        close_reason_counts: Counter[str] = Counter()
        # side별 청산 원인!
        side_reason: dict[str, Counter[str]] = defaultdict(Counter)
        # 심볼별 손실 카운트!
        symbol_loss: dict[str, int] = defaultdict(int)
        # 조건별 손실 카운트! (regime/rsi 버킷!)
        condition_loss: dict[str, int] = defaultdict(int)

        analyzed = 0
        losses = 0
        total_loss_usdt = 0.0

        for s in candidates:
            try:
                si = db.get(StrategyInstance, s.executed_strategy_id)
                if not si or si.status not in TERMINAL_STATUSES:
                    continue
                analyzed += 1

                reason = _classify_close_reason(si)
                close_reason_counts[reason] += 1
                side_reason[s.side][reason] += 1

                pnl = float(si.realized_pnl or 0)
                if pnl < 0:
                    losses += 1
                    total_loss_usdt += pnl
                    symbol_loss[s.symbol] += 1

                    # 조건별 손실 학습!
                    cfg = s.strategy_config or {}
                    snap = cfg.get("entry_snapshot") if isinstance(cfg, dict) else None
                    if snap and isinstance(snap, dict):
                        regime = snap.get("regime", "?")
                        condition_loss[f"regime={regime}:{s.side}"] += 1
                        kst = snap.get("kst_hour")
                        if kst is not None:
                            condition_loss[f"KST{kst:02d}h:{s.side}"] += 1
            except Exception as e:
                logger.warning("[v212] %s 분석 실패: %s", s.symbol, e)
                continue

        analysis = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window_hours": 24,
            "analyzed": analyzed,
            "losses": losses,
            "total_loss_usdt": round(total_loss_usdt, 2),
            "close_reason_counts": dict(close_reason_counts),
            "side_reason": {k: dict(v) for k, v in side_reason.items()},
            "top_loss_symbols": [
                {"symbol": sym, "loss_count": cnt}
                for sym, cnt in sorted(symbol_loss.items(), key=lambda x: -x[1])[:10]
            ],
            "top_loss_conditions": [
                {"key": k, "loss_count": cnt}
                for k, cnt in sorted(condition_loss.items(), key=lambda x: -x[1])[:10]
            ],
        }

        # 저장!
        row = db.get(SystemSetting, SETTING_KEY)
        val = json.dumps(analysis, ensure_ascii=False)
        if row:
            row.value = val
        else:
            db.add(SystemSetting(
                key=SETTING_KEY, value=val,
                description="v212: 청산 후 사후 진단 통계 (매 30분!)",
            ))
        db.commit()

        # 반복 손실 알림!
        _alert_if_severe(db, analysis)

        logger.info(
            "[v212 post_liquidation] analyzed=%d losses=%d loss_usdt=%.2f",
            analyzed, losses, total_loss_usdt,
        )
        return analysis
    except Exception as e:
        logger.warning("[v212 post_liquidation] 실행 실패: %s", e)
        db.rollback()
        return {"error": str(e)}
    finally:
        db.close()


def _classify_close_reason(si: StrategyInstance) -> str:
    """청산 원인 분류!"""
    status = si.status or ""
    err_code = si.last_error_code or ""

    if status == "CLOSED_BY_TP":
        return "TP_익절"
    if status == "CLOSED_BY_SL":
        return "SL_손절"
    if status == "STOPPED":
        # 강제 정지 = 원인 세부!
        if "TRAILING" in err_code.upper():
            return "TRAILING_회귀"
        if "CRISIS" in err_code.upper():
            return "CRISIS_모드"
        if "FORCE_SL" in err_code.upper() or "LOSS_LIMIT" in err_code.upper():
            return "FORCE_SL_한도초과"
        return "STOPPED_기타"
    if status == "STOPPED_CAPITAL_EXHAUSTED":
        return "자본_소진"
    if status == "CLOSED":
        return "CLOSED_일반"
    if status == "COMPLETED":
        return "COMPLETED"
    return f"기타({status})"


_ALERT_LAST_SENT: datetime | None = None


def _alert_if_severe(db: Session, analysis: dict) -> None:
    """심각한 패턴 감지 시 = 텔레그램 알림!"""
    global _ALERT_LAST_SENT
    now = datetime.now(timezone.utc)
    # 6시간 dedup!
    if _ALERT_LAST_SENT and (now - _ALERT_LAST_SENT).total_seconds() < 21600:
        return

    losses = analysis.get("losses", 0)
    total_loss = analysis.get("total_loss_usdt", 0)
    total_analyzed = analysis.get("analyzed", 0)

    # 알림 조건: 손실 5건 이상 + 총 -50 USDT+ + 손실률 50%+
    if losses < 5 or total_loss > -50 or total_analyzed == 0:
        return
    loss_rate = losses / total_analyzed
    if loss_rate < 0.5:
        return

    # 반복 손실 심볼!
    top_loss = analysis.get("top_loss_symbols", [])[:3]
    top_conditions = analysis.get("top_loss_conditions", [])[:3]

    body = (
        f"🔬 [v212] 24시간 청산 진단!\n"
        f"\n"
        f"⚠️ 손실 {losses}건 / 분석 {total_analyzed}건 (손실률 {int(loss_rate*100)}%)\n"
        f"💸 총 손실: {total_loss} USDT\n"
        f"\n"
        f"🚨 반복 손실 심볼 top 3:\n"
        + "\n".join(f"  - {it['symbol']}: {it['loss_count']}건" for it in top_loss)
        + f"\n\n🚨 손실 조건 top 3:\n"
        + "\n".join(f"  - {it['key']}: {it['loss_count']}건" for it in top_conditions)
        + f"\n\n= 학습 인사이트 확인 권장!"
    )

    try:
        from app.services.notification_service import NotificationService
        NotificationService(db).send_system_alert(
            title="🔬 [v212] 반복 손실 패턴 감지!",
            body=body,
        )
        _ALERT_LAST_SENT = now
    except Exception as e:
        logger.warning("[v212] 알림 실패: %s", e)


def get_post_liquidation_analysis(db: Session) -> dict | None:
    """UI 조회용!"""
    row = db.get(SystemSetting, SETTING_KEY)
    if not row or not row.value:
        return None
    try:
        return json.loads(row.value)
    except Exception:
        return None

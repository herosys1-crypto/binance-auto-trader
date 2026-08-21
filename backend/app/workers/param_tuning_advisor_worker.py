"""🎯 v214 사장님 (2026-08-21): 자동 파라미터 튜닝 어드바이저!

⚠️ 자동 적용 X = 사장님 알림만! (안전!)

= 학습 데이터 기반 = 파라미터 조정 제안!
= 사장님 판단으로 = 실 적용!

로직 (매일 KST 09:30!):
1. 학습 인사이트 조회!
2. 청산 원인 분석 (v212!)!
3. 성과 vs 파라미터 비교:
   - 승률 <30% + 표본 20+ = 필터 강화 제안!
   - 승률 >70% + 표본 20+ = 필터 완화 제안!
   - 손실 조건 반복 = 임계값 상향 제안!
4. 텔레그램으로 = 사장님 확인 요청!

효과:
- 사장님 = 파라미터 조정 = 데이터 기반!
- 자동 X = 안전!
- 실 배포는 사장님 결정!
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.core.database import SessionLocal

logger = logging.getLogger(__name__)

_LAST_SENT: datetime | None = None


def run_param_tuning_advisor() -> dict:
    """매일 KST 09:30 = 파라미터 조정 제안!"""
    global _LAST_SENT
    db: Session = SessionLocal()
    proposals: list[str] = []
    try:
        # 학습 인사이트 로드!
        from app.workers.pattern_learning_worker import get_learning_insights, get_learning_health_check
        insights = get_learning_insights(db) or {}
        health = get_learning_health_check(db) or {}

        # 1. 전체 승률 = 임계값 조정 제안!
        totals = health.get("totals", {})
        learnable = totals.get("learnable_samples", 0)
        if learnable >= 20:
            samples = insights.get("total_samples", 0)
            if samples > 0:
                # type_side_rankings에서 전체 승률!
                rankings = insights.get("type_side_rankings", [])
                total_success = sum(r.get("success", 0) for r in rankings)
                total_all = sum(r.get("total", 0) for r in rankings)
                overall_rate = total_success / total_all if total_all > 0 else 0

                if overall_rate < 0.30:
                    proposals.append(
                        f"⚠️ 전체 승률 {int(overall_rate*100)}% (표본 {total_all}건!) - "
                        "MIN_SUCCESS_PROBABILITY 상향 검토 (0.70 → 0.75)!"
                    )
                elif overall_rate > 0.70:
                    proposals.append(
                        f"🌟 전체 승률 {int(overall_rate*100)}% - 필터 완화 검토 "
                        "(MIN_SUCCESS_PROBABILITY 0.70 → 0.65)!"
                    )

        # 2. 손실 조건 반복 감지!
        from app.workers.post_liquidation_analysis_worker import get_post_liquidation_analysis
        pla = get_post_liquidation_analysis(db) or {}
        loss_conditions = pla.get("top_loss_conditions", [])[:3]
        for c in loss_conditions:
            if c.get("loss_count", 0) >= 5:
                proposals.append(
                    f"🚨 반복 손실 조건: {c['key']} = {c['loss_count']}건! "
                    "- 해당 조건 skip 규칙 추가 검토!"
                )

        # 3. 청산 원인 편중!
        reasons = pla.get("close_reason_counts", {})
        total_closes = sum(reasons.values())
        if total_closes >= 10:
            sl_count = reasons.get("SL_손절", 0)
            force_sl = reasons.get("FORCE_SL_한도초과", 0)
            if sl_count + force_sl > total_closes * 0.5:
                proposals.append(
                    f"⚠️ SL 청산 편중: SL {sl_count} + FORCE_SL {force_sl} / 전체 {total_closes} "
                    f"({int((sl_count+force_sl)/total_closes*100)}%!) - "
                    "SL 임계값 완화 or 진입 조건 강화 검토!"
                )
            trailing = reasons.get("TRAILING_회귀", 0)
            if trailing > total_closes * 0.4:
                proposals.append(
                    f"🌟 TRAILING 우세: {trailing}/{total_closes} ({int(trailing/total_closes*100)}%!) - "
                    "TRAILING_RETRACE_PCT 조정 검토 (5% → 3%?)"
                )

        # 4. WORST 심볼 반복!
        worst_l = insights.get("worst_symbols_long", [])[:5]
        worst_s = insights.get("worst_symbols_short", [])[:5]
        for w in worst_l + worst_s:
            if w.get("total", 0) >= 10 and w.get("success_rate", 1) <= 0.20:
                proposals.append(
                    f"🚨 WORST 심볼 반복: {w['symbol']} = 승률 "
                    f"{int(w['success_rate']*100)}% ({w['total']}건!) - "
                    "영구 blocklist 추가 검토!"
                )

        # 알림 발송!
        _send_advisory(db, proposals)

        logger.info("[v214 param_tuning_advisor] proposals=%d", len(proposals))
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "proposals": proposals,
            "learnable_samples": learnable,
        }
    except Exception as e:
        logger.warning("[v214 param_tuning_advisor] 실패: %s", e)
        return {"error": str(e)}
    finally:
        db.close()


def _send_advisory(db: Session, proposals: list[str]) -> None:
    """텔레그램 알림!"""
    global _LAST_SENT
    if not proposals:
        return
    # 12시간 dedup!
    now = datetime.now(timezone.utc)
    if _LAST_SENT and (now - _LAST_SENT).total_seconds() < 43200:
        return

    body = (
        f"🎯 [v214] 파라미터 조정 제안!\n"
        f"\n"
        f"⚠️ 자동 적용 X = 사장님 판단!\n"
        f"\n"
        + "\n\n".join(f"{i+1}. {p}" for i, p in enumerate(proposals))
        + "\n\n📊 학습 인사이트 확인 후 결정!"
    )

    try:
        from app.services.notification_service import NotificationService
        NotificationService(db).send_system_alert(
            title="🎯 [v214] 파라미터 튜닝 제안!", body=body,
        )
        _LAST_SENT = now
    except Exception as e:
        logger.warning("[v214] 알림 실패: %s", e)

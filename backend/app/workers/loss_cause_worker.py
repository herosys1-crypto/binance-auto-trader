"""📉 Fix 371b 손실 원인 태깅 워커 — 매시간. 주문 없음.

1) 이 버전으로 아직 태깅되지 않은 손실 기록을 SQL 에서 골라(필요 컬럼만, progression 등 큰 JSONB 제외) BATCH 건 태깅
   — insights 의 loss_causes 키만 jsonb_set 으로 바꾼다. 건마다 savepoint(한 건 오류가 배치를 날리지 않게).
2) 최근 REPORT_DAYS 일 집계를 system_settings.loss_cause_report_last(JSON) 에 저장.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

BATCH = 200              # Claude가 정함 — 사이클당 태깅 건수 (2코어 VPS 부담 제한)
REPORT_DAYS = 30


def run_loss_cause_once() -> dict:
    from app.core.database import SessionLocal
    from app.models.strategy_instance import StrategyInstance
    from app.models.system_setting import SystemSetting
    from app.services import loss_cause as LC

    db = SessionLocal()
    tagged = skipped = failed = 0
    try:
        th = LC.thresholds(db)
        rows = db.execute(LC.scan_stmt(version=LC.VERSION, min_loss=th["min_loss_usdt"], limit=BATCH)).mappings().all()
        for rec in rows:
            try:
                with db.begin_nested():
                    si = db.get(StrategyInstance, rec["strategy_instance_id"])
                    if si is None:
                        skipped += 1
                        result = {"v": LC.VERSION, "tags": [], "primary": None, "note": "instance_missing"}
                    else:
                        result = LC.classify(LC.gather_facts(db, si, dict(rec), th), th)
                        tagged += 1
                    result["tagged_at"] = datetime.now(timezone.utc).isoformat()
                    db.execute(LC.save_stmt(rec["id"], result))
            except Exception as e:  # noqa: BLE001
                failed += 1
                logger.warning("[%s] 기록 #%s (전략 #%s) 태깅 실패: %s", LC.FIX, rec["id"], rec["strategy_instance_id"], e)
        db.commit()

        rep = LC.build_report(db, days=REPORT_DAYS)
        payload = json.dumps(rep, ensure_ascii=False, default=str)
        row = db.get(SystemSetting, LC.REPORT_KEY)
        if row is None:
            db.add(SystemSetting(key=LC.REPORT_KEY, value=payload))
        else:
            row.value = payload
        db.commit()
        top = ", ".join(f"{a['code']} {a['primary_pnl_usdt']}" for a in rep["actions"][:3])
        logger.info("[%s] 손실 원인 태깅 %d (인스턴스 없음 %d · 실패 %d) · %d일 손실 %d건 %s USDT · 주원인 상위: %s",
                    LC.FIX, tagged, skipped, failed, REPORT_DAYS, rep["n_loss"], rep["loss_usdt"], top or "-")
        return {"tagged": tagged, "skipped": skipped, "failed": failed, "n_loss": rep["n_loss"]}
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error("[Fix371b] 손실 원인 워커 오류: %s", e, exc_info=True)
        return {"tagged": tagged, "failed": failed + 1, "error": str(e)}
    finally:
        db.close()

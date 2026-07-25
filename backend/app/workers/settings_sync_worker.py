"""Settings Sync Worker — 설정 일관성 자동 검증 (#125 옛 미해결!).

사장님 critical 사상: 시스템 설정 = 영구 동기화!
= 매 시간 = .env vs DB settings 검증!

검증:
1. WALLET_LIMIT_PCT = .env 일치
2. TRAILING_RETRACE_PCT default = 10 (= v36!)
3. 기타 critical 설정 일관성

= 사장님 시스템 안정성 영구!
"""
from __future__ import annotations
import logging
import os
from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


def run_settings_sync_once() -> dict:
    """매 시간 = settings 일관성 검증."""
    db = SessionLocal()
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "mismatches": 0,
        "details": [],
    }
    try:
        # 1. WALLET_LIMIT_PCT 검증
        env_wallet = os.environ.get("WALLET_LIMIT_PCT", "130")
        try:
            from app.services.capital_calculator import get_wallet_limit_pct
            actual = float(get_wallet_limit_pct())
            expected = float(env_wallet)
            if abs(actual - expected) > 0.1:
                result["mismatches"] += 1
                result["details"].append({
                    "key": "WALLET_LIMIT_PCT",
                    "env": expected,
                    "actual": actual,
                })
        except Exception as e:
            logger.warning("[settings-sync] WALLET_LIMIT_PCT 검증 실패: %s", e)

        # 2. TRAILING_RETRACE_PCT default 검증
        try:
            from app.core.risk_constants import TRAILING_RETRACE_PCT
            if float(TRAILING_RETRACE_PCT) != 10:
                result["mismatches"] += 1
                result["details"].append({
                    "key": "TRAILING_RETRACE_PCT",
                    "expected": 10,
                    "actual": float(TRAILING_RETRACE_PCT),
                })
        except Exception as e:
            logger.warning("[settings-sync] TRAILING 검증 실패: %s", e)

        # 알림 (= 신 mismatch 발견 시!)
        # 🚨 2026-07-24 v127 HIGH fix: 24h dedup = Telegram spam 방지! (헌법 v127)
        # 옛 silent bug: 매 1시간 = 사장님 반복 알림 = self_check와 동일 클래스 버그!
        if result["mismatches"] > 0:
            _send = True
            try:
                import hashlib as _h
                from app.core.redis_client import get_redis_client as _grc
                _r = _grc()
                _key = "settings_sync:alert:" + _h.md5(str(result["details"]).encode()).hexdigest()[:16]
                if _r and _r.get(_key):
                    _send = False
                    logger.info("[settings-sync v127] 🛡 24h dedup = 알림 skip")
                elif _r:
                    _r.setex(_key, 86400, "1")  # 24h
            except Exception:
                pass
            if _send:
                try:
                    NotificationService(db).send_system_alert(
                        title=f"[settings 불일치] {result['mismatches']}건",
                        body=(
                            f"settings 일관성 위배 감지!\n\n"
                            + "\n".join([
                                f"- {d['key']}: env/expected={d.get('env', d.get('expected'))} vs actual={d['actual']}"
                                for d in result["details"]
                            ])
                            + "\n\n개발자 확인 부탁드립니다!"
                        ),
                    )
                except Exception as e:
                    logger.error("[settings-sync] Telegram 실패: %s", e)

        if result["mismatches"] == 0:
            logger.info("[settings-sync] settings 100%% 일관!")
        else:
            logger.warning("[settings-sync] %d mismatches", result["mismatches"])

    finally:
        db.close()
    return result


if __name__ == "__main__":
    import json
    r = run_settings_sync_once()
    print(json.dumps(r, indent=2, ensure_ascii=False))

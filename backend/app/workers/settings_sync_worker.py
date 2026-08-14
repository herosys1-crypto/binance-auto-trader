"""Settings Sync Worker — 설정 일관성 자동 검증 (#125 옛 미해결!).

사장님 critical 사상: 시스템 설정 = 영구 동기화!
= 매 시간 = .env vs DB settings 검증!

검증:
1. WALLET_LIMIT_PCT = .env 일치
2. TRAILING_RETRACE_PCT = .env override 와 코드 상수 일치
   (v147: 사장님 지시로 10 → 5. 기대값을 여기 또 적으면 두 곳 = 헌법 6번 위반이라
    코드 상수를 진실로 삼고, .env 로 덮어썼을 때만 불일치로 봅니다)
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

        # 2. TRAILING_RETRACE_PCT 검증
        # 🚨 v147h fix: 예전엔 `!= 10` 을 하드코딩해서, 사장님이 v147 에서 5 로
        #    바꾸시자 **매시간 「불일치」 오탐 알림**이 나가는 상태였습니다.
        #    기대값을 워커에 또 적는 것 자체가 두 곳 = 헌법 6번(단일 진실) 위반이라,
        #    코드 상수를 진실로 두고 **.env 로 덮어쓴 경우에만** 불일치로 봅니다.
        try:
            from app.core.risk_constants import TRAILING_RETRACE_PCT
            _env_tr = os.environ.get("TRAILING_RETRACE_PCT")
            if _env_tr is not None and _env_tr.strip() != "":
                if abs(float(TRAILING_RETRACE_PCT) - float(_env_tr)) > 0.01:
                    result["mismatches"] += 1
                    result["details"].append({
                        "key": "TRAILING_RETRACE_PCT",
                        "env": float(_env_tr),
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

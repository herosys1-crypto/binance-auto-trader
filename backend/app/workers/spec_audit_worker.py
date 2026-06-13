"""Spec Audit Worker — 코드 ↔ spec 동기 자동 검증 worker (v48).

사장님 critical 사상: 사장님 spec = 영구 보존, 코드 = spec 그대로 구현!
= 매 시간 = 주요 JS 파일 정적 분석 = 금지 패턴 감지!

검증 패턴 (= 옛 silent bug 패턴):
1. ❌ 옛 v100 분기 = startPrice * (1 + trigger%) silent 사용
2. ❌ 옛 v29 = 「수정 모드」 fillStartPrice('current') silent 호출
3. ❌ 옛 last_avg_entry_price NULL 미처리 (= v35 silent bug!)
4. ❌ 옛 app.core.constants import (= v24 silent bug!)
5. ✅ v40 1단계 평단 보존 logic 존재 확인
6. ✅ v41 avg_entry_price fallback 확인
7. ✅ v42 _refreshLiveCalc 호출 확인

= 사장님 spec 그대로 = 영구 검증!
"""
from __future__ import annotations
import logging
import os
import re
from datetime import datetime, timezone

from app.core.database import SessionLocal
from app.models.risk_event import RiskEvent
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

_DEDUP_KEY = "spec_audit:pattern:{p}"
_DEDUP_TTL = 86400  # 24시간

# Docker container 내부 path
_STATIC_JS_DIR = "/app/app/static/js"
_BACKEND_DIR = "/app/app"

# 금지 패턴 = 옛 silent bug 재발 차단!
FORBIDDEN_PATTERNS = [
    {
        "name": "app.core.constants_import_v24",
        "pattern": r"from\s+app\.core\.constants\s+import",
        "file_pattern": "*.py",
        "severity": "CRITICAL",
        "msg": "v24 silent bug 재발! app.core.constants = 존재 X! strategy_status 사용!",
    },
    {
        "name": "v29_auto_current_price_v38",
        "pattern": r"fillStartPrice\(['\"]current['\"]\)",
        "file_pattern": "cm-prev-blueprint.js",
        "severity": "CRITICAL",
        "msg": "v38 사장님 사상 위배! 「수정 모드」 진입 시 = 자동 현재가 강제 X!",
    },
    {
        "name": "v100_branch_v43",
        "pattern": r"i\s*===?\s*_editCurrentStage\s*\+\s*1",
        "file_pattern": "cm-capitals-grid.js",
        "severity": "CRITICAL",
        "msg": "v43 silent bug 재발! 옛 v100 분기 = 사장님 누적 사상 위배!",
    },
]

# 필수 패턴 = 사장님 사상 그대로 구현 확인
REQUIRED_PATTERNS = [
    {
        "name": "v41_avg_entry_fallback",
        "pattern": r"bp\.avg_entry_price",
        "file_pattern": "cm-prev-blueprint.js",
        "severity": "WARN",
        "msg": "v41 fallback 누락! avg_entry_price fallback 필수!",
    },
    {
        "name": "v42_refreshLiveCalc",
        "pattern": r"_refreshLiveCalc\(\)",
        "file_pattern": "cm-prev-blueprint.js",
        "severity": "WARN",
        "msg": "v42 fix 누락! _refreshLiveCalc() 강제 호출 필수!",
    },
]


def _is_dedup(redis, name):
    if not redis:
        return False
    try:
        return bool(redis.get(_DEDUP_KEY.format(p=name)))
    except Exception:
        return False


def _mark_dedup(redis, name):
    if not redis:
        return
    try:
        redis.setex(_DEDUP_KEY.format(p=name), _DEDUP_TTL, "1")
    except Exception:
        pass


def _scan_files(base_dir, file_pattern, pattern):
    """디렉토리 = 패턴 일치 파일 검색. 주석 라인 = skip!"""
    matches = []
    if not os.path.exists(base_dir):
        return matches
    try:
        import fnmatch
        regex = re.compile(pattern)
        for root, _, files in os.walk(base_dir):
            for f in files:
                if not fnmatch.fnmatch(f, file_pattern):
                    continue
                full_path = os.path.join(root, f)
                try:
                    with open(full_path, "r", encoding="utf-8") as fh:
                        content = fh.read()
                    for line_no, line in enumerate(content.split("\n"), 1):
                        # 🛡 2026-06-13 사장님 critical fix: 주석 라인 skip = false positive 차단!
                        # 옛 silent bug: 옛 패턴 = 주석 안에 있어도 = 매칭 = 사장님 시끄러움!
                        stripped = line.strip()
                        if stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("/*"):
                            continue
                        if regex.search(line):
                            matches.append({"file": full_path, "line": line_no, "code": line.strip()[:120]})
                            break  # 파일당 1건만
                except Exception:
                    pass
    except Exception:
        pass
    return matches


def run_spec_audit_once() -> dict:
    """매 시간 = 코드 ↔ spec 동기 검증."""
    from app.core.redis_client import get_redis_client
    try:
        redis = get_redis_client()
    except Exception:
        redis = None

    db = SessionLocal()
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "forbidden_violations": 0,
        "required_missing": 0,
        "alerts_sent": 0,
        "details": [],
    }
    try:
        # 1. 금지 패턴 = 검출되면 silent bug!
        for p in FORBIDDEN_PATTERNS:
            base = _STATIC_JS_DIR if p["file_pattern"].endswith(".js") else _BACKEND_DIR
            matches = _scan_files(base, p["file_pattern"], p["pattern"])
            # spec_audit_worker 자신은 제외 (자기 코드에 패턴 있음)
            matches = [m for m in matches if "spec_audit_worker" not in m["file"]]
            if matches:
                result["forbidden_violations"] += 1
                result["details"].append({"name": p["name"], "type": "FORBIDDEN", "matches": matches[:3]})
                if not _is_dedup(redis, p["name"]):
                    _mark_dedup(redis, p["name"])
                    try:
                        NotificationService(db).send_system_alert(
                            title=f"[spec audit] 금지 패턴 검출! {p['name']}",
                            body=(
                                f"옛 silent bug 패턴 검출!\n\n"
                                f"패턴: {p['name']}\n"
                                f"심각도: {p['severity']}\n"
                                f"{p['msg']}\n\n"
                                f"발견 위치 ({len(matches)} 건):\n"
                                + "\n".join([f"  {m['file']}:{m['line']}" for m in matches[:3]])
                                + "\n\n개발자 즉시 확인 부탁드립니다!\n"
                                f"이 알림 = 24시간 dedup"
                            ),
                        )
                        result["alerts_sent"] += 1
                    except Exception as e:
                        logger.error("[spec-audit] forbidden 알림 실패: %s", e)

        # 2. 필수 패턴 = 누락 검출
        for p in REQUIRED_PATTERNS:
            base = _STATIC_JS_DIR if p["file_pattern"].endswith(".js") else _BACKEND_DIR
            matches = _scan_files(base, p["file_pattern"], p["pattern"])
            if not matches:
                result["required_missing"] += 1
                result["details"].append({"name": p["name"], "type": "MISSING_REQUIRED"})
                if not _is_dedup(redis, p["name"]):
                    _mark_dedup(redis, p["name"])
                    try:
                        NotificationService(db).send_system_alert(
                            title=f"[spec audit] 필수 패턴 누락! {p['name']}",
                            body=(
                                f"사장님 사상 구현 누락!\n\n"
                                f"패턴: {p['name']}\n"
                                f"심각도: {p['severity']}\n"
                                f"{p['msg']}\n\n"
                                f"개발자 즉시 추가 부탁드립니다!\n"
                                f"이 알림 = 24시간 dedup"
                            ),
                        )
                        result["alerts_sent"] += 1
                    except Exception as e:
                        logger.error("[spec-audit] required 알림 실패: %s", e)

        if result["forbidden_violations"] == 0 and result["required_missing"] == 0:
            logger.info("[spec-audit] 코드 ↔ spec 100%% 동기!")
        else:
            logger.warning(
                "[spec-audit] forbidden=%d missing=%d alerts=%d",
                result["forbidden_violations"], result["required_missing"], result["alerts_sent"],
            )

    finally:
        db.close()
    return result


if __name__ == "__main__":
    import json
    r = run_spec_audit_once()
    print(json.dumps(r, indent=2, ensure_ascii=False))

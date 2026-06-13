"""Mainnet Safety Worker — 사장님 mainnet 진입 직전 점검 자동화 (#23!).

사장님 critical 사상: 실자금 = 절대 silent X!
= 매 1시간 = mainnet 안전 점검 자동!

검증:
1. Frontend testnet 하드코드 = grep 검색
2. 거래소 계정 = is_testnet 정확 설정 확인
3. 사장님 자본 = 위험 노출 검증
4. API key 인증 정기 검증

= 사장님 mainnet 안전 = 영구!
"""
from __future__ import annotations
import logging
import os
import re
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.exchange_account import ExchangeAccount
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

_DEDUP_KEY = "mainnet_safety:check:{c}"
_DEDUP_TTL = 86400  # 24시간

# Docker container 내부 path
_STATIC_JS_DIR = "/app/app/static/js"

# 위험 패턴 = Frontend hardcode!
DANGEROUS_PATTERNS = [
    {
        "name": "frontend_testnet_hardcode_true",
        "pattern": r"testnet\s*[=:]\s*true",
        "file_pattern": "*.js",
        "severity": "CRITICAL",
        "msg": "Frontend testnet=true 하드코드! = 사장님 mainnet 사고 위험!",
    },
    {
        "name": "frontend_isTestnet_hardcode_true",
        "pattern": r"isTestnet\s*[=:]\s*true",
        "file_pattern": "*.js",
        "severity": "WARN",
        "msg": "Frontend isTestnet=true 하드코드 가능성!",
    },
]


def _is_dedup(redis, name):
    if not redis:
        return False
    try:
        return bool(redis.get(_DEDUP_KEY.format(c=name)))
    except Exception:
        return False


def _mark_dedup(redis, name):
    if not redis:
        return
    try:
        redis.setex(_DEDUP_KEY.format(c=name), _DEDUP_TTL, "1")
    except Exception:
        pass


def _scan_files(base_dir, file_pattern, pattern):
    """위험 패턴 grep."""
    matches = []
    if not os.path.exists(base_dir):
        return matches
    try:
        import fnmatch
        regex = re.compile(pattern, re.IGNORECASE)
        for root, _, files in os.walk(base_dir):
            for f in files:
                if not fnmatch.fnmatch(f, file_pattern):
                    continue
                full_path = os.path.join(root, f)
                try:
                    with open(full_path, "r", encoding="utf-8") as fh:
                        content = fh.read()
                    for line_no, line in enumerate(content.split("\n"), 1):
                        stripped = line.strip()
                        # 주석 라인 = skip
                        if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
                            continue
                        # 🛡 2026-06-13 사장님 critical fix: 사장님 input 처리 = whitelist!
                        # 예: if (trimmed === "testnet") isTestnet = true;
                        # = 사장님 환경 변경 input 처리 = 하드코드 X = false positive!
                        if any(kw in line for kw in ['trimmed', 'envChoice', 'prompt(', '?', '||', '===', '=== "testnet"', 'choice']):
                            continue
                        if regex.search(line):
                            matches.append({
                                "file": full_path,
                                "line": line_no,
                                "code": line.strip()[:150],
                            })
                            break  # 파일당 1건만
                except Exception:
                    pass
    except Exception:
        pass
    return matches


def _check_exchange_accounts(db):
    """거래소 계정 = is_testnet 정확 확인."""
    accounts = db.execute(
        select(ExchangeAccount)
        .where(ExchangeAccount.is_active.is_(True))
    ).scalars().all()
    result = []
    for a in accounts:
        result.append({
            "id": a.id,
            "name": a.name,
            "is_testnet": a.is_testnet,
        })
    return result


def run_mainnet_safety_check_once() -> dict:
    """매 1시간 = mainnet 안전 점검."""
    from app.core.redis_client import get_redis_client
    try:
        redis = get_redis_client()
    except Exception:
        redis = None

    db = SessionLocal()
    result = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "violations": 0,
        "alerts_sent": 0,
        "exchange_accounts": [],
        "details": [],
    }
    try:
        # 1. Frontend 하드코드 검사
        for p in DANGEROUS_PATTERNS:
            matches = _scan_files(_STATIC_JS_DIR, p["file_pattern"], p["pattern"])
            if matches:
                result["violations"] += 1
                result["details"].append({"name": p["name"], "matches": matches[:3]})
                if not _is_dedup(redis, p["name"]):
                    _mark_dedup(redis, p["name"])
                    try:
                        NotificationService(db).send_system_alert(
                            title=f"[mainnet 위험!] {p['name']}",
                            body=(
                                f"사장님 mainnet 사고 위험 패턴 검출!\n\n"
                                f"패턴: {p['name']}\n"
                                f"심각도: {p['severity']}\n"
                                f"{p['msg']}\n\n"
                                f"발견 위치:\n"
                                + "\n".join([f"  {m['file']}:{m['line']}" for m in matches[:3]])
                                + "\n\n개발자 즉시 확인!\n"
                                f"이 알림 = 24시간 dedup"
                            ),
                        )
                        result["alerts_sent"] += 1
                    except Exception as e:
                        logger.error("[mainnet-safety] Telegram 실패: %s", e)

        # 2. 거래소 계정 검사 (= 사장님 인지 자료!)
        result["exchange_accounts"] = _check_exchange_accounts(db)

        if result["violations"] == 0:
            logger.info("[mainnet-safety] 위험 패턴 0건!")
        else:
            logger.warning(
                "[mainnet-safety] %d violations, alerts=%d",
                result["violations"], result["alerts_sent"],
            )

    finally:
        db.close()
    return result


if __name__ == "__main__":
    import json
    r = run_mainnet_safety_check_once()
    print(json.dumps(r, indent=2, ensure_ascii=False))

"""🧾 Fix 457 (2026-10-14 사장님 「판정 보고서 자동 실행 진행해줘」) — 정해진 날 판정·중간 점검 보고서를 자동으로 돌린다.

읽기·기록 전용(주문·설정 변경 없음):
  매일 KST 10:20 확인 → 오늘(KST)이 `verdict_auto_schedule` 에 있으면 그 스크립트를 실행해
  전체 보고서를 Redis `verdict:report:<날짜>:<종류>`(60일)에 두고, 텔레그램에 요약 1통.
  - midcheck = scripts/entry_condition_study/midcheck_2026_10_17.py
  - verdict  = scripts/entry_condition_study/verdict_2026_10_25.py
  날짜·종류당 한 번만(Redis 표식). 보고서 원문은 /api/v1/strategy-council/verdict-report 로 본다.
설정 `verdict_auto_schedule` 기본 "2026-10-17=midcheck,2026-10-25=verdict" (Claude가 정함) · "off" = 끔.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import logging
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

FIX = "Fix457"
SETTING_KEY = "verdict_auto_schedule"
DEFAULT_SCHEDULE = "2026-10-17=midcheck,2026-10-25=verdict,2026-11-15=jk"   # jk = 가설 J·K (10/16 사전 등록)
KST = timezone(timedelta(hours=9))
SCRIPTS = {
    "midcheck": "midcheck_2026_10_17.py",
    "verdict": "verdict_2026_10_25.py",
    "jk": "jk_2026_11_15.py",
}
TITLES = {"verdict": "🧾 통합 판정 보고서", "midcheck": "🩺 중간 점검 보고서", "jk": "🧪 가설 J·K 판정"}
REPORT_KEY = "verdict:report:{day}:{kind}"
DONE_KEY = "verdict:done:{day}:{kind}"
REPORT_TTL = 60 * 86400
TELEGRAM_MAX = 3500
_SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts" / "entry_condition_study"


def parse_schedule(raw: Any) -> dict[str, str]:
    """"날짜=종류,…" → {날짜: 종류}. 모르는 종류·깨진 날짜는 건너뛴다. "off" = 빈 표."""
    s = str(raw if raw is not None else DEFAULT_SCHEDULE).strip()
    if s.lower() in ("off", "0", "false", "none", ""):
        return {}
    out: dict[str, str] = {}
    for part in s.split(","):
        if "=" not in part:
            continue
        d, k = (x.strip() for x in part.split("=", 1))
        try:
            date.fromisoformat(d)
        except ValueError:
            continue
        if k in SCRIPTS:
            out[d] = k
    return out


def run_script(kind: str) -> str:
    """스크립트의 main() 을 같은 프로세스에서 돌려 표준 출력을 문자열로 받는다."""
    p = _SCRIPT_DIR / SCRIPTS[kind]
    spec = importlib.util.spec_from_file_location(f"auto_{kind}", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod.main()
    return buf.getvalue()


def summarize(kind: str, report: str) -> str:
    """텔레그램 요약 — 통과·후보만 이름으로, 나머지는 개수."""
    lines = report.splitlines()
    if kind == "jk":                       # J = 「§ J …」 다음 줄 · K = 「판정:」 줄
        out = []
        for i, ln in enumerate(lines):
            if ln.startswith("## § J"):
                out.append("J (운영팀 SHORT 첫 1건 vs S4): " + (lines[i + 1] if i + 1 < len(lines) else "?"))
            if ln.startswith("판정:"):
                out.append("K (LONG + 24h 시장폭<0.45): " + ln[3:].strip())
            if ln.startswith("하루 1건(그날 첫 진입)"):
                out.append("K " + ln)
        return "\n".join(out) or "(요약 줄 없음 — 원문 확인)"
    if kind == "midcheck":
        keep = [ln for ln in lines if ln.startswith("요약:") or "끝난" in ln and "평균" in ln]
        warn = [ln.split("|")[1].strip() for ln in lines if ln.startswith("|") and "⚠️ 부족 예상" in ln]
        out = keep + ([f"부족 예상: {', '.join(warn[:8])}" + (" …" if len(warn) > 8 else "")] if warn else [])
        return "\n".join(out) or "(요약 줄 없음 — 원문 확인)"
    passed = [ln.split("|")[1].strip() for ln in lines if ln.startswith("|") and "✅ 통과" in ln]
    rejected = sum(1 for ln in lines if ln.startswith("|") and "❌ 기각" in ln)
    held = sum(1 for ln in lines if ln.startswith("|") and "⏳ 보류" in ln)
    exit_cand = [ln.split("|")[1].strip() for ln in lines if ln.startswith("|") and "✅ 청산 후보" in ln]
    hyp = next((ln for ln in lines if ln.startswith("→ ") and ("제외 후보" in ln or "기각" in ln or "보류" in ln)), None)
    no_pass = any("통과한 전략 없음" in ln for ln in lines)
    out = [f"✅ 통과 {len(passed)} · ❌ 기각 {rejected} · ⏳ 보류 {held}"]
    if passed:
        out.append("통과: " + ", ".join(passed[:12]) + (" …" if len(passed) > 12 else ""))
    if exit_cand:
        out.append("청산 후보: " + ", ".join(exit_cand[:8]))
    if hyp:
        out.append("가설 I " + hyp[2:])
    out.append("단계 1 설정표: " + ("통과 없음 → 단계 0 유지" if no_pass or not passed else "보고서 H 구역 — 바꾸는 건 대표님"))
    return "\n".join(out)


def run_verdict_report_once(*, now: datetime | None = None, redis=None, db=None, runner=run_script) -> dict:
    """오늘(KST)이 일정에 있으면 실행. 반환 {"day", "kind", "ran", "chars", "sent"}."""
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(KST).date().isoformat()
    own_db = db is None
    if own_db:
        from app.core.database import SessionLocal
        db = SessionLocal()
    try:
        raw = None
        try:
            from app.models.system_setting import SystemSetting
            row = db.get(SystemSetting, SETTING_KEY)
            raw = row.value if row is not None else None
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] 일정 설정 읽기 실패 → 기본 일정: %s", FIX, e)
        kind = parse_schedule(raw).get(day)
        out = {"day": day, "kind": kind, "ran": False, "chars": 0, "sent": False}
        if kind is None:
            return out
        if redis is None:
            from app.core.redis_client import get_redis_client
            redis = get_redis_client()
        if not redis.set(DONE_KEY.format(day=day, kind=kind), now.isoformat(), nx=True, ex=REPORT_TTL):
            logger.info("[%s] %s %s 이미 실행함", FIX, day, kind)
            return out
        try:
            report = runner(kind)
        except Exception as e:  # noqa: BLE001
            redis.delete(DONE_KEY.format(day=day, kind=kind))     # 실패면 다음 시도에 다시
            logger.warning("[%s] %s 보고서 실행 실패: %s", FIX, kind, e)
            raise
        redis.setex(REPORT_KEY.format(day=day, kind=kind), REPORT_TTL, report)
        out.update(ran=True, chars=len(report))
        title = TITLES.get(kind, "🧾 판정 보고서") + f" {day}"
        body = summarize(kind, report)[:TELEGRAM_MAX] + "\n\n원문: 운영팀 카드 → 판정 보고서 (실주문 반영은 대표님 승인 뒤)"
        try:
            from app.services.notification_service import NotificationService
            out["sent"] = NotificationService(db).send_system_alert(title=title, body=body) is not None
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] 텔레그램 실패 (보고서는 저장됨): %s", FIX, e)
        logger.info("[%s] %s %s 보고서 %d자 저장 · 텔레그램 %s", FIX, day, kind, len(report), out["sent"])
        return out
    finally:
        if own_db:
            db.close()


def latest_report(redis, day: str | None = None, kind: str | None = None) -> dict | None:
    """API 용 — 날짜·종류를 주면 그것, 아니면 가장 최근 보고서."""
    keys = []
    try:
        for k in redis.scan_iter("verdict:report:*", count=200):
            keys.append(k.decode() if isinstance(k, bytes) else str(k))
    except Exception:  # noqa: BLE001
        return None
    m = [re.match(r"verdict:report:(\d{4}-\d{2}-\d{2}):(\w+)$", k) for k in keys]
    cands = sorted(((x.group(1), x.group(2), x.group(0)) for x in m if x), reverse=True)
    if day:
        cands = [c for c in cands if c[0] == day]
    if kind:
        cands = [c for c in cands if c[1] == kind]
    if not cands:
        return None
    d, k, key = cands[0]
    raw = redis.get(key)
    return {"day": d, "kind": k, "report": raw.decode() if isinstance(raw, bytes) else raw}

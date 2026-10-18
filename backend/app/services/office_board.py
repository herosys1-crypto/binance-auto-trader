"""🏢 Fix 458 (2026-10-14 사장님 「사무실 탭 진행해줘」) — 자동매매 「사무실」 화면 데이터.

AI HQ 개발실 「사무실」 탭처럼 본부(방)마다 책상(팀·워커)을 두고 상태 배지를 단다. 읽기 전용(주문·설정 변경 없음).
상태 근거:
  - 스케줄러 잡별 마지막 실행 `sched:last`(Fix 458 기록) — 시작·끝·성공/오류
  - 감시 진단 `orchestra:health:last` · 학습 기록 `orchestra:learning:last`(Fix 450) · 패턴 학습 재료 없음(Fix 455)
  - 가상매매 마지막 사이클 `paper_trading:last_cycle` · 운영팀 성적표 `council:day:<날짜>`
  - 실주문 가족 모드·진행 중 전략 수 · 자동매매 전면 중단
상태: working(작업 중) · waiting(다음 실행 대기) · error(오류) · stale(멈춤?) · off(꺼짐) · nodata(재료 없음) · unknown(기록 없음)
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

KST = timezone(timedelta(hours=9))
JOB_LAST_KEY = "sched:last"
STALE_FACTOR = 3.0          # 주기의 3배 넘게 실행이 없으면 「멈춤?」 (Claude가 정함)
# 🏢 Fix 459: 마지막이 오류여도 24h 오류 ≤1번 · 실행 ≥10번이면 「일시 오류」(blip) — 288번 중 1번 시간 초과를 「오류」로 키우지 않게 (Claude가 정함)
BLIP_MAX_ERRORS = 1
BLIP_MIN_RUNS = 10
JOB_RUNS_PREFIX = "sched:runs:"
JOB_ERRS_PREFIX = "sched:errs:"
JOB_NEXT_KEY = "sched:next"


@dataclass(frozen=True)
class Desk:
    key: str
    label: str
    avatar: str
    jobs: tuple[str, ...] = ()        # sched:last 잡 이름 (가장 최근 것으로 판정)
    every_s: int = 300                # 정상 주기(초) — 멈춤 판정 기준
    role: str = ""


@dataclass(frozen=True)
class Room:
    key: str
    label: str
    icon: str
    color: str
    desks: tuple[Desk, ...] = field(default_factory=tuple)


ROOMS: tuple[Room, ...] = (
    Room("command", "지휘실", "🎩", "#fde68a", (
        Desk("conductor", "지휘자 · 감시 진단", "🎩", ("orchestra_health",), 300, "5분마다 팀 점검 · 이상이면 자동 복구·알림"),
        Desk("halt", "전면 중단 스위치", "🛑", (), 0, "auto_trading_halt — 켜지면 자동 진입 모두 멈춤"),
        Desk("verdict", "판정 보고서", "🧾", ("verdict_report",), 86400, "10/17 중간 점검 · 10/25 통합 판정 자동 실행"),
    )),
    Room("trade", "실주문 매매실", "⚔️", "#bfdbfe", (
        Desk("rf_bottom_long", "3B 저점 반전 LONG", "📈", ("rule_families",), 60, "규칙 가족 실주문 · 장세 필터(시장폭<0.4)"),
        Desk("rf_zone_s4", "S4 급반등 꼭대기 SHORT", "📉", ("rule_families",), 60, "규칙 가족 실주문 · 장세 필터(24h+10%)"),
        Desk("external", "외부 전략(그림자)", "🧭", ("external_strategies",), 60, "후지모토·마하세븐·EMA·볼린저·3중 이평 — 기록만"),
        Desk("reconcile", "포지션 대조", "🔁", ("position_reconcile",), 120, "거래소 ↔ DB 맞추기"),
        Desk("risk", "청산 위험·하루 손실", "🛡️", ("liquidation_risk", "daily_loss_check"), 60, "청산가 근접·하루 손실 한도"),
    )),
    Room("lab", "가상매매 연구실", "🧪", "#bbf7d0", (
        Desk("paper", "가상매매 엔진", "🧪", ("paper_trading",), 900, "608종목 · 15분마다 규칙 판정·청산 변형 기록"),
        Desk("council", "전략 운영팀", "🧑‍⚖️", ("strategy_council",), 86400, "매일 KST 09:40 성적표·배치표"),
        Desk("ichilab", "일목 기준선 실험실", "🗾", ("ichikijun_lab", "ichikijun_board", "ichikijun_exit"), 900, "변형 72줄 가상 기록 · 매일 10:30 챔피언 · 기준선 청산(Fix 465·467)"),
        Desk("chart_journal", "차트 학습 일지", "📚", ("chart_learning_snapshot", "chart_learning_outcome"), 86400, "상승·하락 50 종목 기록·라벨"),
    )),
    Room("learn", "학습실", "🎓", "#e9d5ff", (
        Desk("learning_team", "학습 팀", "🎓", ("learning_team_cycle",), 4 * 3600, "4시간마다 학습 사이클"),
        Desk("chart_pattern", "차트 패턴 학습 팀", "🔍", ("chart_pattern_scan",), 6 * 3600, "6시간마다 상위 100 종목 패턴"),
        Desk("pattern_learning", "패턴 학습", "🧠", ("pattern_learning",), 3600, "전략 제안 결과로 학습 (재료 없으면 쉼)"),
        Desk("suggestion", "전략 제안 팀", "💡", ("suggestion_daily_predict", "daily_briefing"), 86400, "매일 예측 · 아침 브리핑"),
    )),
    Room("watch", "감시실", "📡", "#fecaca", (
        Desk("watchlist", "실시간 감시 목록", "👀", ("realtime_watchlist",), 900, "급등·급락·거래량 상위 45"),
        Desk("silent_bug", "조용한 버그 감지", "🐞", ("silent_bug_detector",), 60, "1분마다 결손·불일치 감지"),
        Desk("pump", "급등락 감시", "🚨", ("pump_dump_early_detector", "pump_top_detector"), 300, "급등·급락 조기 감지"),
        Desk("telegram", "텔레그램 재전송", "📨", ("telegram_retry",), 300, "실패한 알림 다시 보내기"),
    )),
)

STATUS_LABEL = {
    "working": "작업 중", "waiting": "다음 실행 대기", "error": "오류", "stale": "멈춤?",
    "off": "꺼짐", "nodata": "재료 없음", "unknown": "기록 없음", "on": "켜짐", "shadow": "그림자",
    "blip": "일시 오류",
}


def _s(x) -> str:
    return x.decode() if isinstance(x, bytes) else str(x)


def hour_keys(now: float, hours: int = 24) -> list[str]:
    """지금 시간 칸 포함 최근 hours 칸(UTC YYYYMMDDHH), 최근 것부터."""
    base = datetime.fromtimestamp(now, timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [(base - timedelta(hours=i)).strftime("%Y%m%d%H") for i in range(hours)]


def parse_counts(runs: list[dict | None], errs: list[dict | None]) -> dict[str, tuple[int, int]]:
    """시간 칸 해시들 → 잡별 (실행 합, 오류 합). bytes/str 혼합 · 숫자 아닌 값은 건너뜀."""
    tot: dict[str, list[int]] = {}
    for i, group in enumerate((runs, errs)):
        for h in group or ():
            for k, v in (h or {}).items():
                try:
                    n = int(_s(v))
                except (TypeError, ValueError):
                    continue
                tot.setdefault(_s(k), [0, 0])[i] += n
    return {k: (r, e) for k, (r, e) in tot.items()}


def parse_next_runs(raw: dict | None) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for k, v in (raw or {}).items():
        try:
            val = json.loads(_s(v))
            out[_s(k)] = float(val) if val is not None else None
        except (TypeError, ValueError):
            continue
    return out


def _until(ts: float, now: float) -> str:
    s = int(ts - now)
    if s <= 0:
        return "곧"
    if s < 90:
        return f"{s}초 뒤"
    if s < 5400:
        return f"{(s + 30) // 60}분 뒤"          # 반올림(은행가 반올림 round 대신 — 150초 = 3분)
    if s < 172800:
        return f"{(s + 1800) // 3600}시간 뒤"
    return f"{(s + 43200) // 86400}일 뒤"


def parse_job_records(raw: dict | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for k, v in (raw or {}).items():
        try:
            key = k.decode() if isinstance(k, bytes) else str(k)
            out[key] = json.loads(v)
        except Exception:  # noqa: BLE001
            continue
    return out


def job_status(recs: dict[str, dict], jobs: tuple[str, ...], every_s: int, now: float) -> tuple[str, dict | None]:
    """책상의 잡들 중 가장 최근 기록으로 상태를 정한다."""
    cands = [(recs[j].get("s") or 0, j, recs[j]) for j in jobs if j in recs]
    if not cands:
        return "unknown", None
    _s, job, rec = max(cands)
    if rec.get("st") == "run":
        return "working", {"job": job, **rec}
    last = rec.get("e") or rec.get("s") or 0
    if rec.get("st") == "err":
        return "error", {"job": job, **rec}
    if every_s and now - last > every_s * STALE_FACTOR:
        return "stale", {"job": job, **rec}
    return "waiting", {"job": job, **rec}


def _ago(ts: float | None, now: float) -> str:
    if not ts:
        return "—"
    s = max(0, int(now - ts))
    if s < 90:
        return f"{s}초 전"
    if s < 5400:
        return f"{s // 60}분 전"
    if s < 172800:
        return f"{s // 3600}시간 전"
    return f"{s // 86400}일 전"


@dataclass(frozen=True)
class DailyJob:
    job: str
    label: str
    kst: str            # 예정 시각 "HH:MM" (KST, 표시·놓침 판정용 — 실제 트리거는 scheduler_runner)


# 📅 Fix 461 (2026-10-15 사장님 「실장님 승인으로 모두 개발 완료」): 오늘 하루 1번 잡 표 — 돌았는지·실패·놓침
DAILY_JOBS: tuple[DailyJob, ...] = (
    DailyJob("daily_summary", "일일 운영 요약", "00:00"),
    DailyJob("memory_consolidator", "기억 정리", "03:00"),
    DailyJob("daily_briefing", "아침 브리핑", "07:30"),
    DailyJob("daily_report", "일일 운영 보고", "09:00"),
    DailyJob("strategy_council", "전략 운영팀 성적표", "09:40"),
    DailyJob("verdict_report", "판정 보고서(정해진 날만)", "10:20"),
    DailyJob("ichikijun_board", "일목 실험실 순위표·챔피언", "10:30"),
    DailyJob("symbol_sync_daily", "심볼 동기화", "12:00"),
    DailyJob("paper_retention", "가상 상세 정리", "12:40"),
    DailyJob("suggestion_daily_predict", "전략 제안 예측", "15:30"),
    DailyJob("suggestion_auto_execute", "제안 자동 실행(옵션)", "16:00"),
)
DAILY_OPTIONAL = frozenset({"verdict_report", "suggestion_auto_execute"})   # 정해진 날·옵션일 때만 일을 한다
DAILY_GRACE_MIN = 10        # 예정 + 10분이 지나야 「놓침?」 (Claude가 정함)


def _epoch(v) -> float | None:
    """유효한 epoch 초만(유한·0~1e11), 아니면 None."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and 0 < f < 1e11 else None


def daily_table(recs: dict[str, dict], next_runs: dict[str, float | None], now: float) -> list[dict]:
    """DAILY_JOBS 순서대로 오늘(KST) 실행 여부. 순수 함수."""
    now_k = datetime.fromtimestamp(now, KST)
    out = []
    for dj in DAILY_JOBS:
        rec = recs.get(dj.job) or {}
        s, e = _epoch(rec.get("s")), _epoch(rec.get("e"))   # 깨진 기록(문자열·NaN·무한대)은 「기록 없음」(감사·Gemini 지적)
        if s is None:
            e = None
        hh, mm = (int(x) for x in dj.kst.split(":"))
        due = now_k.replace(hour=hh, minute=mm, second=0, microsecond=0)
        late = now_k > due + timedelta(minutes=DAILY_GRACE_MIN)
        today = bool(s) and datetime.fromtimestamp(s, KST).date() == now_k.date()
        st = rec.get("st")
        if today and st == "run":
            state = "running"
        elif today and st == "err":
            state = "failed"
        elif today:
            state = "done"
        elif not late:
            state = "later"
        elif not s:
            state = "unknown"
        else:
            state = "skip" if dj.job in DAILY_OPTIONAL else "missed"
        nxt = _epoch((next_runs or {}).get(dj.job))
        out.append({
            "job": dj.job, "label": dj.label, "kst": dj.kst, "state": state, "today": today,
            "last": datetime.fromtimestamp(s, KST).strftime("%m-%d %H:%M") if s else None,
            "ago": _ago(e or s, now) if s else "—",
            "next": _until(nxt, now) if nxt is not None else "—",
            "err": (str(rec.get("err") or "")[:120] or None) if state == "failed" else None,
        })
    return out


LIVE_CACHE_KEY = "orchestra:office:live"
LIVE_CACHE_TTL = 300        # 📒 10/16: 가족 손익 분해는 무겁다 — 사무실(20초 캐시)이 DB 를 두드리지 않게 5분
LIVE_DAYS = 14
LIVE_FAIL_KEY = "orchestra:office:live:fail"
LIVE_FAIL_TTL = 60          # 표 만들기가 실패하면 60초 동안 다시 시도하지 않는다(느린 DB 를 20초마다 더 두드리지 않게 — 교차 감사)


def live_line(v: dict | None) -> str:
    """실주문 가족 책상 한 줄: 오늘 진입·14일 시스템 몫·사람 추가 몫. 값이 없으면 빈 문자열."""
    if not isinstance(v, dict):
        return ""
    parts = []
    if v.get("cap") is not None:
        parts.append(f"오늘 {'?' if v.get('today') is None else v['today']}/{v['cap']}건")
    if v.get("system") is not None:
        parts.append(f"{LIVE_DAYS}일 시스템 몫 {float(v['system']):+.1f} (끝난 {int(v.get('closed') or 0)}·이긴 {int(v.get('wins') or 0)})")
    if v.get("human") and round(float(v["human"]), 1) != 0:        # 반올림해 0 이면 「+0.0」 대신 생략
        parts.append(f"사람 추가 몫 {float(v['human']):+.1f}")
    return (" · " + " · ".join(parts)) if parts else ""


def build(*, recs: dict[str, dict], extras: dict[str, Any], now: float | None = None,
          counts24: dict[str, tuple[int, int]] | None = None, next_runs: dict[str, float | None] | None = None) -> dict:
    """화면 데이터. extras = {halt, modes{fam: on/shadow/off}, active{fam: n}, health, learning, pattern_no_data,
    paper_last, council_today, verdict_latest}. 순수 함수(테스트용)."""
    now = now or time.time()
    rooms = []
    counts: dict[str, int] = {}
    for room in ROOMS:
        desks = []
        for d in room.desks:
            status, rec = job_status(recs, d.jobs, d.every_s, now) if d.jobs else ("unknown", None)
            runs24 = errs24 = None
            if counts24 is not None and any(j in counts24 for j in d.jobs):
                runs24 = sum(counts24.get(j, (0, 0))[0] for j in d.jobs)
                errs24 = sum(counts24.get(j, (0, 0))[1] for j in d.jobs)
            if status == "error" and errs24 is not None and errs24 <= BLIP_MAX_ERRORS and runs24 >= BLIP_MIN_RUNS:
                status = "blip"
            nxt = [t for j in d.jobs if (t := (next_runs or {}).get(j)) is not None]
            fut = [t for t in nxt if t > now]       # 가장 이른 「미래」 — 스냅숏(60초)이 지난 시각만 있으면 「곧」
            soon = min(fut) if fut else (max(nxt) if nxt else None)
            detail = d.role
            badge = None
            if d.key == "halt":
                status = "error" if extras.get("halt") else "on"
                detail = "⛔ 전면 중단 중 — 자동 진입 없음" if extras.get("halt") else "정상 — 자동 진입 허용"
            elif d.key in ("rf_bottom_long", "rf_zone_s4"):
                mode = (extras.get("modes") or {}).get(d.key, "?")
                n = (extras.get("active") or {}).get(d.key, 0)
                badge = STATUS_LABEL.get(mode, mode)
                if mode == "off":
                    status = "off"
                detail = f"모드 {badge} · 진행 중 {n}건 · {d.role}" + live_line((extras.get("live") or {}).get(d.key))
            elif d.key == "conductor" and extras.get("health"):
                h = extras["health"]
                ok = h.get("checks") and h.get("healthy") == h.get("checks")
                detail = f"점검 {h.get('healthy')}/{h.get('checks')} 정상 · 자동 복구 {h.get('fixes', 0)}"
                if not ok and status == "waiting":
                    status = "error"
            elif d.key == "pattern_learning" and extras.get("pattern_no_data"):
                status = "nodata"
                detail = f"결과 난 전략 제안이 30일 안에 없음(마지막 {str(extras['pattern_no_data'].get('newest_outcome') or '')[:10]})"
            elif d.key == "paper" and extras.get("paper_last"):
                p = extras["paper_last"]
                detail = (f"감시 {p.get('symbols')} · 열림 {p.get('opened')} · 관리 {p.get('managed')} · 마감 {p.get('closed')} · "
                          f"국면 {p.get('regime')}({p.get('breadth')}) · {p.get('seconds')}초")
            elif d.key == "council":
                detail = ("오늘 성적표 있음 · " if extras.get("council_today") else "오늘 성적표 아직 · ") + d.role
            elif d.key == "verdict" and extras.get("verdict_latest"):
                v = extras["verdict_latest"]
                detail = f"최근 보고서 {v.get('day')} {('통합 판정' if v.get('kind') == 'verdict' else '중간 점검')} · {d.role}"
            if d.key in ("learning_team", "chart_pattern") and extras.get("learning"):
                lk = {"learning_team": "learning", "chart_pattern": "chart_pattern_learning"}[d.key]
                lv = extras["learning"].get(lk)
                if lv:
                    detail = f"마지막 학습 완료 {str(lv.get('at', ''))[5:16].replace('T', ' ')} UTC · {d.role}"
            counts[status] = counts.get(status, 0) + 1
            desks.append({
                "key": d.key, "label": d.label, "avatar": d.avatar, "status": status,
                "status_label": STATUS_LABEL.get(status, status), "badge": badge, "detail": detail,
                "last": _ago((rec or {}).get("e") or (rec or {}).get("s"), now) if rec else "—",
                "job": (rec or {}).get("job"), "error": (rec or {}).get("err"),
                "runs_24h": runs24, "errors_24h": errs24,
                "next_run": _until(soon, now) if soon is not None else "—",
                "next_run_at": datetime.fromtimestamp(soon, KST).strftime("%H:%M") if soon is not None else None,
            })
        rooms.append({"key": room.key, "label": room.label, "icon": room.icon, "color": room.color, "desks": desks})
    others_err = sorted(j for j, r in recs.items() if r.get("st") == "err"
                        and not any(j in d.jobs for room in ROOMS for d in room.desks))
    return {"at": datetime.fromtimestamp(now, KST).strftime("%Y-%m-%d %H:%M:%S KST"), "rooms": rooms, "counts": counts,
            "jobs_recorded": len(recs), "other_errors": others_err[:20], "daily": _daily_safe(recs, next_runs, now)}


def _daily_safe(recs, next_runs, now) -> list[dict]:
    try:
        return daily_table(recs, next_runs or {}, now)
    except Exception:  # noqa: BLE001 — 표 하나 때문에 사무실 전체가 죽으면 안 된다
        return []


def collect(db: Any, redis: Any, *, now: float | None = None) -> dict:
    """운영 데이터 모으기(읽기 전용). 하나가 실패해도 나머지는 그린다."""
    now = now or time.time()

    def safe(fn: Callable[[], Any], default=None):
        try:
            return fn()
        except Exception:  # noqa: BLE001
            return default

    def jget(key):
        raw = redis.get(key)
        if not raw:
            return None
        return json.loads(raw.decode() if isinstance(raw, bytes) else raw)

    recs = safe(lambda: parse_job_records(redis.hgetall(JOB_LAST_KEY)), {})
    extras: dict[str, Any] = {}
    from app.services import auto_trading_halt as AH
    extras["halt"] = safe(lambda: AH.halt_enabled(db), None)
    from app.services import rule_families as RF
    extras["modes"] = {k: safe(lambda k=k: RF.mode_of(db, k), "?") for k in ("rf_bottom_long", "rf_zone_s4")}

    def _active():
        from sqlalchemy import text
        rows = db.execute(text("""select st.strategy_type, count(*) from strategy_instances si
            join strategy_templates st on st.id = si.strategy_template_id
            where st.strategy_type in ('rf_bottom_331', 'rf_zone_s4')
              and si.status not in ('COMPLETED','STOPPED','FAILED','CANCELLED','LIQUIDATED','ERROR')
            group by 1""")).all()
        m = {"rf_bottom_331": "rf_bottom_long", "rf_zone_s4": "rf_zone_s4"}
        return {m[t]: int(n) for t, n in rows if t in m}
    extras["active"] = safe(_active, {})

    def _live():
        raw = redis.get(LIVE_CACHE_KEY)
        if raw:
            board = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
        else:
            if redis.get(LIVE_FAIL_KEY):
                return None
            from app.services import live_family_board as LFB
            try:
                board = LFB.build(db, days=LIVE_DAYS)
            except Exception:
                try:
                    redis.setex(LIVE_FAIL_KEY, LIVE_FAIL_TTL, "1")
                except Exception:  # noqa: BLE001
                    pass
                raise
            try:
                redis.setex(LIVE_CACHE_KEY, LIVE_CACHE_TTL, json.dumps(board, ensure_ascii=False, default=str))
            except Exception:  # noqa: BLE001
                pass
        out = {f["key"]: {k: f.get(k) for k in ("system", "human", "closed", "wins")} for f in board.get("families") or []}
        from app.services import auto_family_registry as AF
        for key in ("rf_bottom_long", "rf_zone_s4"):
            row = out.setdefault(key, {})
            cap = safe(lambda key=key: AF.daily_max(db, key))
            used = safe(lambda key=key: AF.count_today(db, key))
            row["cap"] = cap
            row["today"] = None if used is None or used >= AF.COUNT_FAILED else used
        return out
    live = safe(_live)
    if live:
        extras["live"] = live
    extras["health"] = safe(lambda: jget("orchestra:health:last"))
    extras["learning"] = safe(lambda: {(k.decode() if isinstance(k, bytes) else k): json.loads(v)
                                       for k, v in (redis.hgetall("orchestra:learning:last") or {}).items()}, {})
    extras["pattern_no_data"] = safe(lambda: jget("pattern_learning:no_data"))
    extras["paper_last"] = safe(lambda: jget("paper_trading:last_cycle"))
    today = datetime.fromtimestamp(now, KST).date().isoformat()
    extras["council_today"] = safe(lambda: bool(redis.exists(f"council:day:{today}")), False)

    def _verdict():
        from app.workers.verdict_report_worker import latest_report
        r = latest_report(redis)
        return {"day": r["day"], "kind": r["kind"]} if r else None
    extras["verdict_latest"] = safe(_verdict)

    def _counts():
        keys = hour_keys(now)
        pipe = redis.pipeline(transaction=False)
        for k in keys:
            pipe.hgetall(JOB_RUNS_PREFIX + k)
        for k in keys:
            pipe.hgetall(JOB_ERRS_PREFIX + k)
        res = pipe.execute()
        return parse_counts(res[:len(keys)], res[len(keys):])
    counts24 = safe(_counts)
    next_runs = safe(lambda: parse_next_runs(redis.hgetall(JOB_NEXT_KEY)))
    return build(recs=recs, extras=extras, now=now, counts24=counts24, next_runs=next_runs)

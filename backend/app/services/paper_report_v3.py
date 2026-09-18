"""📊 Fix 370 (2026-09-14) — 가상 매매 학습 보고서 v3. 리드의 9/14 분석이 지목한 옛 보고서
(`paper_trading_worker.build_report_from_db` → `PT.build_report`) 4대 결함을 고친다:

  1. 메모리 — `select(PaperTrade)` 로 전 건을 ORM 객체로 읽어 2코어 VPS 에서 1.8GB 를 먹었다.
     → 여기서는 스칼라 컬럼(id/symbol/side/rule/opened_at/status/tags)과 JSONB 경로 값만
     `.astext` 로 뽑는다. `engines`·`snapshot` 전체 컬럼은 절대 select 하지 않는다(추가 lot 은
     `adds` 컬럼만 별도로 가볍게 읽는다 — 한 건당 변형 5개 × lot 최대 2개라 작다).
  2. 기간 혼합 — `source=backfill`(다른 강세장 3주를 재생한 10만 건)과 `source=live`(실시간
     ~1만 건)를 섞어서 채택 문턱을 계산했다. → 이 모듈은 **live 만** 본다. backfill 은
     `context`(참고)로만 노출한다.
  3. 기준선 왜곡 — 전체 기간 무작위 진입과 비교해 시장 방향이 Δ 를 지배했다(규칙 일평균이
     기준선과 0.90~0.97 상관). → 같은 `WINDOW_HOURS`(6시간) 창의 baseline_LONG/SHORT 행과만
     비교한다(그 창에 표본이 모자라면 그 날 전체로 물러난다 — `MIN_BUCKET_BASE`).
  4. 중복 계산 — 같은 심볼·같은 시간에 여러 규칙이 동시에 발동하면 서로 다른 독립 표본처럼
     세었다. → t 통계의 표준오차 분모를 표본수가 아니라 **심볼×시간(1시간) 클러스터 수**로
     나눠, 같은 클러스터의 중복 발동이 유의성을 부풀리지 못하게 한다.

추가로 **사전등록**: 새 청산 변형(Fix 370 EXIT_VARIANTS)·새 진입 필터는 이 파일이 도입된 시각
(`PREREG_AT_DEFAULT`, 설정키 `paper_prereg_at` 로 덮어쓸 수 있다) **이후에 열린 표본에서만**
채택 여부를 판단한다 — 오늘 분석으로 고른 값을 같은 오늘 데이터로 검증하면 과적합이다.

이 파일은 매매 판정을 하지 않는다(주문·손절·자본 계산 없음) — 실시간 자동에 아무것도 걸지 않는
**읽기 전용 분석 보고서**다. 숫자는 전부 모듈 상수(「Claude가 정함」)이고 설정키로 덮을 수 있는
것은 그렇게 표시했다.

엔진/워커: app/services/paper_trading.py(PT, 리드가 관리) / app/workers/paper_trading_worker.py.
옛 보고서(app/services/paper_trading.py 의 build_report / render_markdown)는 그대로 둔다 — 고정
테스트가 있고 `/paper-trading/report/legacy` 로 계속 노출한다.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from sqlalchemy import Float, cast, func, select

from app.models.paper_trade import PaperTrade
from app.services import paper_trading as PT

# ── 숫자 (Claude 가 정함 — 설정키로 덮을 수 있다) ──────────────────────────────
WINDOW_HOURS = 6                 # 기준선 비교 창 — 같은 6시간 안의 baseline_LONG/SHORT 행과만 비교
MIN_BUCKET_BASE = 10             # 창 안 기준선 표본이 이 미만이면 그 날 전체로 물러난다(그래도 모자라면 no_base)

ADOPT_MIN_CLUSTERS = 300         # 채택 최소 심볼×시간 클러스터 수 (중복 발동을 하나로 센 뒤)
ADOPT_MIN_T = 2.0                # 채택 최소 t (클러스터 표준오차 기준)
ADOPT_MIN_DAYS = 7               # 채택 최소 날짜 수
GATE_MIN_DAY_SHARE = 0.7         # 필터 채택 — 「채택군 평균이 더 좋았던 날」 비율 최소치

PREREG_SETTING_KEY = "paper_prereg_at"                         # system_settings 오버라이드 키
PREREG_AT_DEFAULT = "2026-09-15T00:00:00+00:00"                # Fix 370 배포 다음날부터 — 오늘 데이터로 고른 값을 오늘 표본으로 검증하지 않는다

# Fix 370 (2026-09-14 분석) 사전 등록 「약한 규칙」 — P1 필터가 이 값을 걸러본다(관측 weak_flag 와는 별개, 고정 목록)
WEAK_RULES: dict[str, set[str]] = {
    "LONG": {"surge_start_346", "mach7_trap_long"},
    "SHORT": {"s1_breakdown", "off8_267", "fujimoto_s1_rsi", "mach7_trap_short"},
}

SIDES: tuple[str, ...] = ("LONG", "SHORT")
_TP1_CHECKED_ENGINES = ("live", "live_sl15") + tuple(PT.EXIT_VARIANT_ENGINES)  # 이 엔진들만 TP1=15 고정 가정을 확인한다
_AMBIG_ARM_ENGINES = ("live_be10", "live_lock5")   # 리드 지시(2026-09-14): PROTECT 무장이 같은 봉 비관적 가정으로 됐는지


# ══════════════════════════════════════════════════════════════════════
# 시각 도구
# ══════════════════════════════════════════════════════════════════════

def parse_prereg_at(value: str | datetime) -> datetime:
    """ISO 문자열 또는 datetime → tz-aware UTC datetime. 실패하면 호출자가 기본값으로 재시도한다."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = str(value).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def resolve_prereg_at(db: Any) -> datetime:
    """system_settings 키 `paper_prereg_at` 오버라이드, 없거나 파싱 실패면 `PREREG_AT_DEFAULT`.
    이 값은 종목/표본을 거르는 분석 판단이지 자금이 나가는 판정이 아니다 — 실패해도 기본값으로 계속 진행(fail-open)."""
    raw: str | None = None
    if db is not None:
        try:
            from app.models.system_setting import SystemSetting

            row = db.get(SystemSetting, PREREG_SETTING_KEY)
            if row is not None and row.value:
                raw = str(row.value).strip() or None
        except Exception:  # noqa: BLE001
            raw = None
    try:
        return parse_prereg_at(raw or PREREG_AT_DEFAULT)
    except Exception:  # noqa: BLE001
        return parse_prereg_at(PREREG_AT_DEFAULT)


def _cutoff(days: int, *, now: datetime | None = None) -> datetime:
    return (now or datetime.now(timezone.utc)) - timedelta(days=days)


# ══════════════════════════════════════════════════════════════════════
# 로더 — 메모리 가벼운 스칼라 쿼리 (ORM 전체 로딩 금지 · engines/snapshot 전체 컬럼 금지)
# ══════════════════════════════════════════════════════════════════════

def load_live_rows(db: Any, *, days: int = 30) -> list[dict[str, Any]]:
    """실시간(source=live) CLOSED 행을 스칼라 컬럼 + JSONB 경로 값만 골라 가볍게 읽는다.
    반환 = 작은 dict 목록(파싱된 float/bool, 없으면 None) — ORM 객체가 아니다."""
    cutoff = _cutoff(days)
    engine_names = tuple(PT.ENGINES) + tuple(PT.LEGACY_ENGINES)
    cols: list[Any] = [PaperTrade.id, PaperTrade.symbol, PaperTrade.side, PaperTrade.rule,
                       PaperTrade.opened_at, PaperTrade.status, PaperTrade.tags]
    for name in engine_names:
        base = PaperTrade.engines[name]
        cols.append(cast(base["roi"].astext, Float).label(f"eng_{name}_roi"))
        cols.append(base["hit"].astext.label(f"eng_{name}_hit"))
        cols.append(base["done"].astext.label(f"eng_{name}_done"))
        cols.append(cast(base["tp1_pct"].astext, Float).label(f"eng_{name}_tp1_pct"))
        if name in _AMBIG_ARM_ENGINES:
            # 리드 지시: 같은 봉 안에서 고·저 순서를 모른 채(비관적 가정) PROTECT 를 무장했는지 — be10/lock5 만 갖는 값
            cols.append(base["ambig_arm"].astext.label(f"eng_{name}_ambig_arm"))
    cols.append(cast(PaperTrade.snapshot["dist_high5d_pct"].astext, Float).label("dist_high5d_pct"))
    # 🎯 Fix 375: 차트 자리 게이트(P5·P6) 판정값 — chart_state 의 from_hi_pct 는 Fix 375 배포 뒤 행에만 있다 = 새 표본만 판정
    _cs = PaperTrade.snapshot["chart_state"]
    cols.append(cast(_cs["h1"]["from_hi_pct"].astext, Float).label("g_h1_from_hi"))
    cols.append(cast(_cs["m5"]["from_hi_pct"].astext, Float).label("g_m5_from_hi"))
    # 🎚 Fix 378 (사전등록 2026-09-18): 미세조정 후보 P8·P9·P10 이 보는 값
    cols.append(cast(_cs["h1"]["atr14_pct"].astext, Float).label("g_h1_atr"))
    cols.append(cast(_cs["h4"]["bb"]["bars_since_below_lower"].astext, Float).label("g_h4_since_lower"))
    cols.append(cast(_cs["d1"]["pctb"].astext, Float).label("g_d1_pctb"))
    cols.append(_cs["d1"]["bb"]["trend"].astext.label("g_d1_trend"))
    cols.append(cast(PaperTrade.chg_24h, Float).label("g_chg24"))

    stmt = (
        select(*cols)
        .where(PaperTrade.source == "live", PaperTrade.status == "CLOSED", PaperTrade.opened_at >= cutoff)
        .execution_options(yield_per=1000)
    )
    out: list[dict[str, Any]] = []
    for row in db.execute(stmt):
        m = row._mapping
        engines: dict[str, dict[str, Any]] = {}
        for name in engine_names:
            roi = m[f"eng_{name}_roi"]
            done_raw = m[f"eng_{name}_done"]
            tp1 = m[f"eng_{name}_tp1_pct"]
            ambig_raw = m[f"eng_{name}_ambig_arm"] if name in _AMBIG_ARM_ENGINES else None
            engines[name] = {
                "roi": float(roi) if roi is not None else None,
                "hit": m[f"eng_{name}_hit"],
                "done": None if done_raw is None else (str(done_raw).lower() == "true"),
                "tp1_pct": float(tp1) if tp1 is not None else None,
                "ambig_arm": None if ambig_raw is None else (str(ambig_raw).lower() == "true"),
            }
        dh5 = m["dist_high5d_pct"]
        gate = {"h1_from_hi": m["g_h1_from_hi"], "m5_from_hi": m["g_m5_from_hi"],
                "d1_trend": m["g_d1_trend"], "chg24": m["g_chg24"],
                "h1_atr": m["g_h1_atr"], "h4_since_lower": m["g_h4_since_lower"], "d1_pctb": m["g_d1_pctb"]}
        out.append({
            "id": m["id"], "symbol": m["symbol"], "side": m["side"], "rule": m["rule"],
            "opened_at": m["opened_at"], "status": m["status"], "tags": list(m["tags"] or []),
            "dist_high5d_pct": float(dh5) if dh5 is not None else None,
            "gate": gate,
            "engines": engines,
        })
    return out


def load_add_lots(db: Any, *, days: int = 30) -> list[tuple[str, str, datetime, str, float, float]]:
    """추가(피라미딩) lot — `adds` 컬럼만 읽어 (side, rule, opened_at, variant, roi, pnl_usdt) 로 펼친다."""
    cutoff = _cutoff(days)
    stmt = (
        select(PaperTrade.id, PaperTrade.side, PaperTrade.rule, PaperTrade.opened_at, PaperTrade.adds)
        .where(PaperTrade.source == "live", PaperTrade.status == "CLOSED", PaperTrade.opened_at >= cutoff)
        .execution_options(yield_per=1000)
    )
    out: list[tuple[str, str, datetime, str, float, float]] = []
    for _id, side, rule, opened_at, adds in db.execute(stmt):
        for variant, lots in (adds or {}).items():
            for lot in (lots or []):
                roi = lot.get("roi")
                if roi is None:
                    continue
                pnl = lot.get("pnl_usdt")
                out.append((side, rule, opened_at, variant, float(roi), float(pnl) if pnl is not None else 0.0))
    return out


def sql_context(db: Any, *, days: int = 30) -> dict[str, Any]:
    """SQL 집계만(ORM 로딩 없음) — backfill 참고치 + 열린 실시간 건(검열 편향 지표), 방향별."""
    cutoff = _cutoff(days)
    roi_expr = cast(PaperTrade.engines["live"]["roi"].astext, Float)

    def _grouped(where_clause) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        rows = db.execute(select(PaperTrade.side, func.count(), func.avg(roi_expr)).where(*where_clause)
                          .group_by(PaperTrade.side)).all()
        for side, n, avg in rows:
            out[side] = {"n": int(n), "avg_roi": round(float(avg), 3) if avg is not None else None}
        return out

    backfill = _grouped((PaperTrade.source == "backfill", PaperTrade.status == "CLOSED", PaperTrade.opened_at >= cutoff))
    open_live = _grouped((PaperTrade.source == "live", PaperTrade.status == "OPEN"))
    return {"backfill": backfill, "open_live": open_live}


# ══════════════════════════════════════════════════════════════════════
# 순수 통계 도구 (DB 없음)
# ══════════════════════════════════════════════════════════════════════

def is_engine_valid(edata: Mapping[str, Any] | None, engine: str) -> bool:
    """엔진 E 값 하나가 통계에 쓸 만큼 유효한가 — roi 있음 + done + (live/live_sl15/청산변형은 TP1 15 고정
    가정도 확인, v1 적응 TP(3) 등 다른 정의로 계산된 옛 값은 걸러낸다). house/레거시 엔진은 TP1 확인 없음."""
    if not edata:
        return False
    if edata.get("roi") is None:
        return False
    if not edata.get("done"):
        return False
    if engine in _TP1_CHECKED_ENGINES:
        tp1 = edata.get("tp1_pct")
        if tp1 is not None and float(tp1) != PT.TP1_FLAT:
            return False
    return True


def bucket_of(opened_at: datetime) -> tuple[Any, int]:
    """(UTC 날짜, WINDOW_HOURS 시간 구간) — 기준선 비교 창."""
    return (opened_at.date(), opened_at.hour // WINDOW_HOURS)


def hour_cluster_of(row: Mapping[str, Any]) -> tuple[str, datetime]:
    """(심볼, 시(hour) 단위 절삭 시각) — 같은 심볼·같은 시간에 여러 규칙이 겹쳐 뜬 것을 하나로 묶는 클러스터 키."""
    oa = row["opened_at"]
    return (row["symbol"], oa.replace(minute=0, second=0, microsecond=0))


def _t_stat(values: Sequence[float], clusters: int) -> float | None:
    """t = mean(values) / (pstdev(values) / sqrt(clusters)) — 표본수가 아니라 **클러스터 수**로 나눠
    같은 심볼×시간의 중복 발동이 유의성을 부풀리지 못하게 한다(9/14 분석 결함 4)."""
    if len(values) < 2 or clusters <= 0:
        return None
    sd = statistics.pstdev(values)
    denom = sd / math.sqrt(clusters)
    if denom <= 1e-12:
        return None
    return round(statistics.fmean(values) / denom, 3)


def _half_by_date(rows: Sequence[Mapping[str, Any]], values: Sequence[float]) -> dict[str, float | None]:
    """distinct 날짜를 정렬해 앞 절반/뒤 절반으로 나누고 그 절반에 속한 값들의 평균(없으면 None)."""
    dates = sorted({r["opened_at"].date() for r in rows})
    if not dates:
        return {"first": None, "second": None}
    mid = len(dates) // 2
    first_dates, second_dates = set(dates[:mid]), set(dates[mid:])
    first_vals = [v for r, v in zip(rows, values) if r["opened_at"].date() in first_dates]
    second_vals = [v for r, v in zip(rows, values) if r["opened_at"].date() in second_dates]
    return {"first": round(statistics.fmean(first_vals), 4) if first_vals else None,
            "second": round(statistics.fmean(second_vals), 4) if second_vals else None}


def _stats(valid_rows: list[dict[str, Any]], base_fn) -> dict[str, Any]:
    """valid_rows = 이미 엔진 E 로 유효성 확인된 (roi/symbol/opened_at 을 가진) 행. base_fn(row) = 그 행의
    기준선(없으면 None — no_base 로 세고 **조정(adj/t/half) 통계에서만** 뺀다).

    `clusters`/`days` 는 **전체 유효 행**(raw n) 기준이다 — 필터(c) 의 채택 문턱("kept 클러스터 ≥ 300")은
    기준선 유무와 무관하게 kept 표본 자체의 다양성을 묻는 것이라 baseline 유무로 깎이면 안 된다. 반면
    `adj`/`t`/`half` 는 기준선이 있는 행만으로 계산하고, t 의 표준오차 분모는 그 부분집합의 클러스터 수를
    쓴다(결함4: 같은 심볼×시간 중복이 유의성을 부풀리지 않게) — 그 값은 따로 노출하지 않고 t 계산에만 쓴다."""
    n = len(valid_rows)
    if n == 0:
        return {"n": 0, "no_base": 0, "clusters": 0, "days": 0, "mean": None, "win": None,
                "adj": None, "t": None, "half": {"first": None, "second": None}}
    rois = [r["roi"] for r in valid_rows]
    mean = round(statistics.fmean(rois), 4)
    win = round(100.0 * sum(1 for x in rois if x > 0) / n, 2)
    clusters = len({hour_cluster_of(r) for r in valid_rows})
    days = len({r["opened_at"].date() for r in valid_rows})
    based_rows: list[dict[str, Any]] = []
    adj_vals: list[float] = []
    no_base = 0
    for r in valid_rows:
        b = base_fn(r)
        if b is None:
            no_base += 1
            continue
        based_rows.append(r)
        adj_vals.append(r["roi"] - b)
    base_clusters = len({hour_cluster_of(r) for r in based_rows})
    adj = round(statistics.fmean(adj_vals), 4) if adj_vals else None
    t = _t_stat(adj_vals, base_clusters)
    half = _half_by_date(based_rows, adj_vals)
    return {"n": n, "no_base": no_base, "clusters": clusters, "days": days, "mean": mean, "win": win,
            "adj": adj, "t": t, "half": half}


def make_baseline_fn(baseline_rows: Sequence[Mapping[str, Any]], engine: str):
    """같은 방향의 baseline_LONG/SHORT 행에서 (버킷/날짜)별 유효 roi 평균을 미리 인덱싱한 base(row) 함수를 만든다."""
    bucket_idx: dict[tuple, list[float]] = defaultdict(list)
    day_idx: dict[Any, list[float]] = defaultdict(list)
    for r in baseline_rows:
        edata = (r.get("engines") or {}).get(engine)
        if not is_engine_valid(edata, engine):
            continue
        bucket_idx[bucket_of(r["opened_at"])].append(edata["roi"])
        day_idx[r["opened_at"].date()].append(edata["roi"])

    def base_fn(row: Mapping[str, Any]) -> float | None:
        b = bucket_idx.get(bucket_of(row["opened_at"]))
        if b is not None and len(b) >= MIN_BUCKET_BASE:
            return statistics.fmean(b)
        d = day_idx.get(row["opened_at"].date())
        if d is not None and len(d) >= MIN_BUCKET_BASE:
            return statistics.fmean(d)
        return None

    return base_fn


# ══════════════════════════════════════════════════════════════════════
# a) 규칙
# ══════════════════════════════════════════════════════════════════════

def _rules_section(side_rows: list[dict[str, Any]], side: str, base_fn) -> dict[str, Any]:
    by_rule: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in side_rows:
        edata = (r.get("engines") or {}).get("live")
        if is_engine_valid(edata, "live"):
            by_rule[r["rule"]].append({"roi": edata["roi"], "symbol": r["symbol"], "opened_at": r["opened_at"]})
    weak_set = WEAK_RULES.get(side, set())
    out: dict[str, Any] = {}
    for rule, rows in by_rule.items():
        st = _stats(rows, base_fn)
        adopt = (st["clusters"] >= ADOPT_MIN_CLUSTERS and st["days"] >= ADOPT_MIN_DAYS
                 and st["adj"] is not None and st["adj"] > 0
                 and st["t"] is not None and st["t"] >= ADOPT_MIN_T
                 and st["half"]["first"] is not None and st["half"]["first"] > 0
                 and st["half"]["second"] is not None and st["half"]["second"] > 0)
        weak_flag = (st["adj"] is not None and st["adj"] < 0
                    and st["t"] is not None and st["t"] <= -ADOPT_MIN_T)
        out[rule] = {**st, "adopt": bool(adopt), "weak_flag": bool(weak_flag), "pre_flagged_weak": rule in weak_set}
    return out


# ══════════════════════════════════════════════════════════════════════
# b) 청산 변형 — live 대비 짝 비교(diff)
# ══════════════════════════════════════════════════════════════════════

def _exit_stats(pairs: list[dict[str, Any]], *, legacy: bool) -> dict[str, Any]:
    """채택 판정은 diff(변형−live 평균차)·t·전후 반쪽만 본다 — 승률은 참고용(리드 지시 2026-09-14):
    live_be10 의 본전(ROI 0.0) 청산은 손실은 아니지만 승리로 세면 안 되므로 win 계산에 넣지 않는 게 맞고,
    실제로 win% 은 여기서도 계산은 하지만 `adopt` 판정에는 절대 쓰지 않는다."""
    n = len(pairs)
    if n == 0:
        return {"n": 0, "clusters": 0, "days": 0, "mean_live": None, "mean_variant": None, "diff": None,
                "t": None, "half": {"first": None, "second": None}, "hits": {}, "win": None,
                "ambig_n": 0, "ambig_share": None, "legacy": legacy, "adopt": False}
    clusters = len({hour_cluster_of(p) for p in pairs})
    days = len({p["opened_at"].date() for p in pairs})
    mean_live = round(statistics.fmean(p["live_roi"] for p in pairs), 4)
    mean_variant = round(statistics.fmean(p["var_roi"] for p in pairs), 4)
    diffs = [p["roi"] for p in pairs]
    diff = round(statistics.fmean(diffs), 4)
    t = _t_stat(diffs, clusters)
    half = _half_by_date(pairs, diffs)
    hits: dict[str, int] = {}
    for p in pairs:
        hk = str(p.get("hit"))
        hits[hk] = hits.get(hk, 0) + 1
    win = round(100.0 * sum(1 for p in pairs if p["var_roi"] > 0) / n, 2)          # 참고용 — adopt 에 쓰지 않는다
    protect_n = hits.get("PROTECT", 0)
    ambig_n = sum(1 for p in pairs if p.get("ambig_arm") is True)
    ambig_share = round(ambig_n / protect_n, 4) if protect_n > 0 else None
    adopt = (not legacy and clusters >= ADOPT_MIN_CLUSTERS and days >= ADOPT_MIN_DAYS and diff > 0
             and t is not None and t >= ADOPT_MIN_T
             and half["first"] is not None and half["first"] > 0
             and half["second"] is not None and half["second"] > 0)
    return {"n": n, "clusters": clusters, "days": days, "mean_live": mean_live, "mean_variant": mean_variant,
            "diff": diff, "t": t, "half": half, "hits": hits, "win": win, "ambig_n": ambig_n,
            "ambig_share": ambig_share, "legacy": legacy, "adopt": bool(adopt)}


def _exits_section(side_rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    variants = ("live_sl15",) + tuple(PT.EXIT_VARIANT_ENGINES)
    for variant in variants:
        pairs = []
        for r in side_rows:
            engines = r.get("engines") or {}
            live_e, var_e = engines.get("live"), engines.get(variant)
            if is_engine_valid(live_e, "live") and is_engine_valid(var_e, variant):
                pairs.append({"roi": var_e["roi"] - live_e["roi"], "live_roi": live_e["roi"], "var_roi": var_e["roi"],
                             "symbol": r["symbol"], "opened_at": r["opened_at"], "hit": var_e.get("hit"),
                             "ambig_arm": var_e.get("ambig_arm")})
        out[variant] = _exit_stats(pairs, legacy=False)
    for variant in PT.LEGACY_ENGINES:
        pairs = []
        for r in side_rows:
            engines = r.get("engines") or {}
            live_e, var_e = engines.get("live"), engines.get(variant)
            if var_e is None:
                continue
            if is_engine_valid(live_e, "live") and is_engine_valid(var_e, variant):
                pairs.append({"roi": var_e["roi"] - live_e["roi"], "live_roi": live_e["roi"], "var_roi": var_e["roi"],
                             "symbol": r["symbol"], "opened_at": r["opened_at"], "hit": var_e.get("hit"),
                             "ambig_arm": var_e.get("ambig_arm")})
        if pairs:
            out[variant] = _exit_stats(pairs, legacy=True)
    return out


# ══════════════════════════════════════════════════════════════════════
# c) 진입 필터 — 사전등록 4종
# ══════════════════════════════════════════════════════════════════════

def _to_stat_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"roi": r["engines"]["live"]["roi"], "symbol": r["symbol"], "opened_at": r["opened_at"], "id": r.get("id")}
            for r in rows]


def _day_edge(kept_rows: list[dict[str, Any]], excluded_rows: list[dict[str, Any]]) -> dict[str, int]:
    """kept·excluded 모두 ≥10건인 날만 세어 그날 kept 평균이 더 좋았던 날 수(긍정일) / 함께있는 날 수."""
    kept_by_day: dict[Any, list[float]] = defaultdict(list)
    exc_by_day: dict[Any, list[float]] = defaultdict(list)
    for r in kept_rows:
        kept_by_day[r["opened_at"].date()].append(r["roi"])
    for r in excluded_rows:
        exc_by_day[r["opened_at"].date()].append(r["roi"])
    days_with_both = positive_days = 0
    for d in set(kept_by_day) & set(exc_by_day):
        k, e = kept_by_day[d], exc_by_day[d]
        if len(k) >= 10 and len(e) >= 10:
            days_with_both += 1
            if statistics.fmean(k) > statistics.fmean(e):
                positive_days += 1
    return {"days_with_both": days_with_both, "positive_days": positive_days}


# 필터마다 사전등록 시각이 다르다 — 그 조건을 고를 때 본 행은 판정에서 뺀다 (자기확인 금지).
#   P5·P6 = Fix 375(9/17) · P7 = Fix 377(9/18) · P8·P9·P10 = Fix 378(9/18) 에 골랐다.
#   차트 값이 기록되기 시작한 시점과 무관하게, **고른 날 자정 이후에 열린 행만** 센다.
FILTER_PREREG: dict[str, str] = {
    "P5_short_near_high_not_d1_up": "2026-09-17T00:00:00+00:00",
    "P6_long_after_drop_or_pullback": "2026-09-17T00:00:00+00:00",
    "P7_long_no_high_chase": "2026-09-19T00:00:00+00:00",
    "P8_short_calm_hour": "2026-09-19T00:00:00+00:00",
    "P9_short_not_after_breakdown": "2026-09-19T00:00:00+00:00",
    "P10_long_gate_or_low_band": "2026-09-19T00:00:00+00:00",
}


def _filter_result(universe: list[dict[str, Any]], kept: list[dict[str, Any]], excluded: list[dict[str, Any]],
                   base_fn, *, name: str | None = None) -> dict[str, Any]:
    since = FILTER_PREREG.get(name or "")
    if since:
        cut = parse_prereg_at(since)
        universe = [r for r in universe if r["opened_at"] >= cut]
        kept = [r for r in kept if r["opened_at"] >= cut]
        excluded = [r for r in excluded if r["opened_at"] >= cut]
    kept_rows, excl_rows, univ_rows = _to_stat_rows(kept), _to_stat_rows(excluded), _to_stat_rows(universe)
    kept_stats, excl_stats, univ_stats = _stats(kept_rows, base_fn), _stats(excl_rows, base_fn), _stats(univ_rows, base_fn)
    day_edge = _day_edge(kept_rows, excl_rows)
    share = (day_edge["positive_days"] / day_edge["days_with_both"]) if day_edge["days_with_both"] > 0 else 0.0
    adopt = (kept_stats["clusters"] >= ADOPT_MIN_CLUSTERS and day_edge["days_with_both"] >= ADOPT_MIN_DAYS
             and share >= GATE_MIN_DAY_SHARE and kept_stats["mean"] is not None and excl_stats["mean"] is not None
             and kept_stats["mean"] > excl_stats["mean"])
    return {"universe": univ_stats, "kept": kept_stats, "excluded": excl_stats, "day_edge": day_edge,
            "adopt": bool(adopt), "since": FILTER_PREREG.get(name or "")}


# 🎚 Fix 378 미세조정 후보의 숫자 (모두 「Claude가 정함」 — 가상 분석에서 고른 값, 판정은 7일 표본으로)
TUNE: dict[str, float] = {
    "short_max_atr_1h_pct": 1.5,            # P8: 1시간 ATR 이 이 이하일 때만
    "short_min_bars_since_h4_lower": 14.0,  # P9: 4시간 하단 밖 종가 이후 이 봉 수 이상 지났을 때만
    "long_max_d1_pctb": 0.5,                # P10: 일봉 %B 가 이 이하(하단권)일 때만 P7 가지를 쓴다
}


def _gate_snapshot(r: Mapping[str, Any]) -> dict[str, Any]:
    """보고서 행의 게이트 값 → entry_conditions 가 읽는 snapshot 모양."""
    g = r.get("gate") or {}
    return {"chart_state": {"h1": {"from_hi_pct": g.get("h1_from_hi")}, "m5": {"from_hi_pct": g.get("m5_from_hi")},
                            "d1": {"bb": {"trend": g.get("d1_trend")}}}}


def _filters_section(side_rows: list[dict[str, Any]], side: str, base_fn) -> dict[str, Any]:
    live_valid = [r for r in side_rows if is_engine_valid((r.get("engines") or {}).get("live"), "live")]
    out: dict[str, Any] = {}

    # P1: 사전등록 「약한 규칙」 제외
    weak_set = WEAK_RULES.get(side, set())
    kept = [r for r in live_valid if r["rule"] not in weak_set]
    excluded = [r for r in live_valid if r["rule"] in weak_set]
    out["P1_drop_weak_rules"] = _filter_result(live_valid, kept, excluded, base_fn)

    if side == "SHORT":
        # P2: 시장 국면 태그(MKT_*)가 있는 행 중 MKT_DOWN 이면 제외. 태그 자체가 없는 옛 행(9/10 이전)은 universe 밖.
        universe = [r for r in live_valid if any(str(t).startswith("MKT_") for t in (r.get("tags") or []))]
        kept = [r for r in universe if "MKT_DOWN" not in (r.get("tags") or [])]
        excluded = [r for r in universe if "MKT_DOWN" in (r.get("tags") or [])]
        out["P2_short_skip_mkt_down"] = _filter_result(universe, kept, excluded, base_fn)

    if side == "LONG":
        # P3: 5일 고점 대비 되돌림이 숫자로 기록된 행 중 −10% 이하(깊은 조정)만 유지
        universe = [r for r in live_valid if r.get("dist_high5d_pct") is not None]
        kept = [r for r in universe if r["dist_high5d_pct"] <= -10.0]
        excluded = [r for r in universe if r["dist_high5d_pct"] > -10.0]
        out["P3_long_deep_pullback"] = _filter_result(universe, kept, excluded, base_fn)

    # P5·P6 (Fix 375, 사전등록 2026-09-17): 차트 자리 게이트. from_hi_pct 가 기록된 행(= 배포 뒤 새 행)만 universe.
    #   조건은 9/9~9/16 재계산 분석에서 골랐다 — 그 행들에는 이 값이 없으므로 여기 판정은 전부 새 표본이다.
    from app.services import entry_conditions as _EC
    if side == "SHORT":
        universe = [r for r in live_valid if (r.get("gate") or {}).get("h1_from_hi") is not None
                    and (r.get("gate") or {}).get("d1_trend")]
        kept = [r for r in universe if _EC.evaluate("SHORT", _gate_snapshot(r))["verdict"] == "pass"]
        excluded = [r for r in universe if _EC.evaluate("SHORT", _gate_snapshot(r))["verdict"] != "pass"]
        out["P5_short_near_high_not_d1_up"] = _filter_result(universe, kept, excluded, base_fn, name="P5_short_near_high_not_d1_up")

        # 🎚 Fix 378 미세조정 후보 (사전등록 2026-09-18 · 가상 SHORT 11,257건에서 두 기간 모두 통과 쪽이 나았다)
        #   P8 = P5 + 1시간 변동성 낮음 (발견 ex +1.67 vs −0.71 · 검증 +0.75 vs −1.41)
        #   P9 = P5 + 4시간 하단이탈 뒤 14봉 지남 = 급락 직후 추격 금지
        #        (값이 있는 행만 universe: 발견 통과 15% ex +2.35 vs +0.12 · 검증 20% +2.24 vs −2.25 · 검증 5/5일)
        #   ⚠️ h4_since_lower 가 None = 「최근 60봉 안에 하단 이탈이 아예 없었다」(SHORT 행의 38%).
        #      취지상 통과처럼 보이지만 실측은 발견 +2.79 / 검증 −0.62 로 뒤집혔다 → universe 에서 뺀다(통과도 제외도 아님).
        pass_ids = {r["id"] for r in universe if _EC.evaluate("SHORT", _gate_snapshot(r))["verdict"] == "pass"}
        for name, field, ok in (("P8_short_calm_hour", "h1_atr",
                                 lambda v: v <= TUNE["short_max_atr_1h_pct"]),
                                ("P9_short_not_after_breakdown", "h4_since_lower",
                                 lambda v: v >= TUNE["short_min_bars_since_h4_lower"])):
            uu = [r for r in universe if (r.get("gate") or {}).get(field) is not None]
            kk = [r for r in uu if r["id"] in pass_ids and ok(r["gate"][field])]
            kept_ids = {r["id"] for r in kk}
            out[name] = _filter_result(uu, kk, [r for r in uu if r["id"] not in kept_ids], base_fn, name=name)
    if side == "LONG":
        # P7 (Fix 377, 사전등록 2026-09-18): 고점 바로 밑 추격 금지 · 24h 과열(≥20) 금지 · 24h 0~5% 미동 제외.
        # (아래 _p7 은 P10 도 쓴다)
        #   근거 = 가상 LONG 규칙 합산 발견 +0.25 vs 막힘 −0.90 · 검증 +0.90 vs +0.10 (t 4.0) · 상승 초입 LONG 은 검증 5/5일.
        #   ⚠️ 무작위 LONG 에서는 발견 기간에 반대였다 → 규칙 진입에만 건다(가족 전용 조건은 entry_conditions.FAMILY_RULES).
        universe = [r for r in live_valid if (r.get("gate") or {}).get("h1_from_hi") is not None
                    and (r.get("gate") or {}).get("chg24") is not None]
        def _p7(r):
            g = r["gate"]
            hi, chg = g["h1_from_hi"], g["chg24"]
            return hi <= -1.5 and chg < 20.0 and not (0.0 <= chg < 5.0)
        kept = [r for r in universe if _p7(r)]
        excluded = [r for r in universe if not _p7(r)]
        out["P7_long_no_high_chase"] = _filter_result(universe, kept, excluded, base_fn, name="P7_long_no_high_chase")

        # 🎚 Fix 378 미세조정 후보 P10 = 지금 LONG 게이트 **또는** (고점추격 아님 + 일봉 하단권)
        #   가상 LONG 11,088건: 발견 ex +0.34 vs 막힘 −0.86 · 검증 +1.25 vs −0.21 (통과 비중 48~53%)
        u10 = [r for r in universe if (r.get("gate") or {}).get("d1_pctb") is not None
               and (r.get("gate") or {}).get("m5_from_hi") is not None]
        def _p10(r):
            g = r["gate"]
            gate_ok = _EC.evaluate("LONG", _gate_snapshot(r), chg_24h=g.get("chg24"))["verdict"] == "pass"
            return gate_ok or (_p7(r) and g["d1_pctb"] <= TUNE["long_max_d1_pctb"])
        k10 = [r for r in u10 if _p10(r)]
        out["P10_long_gate_or_low_band"] = _filter_result(u10, k10, [r for r in u10 if not _p10(r)], base_fn,
                                                          name="P10_long_gate_or_low_band")

        universe = [r for r in live_valid if (r.get("gate") or {}).get("m5_from_hi") is not None]
        kept = [r for r in universe if _EC.evaluate("LONG", _gate_snapshot(r), chg_24h=r["gate"].get("chg24"))["verdict"] == "pass"]
        excluded = [r for r in universe if _EC.evaluate("LONG", _gate_snapshot(r), chg_24h=r["gate"].get("chg24"))["verdict"] != "pass"]
        out["P6_long_after_drop_or_pullback"] = _filter_result(universe, kept, excluded, base_fn,
                                                               name="P6_long_after_drop_or_pullback")

    # P4: 같은 (심볼, 방향, 시간) 에 규칙이 여러 개 겹치면 (진입시각, id) 순으로 첫 건만 유지
    ordered = sorted(live_valid, key=lambda r: (r["opened_at"], r["id"]))
    seen: set[tuple] = set()
    kept, excluded = [], []
    for r in ordered:
        key = (r["symbol"], side, r["opened_at"].replace(minute=0, second=0, microsecond=0))
        if key in seen:
            excluded.append(r)
        else:
            seen.add(key)
            kept.append(r)
    out["P4_first_rule_per_hour"] = _filter_result(live_valid, kept, excluded, base_fn)
    return out


# ══════════════════════════════════════════════════════════════════════
# d) 추가(피라미딩) lot — 정보용, 채택 없음(기간 의존적)
# ══════════════════════════════════════════════════════════════════════

def _adds_section(lots: list[tuple[str, str, datetime, str, float, float]]) -> dict[str, Any]:
    idx: dict[tuple[str, str], list[tuple[datetime, float, float]]] = defaultdict(list)
    for side, _rule, opened_at, variant, roi, pnl in lots:
        idx[(variant, side)].append((opened_at, roi, pnl))
    out: dict[str, Any] = {}
    for variant in PT.VARIANTS:
        out[variant] = {}
        for side in SIDES:
            items = idx.get((variant, side), [])
            n = len(items)
            if n == 0:
                out[variant][side] = {"n": 0, "mean": None, "win": None, "pnl_sum": 0.0,
                                      "half": {"first": None, "second": None}}
                continue
            rois = [roi for _, roi, _ in items]
            mean = round(statistics.fmean(rois), 4)
            win = round(100.0 * sum(1 for x in rois if x > 0) / n, 2)
            pnl_sum = round(sum(p for _, _, p in items), 4)
            half = _half_by_date([{"opened_at": oa} for oa, _, _ in items], rois)
            out[variant][side] = {"n": n, "mean": mean, "win": win, "pnl_sum": pnl_sum, "half": half}
    return out


# ══════════════════════════════════════════════════════════════════════
# 블록(all/prereg) 조립 + 채택 목록
# ══════════════════════════════════════════════════════════════════════

def _build_block(rows: list[dict[str, Any]], lots: list[tuple[str, str, datetime, str, float, float]]) -> dict[str, Any]:
    rules: dict[str, Any] = {}
    exits: dict[str, Any] = {}
    filters: dict[str, Any] = {}
    for side in SIDES:
        baseline_rows = [r for r in rows if r["rule"] == f"baseline_{side}"]
        base_fn = make_baseline_fn(baseline_rows, "live")
        side_rows = [r for r in rows if r["side"] == side and r["rule"] not in PT.BASELINE_KEYS]
        rules[side] = _rules_section(side_rows, side, base_fn)
        exits[side] = _exits_section(side_rows)
        filters[side] = _filters_section(side_rows, side, base_fn)
    return {"rules": rules, "exits": exits, "filters": filters, "adds": _adds_section(lots),
            "n": len(rows), "days": len({r["opened_at"].date() for r in rows})}


def _collect_adoption(prereg_block: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for side in SIDES:
        for rule, st in prereg_block["rules"][side].items():
            if st.get("adopt"):
                items.append({"kind": "rule", "side": side, "name": rule, "adj": st["adj"], "t": st["t"],
                             "clusters": st["clusters"], "days": st["days"]})
        for variant, st in prereg_block["exits"][side].items():
            if st.get("adopt"):
                items.append({"kind": "exit", "side": side, "name": variant, "diff": st["diff"], "t": st["t"],
                             "clusters": st["clusters"], "days": st["days"]})
        for fname, st in prereg_block["filters"][side].items():
            if st.get("adopt"):
                items.append({"kind": "filter", "side": side, "name": fname,
                             "kept_mean": st["kept"]["mean"], "excluded_mean": st["excluded"]["mean"],
                             "clusters": st["kept"]["clusters"], "days_with_both": st["day_edge"]["days_with_both"]})
    return items


# ══════════════════════════════════════════════════════════════════════
# 진입점 — 순수 함수
# ══════════════════════════════════════════════════════════════════════

def build_report_v3(rows: list[dict[str, Any]], lots: list[tuple[str, str, datetime, str, float, float]],
                    context: Mapping[str, Any], *, prereg_at: str | datetime, now: datetime | None = None) -> dict[str, Any]:
    """rows = load_live_rows() 결과, lots = load_add_lots() 결과, context = sql_context() 결과. DB 를 만지지 않는다."""
    prereg_at = parse_prereg_at(prereg_at)
    now = now or datetime.now(timezone.utc)
    prereg_rows = [r for r in rows if r["opened_at"] >= prereg_at]
    prereg_lots = [lot for lot in lots if lot[2] >= prereg_at]

    blocks = {"all": _build_block(rows, lots), "prereg": _build_block(prereg_rows, prereg_lots)}
    adoption_items = _collect_adoption(blocks["prereg"])
    return {
        "prereg_at": prereg_at.isoformat(),
        "window_hours": WINDOW_HOURS,
        "generated_at": now.isoformat(),
        "n_live": len(rows),
        "blocks": blocks,
        "adoption": {"items": adoption_items, "prereg_at": prereg_at.isoformat(), "window_hours": WINDOW_HOURS,
                    "n_live": len(prereg_rows),
                    "days_so_far": blocks["prereg"]["days"] if blocks["prereg"]["n"] else 0},
        "context": {**dict(context or {}),
                   "warnings": ["backfill 은 다른 기간 재생 — 채택 판단에 쓰지 않음",
                                "OPEN n건 — 청산 표본은 빨리 끝난 건이 과다"]},
    }


# ══════════════════════════════════════════════════════════════════════
# markdown 렌더링
# ══════════════════════════════════════════════════════════════════════

def _f(x: Any, nd: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x:+.{nd}f}" if isinstance(x, float) else str(x)


def _half_str(half: Mapping[str, Any]) -> str:
    return f"{_f(half.get('first'))}/{_f(half.get('second'))}"


def render_markdown_v3(rep: Mapping[str, Any]) -> str:
    L: list[str] = []
    ad = rep.get("adoption") or {}
    L.append(f"# 가상 매매 보고서 v3 (Fix 370) — 실시간(live) {rep.get('n_live', 0)}건 창 "
             f"(사전등록 이후 {ad.get('n_live', 0)}건 · {ad.get('days_so_far', 0) or 0}일)")
    L.append(f"기준 = **실시간만**(source=live, backfill 은 참고) · 같은 {rep.get('window_hours', WINDOW_HOURS)}시간 창 "
             f"baseline_LONG/SHORT 무작위 대비(모자라면 그 날 전체) · 심볼×시간 클러스터(중복 발동 1건) · "
             f"채택은 사전등록(`{rep.get('prereg_at')}`) 이후 표본만.")
    L.append(f"채택 조건 — 규칙/청산: 클러스터≥{ADOPT_MIN_CLUSTERS} · 날짜≥{ADOPT_MIN_DAYS} · Δ(diff)>0 · "
             f"t≥{ADOPT_MIN_T:g} · 전/후 반쪽 모두 양수. 필터: 클러스터≥{ADOPT_MIN_CLUSTERS} · "
             f"함께있는 날짜≥{ADOPT_MIN_DAYS} · 긍정일 비율≥{GATE_MIN_DAY_SHARE:g} · 채택군 평균 > 제외군 평균.")
    L.append("")

    L.append("## 0. 지금 채택 문턱을 넘는 것 (사전등록 표본만)")
    items = ad.get("items") or []
    if items:
        for it in items:
            if it["kind"] == "rule":
                L.append(f"- 규칙 **{it['name']}** {it['side']}: Δ{_f(it['adj'])} t={_f(it['t'])} "
                         f"클러스터{it['clusters']} 날짜{it['days']}")
            elif it["kind"] == "exit":
                L.append(f"- 청산 **{it['name']}** {it['side']}: diff{_f(it['diff'])} t={_f(it['t'])} "
                         f"클러스터{it['clusters']} 날짜{it['days']}")
            else:
                L.append(f"- 필터 **{it['name']}** {it['side']}: 채택군{_f(it['kept_mean'])} vs "
                         f"제외군{_f(it['excluded_mean'])} 클러스터{it['clusters']} "
                         f"함께있는날짜{it['days_with_both']}")
    else:
        L.append(f"- 아직 없음 (사전등록 표본 {ad.get('n_live', 0)}건 · {ad.get('days_so_far', 0) or 0}일 경과 — "
                 f"클러스터 {ADOPT_MIN_CLUSTERS}개·날짜 {ADOPT_MIN_DAYS}일 문턱을 채워야 판단 가능)")
    L.append("")

    L.append("## 1. 청산 변형 (live 대비 짝 비교, diff = 변형 − live)")
    L.append("⚠️ 채택 판정은 **diff·t·전후 반쪽만** 본다 — 승률은 참고용(live_be10 본전 청산 ROI 0.0 은 승리로 안 셈). "
             "ambig공유 = PROTECT 청산 중 같은 봉 안 고·저 순서를 몰라 비관적으로 무장된 비율(live_be10/live_lock5 만).")
    L.append("| 구간 | 방향 | 변형 | n | 클러스터 | 날짜 | live평균 | 변형평균 | diff | t | 전/후 반쪽 | 승률(참고) | ambig공유 | 채택 |")
    L.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---|")
    for block in ("all", "prereg"):
        b = (rep.get("blocks") or {}).get(block) or {}
        for side in SIDES:
            for variant, st in (b.get("exits") or {}).get(side, {}).items():
                if not st.get("n"):
                    continue
                mark = " ✅" if st.get("adopt") else (" (legacy)" if st.get("legacy") else "")
                ambig = f"{st['ambig_n']}/{_f(st.get('ambig_share'), 2)}" if st.get("ambig_share") is not None else "—"
                L.append(f"| {block} | {side} | {variant} | {st['n']} | {st['clusters']} | {st['days']} | "
                         f"{_f(st['mean_live'])} | {_f(st['mean_variant'])} | {_f(st['diff'])} | {_f(st['t'])} | "
                         f"{_half_str(st['half'])} | {_f(st.get('win'), 1)}% | {ambig} |{mark} |")
    L.append("")

    L.append("## 2. 진입 필터 (사전등록 — kept/excluded/universe · 필터별 사전등록 시각 이후 행만)")
    L.append("| 구간 | 방향 | 필터 | 구분 | n | 클러스터 | 날짜 | 평균 | 승률 | 긍정일/함께있는날 | 채택 |")
    L.append("|---|---|---|---|---:|---:|---:|---:|---:|---|---|")
    for block in ("all", "prereg"):
        b = (rep.get("blocks") or {}).get(block) or {}
        for side in SIDES:
            for fname, st in (b.get("filters") or {}).get(side, {}).items():
                de = st.get("day_edge") or {}
                mark = " ✅" if st.get("adopt") else ""
                reg = f" (등록 {str(st['since'])[:10]}~)" if st.get("since") else ""
                for part in ("kept", "excluded", "universe"):
                    ps = st.get(part) or {}
                    if not ps.get("n"):
                        continue
                    L.append(f"| {block} | {side} | {fname}{reg} | {part} | {ps['n']} | {ps['clusters']} | {ps['days']} | "
                             f"{_f(ps['mean'])} | {_f(ps.get('win'), 1)}% | "
                             f"{de.get('positive_days', 0)}/{de.get('days_with_both', 0)} |"
                             f"{mark if part == 'kept' else ''} |")
    L.append("")

    L.append(f"## 3. 규칙 (엔진 live, WEAK_RULES 사전 등록: {sorted({r for s in WEAK_RULES.values() for r in s})})")
    L.append("| 구간 | 방향 | 규칙 | n | no_base | 클러스터 | 날짜 | 평균 | 승률 | Δ | t | 전/후 반쪽 | 채택 | 약함 |")
    L.append("|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|")
    for block in ("all", "prereg"):
        b = (rep.get("blocks") or {}).get(block) or {}
        for side in SIDES:
            for rule, st in (b.get("rules") or {}).get(side, {}).items():
                mark = " ✅" if st.get("adopt") else ""
                weak = " ⚠️" if st.get("weak_flag") else ""
                L.append(f"| {block} | {side} | {rule} | {st['n']} | {st['no_base']} | {st['clusters']} | "
                         f"{st['days']} | {_f(st['mean'])} | {_f(st.get('win'), 1)}% | {_f(st['adj'])} | "
                         f"{_f(st['t'])} | {_half_str(st['half'])} |{mark} |{weak} |")
    L.append("")

    L.append("## 4. 추가(피라미딩) lot — 정보용 (채택 없음, 기간 의존적)")
    L.append("| 구간 | 변형 | 방향 | n | 평균 | 승률 | 합 USDT | 전/후 반쪽 |")
    L.append("|---|---|---|---:|---:|---:|---:|---|")
    for block in ("all", "prereg"):
        b = (rep.get("blocks") or {}).get(block) or {}
        for variant, vd in (b.get("adds") or {}).items():
            for side, st in vd.items():
                if not st.get("n"):
                    continue
                L.append(f"| {block} | {variant} | {side} | {st['n']} | {_f(st['mean'])} | "
                         f"{_f(st.get('win'), 1)}% | {_f(st.get('pnl_sum'))} | {_half_str(st['half'])} |")
    L.append("")

    ctx = rep.get("context") or {}
    L.append("## 5. 참고 (채택 판단에 쓰지 않음)")
    for side, d in (ctx.get("backfill") or {}).items():
        L.append(f"- backfill {side}: n={d.get('n')} 평균(live) {_f(d.get('avg_roi'))}")
    for side, d in (ctx.get("open_live") or {}).items():
        L.append(f"- 열린 실시간 {side}: n={d.get('n')} 평균(live, 미확정) {_f(d.get('avg_roi'))}")
    for w in ctx.get("warnings") or []:
        L.append(f"- ⚠️ {w}")
    return "\n".join(L)

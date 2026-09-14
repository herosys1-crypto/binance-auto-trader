"""📐 Fix 372 차트 상태 학습 보고서 — 읽기 전용 (JSONB 경로 스칼라만 SQL 로 뽑는다 · snapshot/engines 전체 컬럼 금지).

무엇을 보나 (가상매매 source=live, 진입 기록에 chart_state 가 붙은 행):
  ① 일봉 볼밴 상태 × 방향  규칙 진입 평균 ROI(live 엔진, 끝난 건) vs **같은 상태의 무작위 진입(baseline_LONG/SHORT)** → Δ
     + 4조각(심볼 홀짝 × 기간 전·후반) 중 Δ>0 인 조각 수
  ② 일봉 추세(UP/DOWN/FLAT) × 방향
  ③ 5분 2시간 범위 위치(0=저점 · 1=고점) × 방향
  ④ 진입 타이밍 라벨(GOOD/EARLY/LATE/WRONG_DIRECTION/NO_MOVE) × 방향 — 가상과 실거래 따로
표본이 5일·특정 국면이면 우연이 크다 — 「채택」은 여기서 하지 않는다 (가상 보고서 v3 사전등록 규칙으로).
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

MAX_DAYS = 60
MIN_N = 15
POS_BUCKETS = ((0.0, 0.15, "0~0.15 바닥권"), (0.15, 0.5, "0.15~0.5"), (0.5, 0.85, "0.5~0.85"), (0.85, 1.01, "0.85~1 고점권"))


def paper_stmt(*, cutoff: datetime):
    from sqlalchemy import Float, cast, select
    from app.models.paper_trade import PaperTrade as P
    cs = P.snapshot["chart_state"]
    return (
        select(P.side, P.rule, P.symbol, P.opened_at,
               cast(P.engines["live"]["roi"].astext, Float).label("roi"),
               P.engines["live"]["done"].astext.label("done"),
               cs["d1"]["bb"]["state"].astext.label("d1_state"),
               cs["d1"]["bb"]["trend"].astext.label("d1_trend"),
               cs["h4"]["bb"]["state"].astext.label("h4_state"),
               cast(cs["m5"]["st"]["range_pos"].astext, Float).label("m5_pos"),
               P.snapshot["chart_timing"]["label"].astext.label("timing"),
               cast(P.snapshot["chart_timing"]["best_offset_bars"].astext, Float).label("best_offset"))
        .where(P.source == "live", P.opened_at >= cutoff, P.snapshot["chart_state"].isnot(None))
    )


def real_stmt(*, cutoff: datetime):
    from sqlalchemy import Float, cast, select
    from app.models.trade_learning_record import TradeLearningRecord as T
    return (
        select(T.side, T.status, cast(T.pnl_pct, Float).label("pnl_pct"), T.pnl_usdt,
               T.insights["chart_timing"]["label"].astext.label("timing"),
               T.entry_context["chart_state"]["d1"]["bb"]["state"].astext.label("d1_state"))
        .where(T.entry_time >= cutoff, T.insights["chart_timing"].isnot(None))
    )


def _is_base(rule: str | None) -> bool:
    return str(rule or "").startswith("baseline_")


def _done(r: Mapping[str, Any]) -> bool:
    return r.get("roi") is not None and str(r.get("done")).lower() == "true"


def _mean(xs: list[float]) -> float | None:
    return round(statistics.fmean(xs), 3) if xs else None


def _piece(r: Mapping[str, Any], mid_ts: float) -> tuple[int, int]:
    parity = sum(map(ord, str(r.get("symbol") or ""))) % 2
    ts = r["opened_at"].timestamp() if r.get("opened_at") else 0.0
    return parity, int(ts >= mid_ts)


def _group(rows: list[Mapping[str, Any]], key_fn) -> dict[tuple, dict[str, Any]]:
    """(key) → 규칙 n·평균·승률 · 같은 key 기준선 평균 · Δ · 4조각 Δ>0 수."""
    done = [r for r in rows if _done(r)]
    if not done:
        return {}
    ts = sorted(r["opened_at"].timestamp() for r in done if r.get("opened_at"))
    mid_ts = ts[len(ts) // 2] if ts else 0.0
    rule_v: dict[tuple, list[float]] = defaultdict(list)
    base_v: dict[tuple, list[float]] = defaultdict(list)
    rule_p: dict[tuple, dict[tuple, list[float]]] = defaultdict(lambda: defaultdict(list))
    base_p: dict[tuple, dict[tuple, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in done:
        k = key_fn(r)
        if k is None:
            continue
        piece = _piece(r, mid_ts)
        if _is_base(r.get("rule")):
            base_v[k].append(r["roi"])
            base_p[k][piece].append(r["roi"])
        else:
            rule_v[k].append(r["roi"])
            rule_p[k][piece].append(r["roi"])
    out: dict[tuple, dict[str, Any]] = {}
    for k, vals in rule_v.items():
        b = _mean(base_v.get(k, []))
        m = _mean(vals)
        pos_pieces = 0
        for pc, pv in rule_p[k].items():
            bp = base_p[k].get(pc)
            if pv and bp and statistics.fmean(pv) - statistics.fmean(bp) > 0:
                pos_pieces += 1
        out[k] = {"n": len(vals), "avg_roi": m, "win_pct": round(100 * sum(1 for x in vals if x > 0) / len(vals), 1),
                  "base_n": len(base_v.get(k, [])), "base_avg_roi": b,
                  "delta": round(m - b, 3) if m is not None and b is not None else None, "pieces_pos": pos_pieces}
    return out


def aggregate(paper_rows: Iterable[Mapping[str, Any]], real_rows: Iterable[Mapping[str, Any]], *, days: int) -> dict[str, Any]:
    paper = list(paper_rows)
    real = list(real_rows)

    def _bucket(r):
        p = r.get("m5_pos")
        if p is None:
            return None
        return next((lbl for lo, hi, lbl in POS_BUCKETS if lo <= p < hi), None)

    by_state = _group(paper, lambda r: (r["side"], r.get("d1_state")) if r.get("d1_state") else None)
    by_trend = _group(paper, lambda r: (r["side"], r.get("d1_trend")) if r.get("d1_trend") else None)
    by_pos = _group(paper, lambda r: (r["side"], _bucket(r)) if _bucket(r) else None)
    timing: dict[tuple, dict[str, Any]] = {}
    labeled = [r for r in paper if r.get("timing") and not _is_base(r.get("rule"))]
    for side in ("LONG", "SHORT"):
        rows = [r for r in labeled if r["side"] == side]
        for lbl in ("GOOD", "EARLY", "LATE", "WRONG_DIRECTION", "NO_MOVE"):
            sel = [r for r in rows if r["timing"] == lbl]
            if sel:
                rois = [r["roi"] for r in sel if _done(r)]
                offs = [r["best_offset"] for r in sel if r.get("best_offset") is not None]
                timing[(side, lbl)] = {"n": len(sel), "share_pct": round(100 * len(sel) / len(rows), 1),
                                       "avg_roi": _mean(rois), "median_best_offset_bars": statistics.median(offs) if offs else None}
    real_timing: dict[tuple, dict[str, Any]] = {}
    for r in real:
        k = (r.get("side"), r.get("timing"))
        d = real_timing.setdefault(k, {"n": 0, "pnl_pct": []})
        d["n"] += 1
        if r.get("pnl_pct") is not None and str(r.get("status")) == "CLOSED":
            d["pnl_pct"].append(float(r["pnl_pct"]))
    real_timing = {k: {"n": v["n"], "avg_pnl_pct": _mean(v["pnl_pct"])} for k, v in real_timing.items()}

    def _j(d):
        return [{"key": list(k), **v} for k, v in sorted(d.items(), key=lambda kv: (str(kv[0][0]), -kv[1]["n"]))]

    return {"fix": "Fix372", "generated_at": datetime.now(timezone.utc).isoformat(), "days": days,
            "paper_rows": len(paper), "paper_rule_done": sum(1 for r in paper if _done(r) and not _is_base(r.get("rule"))),
            "paper_timing_labeled": len(labeled), "real_rows": len(real),
            "by_d1_state": _j(by_state), "by_d1_trend": _j(by_trend), "by_m5_pos": _j(by_pos),
            "timing": _j(timing), "real_timing": _j(real_timing)}


def build(db: Any, *, days: int = 14) -> dict[str, Any]:
    days = max(1, min(int(days or 14), MAX_DAYS))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    paper = [dict(m) for m in db.execute(paper_stmt(cutoff=cutoff)).mappings().all()]
    real = [dict(m) for m in db.execute(real_stmt(cutoff=cutoff)).mappings().all()]
    return aggregate(paper, real, days=days)


def render_markdown(rep: Mapping[str, Any], *, min_n: int = MIN_N) -> str:
    from app.services.chart_state import BB_EVENTS, TIMING_LABELS
    L = [f"# 📐 차트 상태 학습 보고서 (최근 {rep.get('days')}일 · {str(rep.get('generated_at', ''))[:16]} UTC)", "",
         f"- 가상 진입(차트 상태 기록) {rep.get('paper_rows')}건 · 규칙 진입 끝난 건 {rep.get('paper_rule_done')} · "
         f"타이밍 채점 {rep.get('paper_timing_labeled')} · 실거래 채점 {rep.get('real_rows')}",
         f"- Δ = 규칙 평균 ROI − **같은 조건의 무작위 진입(기준선)** 평균 · 4조각 = 심볼 홀짝 × 기간 전후반 중 Δ>0 수 · n<{min_n} 생략",
         "- 채택 판단은 하지 않는다 (가상 보고서 v3 사전등록 규칙으로)", ""]

    def _tbl(title: str, rows: list, name_fn):
        L.extend([f"## {title}", "", "| 방향 | 조건 | n | 평균 ROI | 승률 | 기준선 n | 기준선 ROI | Δ | 4조각 |",
                  "|---|---|---:|---:|---:|---:|---:|---:|---:|"])
        for r in rows:
            if r["n"] < min_n:
                continue
            L.append(f"| {r['key'][0]} | {name_fn(r['key'][1])} | {r['n']} | {r['avg_roi']} | {r['win_pct']}% | "
                     f"{r['base_n']} | {r['base_avg_roi']} | {r['delta']} | {r['pieces_pos']}/4 |")
        L.append("")

    _tbl("① 일봉 볼밴 상태", rep.get("by_d1_state") or [],
         lambda s: f"{BB_EVENTS.get(s, {'ABOVE_MID': '중단선 위', 'BELOW_MID': '중단선 아래'}.get(s, s))} (`{s}`)")
    _tbl("② 일봉 추세", rep.get("by_d1_trend") or [], lambda s: s)
    _tbl("③ 5분 2시간 범위 위치", rep.get("by_m5_pos") or [], lambda s: s)
    L.extend(["## ④ 진입 타이밍 (가상 규칙 진입)", "", "| 방향 | 라벨 | n | 비율 | 평균 ROI | 최적 가격까지 봉(중앙, −=이미 지남) |",
              "|---|---|---:|---:|---:|---:|"])
    for r in rep.get("timing") or []:
        L.append(f"| {r['key'][0]} | {TIMING_LABELS.get(r['key'][1], r['key'][1])} | {r['n']} | {r['share_pct']}% | "
                 f"{r['avg_roi']} | {r['median_best_offset_bars']} |")
    L.extend(["", "## ⑤ 진입 타이밍 (실거래)", "", "| 방향 | 라벨 | n | 평균 손익% (청산 건) |", "|---|---|---:|---:|"])
    for r in rep.get("real_timing") or []:
        L.append(f"| {r['key'][0]} | {TIMING_LABELS.get(r['key'][1], r['key'][1])} | {r['n']} | {r['avg_pnl_pct']} |")
    return "\n".join(L) + "\n"

"""🧑‍⚖️ Fix 430 (2026-10-10 사장님) — 전략 운영팀 성적표·배치표 (분석 전용, 주문·설정 변경 없음).

사장님: "새로운 전략들이 만들면 이것들을 서로 교차검증하고 서로 도움은 되는것을 같이 활용하는 전략으로 운영할수 있게
        … 분석과 운영팀을 구성하고 … 계속 새로운 전략이 들어오면 그것도 그렇게 같이 활용해서 만들수 있게 해줘"

가상매매(paper_trades) 마감 행으로 모든 규칙을 **같은 잣대**로 잰다 — 새 규칙은 가상 규칙에 등록되는 순간 자동 편입.
  A 규칙별     : n · 평균 roi · edge(같은 날·같은 방향 무작위 baseline 평균 대비)
  B 겹침       : 같은 봉에 같은 방향 규칙이 몇 개 켜졌나(k=1~4+) → 서로 돕는가
  C 장세       : 시장폭 구간(low/mid/high)별 무작위·전략 평균
  D 전진 검증  : 날짜 D 마다 학습창 [D−gap−train+1, D−gap] 로 칸(규칙·방향·장세)을 골라 D 에 그 칸만 — 미래 참조 없음
  E 오늘 쓸 칸 : 같은 방식으로 today(워커 = 실행일 UTC, 없으면 마지막 날+1)의 칸
  F 규칙 상태  : 표본 부족 / 사용 후보 / 중지 후보 / 관찰
10/10 운영 측정(30일 13만 행): 선택 +0.87 · 전체 +0.33 · 무작위 +0.37 · 선택>전체 12/17일 · 최악의 날 −6.56 (장세가 뒤집힌 날).
→ 손실 없는 정책이 아니다. 실주문 게이트로 쓰기 전에 이 성적표의 전진 기록이 먼저 쌓여야 한다.
설정(모두 「Claude가 정함」): council_breadth_lo 0.4 · council_breadth_hi 0.6 · council_train_days 11 · council_gap_days 3 · council_min_n 30.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Iterable

FIX = "Fix430"
BASE_PREFIX = "baseline_"
DEFAULTS = {"lo": 0.4, "hi": 0.6, "train_days": 11, "gap": 3, "min_n": 30}
KEYS = {"lo": "council_breadth_lo", "hi": "council_breadth_hi", "train_days": "council_train_days",
        "gap": "council_gap_days", "min_n": "council_min_n"}
_INT_BOUNDS = {"train_days": (3, 60), "gap": (1, 10), "min_n": (5, 5000)}   # gap ≥ 1: 0 이면 D 당일 결과로 D 를 고른다(미래 참조, 교차 감사)
_B_ORDER = ("low", "mid", "high", "?")


@dataclass(frozen=True, slots=True)
class Row:
    rule: str
    side: str
    d: date
    roi: float
    mb: float | None = None
    rf: tuple[str, ...] | None = None


def _num(raw: Any) -> float | None:
    try:
        x = float(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def clean_params(lo: Any = None, hi: Any = None, train_days: Any = None, gap: Any = None, min_n: Any = None) -> dict:
    """범위 밖·파싱 실패 → 기본값. lo ≥ hi 면 둘 다 기본값. 정수 칸은 정수만."""
    p = dict(DEFAULTS)
    flo, fhi = _num(lo), _num(hi)
    flo = flo if flo is not None and 0.05 <= flo <= 0.95 else DEFAULTS["lo"]
    fhi = fhi if fhi is not None and 0.05 <= fhi <= 0.95 else DEFAULTS["hi"]
    if flo < fhi:
        p["lo"], p["hi"] = flo, fhi
    for k, raw in (("train_days", train_days), ("gap", gap), ("min_n", min_n)):
        x = _num(raw)
        a, b = _INT_BOUNDS[k]
        if x is not None and x == int(x) and a <= int(x) <= b:
            p[k] = int(x)
    return p


def params_from(get: Callable[[str], Any]) -> dict:
    vals = {}
    for k, key in KEYS.items():
        try:
            vals[k] = get(key)
        except Exception:  # noqa: BLE001 — 설정 조회 실패 = 기본값 (분석 전용)
            vals[k] = None
    return clean_params(**vals)


def bucket(mb: float | None, lo: float, hi: float) -> str:
    if mb is None:
        return "?"
    return "low" if mb < lo else ("mid" if mb <= hi else "high")


def _r(x: float | None, nd: int = 3) -> float | None:
    return None if x is None or not math.isfinite(x) else round(x, nd)


class _Agg:
    __slots__ = ("n", "s", "en", "es")

    def __init__(self) -> None:
        self.n = 0; self.s = 0.0; self.en = 0; self.es = 0.0   # noqa: E702

    def add(self, n: int, s: float, en: int = 0, es: float = 0.0) -> None:
        self.n += n; self.s += s; self.en += en; self.es += es   # noqa: E702

    @property
    def mean(self) -> float | None:
        return self.s / self.n if self.n else None

    @property
    def edge(self) -> float | None:
        return self.es / self.en if self.en else None


def build_report(rows: Iterable[Row], *, lo: Any = 0.4, hi: Any = 0.6, train_days: Any = 11, gap: Any = 3,
                 min_n: Any = 30, today: date | None = None) -> dict:
    p = clean_params(lo, hi, train_days, gap, min_n)
    lo_, hi_ = p["lo"], p["hi"]
    rows = list(rows)

    # ── 1. 무작위 평균 · 규칙→방향 ──
    base_d: dict[tuple, list] = defaultdict(lambda: [0, 0.0])        # (side, d) → [n, sum]
    base_db: dict[tuple, list] = defaultdict(lambda: [0, 0.0])       # (side, d, b)
    side_of: dict[str, str] = {}
    strat: list[Row] = []
    for r in rows:
        if r.rule.startswith(BASE_PREFIX):
            b = bucket(r.mb, lo_, hi_)
            x = base_d[(r.side, r.d)]; x[0] += 1; x[1] += r.roi       # noqa: E702
            y = base_db[(r.side, r.d, b)]; y[0] += 1; y[1] += r.roi   # noqa: E702
        else:
            side_of.setdefault(r.rule, r.side)
            strat.append(r)
    bm_d = {k: v[1] / v[0] for k, v in base_d.items()}
    bm_db = {k: v[1] / v[0] for k, v in base_db.items()}

    # ── 2. (rule, side, d, b) 집계 + 겹침 k ──
    cell_day: dict[tuple, list] = defaultdict(lambda: [0, 0.0])      # (rule, side, b, d) → [n, sum]
    rule_day: dict[tuple, list] = defaultdict(lambda: [0, 0.0])      # (rule, side, d)
    ov: dict[tuple, _Agg] = defaultdict(_Agg)
    day_all: dict[date, list] = defaultdict(lambda: [0, 0.0])
    reg_strat: dict[tuple, list] = defaultdict(lambda: [0, 0.0])
    for r in strat:
        b = bucket(r.mb, lo_, hi_)
        c = cell_day[(r.rule, r.side, b, r.d)]; c[0] += 1; c[1] += r.roi       # noqa: E702
        q = rule_day[(r.rule, r.side, r.d)]; q[0] += 1; q[1] += r.roi          # noqa: E702
        a = day_all[r.d]; a[0] += 1; a[1] += r.roi                             # noqa: E702
        g = reg_strat[(r.side, b)]; g[0] += 1; g[1] += r.roi                   # noqa: E702
        # 겹침 k: 같은 봉에 함께 켜진 **같은 방향** 비-baseline 규칙(자기 포함, 중복 제거). side_of 는 1단계에서 이미 다 채워졌다.
        names = {r.rule}
        for x in (r.rf or ()):
            if isinstance(x, str) and not x.startswith(BASE_PREFIX) and side_of.get(x) == r.side:
                names.add(x)
        bm = bm_d.get((r.side, r.d))
        ov[(r.side, min(len(names), 4))].add(1, r.roi, *((1, r.roi - bm) if bm is not None else (0, 0.0)))

    # ── A 규칙별 ──
    ra: dict[tuple, _Agg] = defaultdict(_Agg)
    for (rule, side, d), (n, s) in rule_day.items():
        bm = bm_d.get((side, d))
        ra[(rule, side)].add(n, s, *((n, s - n * bm) if bm is not None else (0, 0.0)))
    A = [{"rule": k[0], "side": k[1], "n": a.n, "roi": _r(a.mean), "edge": _r(a.edge)} for k, a in ra.items()]
    A.sort(key=lambda x: (x["edge"] is None, -(x["edge"] or 0.0), x["rule"]))

    # ── B 겹침 ──
    B = [{"side": k[0], "k": k[1], "n": a.n, "roi": _r(a.mean), "edge": _r(a.edge)} for k, a in sorted(ov.items())]

    # ── C 장세 ──
    reg_base: dict[tuple, list] = defaultdict(lambda: [0, 0.0])
    for (side, _d, b), (n, s) in base_db.items():
        x = reg_base[(side, b)]; x[0] += n; x[1] += s   # noqa: E702
    C = []
    for side in ("LONG", "SHORT"):
        for b in _B_ORDER:
            bn, bs = reg_base.get((side, b), (0, 0.0))
            sn, ss = reg_strat.get((side, b), (0, 0.0))
            if bn or sn:
                C.append({"side": side, "b": b, "base_n": bn, "base_roi": _r(bs / bn if bn else None),
                          "strat_n": sn, "strat_roi": _r(ss / sn if sn else None)})

    # ── D 전진 검증 · E 내일 쓸 칸 ──
    by_day: dict[date, dict[tuple, list]] = defaultdict(dict)        # d → {(rule, side, b): [n, sum]}
    for (rule, side, b, d), v in cell_day.items():
        by_day[d][(rule, side, b)] = v
    days = sorted(by_day)

    def pick(D: date) -> tuple[dict[tuple, _Agg], bool]:
        start, end = D - timedelta(days=p["gap"] + p["train_days"] - 1), D - timedelta(days=p["gap"])
        tr: dict[tuple, _Agg] = defaultdict(_Agg)
        covered = 0
        for d in days:
            if start <= d <= end:
                covered += 1
                for (rule, side, b), (n, s) in by_day[d].items():
                    bm = bm_db.get((side, d, b))
                    tr[(rule, side, b)].add(n, s, *((n, s - n * bm) if bm is not None else (0, 0.0)))
        sel = {k: a for k, a in tr.items()
               if a.n >= p["min_n"] and (a.mean or 0.0) > 0 and a.edge is not None and a.edge > 0}
        # 워밍업: 학습창 날짜의 절반 이상에 데이터가 있어야 그 날을 채점한다 (하루 이틀치로 고른 칸은 잡음)
        return sel, covered >= (p["train_days"] + 1) // 2

    D_days = []
    tot = {"sel": [0, 0.0], "all": [0, 0.0], "base": [0, 0.0]}
    for D in days:
        sel, seen = pick(D)
        if not seen:
            continue
        sn = sum(v[0] for k, v in by_day[D].items() if k in sel)
        ss = sum(v[1] for k, v in by_day[D].items() if k in sel)
        an, as_ = day_all[D]
        bn = sum(base_d[(sd, D)][0] for sd in ("LONG", "SHORT") if (sd, D) in base_d)
        bs = sum(base_d[(sd, D)][1] for sd in ("LONG", "SHORT") if (sd, D) in base_d)
        for k, n_, s_ in (("sel", sn, ss), ("all", an, as_), ("base", bn, bs)):
            tot[k][0] += n_; tot[k][1] += s_   # noqa: E702
        D_days.append({"d": D.isoformat(), "cells": len(sel), "n_sel": sn, "sel": _r(ss / sn if sn else None),
                       "all": _r(as_ / an if an else None), "base": _r(bs / bn if bn else None)})
    scored = [x for x in D_days if x["sel"] is not None]
    worst = min(scored, key=lambda x: x["sel"]) if scored else None
    D_walk = {
        "days": D_days,
        "total": {**{k: _r(v[1] / v[0] if v[0] else None) for k, v in tot.items()},
                  **{f"{k}_n": v[0] for k, v in tot.items()}},
        "sel_gt_all_days": sum(1 for x in scored if x["all"] is not None and x["sel"] > x["all"]),
        "sel_pos_days": sum(1 for x in scored if x["sel"] > 0),
        "n_days": len(D_days),
        "worst": {"d": worst["d"], "sel": worst["sel"]} if worst else None,
    }

    last = days[-1] if days else None
    D_next = today or (last + timedelta(days=1) if last else None)
    E_cells = []
    if D_next is not None:
        sel, _ = pick(D_next)
        E_cells = [{"rule": k[0], "side": k[1], "b": k[2], "n": a.n, "roi": _r(a.mean), "edge": _r(a.edge)}
                   for k, a in sel.items()]
    mbs = sorted(r.mb for r in strat if r.d == last and r.mb is not None) if last else []
    cur_b = bucket(mbs[len(mbs) // 2], lo_, hi_) if mbs else "?"
    E_cells.sort(key=lambda x: (x["b"] != cur_b, -(x["edge"] or 0.0), x["rule"]))   # 지금 장세 칸이 먼저

    # ── F 규칙 상태 ──
    used = {(c["rule"], c["side"]) for c in E_cells}
    F = []
    for a in A:
        if a["n"] < p["min_n"]:
            st = "표본 부족"
        elif (a["rule"], a["side"]) in used:
            st = "사용 후보"
        elif a["edge"] is not None and a["edge"] < 0:
            st = "중지 후보"
        else:
            st = "관찰"
        F.append({"rule": a["rule"], "side": a["side"], "status": st, "n": a["n"], "edge": a["edge"]})

    return {
        "fix": FIX, "params": p, "rows": len(rows),
        "days": {"first": days[0].isoformat() if days else None, "last": last.isoformat() if last else None},
        "A_rules": A, "B_overlap": B, "C_regime": C, "D_walk": D_walk,
        "E_today": {"d": D_next.isoformat() if D_next else None, "current_b": cur_b, "cells": E_cells},
        "F_status": F,
    }

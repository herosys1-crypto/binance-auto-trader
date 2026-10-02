#!/usr/bin/env python3
"""measure_bb_1m_guard.py 의 순수 함수 — 일봉 %B · 청산 시뮬레이션 · 집계·보고 (네트워크·운영 코드 없음, 단위 테스트 대상).

500줄 규칙 때문에 2026-10-02 Gemini 심판 지적으로 분리했다. 동작은 분리 전과 같다.
"""
from __future__ import annotations

import csv
import math
import os
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

M1, M15, DAY_MS = 60_000, 900_000, 86_400_000
LEV, MARGINS, ADD_STEPS = 2.0, (100.0, 200.0, 300.0), (0.02, 0.04)
STOP_PRICE, TP_STEP, TP_FRACTION, TRAIL = 0.05, 0.025, 0.25, 0.03  # ROI -10% / +5%×k (레버리지 2)
HOLD_MS, FEE, SLIP = 48 * 3_600_000, 0.0005, 0.0005
EARLY_XS = (0.3, 0.5, 1.0)
MIN_N = 150


# ───────────────────────── 순수 함수: 지표 ─────────────────────────
def daily_pctb(bars: list[tuple]) -> dict[int, float]:
    """UTC 일 번호 → 그 날 종가의 BB(20,2) %B. 23:45 봉이 있는(완료) 날만, 20일 연속일 때만."""
    last: dict[int, tuple[int, float]] = {}
    for t, _o, _h, _l, c in bars:
        last[t // DAY_MS] = (t, c)
    closes = {d: c for d, (t, c) in last.items() if t % DAY_MS == DAY_MS - M15}
    out = {}
    for d, cd in closes.items():
        win = [closes.get(d - k) for k in range(20)]
        if any(x is None for x in win):
            continue
        mid, sd = statistics.fmean(win), statistics.pstdev(win)
        if sd > 0:
            out[d] = (cd - (mid - 2 * sd)) / (4 * sd)
    return out


def daily_pos(pctb: float | None) -> str:
    if pctb is None:
        return "unknown"
    return "above" if pctb > 1 else "below" if pctb < 0 else "inside"


# ───────────────────────── 순수 함수: 청산 시뮬레이션 ─────────────────────────
@dataclass
class Pos:
    s: int
    p1: float
    qty: float = 0.0
    avg: float = 0.0
    margin: float = 0.0
    realized: float = 0.0
    fees: float = 0.0
    adds: list = field(default_factory=list)
    tp_stage: int = 0
    base_qty: float = 0.0
    peak: float | None = None
    closed: bool = False
    reason: str = ""


def _fill(p: Pos, price: float, margin: float) -> None:
    q = margin * LEV / price
    p.avg = (p.avg * p.qty + price * q) / (p.qty + q)
    p.qty += q
    p.margin += margin
    p.fees += price * q * FEE


def _reduce(p: Pos, price: float, q: float, reason: str) -> None:
    full = q >= p.qty
    q = p.qty if full else q
    p.realized += p.s * (price - p.avg) * q
    p.fees += price * q * FEE
    p.qty -= q
    if full:
        p.qty, p.closed, p.reason = 0.0, True, reason


def new_pos(side: str, p1: float) -> Pos:
    if side not in ("LONG", "SHORT") or not (math.isfinite(p1) and p1 > 0):
        raise ValueError(f"잘못된 진입: {side} {p1}")
    s = 1 if side == "LONG" else -1
    p = Pos(s=s, p1=p1)
    _fill(p, p1, MARGINS[0])
    p.adds = [(p1 * (1 - s * ADD_STEPS[0]), MARGINS[1]), (p1 * (1 - s * ADD_STEPS[1]), MARGINS[2])]
    return p


def step(p: Pos, bar: tuple, early: float | None = None) -> None:
    """한 봉 처리. 불리한 쪽 먼저: (조기손절) → 추가 체결 → 손절 → 트레일링 → TP."""
    _t, o, h, l, _c = bar
    s = p.s
    adv, fav = (l, h) if s > 0 else (h, l)
    hit_adv = lambda lv: s * (adv - lv) <= 0                    # noqa: E731
    at_adv = lambda lv: o if s * (o - lv) < 0 else lv           # noqa: E731  시가가 이미 넘었으면 시가
    if early is not None:
        cands = [(early, "early")] if hit_adv(early) else []
        if p.peak is not None and hit_adv(p.peak * (1 - s * TRAIL)):
            cands.append((p.peak * (1 - s * TRAIL), "trail"))
        if cands:
            lv, why = max(cands, key=lambda x: s * x[0])         # 시가에서 불리 방향으로 먼저 닿는 선
            px = at_adv(lv) * ((1 - s * SLIP) if why == "early" else 1.0)
            _reduce(p, px, p.qty, why)
            return
    if p.tp_stage == 0:
        for a in list(p.adds):
            if hit_adv(a[0]):
                _fill(p, at_adv(a[0]), a[1])
                p.adds.remove(a)
    sl = p.avg * (1 - s * STOP_PRICE)
    if hit_adv(sl):
        _reduce(p, at_adv(sl), p.qty, "stop")
        return
    if p.peak is not None:
        tl = p.peak * (1 - s * TRAIL)
        if hit_adv(tl):
            _reduce(p, at_adv(tl), p.qty, "trail")
            return
    while p.tp_stage < 4:
        lv = p.avg * (1 + s * TP_STEP * (p.tp_stage + 1))
        if s * (fav - lv) < 0:
            break
        if p.tp_stage == 0:
            p.base_qty, p.peak = p.qty, lv
            p.adds.clear()
        p.tp_stage += 1
        px = o if s * (o - lv) > 0 else lv
        _reduce(p, px, p.qty if p.tp_stage == 4 else TP_FRACTION * p.base_qty, f"tp{p.tp_stage}")
        if p.closed:
            return
    if p.peak is not None and s * (fav - p.peak) > 0:
        p.peak = fav


def _result(p: Pos, exit_k: int) -> dict:
    pnl = p.realized - p.fees
    return {"pnl": pnl, "roi": pnl / p.margin * 100, "margin": p.margin, "reason": p.reason, "exit_k": exit_k}


def simulate(side: str, p1: float, t0: int, path15: list[tuple],
             path1m: list[tuple] | None = None, early_x: float | None = None) -> tuple[dict | None, str]:
    """path15[0] = 진입봉(시가=p1). path1m 이 있으면 그 구간을 1분봉으로 대체(조기손절 early_x %).
    반환 (결과 or None, 상태). None 이면 확정 불가(누락·데이터 부족)."""
    if early_x is not None and not 0 < early_x / 100 < ADD_STEPS[0]:
        raise ValueError("early_x 는 0 < X < 2% 여야 함(처리 순서 가정)")
    p = new_pos(side, p1)
    k0 = 0
    if path1m is not None:
        if not path1m or (len(path1m) * M1) % M15:
            return None, "bad_1m_window"
        early = None if early_x is None else p1 * (1 - p.s * early_x / 100)
        for j, b in enumerate(path1m):
            if b[0] != t0 + j * M1:
                return None, "gap_1m"
            step(p, b, early)
            if p.closed:
                return _result(p, j * M1 // M15), "ok"
        k0 = len(path1m) * M1 // M15
    for k in range(k0, len(path15)):
        b = path15[k]
        if b[0] != t0 + k * M15:
            return None, "gap_15m"
        if b[0] >= t0 + HOLD_MS:
            _reduce(p, b[1], p.qty, "time")
            return _result(p, k), "ok"
        step(p, b)
        if p.closed:
            return _result(p, k), "ok"
    return None, "incomplete"


def vkeys(windows: list[int]) -> list[tuple[str, int, float | None]]:
    out = []
    for w in windows:
        out += [(f"X{x}_W{w}", w, x) for x in EARLY_XS] + [(f"CTRL_W{w}", w, None)]
    return out


# ───────────────────────── 집계·보고 ─────────────────────────
def pnl_stats(vals: list[float]) -> dict:
    n = len(vals)
    return {"n": n, "win": sum(v > 0 for v in vals) / n * 100 if n else None,
            "mean": statistics.fmean(vals) if n else None, "sum": sum(vals)}


def variant_stats(rows: list[dict], key: str, ref: str | None = None, med: float | None = None) -> dict:
    """Δ 기준 = ref 변형(같은 W 의 CTRL — 1분 재생 해상도 효과를 뺀 순수 조기 손절 효과), 없으면 기준(15분)."""
    pairs = [(t["entry_ms"], t["symbol"], (t["v"][ref]["pnl"] if ref else t["base"]["pnl"]), t["v"][key])
             for t in rows if t["v"].get(key) and (ref is None or t["v"].get(ref))]
    st = pnl_stats([p[3]["pnl"] for p in pairs])
    st["roi"] = statistics.fmean([p[3]["roi"] for p in pairs]) if pairs else None

    def dm(sel) -> float | None:
        d = [p[3]["pnl"] - p[2] for p in pairs if sel(p)]
        return statistics.fmean(d) if d else None

    st["delta"] = dm(lambda p: True)
    if pairs:
        if med is None:                            # 그룹 경계는 호출부가 그룹 전체로 한 번 정한다
            med = statistics.median([p[0] for p in pairs])
        st["slices"] = [dm(lambda p: p[0] <= med), dm(lambda p: p[0] > med),
                        dm(lambda p: sum(map(ord, p[1])) % 2 == 1), dm(lambda p: sum(map(ord, p[1])) % 2 == 0)]
    else:
        st["slices"] = [None] * 4
    st["pass"] = st["n"] >= MIN_N and all(x is not None and x > 0 for x in st["slices"])
    return st


def fmt(x, nd: int = 2, sign: bool = True) -> str:
    if x is None:
        return "—"
    return f"{x:+.{nd}f}" if sign else f"{x:.{nd}f}"


def utc(ms: int | None) -> str:
    return "—" if ms is None else datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def write_trades_csv(path: Path, trades: list[dict], windows: list[int]) -> None:
    keys = [k for k, _, _ in vkeys(windows)]
    head = ["symbol", "side", "entry_time_utc", "entry_price", "baseline", "route", "reason", "chg_24h",
            "daily_pctb", "daily_pos", "base_reason", "base_pnl", "base_roi"]
    head += [f"{k}_{f}" for k in keys for f in ("pnl", "roi")]
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(head)
        for t in trades:
            row = [t["symbol"], t["side"], utc(t["entry_ms"]), f"{t['entry_price']:.10g}", f"{t['baseline']:.10g}",
                   t["route"], t["reason"], f"{t['chg24']:.3f}", "" if t["pctb"] is None else f"{t['pctb']:.4f}",
                   t["pos"], t["base"]["reason"], f"{t['base']['pnl']:.4f}", f"{t['base']['roi']:.4f}"]
            for k in keys:
                v = t["v"].get(k)
                row += ["", ""] if v is None else [f"{v['pnl']:.4f}", f"{v['roi']:.4f}"]
            w.writerow(row)
    os.replace(tmp, path)


def build_report(trades: list[dict], ctx: "Ctx", windows: list[int], n_symbols: int, aborted: str) -> tuple[str, list]:
    st, cl = ctx.st, ctx.client
    L = ["# 볼밴 1차 진입 뒤 1분봉 조기 손절 효과 (읽기 전용 백테스트)", ""]
    if aborted:
        L += [f"> ⚠️ **중단됨: {aborted}** — 아래는 중단 시점까지의 부분 결과다.", ""]
    L += ["## 수집 통계", "",
          f"- 대상 심볼 {n_symbols} · 실패 {len(ctx.failed)} · 기간(진입) {utc(ctx.period[0])} ~ {utc(ctx.period[1])} UTC",
          f"- 후보(|chg24|≥15) {st['candidates']} · 신호 {st['signals']} · 확정 건 {len(trades)}",
          f"- 418 발생: {'예' if cl and cl.banned else '아니오'} · 429 발생: {cl.n429 if cl else 0}회 · 요청 {cl.requests if cl else 0}회",
          f"- 운영 함수 예외 {st['signal_fn_errors']}회" + (" ⚠️" if st["signal_fn_errors"] else "")]
    for k in sorted(k for k in st if k not in ("candidates", "signals", "signal_fn_errors")):
        L.append(f"- {k}: {st[k]}")
    for w in windows:
        L.append(f"- **1분봉 없음/부족으로 W={w} 변형 비교 제외: {st[f'excl_1m_missing_W{w}']}건**")
    if ctx.fn_errors:
        L += ["", "### 운영 함수 예외 예시", ""] + [f"- `{m}`" for m in ctx.fn_errors]
    if ctx.failed:
        L += ["", "### 실패 심볼", ""] + [f"- {s}: {m}" for s, m in ctx.failed]
    L += ["", "## 가정", "", "- 진행 중 봉 자리에 봉 i+1 시가 사용(누설 차단), LONG·SHORT 동시 신호는 제외",
          "- TP '최초 수량' = TP1 직전 보유 수량, 지정가는 그 가격(시가가 넘었으면 시가) 체결",
          "- CTRL_W* = 조기 손절 없이 W분만 1분봉 재생(해상도 효과 대조, 통과 판정 제외)",
          f"- 통과 = 4조각 Δ(시간 앞/뒤, 종목 홀/짝) 모두 > 0 그리고 n ≥ {MIN_N}. Δ 는 같은 건 쌍 비교(건당 USDT)",
          "- 🚨 조기 손절 X*_W* 의 Δ 는 **같은 W 의 CTRL 대비**다. 기준(15분봉, 봉 안 불리한 쪽 먼저) 대비로 재면 1분 재생만으로 생기는 "
          "해상도 이득(CTRL Δ +0.7~+1.5, 2026-10-02 실측)이 조기 손절 효과로 잘못 잡힌다.", ""]
    passed = []
    for side in ("ALL", "LONG", "SHORT"):
        for pos in ("ALL", "above", "inside", "below", "unknown"):
            rows = [t for t in trades if side in ("ALL", t["side"]) and pos in ("ALL", t["pos"])]
            b = pnl_stats([t["base"]["pnl"] for t in rows])
            L += [f"### {side} × 일봉 {pos} (기준 n={b['n']})", "",
                  "| 변형 | n | 승률% | 건당 USDT | 합계 | 평균 ROI% | Δ/건 (X*=CTRL 대비, CTRL=기준 대비) | Δ앞 | Δ뒤 | Δ홀 | Δ짝 | 통과 |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|"]
            broi = statistics.fmean([t["base"]["roi"] for t in rows]) if rows else None
            L.append(f"| 기준 | {b['n']} | {fmt(b['win'], 1, False)} | {fmt(b['mean'])} | {fmt(b['sum'])} | "
                     f"{fmt(broi)} | — | — | — | — | — | — |")
            for key, _w, x in vkeys(windows):
                v = variant_stats(rows, key, None if x is None else f"CTRL_W{_w}",
                                  statistics.median([t["entry_ms"] for t in rows]) if rows else None)
                mark = "참고" if x is None else ("✅" if v["pass"] else "❌")
                if x is not None and v["pass"]:
                    passed.append((side, pos, key, v["n"], v["delta"]))
                L.append(f"| {key} | {v['n']} | {fmt(v['win'], 1, False)} | {fmt(v['mean'])} | {fmt(v['sum'])} | "
                         f"{fmt(v['roi'])} | {fmt(v['delta'])} | " + " | ".join(fmt(s) for s in v["slices"])
                         + f" | {mark} |")
            L.append("")
    return "\n".join(L) + "\n", passed

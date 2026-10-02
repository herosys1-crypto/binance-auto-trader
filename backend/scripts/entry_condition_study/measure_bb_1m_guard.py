#!/usr/bin/env python3
"""볼밴 분할 1차 진입 뒤 「1분봉 조기 손절」 효과 측정 — 읽기 전용 백테스트 (docs/spec/BB_1M_PLAN_2026-09-14.md 5절 0단계).

Duel_Lab(2026-10-02) GPT·Claude 초안 병합본 — 바탕 Claude 초안, GPT 초안에서 엔드포인트 화이트리스트를 가져왔다.
실행(로컬 PC, backend/ 아래 아무 곳): python scripts/entry_condition_study/measure_bb_1m_guard.py [--days 30]

* 바이낸스 USDT-M 선물 **공개 시세 API만** 사용(키·주문·계정 호출 없음). 결과는 파일로만 낸다.
* 진입 신호는 운영 함수 app.services.bb_entry_rules.evaluate_first_entry 를 그대로 재생한다.

명세에 없던 결정(보고서에도 기재):
1. 진행 중 봉 자리(closes[-1])에는 봉 i+1 의 '종가' 대신 '시가'(=진입 순간 가격)를 넣는다(미래 누설 차단).
   함수에는 마지막 연속 구간(봉 누락 이후) 시작부터 넘긴다.
2. 같은 완료봉에서 LONG·SHORT 가 동시에 나오면 임의로 고르지 않고 건너뛰고 센다.
3. TP 수량의 '최초 수량' = TP1 체결 직전 보유 수량(TP1 뒤에는 추가가 없으므로 이후 불변).
4. 2·3차 지정가·TP 는 그 가격(시가가 이미 넘었으면 시가) 체결. 손절·트레일링도 시가가 넘었으면 시가 체결.
5. 1분 구간에서 조기 손절선과 트레일링선이 한 봉에서 함께 닿으면 시가에서 먼저 닿는 쪽(X<2% 이므로
   조기 손절선은 항상 2차 추가선보다 먼저 닿는다).
6. 1분 재생 자체 효과를 분리하려고 '가드 없는 1분 재생' 대조(CTRL_W*)를 함께 보고한다(통과 판정 제외).
7. 경로 중 15분봉 누락·데이터 끝으로 결과를 확정할 수 없는 건은 통계에서 빼고 세며,
   그 건은 최대 보유시간(48h)까지 같은 심볼 신호를 막는다(보수적).
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BACKEND_DIR = Path(__file__).resolve().parents[2]
BASE_URL = "https://fapi.binance.com"
M1, M15, DAY_MS = 60_000, 900_000, 86_400_000
WARMUP_BARS, LOOKBACK_24H, CAND_MIN_ABS_CHG = 150, 96, 15.0
LEV, MARGINS, ADD_STEPS = 2.0, (100.0, 200.0, 300.0), (0.02, 0.04)
STOP_PRICE, TP_STEP, TP_FRACTION, TRAIL = 0.05, 0.025, 0.25, 0.03  # ROI -10% / +5%×k (레버리지 2)
HOLD_MS, FEE, SLIP = 48 * 3_600_000, 0.0005, 0.0005
EARLY_XS = (0.3, 0.5, 1.0)
MIN_N, WEIGHT_LIMIT, MIN_GAP_S, MAX_RETRY = 150, 1800, 0.1, 3
ALLOWED_PATHS = frozenset({"/fapi/v1/exchangeInfo", "/fapi/v1/klines"})
SIGNAL_TAIL = 400  # 운영 함수에 넘기는 종가 길이 상한 — BB(20)·밖 머문 봉수에 충분, O(n²) 방지
SYM_RE = re.compile(r"[A-Z0-9]{2,30}")  # ASCII + 파일 경로 안전


class FetchError(Exception):
    """한 요청/심볼 단위 실패(전체 실행은 계속)."""


class Banned(Exception):
    """HTTP 418 — 즉시 전체 중단."""


# ───────────────────────── 네트워크(공개 시세 전용) ─────────────────────────
class Client:
    def __init__(self) -> None:
        self.last = 0.0
        self.n429 = 0
        self.banned = False
        self.requests = 0

    def _weight_guard(self, headers) -> None:
        try:
            used = int((headers or {}).get("X-MBX-USED-WEIGHT-1M") or 0)
        except (TypeError, ValueError):
            return
        if used > WEIGHT_LIMIT:
            time.sleep(60 - time.time() % 60 + 0.5)

    def get(self, path: str, params: dict):
        if path not in ALLOWED_PATHS:                   # GPT 초안에서 병합: 공개 시세 두 곳 외 호출 금지
            raise ValueError(f"허용되지 않은 엔드포인트: {path}")
        url = f"{BASE_URL}{path}?{urlencode(params)}" if params else BASE_URL + path
        for attempt in range(MAX_RETRY + 1):
            wait = self.last + MIN_GAP_S - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            self.requests += 1
            try:
                with urlopen(Request(url, headers={"User-Agent": "bb-1m-guard-study"}), timeout=20) as r:
                    body = r.read()
                    self._weight_guard(r.headers)
                return json.loads(body)
            except HTTPError as e:
                self._weight_guard(e.headers)
                if e.code == 418:
                    self.banned = True
                    raise Banned("HTTP 418 (IP 차단) — 즉시 중단") from None
                if e.code == 429:
                    self.n429 += 1
                    try:
                        ra = int(float(e.headers.get("Retry-After") or 60))
                    except (TypeError, ValueError):
                        ra = 60
                    if attempt < MAX_RETRY:
                        time.sleep(min(max(ra, 1), 300))
                        continue
                    raise FetchError("HTTP 429 재시도 초과") from None
                if 500 <= e.code < 600 and attempt < MAX_RETRY:
                    time.sleep(2 ** attempt)
                    continue
                raise FetchError(f"HTTP {e.code}") from None
            except (URLError, TimeoutError, OSError, ValueError) as e:  # ValueError ⊃ JSONDecodeError
                if attempt < MAX_RETRY:
                    time.sleep(1 + attempt)
                    continue
                raise FetchError(f"{type(e).__name__}: {e}") from None
        raise FetchError("재시도 소진")


# ───────────────────────── 캐시·파싱 ─────────────────────────
def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def parse_klines(rows) -> tuple[list[tuple], int]:
    """[t,o,h,l,c,...] 목록 → 검증된 (t,o,h,l,c) 정렬 목록, 버린 개수. 0·음수·NaN·모순 봉은 버린다."""
    if not isinstance(rows, list):
        return [], 0
    out: dict[int, tuple] = {}
    bad = 0
    for r in rows:
        try:
            t = int(r[0])
            o, h, l, c = (float(x) for x in r[1:5])
        except (TypeError, ValueError, IndexError):
            bad += 1
            continue
        if (t % M1 or not all(math.isfinite(x) and x > 0 for x in (o, h, l, c))
                or h < max(o, c, l) or l > min(o, c)):
            bad += 1
            continue
        out[t] = (t, o, h, l, c)
    return [out[k] for k in sorted(out)], bad


def fetch_symbols(client: Client) -> list[str]:
    data = client.get("/fapi/v1/exchangeInfo", {})
    if not isinstance(data, dict) or not isinstance(data.get("symbols"), list):
        raise FetchError("exchangeInfo 형식 오류")
    out = []
    for s in data["symbols"]:
        if (isinstance(s, dict) and s.get("contractType") == "PERPETUAL" and s.get("quoteAsset") == "USDT"
                and s.get("status") == "TRADING"):
            name = str(s.get("symbol", ""))
            if name.isascii() and SYM_RE.fullmatch(name):
                out.append(name)
    return sorted(set(out))


def load_15m(sym: str, ctx: "Ctx") -> tuple[list[tuple], int]:
    path = ctx.args.cache_dir / "15m" / f"{sym}.json"
    cached = read_json(path)
    if isinstance(cached, dict) and isinstance(cached.get("bars"), list) and isinstance(cached.get("end_ms"), int):
        bars, bad = parse_klines(cached["bars"])
        ctx.st["bad_bars_15m"] += bad
        return bars, cached["end_ms"]
    if ctx.args.no_fetch:
        raise FetchError("15분봉 캐시 없음/손상(--no-fetch)")
    end = int(time.time() * 1000) // M15 * M15  # open < end 인 봉만 = 완료봉
    cur = end - ctx.args.days * DAY_MS - WARMUP_BARS * M15
    rows: list = []
    while cur < end:
        page = ctx.client.get("/fapi/v1/klines", {"symbol": sym, "interval": "15m", "startTime": cur,
                                                  "endTime": end - 1, "limit": 1500})
        if not isinstance(page, list):
            raise FetchError("15분봉 응답 형식 오류")
        if not page:
            break
        rows.extend(page)
        try:
            nxt = int(page[-1][0]) + M15
        except (TypeError, ValueError, IndexError):
            raise FetchError("15분봉 시각 형식 오류") from None
        if nxt <= cur or len(page) < 1500:
            break
        cur = nxt
    bars, bad = parse_klines(rows)
    ctx.st["bad_bars_15m"] += bad
    bars = [b for b in bars if b[0] < end and b[0] % M15 == 0]
    write_atomic(path, json.dumps({"end_ms": end, "bars": [list(b) for b in bars]}, separators=(",", ":")))
    return bars, end


def load_1m(sym: str, t0: int, limit: int, ctx: "Ctx") -> list[tuple] | None:
    path = ctx.args.cache_dir / "1m" / f"{sym}_{t0}.json"
    rows = read_json(path)
    if not isinstance(rows, list):
        if ctx.args.no_fetch:
            return None
        rows = ctx.client.get("/fapi/v1/klines", {"symbol": sym, "interval": "1m", "startTime": t0, "limit": limit})
        if not isinstance(rows, list):
            raise FetchError("1분봉 응답 형식 오류")
        write_atomic(path, json.dumps(rows, separators=(",", ":")))
        ctx.st["fetched_1m"] += 1
    bars, bad = parse_klines(rows)
    ctx.st["bad_bars_1m"] += bad
    return [b for b in bars if b[0] >= t0]


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


# ───────────────────────── 신호 재생 ─────────────────────────
@dataclass
class Ctx:
    args: argparse.Namespace
    client: Client | None
    st: Counter = field(default_factory=Counter)
    failed: list = field(default_factory=list)
    fn_errors: list = field(default_factory=list)
    period: list = field(default_factory=lambda: [None, None])


def find_trades(sym: str, bars: list[tuple], end_ms: int, eval_fn, ctx: Ctx) -> list[dict]:
    n, st = len(bars), ctx.st
    if n < LOOKBACK_24H + 2:
        st["symbols_too_short"] += 1
        return []
    t = [b[0] for b in bars]
    o = [b[1] for b in bars]
    c = [b[4] for b in bars]
    seg = [0] * n                                   # seg[k] = k 가 속한 연속 구간의 시작 인덱스
    for k in range(1, n):
        seg[k] = seg[k - 1] if t[k] - t[k - 1] == M15 else k
    st["gaps_15m"] += sum(1 for k in range(1, n) if seg[k] == k)
    pctb_map = daily_pctb(bars)
    start = end_ms - ctx.args.days * DAY_MS
    hold_bars = HOLD_MS // M15
    trades, blocked_until = [], -1
    for i in range(n - 1):
        if i < blocked_until or t[i + 1] < start:
            continue
        if i - LOOKBACK_24H < seg[i]:
            st["bars_no_24h_ref"] += 1
            continue
        chg = (c[i] / c[i - LOOKBACK_24H] - 1) * 100
        if abs(chg) < CAND_MIN_ABS_CHG:
            continue
        st["candidates"] += 1
        if seg[i + 1] != seg[i]:
            st["skip_gap_entry"] += 1
            continue
        closes = c[max(seg[i], i + 1 - SIGNAL_TAIL):i + 1] + [o[i + 1]]       # 마지막 = 진행 중 봉(진입 순간 가격)
        fired = []
        for side in ("LONG", "SHORT"):
            try:
                res = eval_fn(closes, side, chg_24h=chg)
                if not (isinstance(res, tuple) and len(res) == 4):
                    raise TypeError(f"반환 형식 이상: {type(res).__name__}")
                if res[0] is not None:
                    fired.append((side, float(res[0]), str(res[1]), str(res[2])))
            except Exception as e:  # 운영 함수 예외는 세고 보고(전체 중단 X)
                st["signal_fn_errors"] += 1
                if len(ctx.fn_errors) < 10:
                    ctx.fn_errors.append(f"{sym} {side} {type(e).__name__}: {str(e)[:120]}")
        if not fired:
            continue
        st["signals"] += 1
        if len(fired) > 1:
            st["skip_both_sides"] += 1
            continue
        side, level, route, reason = fired[0]
        path = bars[i + 1:i + 2 + hold_bars]
        res, status = simulate(side, o[i + 1], t[i + 1], path)
        if res is None:
            st[f"skip_base_{status}"] += 1
            blocked_until = i + 1 + hold_bars
            continue
        blocked_until = i + 1 + res["exit_k"]
        pb = pctb_map.get(t[i + 1] // DAY_MS - 1)   # 진입 직전 '완료된' 일봉
        trades.append({"symbol": sym, "side": side, "entry_ms": t[i + 1], "entry_price": o[i + 1],
                       "baseline": level, "route": route, "reason": reason, "chg24": chg, "pctb": pb,
                       "pos": daily_pos(pb), "base": res, "v": {}, "_path": path})
    return trades


def vkeys(windows: list[int]) -> list[tuple[str, int, float | None]]:
    out = []
    for w in windows:
        out += [(f"X{x}_W{w}", w, x) for x in EARLY_XS] + [(f"CTRL_W{w}", w, None)]
    return out


def attach_variants(tr: dict, windows: list[int], ctx: Ctx) -> None:
    path15 = tr.pop("_path")
    try:
        m1 = load_1m(tr["symbol"], tr["entry_ms"], max(windows) + 1, ctx)
    except FetchError:
        ctx.st["fetch_fail_1m"] += 1
        m1 = None
    for w in windows:
        if not m1 or len(m1) < w:
            ctx.st[f"excl_1m_missing_W{w}"] += 1
    for key, w, x in vkeys(windows):
        if not m1 or len(m1) < w:
            tr["v"][key] = None
            continue
        res, status = simulate(tr["side"], tr["entry_price"], tr["entry_ms"], path15, m1[:w], x)
        tr["v"][key] = res
        if res is None:
            ctx.st[f"excl_{key}_{status}"] += 1


# ───────────────────────── 집계·보고 ─────────────────────────
def pnl_stats(vals: list[float]) -> dict:
    n = len(vals)
    return {"n": n, "win": sum(v > 0 for v in vals) / n * 100 if n else None,
            "mean": statistics.fmean(vals) if n else None, "sum": sum(vals)}


def variant_stats(rows: list[dict], key: str, ref: str | None = None) -> dict:
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


def build_report(trades: list[dict], ctx: Ctx, windows: list[int], n_symbols: int, aborted: str) -> tuple[str, list]:
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
                v = variant_stats(rows, key, None if x is None else f"CTRL_W{_w}")
                mark = "참고" if x is None else ("✅" if v["pass"] else "❌")
                if x is not None and v["pass"]:
                    passed.append((side, pos, key, v["n"], v["delta"]))
                L.append(f"| {key} | {v['n']} | {fmt(v['win'], 1, False)} | {fmt(v['mean'])} | {fmt(v['sum'])} | "
                         f"{fmt(v['roi'])} | {fmt(v['delta'])} | " + " | ".join(fmt(s) for s in v["slices"])
                         + f" | {mark} |")
            L.append("")
    return "\n".join(L) + "\n", passed


# ───────────────────────── 진입점 ─────────────────────────
def parse_args(argv: list[str] | None) -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description="볼밴 1차 진입 뒤 1분봉 조기 손절 효과 측정(읽기 전용)")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--cache-dir", type=Path, default=here / "cache_bb_1m")
    ap.add_argument("--out-dir", type=Path, default=here / "out_bb_1m")
    ap.add_argument("--no-fetch", action="store_true", help="캐시만 사용")
    ap.add_argument("--max-symbols", type=int, default=None)
    ap.add_argument("--symbols", default="", help="A,B,...")
    ap.add_argument("--windows", default="15,30,60", help="조기 손절 감시 분(15의 배수)")
    a = ap.parse_args(argv)
    if a.days < 1:
        ap.error("--days 는 1 이상")
    try:
        a.windows = sorted({int(x) for x in a.windows.split(",") if x.strip()})
    except ValueError:
        ap.error("--windows 는 정수 목록")
    if not a.windows or any(w <= 0 or w % 15 or w > 1440 for w in a.windows):
        ap.error("--windows 는 15의 배수, 15~1440")
    if a.max_symbols is not None and a.max_symbols < 1:
        ap.error("--max-symbols 는 1 이상")
    a.symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    bad = [s for s in a.symbols if not SYM_RE.fullmatch(s)]
    if bad:
        ap.error(f"잘못된 심볼: {bad}")
    return a


def load_signal_fn():
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    from app.services.bb_entry_rules import evaluate_first_entry  # 운영 코드 그대로
    return evaluate_first_entry


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        eval_fn = load_signal_fn()
    except Exception as e:
        print(f"[치명] 운영 함수 import 실패: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    ctx = Ctx(args=args, client=None if args.no_fetch else Client())
    aborted, trades = "", []
    try:
        if args.symbols:
            symbols = args.symbols
        elif args.no_fetch:
            symbols = sorted(p.stem for p in (args.cache_dir / "15m").glob("*.json") if SYM_RE.fullmatch(p.stem))
        else:
            symbols = fetch_symbols(ctx.client)
    except (FetchError, Banned) as e:
        print(f"[치명] 심볼 목록 실패: {e}", file=sys.stderr)
        return 3 if isinstance(e, Banned) else 2
    if args.max_symbols:
        symbols = symbols[:args.max_symbols]
    total = len(symbols)
    for k, sym in enumerate(symbols, 1):
        try:
            bars, end_ms = load_15m(sym, ctx)
            if not bars:
                raise FetchError("15분봉 없음(빈 응답)")
            start = end_ms - args.days * DAY_MS
            ctx.period[0] = start if ctx.period[0] is None else min(ctx.period[0], start)
            ctx.period[1] = end_ms if ctx.period[1] is None else max(ctx.period[1], end_ms)
            for tr in find_trades(sym, bars, end_ms, eval_fn, ctx):
                attach_variants(tr, args.windows, ctx)
                trades.append(tr)
        except Banned as e:
            ctx.failed.append((sym, "418 중단(부분 결과)"))
            aborted = str(e)
        except KeyboardInterrupt:
            ctx.failed.append((sym, "사용자 중단(부분 결과)"))
            aborted = "사용자 중단(Ctrl+C)"
        except FetchError as e:
            ctx.failed.append((sym, str(e)))
        except Exception as e:  # 예상 밖 예외도 심볼 단위로 격리하되 반드시 보고
            ctx.failed.append((sym, f"예외 {type(e).__name__}: {str(e)[:160]}"))
        print(f"[{k}/{total}] {sym} 신호 누적 {ctx.st['signals']} · 확정 {len(trades)}", flush=True)
        if aborted:
            print(f"[중단] {aborted} — 캐시·부분 결과 저장 후 종료", file=sys.stderr)
            break
    try:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        write_trades_csv(args.out_dir / "trades.csv", trades, args.windows)
        report, passed = build_report(trades, ctx, args.windows, total, aborted)
        write_atomic(args.out_dir / "report.md", report)
    except OSError as e:
        print(f"[치명] 결과 저장 실패: {e}", file=sys.stderr)
        return 2
    if ctx.st["signal_fn_errors"]:
        print(f"[경고] 운영 함수 예외 {ctx.st['signal_fn_errors']}회 — report.md 확인", file=sys.stderr)
    print(f"통과 변형 {len(passed)}개" + ("" if passed else " (없음)"))
    for side, pos, key, n, d in passed:
        print(f"  ✅ {side}×{pos} {key}: n={n} Δ/건={d:+.2f} USDT")
    return 3 if aborted.startswith("HTTP 418") else (130 if aborted else 0)


if __name__ == "__main__":
    sys.exit(main())

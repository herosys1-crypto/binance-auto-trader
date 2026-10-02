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
import json
import math
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bb1m_guard_lib import (  # noqa: E402 — 순수 함수(시뮬레이션·보고)는 분리 모듈
    M1, M15, DAY_MS, HOLD_MS, simulate, utc, daily_pctb, daily_pos, vkeys, write_trades_csv, build_report)

BACKEND_DIR = Path(__file__).resolve().parents[2]
BASE_URL = "https://fapi.binance.com"
WARMUP_BARS, LOOKBACK_24H, CAND_MIN_ABS_CHG = 22 * 96, 96, 15.0  # 22일 = 일봉 BB(20) 워밍업 (Gemini 심판 9/02 unknown 쏠림 지적)
WEIGHT_LIMIT, MIN_GAP_S, MAX_RETRY = 1800, 0.1, 3
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
                if e.code == 418:                       # 무게 대기보다 먼저 — 즉시 중단
                    self.banned = True
                    raise Banned("HTTP 418 (IP 차단) — 즉시 중단") from None
                self._weight_guard(e.headers)
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
    want_end = ctx.args.end_ms                       # None = 지금까지
    if (isinstance(cached, dict) and isinstance(cached.get("bars"), list) and isinstance(cached.get("end_ms"), int)
            and (want_end is None or cached["end_ms"] == want_end)):   # 다른 기간 캐시는 재사용하지 않는다
        bars, bad = parse_klines(cached["bars"])
        ctx.st["bad_bars_15m"] += bad
        return bars, cached["end_ms"]
    if ctx.args.no_fetch:
        raise FetchError("15분봉 캐시 없음/손상/다른 기간(--no-fetch)")
    end = want_end if want_end is not None else int(time.time() * 1000) // M15 * M15  # open < end 인 봉만 = 완료봉
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
        if t[i + 1] + HOLD_MS > end_ms - M15:        # 48h 경로가 다 없는 진입 = 결과와 무관하게 제외 (빨리 끝난 건만 남는 편향 차단)
            st["skip_tail_48h"] += 1
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


def attach_variants(tr: dict, windows: list[int], ctx: Ctx) -> None:
    path15 = tr.pop("_path")
    try:
        m1 = load_1m(tr["symbol"], tr["entry_ms"], max(windows) + 1, ctx)
    except FetchError as e:
        ctx.st["fetch_fail_1m"] += 1
        ctx.failed.append((tr["symbol"], f"1분봉 {utc(tr['entry_ms'])}: {e}"))
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
    ap.add_argument("--end", default="", help="측정 끝 UTC 날짜 YYYY-MM-DD (그날 00:00 직전까지). 비우면 지금 — 기간마다 --cache-dir·--out-dir 을 따로")
    a = ap.parse_args(argv)
    if a.days < 1:
        ap.error("--days 는 1 이상")
    try:
        a.end_ms = (int(datetime.strptime(a.end, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
                    if a.end else None)
    except ValueError:
        ap.error("--end 는 YYYY-MM-DD")
    if a.end_ms is not None and a.end_ms > time.time() * 1000:
        ap.error("--end 는 오늘 이전")
    try:
        a.windows = sorted({int(x) for x in a.windows.split(",") if x.strip()})
    except ValueError:
        ap.error("--windows 는 정수 목록")
    if not a.windows or any(w <= 0 or w % 15 or w > 1440 for w in a.windows):
        ap.error("--windows 는 15의 배수, 15~1440")
    if a.max_symbols is not None and a.max_symbols < 1:
        ap.error("--max-symbols 는 1 이상")
    a.symbols = list(dict.fromkeys(s.strip().upper() for s in a.symbols.split(",") if s.strip()))  # 순서 유지 중복 제거
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

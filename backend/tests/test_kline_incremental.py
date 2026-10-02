"""kline_incremental 테스트 — Duel_Lab Claude 초안의 위험 시나리오 + 리드 추가(무작위 동등성 2,000스텝 · get_closed · 무게 보고)."""
from __future__ import annotations

import bisect
import random
import threading
import time
import unittest
import zlib
from collections import Counter

from app.services.kline_incremental import INTERVAL_MS, IncrementalKlines, request_weight

SEC, MIN, M15, H, D = 1_000, 60_000, 900_000, 3_600_000, 86_400_000
T0 = 1_700_000_000_000 // D * D                  # 자정 정렬(4h·1d 경계와도 맞음)
IV = {**INTERVAL_MS, "3m": 180_000}              # 3m: 캐시 대상이 아닌 interval(통과) 시험용


class FetchError(RuntimeError):
    pass


class FakeExchange:
    """시간이 흐르면 봉이 생기고, 진행 중 봉 값은 초 단위로 바뀌며, 확정되면 고정된다.
    klines(..., at_ms) 는 임의 시점의 '정답'을 순수 함수로 계산한다."""

    def __init__(self, now_ms: int):
        self.now_ms = now_ms
        self.markets: dict[str, tuple[int, list[int], list[int]]] = {}
        self.revised: set[tuple[str, str, int]] = set()
        self._memo: dict[tuple[str, str, int], list] = {}

    def add(self, symbol, listing_ms, halts=()):
        hs = sorted(halts)                       # [(정지 시작, 정지 끝)] — 이 구간에 열리는 봉은 없다
        self.markets[symbol] = (listing_ms, [a for a, _ in hs], [b for _, b in hs])

    def revise(self, symbol, interval, open_time):
        self.revised.add((symbol, interval, open_time))   # 확정 봉 정정(A2 위반) 흉내
        self._memo.clear()

    def clock(self) -> float:
        return self.now_ms / 1000.0

    def advance(self, ms: int) -> None:
        self.now_ms += ms

    def klines(self, symbol, interval, limit, at_ms=None):
        t = self.now_ms if at_ms is None else at_ms
        iv = IV[interval]
        listing, starts, ends = self.markets[symbol]
        first = -(-listing // iv) * iv
        ot, out = t // iv * iv, []
        while ot >= first and len(out) < limit:
            i = bisect.bisect_right(starts, ot) - 1
            if i >= 0 and ot < ends[i]:
                ot = (starts[i] - 1) // iv * iv  # 정지 구간 건너뛰기
                continue
            out.append(self._row(symbol, interval, iv, ot, t))
            ot -= iv
        out.reverse()
        return out

    def _row(self, symbol, interval, iv, ot, t):
        end = ot + iv - 1
        key = (symbol, interval, ot)
        if t >= end and key in self._memo:
            return list(self._memo[key])
        age = (min(t, end) - ot) // SEC          # 진행 중 봉은 매초 값이 바뀐다
        h = zlib.crc32(f"{symbol}|{interval}|{ot}".encode())
        o = 100 + (h % 10_000) / 100
        c = o + ((age * 7919 + h) % 2001 - 1000) / 1000
        if key in self.revised:
            c += 0.5
        hi, lo, vol = max(o, c) + 0.01, min(o, c) - 0.01, age * 0.5 + h % 97
        row = [ot, f"{o:.2f}", f"{hi:.2f}", f"{lo:.2f}", f"{c:.4f}", f"{vol:.3f}", end,
               f"{vol * c:.4f}", age + h % 50, f"{vol / 2:.3f}", f"{vol * c / 2:.4f}", "0"]
        if t >= end:
            self._memo[key] = row
        return list(row)


class CountingFetch:
    """호출을 (interval, limit) 별로 센다. script 에 예외 인스턴스나 (s,i,n)->rows 를 넣으면 다음 호출에 적용."""

    def __init__(self, ex: FakeExchange):
        self.ex = ex
        self.calls: Counter = Counter()
        self.script: list = []
        self.lock = threading.Lock()

    def __call__(self, symbol, interval, limit):
        with self.lock:
            self.calls[(interval, limit)] += 1
            action = self.script.pop(0) if self.script else None
        if isinstance(action, BaseException):
            raise action
        if action is not None:
            return action(symbol, interval, limit)
        return self.ex.klines(symbol, interval, limit)

    def n(self) -> int:
        return sum(self.calls.values())

    def weight(self, interval=None) -> int:
        return sum(request_weight(n) * c for (i, n), c in self.calls.items() if interval in (None, i))


def snap(kc, sym, iv):
    slot = kc._slots.get((sym, iv))
    e = slot.entry if slot else None
    if e is None:
        return None
    return ([list(r) for r in e.rows], list(e.times), e.cap, e.contiguous, e.full_at, e.fetched_at)


def expected_for(kc, ex, sym, iv, n, reuse_window_s):
    """엄격 모드: 지금의 fetch. 재사용 모드: 마지막 실제 fetch 시점의 fetch (그리고 그 시점이 창 안인지 확인)."""
    if reuse_window_s > 0:
        slot = kc._slots.get((sym, iv))
        e = slot.entry if slot else None
        if e is not None:
            age = ex.clock() - e.fetched_at
            assert 0 <= age <= min(IV[iv] / 1000, reuse_window_s) + 1e-6, (sym, iv, age)
            return ex.klines(sym, iv, n, at_ms=round(e.fetched_at * 1000))
    return ex.klines(sym, iv, n)


# ====================================================================== 위험 시나리오 단위 테스트
class Scenarios(unittest.TestCase):
    def setUp(self):
        self.ex = FakeExchange(T0 + 7 * MIN)     # 15m 봉 시작 7분 뒤
        self.ex.add("BTC", T0 - 400 * D)
        self.f = CountingFetch(self.ex)
        self.kc = IncrementalKlines(self.f, clock=self.ex.clock, reuse_window_s=0)

    def check(self, sym, iv, n, kc=None):
        got = (kc or self.kc).get(sym, iv, n)
        self.assertEqual(got, self.ex.klines(sym, iv, n))
        return got

    def reasons(self, kc=None):
        return (kc or self.kc).stats()["full_reasons"]

    def test_steady_cycle_uses_tail_weight1(self):
        self.check("BTC", "15m", 262)
        for _ in range(10):
            self.ex.advance(M15)
            self.check("BTC", "15m", 262)
        st = self.kc.stats()
        self.assertEqual((st["full"], st["incremental"]), (1, 10))
        self.assertEqual(self.f.calls[("15m", 262)], 1)
        self.assertEqual(self.f.calls[("15m", 5)], 10)

    def test_in_progress_bar_changes_then_finalizes(self):
        a = self.check("BTC", "15m", 262)
        self.ex.advance(3 * MIN)                 # 같은 봉 안: 마지막 행 값만 바뀜
        b = self.check("BTC", "15m", 262)
        self.assertEqual(b[-1][0], a[-1][0])
        self.assertNotEqual(b[-1], a[-1])
        self.assertEqual(b[:-1], a[:-1])
        self.ex.advance(6 * MIN)                 # 봉 확정 + 새 봉 시작
        c = self.check("BTC", "15m", 262)
        self.assertEqual(c[-2][0], a[-1][0])
        self.assertNotEqual(c[-2], b[-1])        # 확정 값으로 교체됨
        self.assertEqual(c[-2], self.ex.klines("BTC", "15m", 1, at_ms=T0 + M15 - 1)[-1])
        self.assertEqual(self.kc.stats()["incremental"], 2)

    def test_worker_paused_more_than_tail(self):
        self.check("BTC", "15m", 262)
        self.ex.advance(12 * M15)                # 12봉 쌓임 > tail 5 → 꼬리를 14로 늘려 무게 1로 따라잡음
        self.check("BTC", "15m", 262)
        self.assertEqual(self.f.calls[("15m", 14)], 1)
        self.assertEqual(self.kc.stats()["incremental"], 1)
        self.ex.advance(26 * H)                  # 104봉 > 100 → 꼬리 시도 없이 바로 전체 조회
        kc = IncrementalKlines(self.f, clock=self.ex.clock, full_refresh_s=10 ** 9, reuse_window_s=0)
        self.check("BTC", "15m", 262, kc)
        self.ex.advance(26 * H)
        self.check("BTC", "15m", 262, kc)
        self.assertEqual(self.reasons(kc)["stale_too_long"], 1)   # (초안은 6h 재조회가 먼저 걸리는 것을 놓쳤다)
        self.assertEqual(self.kc.stats()["fallback"], 0)

    def test_paused_with_lagging_clock_falls_back(self):
        lag = [0]
        kc = IncrementalKlines(self.f, clock=lambda: (self.ex.now_ms - lag[0]) / 1000, reuse_window_s=0)
        self.check("BTC", "15m", 262, kc)
        self.ex.advance(10 * M15)
        lag[0] = 10 * M15                        # 캐시는 시간이 안 흘렀다고 믿는다 → tail 5 → 겹침 없음
        self.check("BTC", "15m", 262, kc)
        self.assertEqual(self.reasons(kc)["fallback:no_overlap"], 1)

    def test_clock_backwards_forces_full(self):
        now = [self.ex.clock()]
        kc = IncrementalKlines(self.f, clock=lambda: now[0], reuse_window_s=0)
        self.check("BTC", "15m", 262, kc)
        now[0] -= 100
        self.check("BTC", "15m", 262, kc)
        self.assertEqual(self.reasons(kc)["clock_backwards"], 1)

    def test_trading_halt_gap(self):
        self.ex.add("HLT", T0 - 10 * D, halts=[(T0 + 2 * M15, T0 + 5 * M15)])   # 봉 3개 누락
        for _ in range(32):
            self.check("HLT", "15m", 20)
            self.ex.advance(M15)
        r = self.reasons()
        self.assertGreaterEqual(r.get("fallback:gap", 0), 1)   # 재개 순간 연속성 검증이 잡음
        self.assertGreaterEqual(r.get("noncontiguous", 0), 1)  # 누락이 창 안에 있는 동안은 바로 전체 조회
        inc = self.kc.stats()["incremental"]
        for _ in range(3):                                     # 누락이 창 밖으로 → 증분 재개
            self.ex.advance(M15)
            self.check("HLT", "15m", 20)
        self.assertEqual(self.kc.stats()["incremental"], inc + 3)

    def test_young_listing_fewer_rows_than_limit(self):
        self.ex.add("NEW", T0 - 9 * M15 - 5 * MIN)
        self.assertEqual(len(self.check("NEW", "15m", 262)), 10)
        self.assertEqual(len(self.check("NEW", "4h", 82)), 1)
        self.ex.advance(M15)
        self.assertEqual(len(self.check("NEW", "15m", 262)), 11)
        self.ex.advance(4 * H)
        self.assertEqual(len(self.check("NEW", "4h", 82)), 2)
        self.assertEqual(self.kc.stats()["incremental"], 2)        # 15m 1 + 4h 1 (초안 기대값 3 은 셈 오류)
        self.ex.add("MID", self.ex.now_ms // M15 * M15 - 259 * M15)   # 지금 기준 260봉 (초안은 T0 기준이라 시간이 흐른 뒤 어긋났다)
        lens = []
        for _ in range(5):
            lens.append(len(self.check("MID", "15m", 262)))
            self.ex.advance(M15)
        self.assertEqual(lens, [260, 261, 262, 262, 262])

    def test_not_listed_yet_empty_not_cached(self):
        self.ex.add("SOON", T0 + 2 * M15)
        self.assertEqual(self.check("SOON", "15m", 262), [])
        self.assertIsNone(snap(self.kc, "SOON", "15m"))
        self.ex.advance(2 * M15)
        self.assertEqual(len(self.check("SOON", "15m", 262)), 1)
        self.ex.advance(M15)
        self.assertEqual(len(self.check("SOON", "15m", 262)), 2)
        self.assertEqual(self.reasons()["no_cache"], 2)
        self.assertEqual(self.kc.stats()["incremental"], 1)

    def test_varying_limits(self):
        seq = [(82, 0), (262, 0), (82, M15), (100, 0), (262, M15), (1, 0),
               (101, 3 * MIN), (300, 0), (5, M15), (262, M15)]
        for n, adv in seq:
            self.ex.advance(adv)
            self.check("BTC", "15m", n)
        r = self.reasons()
        self.assertEqual((r["no_cache"], r["limit_grew"]), (1, 2))
        self.assertEqual(snap(self.kc, "BTC", "15m")[2], 300)
        self.assertEqual(self.kc.stats()["incremental"], 7)

    def test_full_refresh_uses_cap(self):
        kc = IncrementalKlines(self.f, clock=self.ex.clock, full_refresh_s=3600, reuse_window_s=0)
        self.check("BTC", "15m", 262, kc)
        for _ in range(3):
            self.ex.advance(M15)
            self.check("BTC", "15m", 262, kc)
        self.ex.advance(20 * MIN)
        self.check("BTC", "15m", 82, kc)          # 작은 limit 이어도 cap(262) 으로 재조회
        self.assertEqual(self.reasons(kc)["refresh_due"], 1)
        self.assertEqual(self.f.calls[("15m", 262)], 2)

    def test_fetch_exceptions_propagate_and_keep_cache(self):
        self.f.script = [FetchError("boom")]                       # 1) 캐시 없음 + 전체 조회 실패
        with self.assertRaises(FetchError):
            self.kc.get("BTC", "15m", 262)
        self.assertIsNone(snap(self.kc, "BTC", "15m"))
        self.check("BTC", "15m", 262)
        before = snap(self.kc, "BTC", "15m")
        self.ex.advance(M15)
        self.f.script = [FetchError("tail")]                       # 2) 증분 조회 실패
        with self.assertRaises(FetchError):
            self.kc.get("BTC", "15m", 262)
        self.assertEqual(snap(self.kc, "BTC", "15m"), before)
        self.f.script = [lambda s, i, n: [], FetchError("full")]   # 3) 검증 실패 → 대체 전체 조회 실패
        with self.assertRaises(FetchError):
            self.kc.get("BTC", "15m", 262)
        self.assertEqual(snap(self.kc, "BTC", "15m"), before)
        self.f.script = [TimeoutError("t")]                        # 4) 예외 종류를 바꾸지 않는다
        with self.assertRaises(TimeoutError):
            self.kc.get("BTC", "15m", 262)
        self.assertEqual(snap(self.kc, "BTC", "15m"), before)
        self.check("BTC", "15m", 262)                              # 회복
        self.assertEqual(self.kc.stats()["fetch_errors"], 4)

    def test_bad_tail_results_fall_back(self):
        def bump_closed(rows):
            r = list(rows[-3]); r[4] = "0.0001"
            return rows[:-3] + [r] + rows[-2:]
        bads = {
            "empty": (lambda rows: [], "empty"),
            "none": (lambda rows: None, "malformed"),
            "row_not_list": (lambda rows: [tuple(r) for r in rows], "malformed"),
            "bad_open_time": (lambda rows: [["x"] + r[1:] for r in rows], "malformed"),
            "fractional_open_time": (lambda rows: [[r[0] + 0.5] + r[1:] for r in rows], "malformed"),
            "reversed": (lambda rows: rows[::-1], "malformed"),
            "duplicate": (lambda rows: [rows[0]] + rows[:-1], "malformed"),
            "too_many_rows": (lambda rows: self.ex.klines("BTC", "15m", len(rows) + 3), "malformed"),
            "missing_bar_inside": (lambda rows: rows[:1] + rows[2:], "gap"),
            "stale_tail": (lambda rows: rows[:-1], "stale_tail"),          # 리드 발견: 최신 봉이 조용히 빠지던 것
            "went_backwards": (lambda rows: rows[:-2], "went_backwards"),
            "revised_closed_bar": (bump_closed, "revised"),
        }
        for name, (bad, why) in bads.items():
            with self.subTest(name):
                kc = IncrementalKlines(self.f, clock=self.ex.clock, reuse_window_s=0)
                self.check("BTC", "15m", 262, kc)
                self.ex.advance(M15)
                self.f.script = [lambda s, i, n, b=bad: b(self.ex.klines(s, i, n))]
                self.check("BTC", "15m", 262, kc)
                self.assertEqual(self.reasons(kc).get(f"fallback:{why}"), 1, self.reasons(kc))

    def test_bad_full_result_returned_but_not_cached(self):
        self.f.script = [lambda s, i, n: [["garbage"]]]
        self.assertEqual(self.kc.get("BTC", "15m", 262), [["garbage"]])
        self.assertIsNone(snap(self.kc, "BTC", "15m"))
        self.f.script = [lambda s, i, n: "oops"]
        self.assertEqual(self.kc.get("BTC", "15m", 262), "oops")
        self.check("BTC", "15m", 262)
        self.assertEqual(self.reasons()["no_cache"], 3)

    def test_revised_history(self):
        a = self.check("BTC", "15m", 262)
        self.ex.advance(M15)
        self.ex.revise("BTC", "15m", a[-2][0])   # 겹침 구간 안 확정 봉 정정 → 탐지
        self.check("BTC", "15m", 262)
        self.assertEqual(self.reasons()["fallback:revised"], 1)
        old = a[-100][0]                          # 겹침보다 오래된 봉 정정 → 증분으로는 탐지 불가(알려진 한계)
        self.ex.revise("BTC", "15m", old)
        self.ex.advance(M15)
        got, truth = self.kc.get("BTC", "15m", 262), self.ex.klines("BTC", "15m", 262)
        idx = next(i for i, r in enumerate(truth) if r[0] == old)
        self.assertNotEqual(got[idx], truth[idx])
        self.assertEqual(got[:idx] + got[idx + 1:], truth[:idx] + truth[idx + 1:])
        self.ex.advance(6 * H)                    # full_refresh_s 경과 → 복구
        self.check("BTC", "15m", 262)
        self.assertEqual(self.reasons()["refresh_due"], 1)

    def test_reuse_window(self):
        kc = IncrementalKlines(self.f, clock=self.ex.clock)        # 기본 60초
        t1 = self.ex.now_ms
        self.check("BTC", "15m", 262, kc)
        n = self.f.n()
        self.check("BTC", "15m", 82, kc)          # 같은 사이클 다른 limit → fetch 없음
        self.assertEqual(self.f.n(), n)
        self.ex.advance(30 * SEC)
        got = kc.get("BTC", "15m", 262)
        self.assertEqual(self.f.n(), n)
        self.assertEqual(got, self.ex.klines("BTC", "15m", 262, at_ms=t1))   # 마지막 실제 fetch 시점 값
        self.assertNotEqual(got[-1], self.ex.klines("BTC", "15m", 1)[-1])    # 진행 중 봉이 30초 묵음
        self.ex.advance(31 * SEC)                 # 61초 > 60 → 다시 fetch
        self.check("BTC", "15m", 262, kc)
        self.assertEqual(self.f.n(), n + 1)
        self.assertEqual(kc.stats()["reused"], 2)
        kc2 = IncrementalKlines(self.f, clock=self.ex.clock, reuse_window_s=600)
        kc2.get("BTC", "1m", 100)                 # 1m: min(60, 600) = 60초
        m = self.f.n()
        self.ex.advance(59 * SEC)
        kc2.get("BTC", "1m", 100)
        self.assertEqual(self.f.n(), m)
        self.ex.advance(2 * SEC)
        self.check("BTC", "1m", 100, kc2)
        self.assertEqual(self.f.n(), m + 1)

    def test_returned_rows_are_copies(self):
        got = self.check("BTC", "15m", 262)
        got[-1][4] = "HACKED"; got[0].append("x"); got.clear()
        self.check("BTC", "15m", 262)
        held = []
        def keep(s, i, n):
            rows = self.ex.klines(s, i, n); held.append(rows); return rows
        kc = IncrementalKlines(self.f, clock=self.ex.clock, reuse_window_s=0)
        self.f.script = [keep]
        kc.get("BTC", "15m", 262)
        for r in held[0]:
            r[4] = "MUTATED"                      # fetch 원본을 나중에 바꿔도 캐시는 무관
        self.check("BTC", "15m", 262, kc)


def closed_truth(ex, sym, iv, n, now_ms=None):
    t = ex.now_ms if now_ms is None else now_ms
    return [r for r in ex.klines(sym, iv, n) if r[0] + IV[iv] <= t]


# ====================================================================== get_closed (완료봉만, 가상매매 경로)
class Closed(unittest.TestCase):
    def setUp(self):
        self.ex = FakeExchange(T0 + 7 * MIN)
        self.ex.add("BTC", T0 - 400 * D)
        self.f = CountingFetch(self.ex)
        self.kc = IncrementalKlines(self.f, clock=self.ex.clock, reuse_window_s=0)

    def test_4h_fetches_only_when_new_bar_closes(self):
        for k in range(32):                                   # 15분 × 32 = 8시간 → 4h 봉 2개 닫힘
            self.assertEqual(self.kc.get_closed("BTC", "4h", 82, self.ex.now_ms), closed_truth(self.ex, "BTC", "4h", 82))
            self.assertEqual(self.kc.get_closed("BTC", "15m", 262, self.ex.now_ms), closed_truth(self.ex, "BTC", "15m", 262))
            self.ex.advance(M15)
        c4 = sum(c for (i, _), c in self.f.calls.items() if i == "4h")
        c15 = sum(c for (i, _), c in self.f.calls.items() if i == "15m")
        self.assertEqual(c4, 3)                               # 처음 1 + 4h 경계 2
        self.assertEqual(c15, 32)                             # 15m 은 매 사이클 새 봉이 닫힌다
        self.assertGreaterEqual(self.kc.stats()["closed_hit"], 29)

    def test_halt_no_inprogress_bar_falls_back_exact(self):
        self.ex.add("HLT", T0 - 10 * D, halts=[(T0 + M15, T0 + 4 * M15)])
        for _ in range(8):
            self.assertEqual(self.kc.get_closed("HLT", "15m", 50, self.ex.now_ms), closed_truth(self.ex, "HLT", "15m", 50))
            self.ex.advance(5 * MIN)

    def test_limit_one_and_young_listing(self):
        self.ex.add("NEW", T0 - 3 * M15 - MIN)
        for _ in range(6):
            for n in (1, 2, 262):
                self.assertEqual(self.kc.get_closed("NEW", "15m", n, self.ex.now_ms), closed_truth(self.ex, "NEW", "15m", n))
            self.ex.advance(5 * MIN)

    def test_old_revision_known_limit_recovers_on_refresh(self):
        a = self.kc.get_closed("BTC", "4h", 82, self.ex.now_ms)
        self.ex.revise("BTC", "4h", a[-50][0])               # 확정 봉 사후 정정(A2 위반) — 증분으로는 못 본다
        self.ex.advance(M15)
        self.assertNotEqual(self.kc.get_closed("BTC", "4h", 82, self.ex.now_ms), closed_truth(self.ex, "BTC", "4h", 82))
        self.ex.advance(6 * H)                                # full_refresh_s(6h) → 복구
        self.assertEqual(self.kc.get_closed("BTC", "4h", 82, self.ex.now_ms), closed_truth(self.ex, "BTC", "4h", 82))


# ====================================================================== 무작위 동등성 + 무게
class RandomEquivalence(unittest.TestCase):
    def _run(self, closed: bool, steps: int = 2000, seed: int = 7):
        rnd = random.Random(seed)
        ex = FakeExchange(T0 + 3 * MIN)
        syms = ["AAA", "BBB", "CCC"]
        ex.add("AAA", T0 - 300 * D)
        ex.add("BBB", T0 - 2 * D, halts=[(T0 + 40 * H, T0 + 41 * H), (T0 + 90 * H, T0 + 90 * H + 2 * M15)])
        ex.add("CCC", T0 + 5 * H)                             # 측정 중 상장
        f = CountingFetch(ex)
        kc = IncrementalKlines(f, clock=ex.clock, reuse_window_s=0)
        full_w = 0
        for _ in range(steps):
            ex.advance(rnd.choice([M15, M15, M15, 7 * MIN, 30 * SEC, 3 * M15, 40 * M15]))
            for sym in syms:
                for iv, n in (("15m", rnd.choice([262, 262, 82, 61])), ("4h", rnd.choice([82, 61])), ("1d", 61)):
                    if iv == "1d" and rnd.random() < 0.8:
                        continue
                    full_w += request_weight(n)
                    if closed:
                        self.assertEqual(kc.get_closed(sym, iv, n, ex.now_ms), closed_truth(ex, sym, iv, n), (sym, iv, n))
                    else:
                        self.assertEqual(kc.get(sym, iv, n), ex.klines(sym, iv, n), (sym, iv, n))
        return f.weight(), full_w, kc.stats()

    def test_get_equals_fetch(self):
        w, full_w, st = self._run(closed=False)
        print(f"[get] 무게 {w} / 매번 전체 {full_w} = {w / full_w:.1%} · {st['full_reasons']}")
        self.assertLess(w, full_w)              # get 은 4h·1d 꼬리도 무게 1 이라 절감이 작다 — 본 절감은 get_closed

    def test_get_closed_equals_compact_fetch(self):
        w, full_w, st = self._run(closed=True)
        print(f"[get_closed] 무게 {w} / 매번 전체 {full_w} = {w / full_w:.1%} · closed_hit {st['closed_hit']}")
        self.assertLess(w, full_w * 0.6)


class Threads(unittest.TestCase):
    def test_parallel_symbols_consistent(self):
        ex = FakeExchange(T0 + 7 * MIN)
        for s in "ABCDEFGH":
            ex.add(s, T0 - 50 * D)
        f = CountingFetch(ex)
        kc = IncrementalKlines(f, clock=ex.clock, reuse_window_s=0)
        errs = []

        def work(sym):
            try:
                for _ in range(20):
                    if kc.get(sym, "15m", 262) != ex.klines(sym, "15m", 262):
                        errs.append(sym)
            except Exception as e:  # noqa: BLE001
                errs.append(repr(e))
        ts = [threading.Thread(target=work, args=(s,)) for s in "ABCDEFGH"]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual(errs, [])

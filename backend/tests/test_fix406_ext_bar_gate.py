"""Fix 406 — 외부 전략 워커 봉 마감 게이트 + 완료봉 증분 캐시 (Duel ext-bar-gate).

워커의 실제 `_closed_bars` 를 가짜 거래소·가짜 Redis·주입 시계로 돌린다. 판정 코드는 바뀌지 않았으므로
「어떤 봉을 언제 판정하느냐」만 검증한다: 누락 0 · 중복 0 · 진행 중/정착 전 봉 판정 0 · 기존 경로와 같은 봉.
"""
from __future__ import annotations

import pathlib

import pytest

from app.services import bar_gate as BG
from app.services.kline_incremental import IncrementalKlines
from app.workers import external_strategies_worker as W

I = 900_000                      # 15m
H4 = 14_400_000
SETTLE = 5_000
SYMS = [f"S{i:02d}" for i in range(12)]


# ── 순수 함수 ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("now, settle, exp", [
    (2 * I - 1, 0, 0), (2 * I, 0, I), (2 * I + 1, 0, I),
    (2 * I, SETTLE, 0), (2 * I + SETTLE - 1, SETTLE, 0), (2 * I + SETTLE, SETTLE, I),
])
def test_last_closed_open(now, settle, exp):
    assert BG.last_closed_open(now, I, settle) == exp


@pytest.mark.parametrize("bad", [None, "", "x", "1.5", b"\xff", 12, "9" * 4301])
def test_should_fetch_opens_on_missing_or_broken(bad):
    assert BG.should_fetch(bad, 2 * I + SETTLE, I, SETTLE)


def test_should_fetch_is_monotonic():
    now = 3 * I + SETTLE                          # 기대 완성봉 = 2I
    assert not BG.should_fetch(str(2 * I), now, I, SETTLE)
    assert not BG.should_fetch(str(3 * I).encode(), now, I, SETTLE)   # 더 새 봉을 이미 판정 → 받지 않음
    assert BG.should_fetch(str(I), now, I, SETTLE)
    assert BG.already_judged(str(3 * I), 2 * I) and BG.already_judged(str(2 * I), 2 * I)
    assert not BG.already_judged(str(I), 2 * I) and not BG.already_judged(None, 2 * I)


@pytest.mark.parametrize("iv, settle", [(0, 0), (-1, 0), (I, -1)])
def test_invalid_args(iv, settle):
    with pytest.raises(ValueError):
        BG.last_closed_open(0, iv, settle)
    with pytest.raises(ValueError):
        BG.should_fetch(None, 0, iv, settle)


def test_check_rows():
    rows = [[0], [I]]
    assert BG.check_rows(rows, I, 2 * I - 1) is rows
    with pytest.raises(BG.BarNotSettled):
        BG.check_rows(rows, I, 2 * I)            # 마지막 행이 이미 닫힘 = 다음 봉 미개시
    for bad in ("x", [[I], [0]], [["0"]], [[True]]):
        with pytest.raises((TypeError, ValueError)):
            BG.check_rows(bad, I, 0)
    assert BG.check_rows([], I, 10 * I) == []


def test_settings_parse_and_weight():
    assert BG.parse_settle_ms("3000") == 3000 and BG.parse_settle_ms("99999") == 5000 and BG.parse_settle_ms("-1") == 5000
    assert BG.parse_flag("0") is False and BG.parse_flag("on") is True and BG.parse_flag("오타") is True
    assert [BG.kline_weight(n) for n in (5, 100, 101, 300, 1000, 1500)] == [1, 1, 2, 2, 5, 10]


# ── 워커 루프 재생 ───────────────────────────────────────────────────────────
class FakeRedis:
    def __init__(self):
        self.now_ms = 0
        self.d: dict[str, tuple[str, int]] = {}
        self.fail = False

    def get(self, k):
        if self.fail:
            raise ConnectionError("redis down")
        v = self.d.get(k)
        return v[0] if v and self.now_ms < v[1] else None

    def setex(self, k, ttl, v):
        self.d[k] = (v, self.now_ms + ttl * 1000)


class FakeBC:
    """open_delay = 거래소가 새 봉 행을 늦게 여는 시간. 행 = 바이낸스 원본 모양."""

    def __init__(self, real_now, open_delay, iv, calls):
        self.real_now, self.open_delay, self.iv, self.calls = real_now, open_delay, iv, calls

    def get_klines(self, *, symbol, interval, limit):
        self.calls.append((self.real_now, symbol, limit))
        newest = (self.real_now - self.open_delay) // self.iv * self.iv
        return [[t, "100", "101", "99", "100", "10", t + self.iv - 1, "1000", 10, "5", "500", "0"]
                for t in range(newest - (limit - 1) * self.iv, newest + 1, self.iv)]


class Sim:
    """한 프로세스 = 캐시 하나. cycle() 은 워커 루프 머리(봉 받기 → 봉 부족 → 단조 중복 검사 → 기록)를 그대로 따른다."""

    def __init__(self, monkeypatch, iv=I, interval="15m"):
        self.iv, self.interval = iv, interval
        self.r = FakeRedis()
        self.calls: list = []
        self.judged: list = []
        self.weight = 0
        self.clock = [0]
        monkeypatch.setattr(W, "_KC", IncrementalKlines(W._KFETCH, clock=lambda: self.clock[0] / 1000))

    def cycle(self, real_now, *, skew=0, open_delay=0, incremental=True, settle=SETTLE, syms=SYMS):
        now = real_now + skew
        self.clock[0] = now
        self.r.now_ms = real_now
        bc = FakeBC(real_now, open_delay, self.iv, self.calls)
        stat = {"miss": {}, "gate_skip": 0, "kl_weight": 0}
        ttl = max(W.LAST_TTL, 2 * self.iv // 1000)
        for sym in syms:
            bars, seen = W._closed_bars(bc, self.r, sym, self.interval, settle_ms=settle,
                                        incremental=incremental, stat=stat, now_ms=now)
            if bars is None:
                continue
            if len(bars) < W.MIN_BARS:
                stat["miss"]["봉 부족"] = stat["miss"].get("봉 부족", 0) + 1
                continue
            ts = int(bars[-1][0])
            # 판정 입력이 기존 kl[:-1] 과 같은 모양: 연속 완성봉 299개 (Claude 감사 — 300개면 EMA200 시작점이 달라진다)
            assert len(bars) == W.KLINE_LIMIT - 1 and int(bars[0][0]) == ts - (W.KLINE_LIMIT - 2) * self.iv, (sym, len(bars))
            if BG.already_judged(seen, ts):
                continue
            self.r.setex(W._k_last(sym), ttl, str(ts))
            self.judged.append((sym, ts, real_now, now, settle))
        self.weight += stat["kl_weight"]
        return stat

    def check_safe(self):
        for _, ts, real_now, now, settle in self.judged:
            assert ts + self.iv <= real_now, "거래소에서 아직 안 닫힌 봉을 판정"
            assert ts + self.iv <= now - settle, "정착 지연 안쪽 봉을 판정"
        keys = [(s, ts) for s, ts, *_ in self.judged]
        assert len(keys) == len(set(keys)), "같은 봉 중복 판정"


def old_code_judged(real_nows, iv=I):
    """Fix 406 이전 루프(매번 300봉, kl[:-1], == 비교) — 비교 기준."""
    r, out = FakeRedis(), []
    for t in real_nows:
        r.now_ms = t
        bc = FakeBC(t, 0, iv, [])
        for sym in SYMS:
            kl = bc.get_klines(symbol=sym, interval="15m", limit=W.KLINE_LIMIT)
            bars = kl[:-1]
            ts = int(bars[-1][0])
            if r.get(W._k_last(sym)) == str(ts):
                continue
            r.setex(W._k_last(sym), W.LAST_TTL, str(ts))
            out.append((sym, ts))
    return out


def test_four_hours_same_bars_as_old_code_and_weight(monkeypatch):
    start = 400 * I + SETTLE
    times = [start + m * 60_000 for m in range(240)]
    new, legacy = Sim(monkeypatch), Sim(monkeypatch)
    for t in times:
        new.cycle(t)
        legacy.cycle(t, incremental=False)
    want = {(s, (399 + n) * I) for s in SYMS for n in range(16)}
    got = [(s, ts) for s, ts, *_ in new.judged]
    assert len(got) == 16 * len(SYMS) and set(got) == want
    assert got == [(s, ts) for s, ts, *_ in legacy.judged] == old_code_judged(times)
    new.check_safe()
    old_w = 240 * len(SYMS) * BG.kline_weight(W.KLINE_LIMIT)
    print(f"\n[Fix406] 4시간 · {len(SYMS)}종목: 무게 {new.weight} / 기존 {old_w} = {new.weight / old_w:.2%} (게이트만 {legacy.weight / old_w:.2%})")
    assert new.weight < old_w * 0.06 and legacy.weight < old_w * 0.10


@pytest.mark.parametrize("open_delay, skew", [(3_000, 0), (0, 3_000), (3_000, 3_000), (7_000, 0), (7_000, 4_000), (0, -20_000)])
@pytest.mark.parametrize("phase_s", [0, 2, 4, 6, 9, 30, 59])
@pytest.mark.parametrize("incremental", [True, False])
def test_delay_skew_phase_sweep_no_early_no_dup_no_miss(monkeypatch, open_delay, skew, phase_s, incremental):
    sim = Sim(monkeypatch)
    start = 400 * I + phase_s * 1000
    for m in range(240):
        sim.cycle(start + m * 60_000, skew=skew, open_delay=open_delay, incremental=incremental)
    sim.check_safe()
    per_sym = {}
    for s, ts, *_ in sim.judged:
        per_sym.setdefault(s, []).append(ts)
    for s in SYMS:                                 # 첫 판정 이후 봉은 하나도 빠지지 않는다
        seq = per_sym[s]
        assert seq == sorted(seq) and all(b - a == I for a, b in zip(seq, seq[1:])), (s, seq[:3])
        assert len(seq) >= 15


def test_deploy_transition_old_code_judged_newer_bar_not_rejudged(monkeypatch):
    """Claude 감사 치명 지적: 옛 코드가 경계 1초 뒤 새 봉(400I)을 판정해 둔 상태에서 새 코드(정착 5초)가 돌면
    == 비교로는 399I 를 다시 판정했다(중복 주문 가능). 단조 비교로 막는다."""
    sim = Sim(monkeypatch)
    sim.r.now_ms = 401 * I + 1_000                 # 옛 코드가 경계 1초 뒤 기록
    for s in SYMS:
        sim.r.setex(W._k_last(s), W.LAST_TTL, str(400 * I))
    sim.cycle(401 * I + 2_000)                     # 판정 시각 401I−3s → 기대 완성봉 399I < 기록 400I
    assert sim.judged == [] and sim.calls == []    # fetch 도 없음
    sim.cycle(401 * I + 6_000)                     # 이제 기대 400I = 기록 → 역시 없음
    assert sim.judged == []
    sim.cycle(402 * I + 6_000)
    assert {ts for _, ts, *_ in sim.judged} == {401 * I}


def test_settle_raised_at_runtime_no_rejudge(monkeypatch):
    sim = Sim(monkeypatch)
    t = 500 * I + 6_000
    sim.cycle(t, settle=0)
    sim.cycle(t + 60_000, settle=60_000)          # 정착 지연을 0 → 60초로 키움
    keys = [(s, ts) for s, ts, *_ in sim.judged]
    assert len(keys) == len(set(keys)) == len(SYMS)


def test_redis_failure_opens_gate_and_does_not_crash(monkeypatch):
    sim = Sim(monkeypatch)
    sim.cycle(400 * I + SETTLE)
    sim.r.fail = True
    stat = sim.cycle(400 * I + SETTLE + 60_000)   # 기록을 못 읽으면 게이트가 열린다(기존 동작) — 죽지 않는다
    assert stat["gate_skip"] == 0
    assert sim.weight == len(SYMS) * BG.kline_weight(W.KLINE_LIMIT)   # 완성봉은 캐시가 줘서 추가 무게 0
    sim2 = Sim(monkeypatch)
    sim2.r.fail = True                             # 캐시도 비고 Redis 도 죽음 → 기존처럼 받는다
    sim2.cycle(400 * I + SETTLE)
    assert len(sim2.calls) == len(SYMS)


def test_4h_interval_ttl_longer_than_bar(monkeypatch):
    """LAST_TTL(3h) < 4h 봉이면 기록이 먼저 사라져 같은 봉을 다시 판정했다 → ttl = max(3h, 2봉)."""
    sim = Sim(monkeypatch, iv=H4, interval="4h")
    start = 300 * H4 + SETTLE
    for m in range(0, 12 * 60, 1):                 # 12시간, 1분 간격
        sim.cycle(start + m * 60_000, syms=SYMS[:3])
    sim.check_safe()
    assert {ts for _, ts, *_ in sim.judged} == {299 * H4, 300 * H4, 301 * H4}


def test_worker_loop_pins():
    """루프 머리가 이 테스트의 재생(Sim.cycle)과 같은 순서인지 고정."""
    src = pathlib.Path(W.__file__).read_text(encoding="utf-8")
    loop = src[src.index("for sym in universe:"):src.index("c = [float(b[4]) for b in bars]")]
    order = ["_closed_bars(bc, r, sym, interval", "if bars is None:", "len(bars) < MIN_BARS", "BG.already_judged(seen, ts)",
             "r.setex(_k_last(sym), last_ttl, str(ts))"]
    pos = [loop.index(p) for p in order]
    assert pos == sorted(pos)
    assert "bc.get_klines(symbol=sym, interval=interval, limit=KLINE_LIMIT)" not in loop   # 루프에서 직접 받지 않는다

"""Fix 446 — 재시작해도 일봉 캐시 유지 (Redis 저장소 + 일봉 전체 재조회 주기)."""
from __future__ import annotations

import pathlib

from app.services import kline_store as KS
from app.services.kline_incremental import INTERVAL_MS, IncrementalKlines

DAY = INTERVAL_MS["1d"]
APP = pathlib.Path(KS.__file__).resolve().parents[1]
T0 = 1_760_000_000_000 // DAY * DAY            # 어느 날 00:00 UTC (ms)


class _Clock:
    def __init__(self, ms):
        self.ms = ms

    def __call__(self):
        return self.ms / 1000.0


class _Ex:
    """가짜 거래소 — 가장 최근 n개 일봉 · 마지막은 진행 중(값이 시각에 따라 바뀜)."""
    def __init__(self, clock, start=T0 - 400 * DAY):
        self.clock, self.start, self.calls = clock, start, []
        self.revise: dict[int, str] = {}

    def row(self, t, now):
        live = t + DAY > now
        c = f"{(t // DAY) % 97 + (now % DAY) / DAY if live else (t // DAY) % 97:.4f}"
        if t in self.revise:
            c = self.revise[t]
        return [t, "1", "2", "0.5", c, "10", t + DAY - 1, "5", 3, "1", "1", "0"]

    def __call__(self, sym, interval, n):
        self.calls.append(n)
        now = self.clock.ms
        last = now // DAY * DAY
        ts = [t for t in range(max(self.start, last - (n - 1) * DAY), last + 1, DAY)]
        return [self.row(t, now) for t in ts]

    def closed(self, n):
        now = self.clock.ms
        return [r for r in self(None, "1d", n) if r[0] + DAY <= now]


class _MemStore:
    def __init__(self, intervals=frozenset({"1d"})):
        self.d, self.intervals, self.fail_load, self.fail_save = {}, intervals, False, False

    def load(self, s, i):
        if self.fail_load:
            raise RuntimeError("redis down")
        return self.d.get((s, i))

    def save(self, s, i, v):
        if self.fail_save:
            raise RuntimeError("redis down")
        import copy
        self.d[(s, i)] = copy.deepcopy(v)


def _kc(ex, clock, store=None, refresh_h=168):
    kc = IncrementalKlines(ex, clock=clock, store=store)
    if refresh_h is not None:
        kc.set_full_refresh("1d", refresh_h * 3600)
    return kc


def test_restart_reuses_stored_daily():
    clk = _Clock(T0 + 10 * 60_000)
    ex, st = _Ex(clk), _MemStore()
    a = _kc(ex, clk, st)
    assert a.get_closed("X", "1d", 300, clk.ms) == ex.closed(300)
    assert ex.calls[-1] == 300 and ("X", "1d") in st.d
    # 재시작(새 캐시) — 같은 날: fetch 없이 완료봉
    clk.ms += 5 * 3600_000
    b = _kc(ex, clk, st)
    assert b.get_closed("X", "1d", 300, clk.ms) == ex.closed(300)
    assert b.stats()["fetch_calls"] == 0 and b.stats()["restored"] == 1   # 실제 fetch 0번
    # 다음 날 마감 뒤: 꼬리(무게 1)만
    clk.ms = T0 + DAY + 10 * 60_000
    w0 = b.stats()["weight"]
    assert b.get_closed("X", "1d", 300, clk.ms) == ex.closed(300)
    assert b.stats()["weight"] - w0 == 1 and b.stats()["incremental"] == 1


def test_daily_refresh_period_makes_next_day_incremental():
    clk = _Clock(T0 + 10 * 60_000)
    ex = _Ex(clk)
    old = _kc(ex, clk, None, refresh_h=None)                  # 예전 = 6시간 → 다음 날 전체 조회(무게 2)
    new = _kc(ex, clk, None)
    for kc in (old, new):
        kc.get_closed("X", "1d", 300, clk.ms)
    clk.ms += DAY
    w = [kc.stats()["weight"] for kc in (old, new)]
    for kc in (old, new):
        assert kc.get_closed("X", "1d", 300, clk.ms) == ex.closed(300)
    assert old.stats()["weight"] - w[0] == 2 and new.stats()["weight"] - w[1] == 1
    clk.ms += 8 * DAY                                          # 7일 지나면 전체 재조회
    w1 = new.stats()["weight"]
    assert new.get_closed("X", "1d", 300, clk.ms) == ex.closed(300)
    assert new.stats()["weight"] - w1 == 2 and new.stats()["full_reasons"].get("refresh_due") == 1


def test_corrupt_or_future_store_rejected():
    clk = _Clock(T0 + 10 * 60_000)
    ex = _Ex(clk)
    good = _MemStore()
    _kc(ex, clk, good).get_closed("X", "1d", 300, clk.ms)
    base = good.d[("X", "1d")]
    bad = [None, "x", {"rows": "x", "cap": 300, "full_at": 1.0, "fetched_at": 1.0},
           dict(base, cap=True), dict(base, cap=10),                         # 행 수 > cap
           dict(base, full_at=clk.ms / 1000 + 60, fetched_at=clk.ms / 1000 + 60),   # 미래
           dict(base, full_at=base["fetched_at"] + 1),                       # 뒤바뀜
           dict(base, fetched_at=float("nan")),
           dict(base, rows=list(reversed(base["rows"]))),
           dict(base, rows=base["rows"] + [[base["rows"][-1][0] + DAY] + base["rows"][-1][1:]])]   # 아직 안 열린 봉
    for i, v in enumerate(bad):
        st = _MemStore()
        st.d[("X", "1d")] = v
        kc = _kc(ex, clk, st)
        assert kc.get_closed("X", "1d", 300, clk.ms) == ex.closed(300), i
        s = kc.stats()
        assert s["restored"] == 0 and s["full"] == 1, (i, s)


def test_stale_store_with_revised_bar_falls_back_to_full():
    clk = _Clock(T0 + 10 * 60_000)
    ex, st = _Ex(clk), _MemStore()
    _kc(ex, clk, st).get_closed("X", "1d", 300, clk.ms)
    clk.ms += DAY
    ex.revise[T0 - DAY] = "999"                                 # 저장 뒤 거래소가 확정 봉을 정정 (겹침 구간 안)
    kc = _kc(ex, clk, st)
    assert kc.get_closed("X", "1d", 300, clk.ms) == ex.closed(300)
    assert kc.stats()["restored"] == 1 and kc.stats()["fallback"] == 1


def test_store_failure_is_fail_open_and_15m_not_stored():
    clk = _Clock(T0 + 10 * 60_000)
    ex, st = _Ex(clk), _MemStore()
    st.fail_load = st.fail_save = True
    kc = _kc(ex, clk, st)
    assert kc.get_closed("X", "1d", 300, clk.ms) == ex.closed(300)
    assert kc.stats()["store_errors"] == 2                      # 읽기 1 + 쓰기 1, 예외는 안 샌다
    st2 = _MemStore()
    kc2 = IncrementalKlines(lambda s, i, n: [], clock=clk, store=st2)
    kc2.get("X", "15m", 10)
    assert st2.d == {}


def test_store_read_once_per_slot():
    clk = _Clock(T0 + 10 * 60_000)
    ex = _Ex(clk)
    st = _MemStore()
    loads = []
    orig = st.load
    st.load = lambda s, i: loads.append(1) or orig(s, i)
    kc = _kc(ex, clk, st)
    kc.get_closed("X", "1d", 300, clk.ms)
    kc.get_closed("X", "1d", 300, clk.ms)
    assert len(loads) == 1


class _FakeRedis:
    def __init__(self):
        self.d, self.ttl = {}, {}

    def get(self, k):
        return self.d.get(k)

    def setex(self, k, ttl, v):
        self.d[k], self.ttl[k] = v, ttl


def test_redis_store_roundtrip_and_disable():
    r = _FakeRedis()
    st = KS.RedisKlineStore("paper", client=lambda: r)
    clk = _Clock(T0 + 10 * 60_000)
    ex = _Ex(clk)
    a = IncrementalKlines(ex, clock=clk, store=st)
    a.get_closed("X", "1d", 300, clk.ms)
    k = "kc:paper:1d:X"
    assert k in r.d and r.ttl[k] == KS.TTL_S and len(r.d[k]) < 20_000       # 압축됨
    b = IncrementalKlines(ex, clock=clk, store=st)
    assert b.get_closed("X", "1d", 300, clk.ms) == ex.closed(300) and b.stats()["restored"] == 1
    r.d[k] = "!!not base64!!"
    assert st.load("X", "1d") is None
    st.enabled = False
    assert st.intervals == frozenset()
    c = IncrementalKlines(ex, clock=clk, store=st)
    c.get_closed("Y", "1d", 300, clk.ms)
    assert "kc:paper:1d:Y" not in r.d


def test_apply_settings_bounds():
    kc = IncrementalKlines(lambda s, i, n: [])
    st = KS.RedisKlineStore("t", client=lambda: None)
    assert KS.apply_settings(kc, st, lambda k: None) == {"persist": True, "refresh_h": 168.0}
    assert KS.apply_settings(kc, st, {KS.S_PERSIST: "0", KS.S_REFRESH_H: "6"}.get) == {"persist": False, "refresh_h": 6.0}
    for bad in ("1", "999", "nan", "x"):
        assert KS.apply_settings(kc, st, {KS.S_REFRESH_H: bad}.get)["refresh_h"] == 168.0
    assert KS.apply_settings(kc, st, lambda k: 1 / 0) == {"persist": True, "refresh_h": 168.0}


def test_worker_wiring():
    for name, prefix in (("paper_trading_worker.py", '"paper"'), ("external_strategies_worker.py", '"ext"')):
        src = (APP / "workers" / name).read_text(encoding="utf-8")
        assert f"KS.RedisKlineStore({prefix})" in src and "store=_KC_STORE" in src
        assert "KS.apply_settings(_KC, _KC_STORE, KS.db_getter(db))" in src


def test_truncated_store_rejected_and_forget_does_not_revive():
    clk = _Clock(T0 + 10 * 60_000)
    ex, st = _Ex(clk), _MemStore()
    _kc(ex, clk, st).get_closed("X", "1d", 300, clk.ms)
    d = st.d[("X", "1d")]
    st.d[("X", "1d")] = dict(d, rows=d["rows"][-100:])           # 앞이 잘린 값 (형식은 맞음)
    clk.ms += DAY
    kc = _kc(ex, clk, st)
    assert kc.get_closed("X", "1d", 300, clk.ms) == ex.closed(300)
    assert kc.stats()["restored"] == 0 and kc.stats()["restore_rejected"] == 1
    kc.forget()
    n = kc.stats()["full"]
    assert kc.get_closed("X", "1d", 50, clk.ms) == ex.closed(50)
    assert kc.stats()["restored"] == 0 and kc.stats()["full"] == n + 1    # 저장소가 되살리지 않는다


def test_known_limit_old_revision_waits_for_refresh():
    """한계(문서화): 겹침 구간 밖 오래된 확정 봉 정정은 일봉 전체 재조회 주기(기본 7일)까지 남는다."""
    clk = _Clock(T0 + 10 * 60_000)
    ex = _Ex(clk)
    kc = _kc(ex, clk, None)
    kc.get_closed("X", "1d", 300, clk.ms)
    ex.revise[T0 - 50 * DAY] = "999"
    clk.ms += DAY
    assert kc.get_closed("X", "1d", 300, clk.ms) != ex.closed(300)
    clk.ms += 7 * DAY
    assert kc.get_closed("X", "1d", 300, clk.ms) == ex.closed(300)

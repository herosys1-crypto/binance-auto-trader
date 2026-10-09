"""Fix 408 감시 종목 봉 스냅샷 — Duel_Lab ext-universe-cache GPT 초안 테스트 + 리드 추가."""
import json
from datetime import datetime

import pytest

from app.services import bar_gate as BG
from app.services.universe_cache import cached_universe


I = 15 * 60 * 1000
BASE = 100 * I + 6000
KEY = "ext:universe"


class FakeRedis:
    def __init__(self):
        self.now_ms = BASE
        self.data = {}
        self.writes = []
        self.get_calls = 0
        self.fail_get = False
        self.fail_set = False
        self.return_bytes = False

    def get(self, key):
        self.get_calls += 1
        if self.fail_get:
            raise ConnectionError("get failed")
        item = self.data.get(key)
        if item is None:
            return None
        value, expires_ms = item
        if self.now_ms >= expires_ms:
            del self.data[key]
            return None
        if self.return_bytes and isinstance(value, str):
            return value.encode("utf-8")
        return value

    def setex(self, key, ttl, value):
        if self.fail_set:
            raise ConnectionError("setex failed")
        self.writes.append((key, ttl, value))
        self.data[key] = (value, self.now_ms + ttl * 1000)


class Compute:
    def __init__(self, symbols=None):
        self.calls = 0
        self.symbols = ["BTCUSDT"] if symbols is None else symbols

    def __call__(self):
        self.calls += 1
        return list(self.symbols)


def run(r, compute, now_ms=BASE, **changes):
    r.now_ms = now_ms
    arguments = {
        "interval": "15m",
        "interval_ms": I,
        "settle_ms": 5000,
        "top_n": 60,
        "min_qv": 5_000_000.0,
        "enabled": 1,
        "now_ms": now_ms,
        "compute": compute,
    }
    arguments.update(changes)
    return cached_universe(r, **arguments)


def test_fifteen_one_minute_cycles_compute_once():
    r, compute = FakeRedis(), Compute()
    sources = []

    for minute in range(15):
        symbols, source = run(r, compute, BASE + minute * 60_000)
        assert symbols == ["BTCUSDT"]
        sources.append(source)

    assert compute.calls == 1
    assert sources == ["computed"] + ["snapshot"] * 14

    snapshot = json.loads(r.data[KEY][0])
    assert snapshot == {
        "bar": 99 * I,
        "interval": "15m",
        "top_n": 60,
        "min_qv": 5_000_000.0,
        "symbols": ["BTCUSDT"],
        "at": snapshot["at"],
    }
    assert datetime.fromisoformat(snapshot["at"]).utcoffset().total_seconds() == 0
    assert r.writes[0][1] == 3600


def test_four_hours_weight(capsys):
    r, compute = FakeRedis(), Compute()
    sources = []

    for minute in range(240):
        _, source = run(r, compute, BASE + minute * 60_000)
        sources.append(source)

    assert compute.calls == 16
    assert sources.count("computed") == 16
    assert sources.count("snapshot") == 224

    old_weight = 240 * 40
    new_weight = compute.calls * 40
    ratio = new_weight / old_weight
    print(
        f"4h weight: {old_weight} -> {new_weight}; "
        f"ratio={ratio:.2%}; reduction={1 - ratio:.2%}"
    )
    output = capsys.readouterr().out
    assert "9600 -> 640" in output
    assert "ratio=6.67%" in output
    # pytest -s에서도 비율을 표시한다.
    print(output, end="")


def test_settle_boundary():
    r, compute = FakeRedis(), Compute()
    boundary = 101 * I

    # 경계 이전에 이전 완성봉 스냅샷을 만든다.
    assert run(r, compute, boundary - 1000)[1] == "computed"
    previous_bar = json.loads(r.data[KEY][0])["bar"]

    # 경계 +3초: settle 5초 안쪽이므로 이전 스냅샷 유지.
    assert run(r, compute, boundary + 3000)[1] == "snapshot"
    assert compute.calls == 1
    assert json.loads(r.data[KEY][0])["bar"] == previous_bar

    # 경계 +6초: 새 완성봉으로 전환.
    assert run(r, compute, boundary + 6000)[1] == "computed"
    assert compute.calls == 2
    assert json.loads(r.data[KEY][0])["bar"] == previous_bar + I


@pytest.mark.parametrize(
    "changes",
    [
        {"top_n": 61},
        {"min_qv": 6_000_000.0},
        # 같은 길이를 전달해도 interval 문자열이 다르면 미스.
        {"interval": "other-label", "interval_ms": I},
        {"interval": "1h", "interval_ms": 60 * 60 * 1000},
    ],
)
def test_setting_change_recomputes_immediately(changes):
    r, compute = FakeRedis(), Compute()
    run(r, compute)

    assert run(r, compute, BASE + 60_000, **changes)[1] == "computed"
    assert compute.calls == 2
    assert run(r, compute, BASE + 120_000, **changes)[1] == "snapshot"


def test_empty_result_is_not_written_and_next_cycle_retries():
    r, compute = FakeRedis(), Compute([])

    assert run(r, compute) == ([], "computed")
    assert KEY not in r.data
    assert r.writes == []

    compute.symbols = ["ETHUSDT"]
    assert run(r, compute, BASE + 60_000) == (["ETHUSDT"], "computed")
    assert compute.calls == 2
    assert run(r, compute, BASE + 120_000)[1] == "snapshot"


def test_empty_result_does_not_overwrite_previous_bar_snapshot():
    r, compute = FakeRedis(), Compute()
    run(r, compute)
    previous = r.data[KEY]

    compute.symbols = []
    assert run(r, compute, BASE + I) == ([], "computed")
    assert r.data[KEY] == previous

    assert run(r, compute, BASE + I + 60_000) == ([], "computed")
    assert compute.calls == 3


@pytest.mark.parametrize("failure", ["get", "setex"])
def test_redis_failure_preserves_compute_result(failure):
    r, compute = FakeRedis(), Compute()
    r.fail_get = failure == "get"
    r.fail_set = failure == "setex"

    assert run(r, compute) == (["BTCUSDT"], "computed")
    assert run(r, compute, BASE + 60_000) == (["BTCUSDT"], "computed")
    assert compute.calls == 2


@pytest.mark.parametrize(
    "raw",
    [
        "{broken",
        b"\xff",
        "null",
        "[]",
        "{}",
        json.dumps({
            "bar": 99 * I,
            "interval": "15m",
            "top_n": 60,
            "min_qv": 5_000_000.0,
            "symbols": "BTCUSDT",  # リストでない、不正なスナップショット
            "at": "1970-01-01T00:00:00+00:00",
        }),
    ],
)
def test_invalid_snapshot_recomputes(raw):
    r, compute = FakeRedis(), Compute()
    r.data[KEY] = (raw, BASE + 3_600_000)

    assert run(r, compute) == (["BTCUSDT"], "computed")
    assert compute.calls == 1
    assert run(r, compute, BASE + 60_000)[1] == "snapshot"


def test_bytes_snapshot_is_a_hit():
    r, compute = FakeRedis(), Compute()
    run(r, compute)
    r.return_bytes = True

    assert run(r, compute, BASE + 60_000) == (["BTCUSDT"], "snapshot")
    assert compute.calls == 1


@pytest.mark.parametrize(
    "enabled",
    [0, False, "0", "false", "OFF", " no "],
)
def test_disabled_always_computes_without_redis(enabled):
    r, compute = FakeRedis(), Compute()

    for minute in range(3):
        assert run(
            r, compute, BASE + minute * 60_000, enabled=enabled
        )[1] == "computed"

    assert compute.calls == 3
    assert r.get_calls == 0
    assert r.writes == []


@pytest.mark.parametrize(
    "enabled",
    [1, True, "1", "true", " ON ", "yes", None, "", "unknown"],
)
def test_enabled_and_unrecognized_values_use_default_on(enabled):
    r, compute = FakeRedis(), Compute()

    assert run(r, compute, enabled=enabled)[1] == "computed"
    assert run(r, compute, BASE + 60_000, enabled=enabled)[1] == "snapshot"
    assert compute.calls == 1


def test_unknown_interval_always_computes_without_redis():
    r, compute = FakeRedis(), Compute()

    for minute in range(3):
        assert run(
            r,
            compute,
            BASE + minute * 60_000,
            interval="unknown",
            interval_ms=None,
        )[1] == "computed"

    assert compute.calls == 3
    assert r.get_calls == 0
    assert r.writes == []


def test_ttl_is_twice_interval_with_one_hour_minimum():
    r, compute = FakeRedis(), Compute()
    run(r, compute, interval="4h", interval_ms=4 * 60 * 60 * 1000)
    assert r.writes[0][1] == 8 * 60 * 60


def test_compute_exception_is_not_swallowed():
    def compute():
        raise RuntimeError("original universe failed")

    with pytest.raises(RuntimeError, match="original universe failed"):
        run(FakeRedis(), compute)


def test_mid_bar_new_top_symbol_is_judged_from_next_bar():
    r, compute = FakeRedis(), Compute(["BTCUSDT"])
    seen = set()
    judged = []

    def judge_once(symbols, now_ms):
        # _closed_bars의 완성봉별 중복 판정 방지 계약을 모델링한다.
        bar = ((now_ms - 5000) // I - 1) * I
        for symbol in symbols:
            target = (symbol, bar)
            if target not in seen:
                seen.add(target)
                judged.append(target)

    symbols, _ = run(r, compute, BASE, top_n=1)
    judge_once(symbols, BASE)
    first_bar = 99 * I
    assert judged == [("BTCUSDT", first_bar)]

    # 같은 봉 중간에 NEWUSDT가 거래대금 순위 1위로 진입.
    middle = BASE + 5 * 60_000
    compute.symbols = ["NEWUSDT"]
    symbols, source = run(r, compute, middle, top_n=1)
    assert source == "snapshot"
    assert symbols == ["BTCUSDT"]
    judge_once(symbols, middle)

    # 동일한 판정 대상 봉이고, BTCUSDT는 재판정하지 않는다.
    assert judged == [("BTCUSDT", first_bar)]
    assert compute.calls == 1

    # 기존 매분 계산 방식이라면 NEWUSDT도 같은 봉에서 판정 가능했다.
    legacy_symbols = list(compute.symbols)
    legacy_bar = ((middle - 5000) // I - 1) * I
    assert legacy_symbols == ["NEWUSDT"]
    assert legacy_bar == first_bar
    assert ("NEWUSDT", legacy_bar) not in seen

    # 새 방식에서는 다음 완성봉으로 전환한 뒤 처음 판정한다.
    next_cycle = BASE + I
    symbols, source = run(r, compute, next_cycle, top_n=1)
    assert source == "computed"
    judge_once(symbols, next_cycle)
    assert judged == [
        ("BTCUSDT", first_bar),
        ("NEWUSDT", first_bar + I),
    ]
    assert compute.calls == 2


# ── 리드 추가 (Claude 감사 수용분) ─────────────────────────────────────────
@pytest.mark.parametrize("offset", [0, 1, 4_999, 5_000, 5_001, I - 1])
def test_bar_matches_bar_gate(offset):
    """스냅샷 봉 = _closed_bars 가 판정하는 봉 (같은 함수·같은 시각) — 복제 계산이면 경계에서 어긋난다."""
    r = FakeRedis()
    now = 200 * I + offset
    cached_universe(r, interval="15m", interval_ms=I, settle_ms=5_000, top_n=60, min_qv=5e6, enabled="1",
                    now_ms=now, compute=lambda: ["AUSDT"])
    snap = json.loads(r.data[KEY][0] if isinstance(r.data[KEY], tuple) else r.data[KEY])
    assert snap["bar"] == BG.last_closed_open(now, I, 5_000)


@pytest.mark.parametrize("raw, on", [("0.0", True), ("false", False), ("OFF", False), (None, True), ("abc", True)])
def test_flag_rules_are_bar_gate_rules(raw, on):
    assert (BG.parse_flag(raw, default=True)) is on
    calls = []
    r = FakeRedis()
    for _ in range(2):
        cached_universe(r, interval="15m", interval_ms=I, settle_ms=0, top_n=60, min_qv=5e6, enabled=raw,
                        now_ms=BASE, compute=lambda: calls.append(1) or ["AUSDT"])
    assert len(calls) == (1 if on else 2)


def test_worker_wiring_pins():
    import pathlib
    from app.services import external_strategies as ES
    from app.workers import external_strategies_worker as W
    assert ES.SETTINGS["ext_universe_per_bar"][0] == "1"                 # 미등록이면 ES.setting 이 KeyError → 사이클 정지
    src = pathlib.Path(W.__file__).read_text(encoding="utf-8")
    assert "cycle_now = _now_ms()" in src and "now_ms=cycle_now, last_key=_k_last_iv(sym, interval))" in src and "now_ms=cycle_now," in src   # Fix 427
    assert "universe = _universe(" not in src                              # 매분 직접 계산이 남아 있지 않다
    assert "compute=lambda: _universe(bc, db, top_n, min_qv)" in src

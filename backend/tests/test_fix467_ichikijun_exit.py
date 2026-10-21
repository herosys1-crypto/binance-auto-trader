"""🗾 Fix 467 — 일목 예약 인스턴스의 실주문 「기준선 재이탈 청산」 (기본 shadow)."""
from __future__ import annotations

import ast
import pathlib
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import ichikijun_exit as EX
from app.services import ichimoku_kijun as IK

ROOT = pathlib.Path(EX.__file__).resolve().parents[2]
H4 = 4 * 3_600_000


def _bars(closes, kj=100.0):
    """기준선을 고정값으로 덮은 Bars (판정만 본다)."""
    kl = [[i * H4, f"{c}", f"{c * 1.01}", f"{c * 0.99}", f"{c}", "1"] for i, c in enumerate(closes)]
    B = IK.bars_from(kl)
    B.ind["kj"] = [kj] * len(closes)
    return B


def test_mode_default_shadow():
    assert EX.mode_of(None) == "shadow" and EX.mode_of("ON") == "on" and EX.mode_of("x") == "shadow"
    assert EX.mode_of("off") == "off"


def test_is_target_only_kj_variants():
    m = {"variant": "4h_loose_pb_r2kj", "entry_bar_ts": 5}
    assert EX.is_target("ichikijun", m).key == "4h_loose_pb_r2kj"
    assert EX.is_target("ichikijun", {"variant": "4h_loose_pb_r2", "entry_bar_ts": 5}) is None   # 기준선 청산 없는 변형
    assert EX.is_target(None, m) is None and EX.is_target("ichikijun", None) is None
    assert EX.is_target("ichikijun", {"variant": "4h_loose_pb_r2kj"}) is None                   # 진입 봉 모름
    assert EX.is_target("ichikijun", {"variant": "4h_loose_pb_r2kj", "entry_bar_ts": 0}) is not None  # 0 도 값


def test_kijun_break_boundary_entry_and_missed():
    B = _bars([101, 99, 100, 102, 99.9])          # 0=진입 · 1 이탈(아래) · 2 같음 · 4 이탈
    hit, info = EX.kijun_break(B, entry_bar_ts=0, last_judged_ts=None, side="LONG")
    assert hit and info["bar_ts"] == H4             # 진입 봉 자체는 제외, 다음 봉
    hit, info = EX.kijun_break(B, 0, last_judged_ts=H4, side="LONG")
    assert hit and info["bar_ts"] == 4 * H4         # 판정한 봉 뒤만 · 같음(100)=이탈 아님
    assert EX.kijun_break(B, 0, 4 * H4, "LONG") == (False, {})
    S = _bars([99, 100, 100.5])
    assert EX.kijun_break(S, 0, None, "SHORT")[1]["bar_ts"] == 2 * H4      # SHORT: 종가 > 기준선


# ───────── 워커 (전부 가짜 — 주문 없음) ─────────
class _R:
    def __init__(self):
        self.d = {}

    def get(self, k):
        return self.d.get(k)

    def setex(self, k, _t, v):
        self.d[k] = v


class _BC:
    def __init__(self, closes):
        self.closes, self.calls = closes, 0

    def get_klines(self, *, symbol, interval, limit):
        self.calls += 1
        kl = [[i * H4, f"{c}", f"{c * 1.01}", f"{c * 0.99}", f"{c}", "1"] for i, c in enumerate(self.closes)]
        return kl + [[len(self.closes) * H4, "1", "1", "1", "1", "1"]]


def _si(**kw):
    base = dict(id=9, symbol="AAAUSDT", side="LONG", status="ACTIVE", current_position_qty=Decimal("-3"),
                entry_signal="ichikijun:4h_loose_pb_r2kj", exchange_account_id=1, last_error_message=None,
                entry_signal_meta={"variant": "4h_loose_pb_r2kj", "iv": "4h", "entry_bar_ts": 0})
    base.update(kw)
    return SimpleNamespace(**base)


def _run(monkeypatch, sis, mode, closes, r=None):
    from app.workers import ichikijun_exit_worker as W
    n = len(closes)
    now = (n - 1) * H4 + H4 + 61_000 + 0                       # 마지막 봉(n-1) 마감 뒤
    calls = {"close": [], "commit": 0, "rollback": 0}

    class DB:
        def get(self, _m, key):
            return SimpleNamespace(value=mode) if key == EX.MODE_KEY else None

        def execute(self, _q):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: sis))

        def commit(self):
            calls["commit"] += 1

        def refresh(self, obj, attribute_names=None):
            pass

        def rollback(self):
            calls["rollback"] += 1

        def close(self):
            pass

    bc = _BC(closes)
    r = r or _R()
    monkeypatch.setattr("app.core.database.SessionLocal", DB)
    monkeypatch.setattr("app.core.redis_client.get_redis_client", lambda: r)
    monkeypatch.setattr(W, "_client", lambda db, aid, cache: (bc, {"api_key": "k", "api_secret": "s", "is_testnet": False}))
    monkeypatch.setattr(W, "_closed", lambda b, sym, iv, target: _patched_bars(closes))
    monkeypatch.setattr(W, "_close", lambda db, si, keys: calls["close"].append((si.id, abs(si.current_position_qty))))
    import datetime as _dt

    class _FakeDT(_dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return _dt.datetime.fromtimestamp(now / 1000, tz=_dt.timezone.utc)
    monkeypatch.setattr(W, "datetime", _FakeDT)
    return W.run_ichikijun_exit_once(None), calls, r


def _patched_bars(closes):
    return _bars(closes)


def test_shadow_records_once_no_order(monkeypatch):
    si = _si()
    stat, calls, r = _run(monkeypatch, [si], "shadow", [101, 99, 98])
    assert calls["close"] == [] and stat["signals"] == 1 and stat["closed"] == 0
    assert si.entry_signal_meta["kj_exit_signal"]["bar_ts"] == H4
    first = dict(si.entry_signal_meta["kj_exit_signal"])
    stat, calls, _ = _run(monkeypatch, [si], "shadow", [101, 99, 98], r=r)   # 같은 봉 = 다시 안 봄
    assert stat["judged"] == 0 and si.entry_signal_meta["kj_exit_signal"] == first


def test_redis_lost_does_not_rescan_old_breaks(monkeypatch):
    si = _si()
    stat, calls, r = _run(monkeypatch, [si], "shadow", [101, 99, 98])        # 그림자: 1봉 이탈 기록 · 커서 = 마지막 봉
    assert si.entry_signal_meta["kj_judged_ts"] == 2 * H4
    stat, calls, _ = _run(monkeypatch, [si], "on", [101, 99, 98, 103], r=_R())   # Redis 비었음 + on 전환 + 새 봉은 회복
    assert calls["close"] == [] and stat["signals"] == 0                     # 지난 이탈로 청산하지 않는다


def test_on_closes_full_qty_once(monkeypatch):
    si = _si()
    stat, calls, _ = _run(monkeypatch, [si], "on", [101, 99, 98])
    assert calls["close"] == [(9, Decimal("3"))] and stat["closed"] == 1
    assert si.entry_signal_meta["kj_exit_done"]["bar_ts"] == H4 and "기준선" in si.last_error_message
    stat, calls, _ = _run(monkeypatch, [si], "on", [101, 99, 98, 97])        # 이미 청산 표식 = 대상 아님
    assert calls["close"] == [] and stat["targets"] == 0


def test_no_break_and_other_families(monkeypatch):
    a = _si()
    b = _si(id=10, entry_signal="ichikijun:4h_loose_pb_r2", entry_signal_meta={"variant": "4h_loose_pb_r2", "iv": "4h", "entry_bar_ts": 0})
    c = _si(id=11, entry_signal=None, entry_signal_meta=None)
    stat, calls, _ = _run(monkeypatch, [a, b, c], "on", [101, 102, 103])
    assert calls["close"] == [] and stat["targets"] == 1 and stat["signals"] == 0


def test_off_does_nothing(monkeypatch):
    stat, calls, _ = _run(monkeypatch, [_si()], "off", [101, 99])
    assert stat == {"targets": 0, "judged": 0, "signals": 0, "closed": 0, "errors": 0, "mode": "off"} and calls["close"] == []


def test_close_failure_rolls_back_and_retries(monkeypatch):
    from app.workers import ichikijun_exit_worker as W

    def boom(*a, **k):
        raise RuntimeError("exchange down")
    si2 = _si(id=12)
    monkeypatch.setattr(W, "_close", boom)
    stat2, calls2, r2 = _run_fail(monkeypatch, si2)
    assert stat2["errors"] == 1 and calls2["rollback"] == 1 and "kj_exit_done" not in si2.entry_signal_meta
    assert not any(k.startswith("ichiexit:last:12") for k in r2.d)            # 표식 없음 = 다음 사이클 재시도


def _run_fail(monkeypatch, si):
    from app.workers import ichikijun_exit_worker as W
    closes = [101, 99]
    calls = {"rollback": 0}

    class DB:
        def get(self, _m, key):
            return SimpleNamespace(value="on") if key == EX.MODE_KEY else None

        def execute(self, _q):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [si]))

        def commit(self):
            pass

        def refresh(self, obj, attribute_names=None):
            pass

        def rollback(self):
            calls["rollback"] += 1

        def close(self):
            pass
    r = _R()
    monkeypatch.setattr("app.core.database.SessionLocal", DB)
    monkeypatch.setattr("app.core.redis_client.get_redis_client", lambda: r)
    monkeypatch.setattr(W, "_client", lambda db, aid, cache: (object(), {}))
    monkeypatch.setattr(W, "_closed", lambda b, sym, iv, target: _bars(closes))
    return W.run_ichikijun_exit_once(None), calls, r


def test_no_position_on_exchange_ends(monkeypatch):
    from app.workers import ichikijun_exit_worker as W

    def gone(*a, **k):
        raise ValueError("Exchange has no open position for AAAUSDT")
    si = _si(id=13)
    monkeypatch.setattr(W, "_close", gone)
    stat, calls, r = _run_fail(monkeypatch, si)
    assert stat["errors"] == 0 and si.entry_signal_meta["kj_exit_done"]["no_position"] is True
    assert any(k.startswith("ichiexit:last:13") for k in r.d)


def test_meta_merge_keeps_other_keys(monkeypatch):
    si = _si()
    from app.workers import ichikijun_exit_worker as W
    orig = W.run_ichikijun_exit_once

    def run_with_foreign_key(*a, **k):
        return orig(*a, **k)
    # 다른 곳이 같은 meta 에 키를 넣었다고 치고(refresh 가 그 값을 돌려줌) — 그 키가 지워지지 않아야 한다
    si.entry_signal_meta["foreign"] = 1
    stat, calls, _ = _run(monkeypatch, [si], "shadow", [101, 99])
    assert si.entry_signal_meta["foreign"] == 1 and "kj_exit_signal" in si.entry_signal_meta


def test_worker_close_uses_account_keys():
    """본보기(bb_mid_line)처럼 ExecutionService(db) 로 키 없이 부르지 않는다 — 키를 넘긴다."""
    src = (ROOT / "app/workers/ichikijun_exit_worker.py").read_text(encoding="utf-8")
    assert "ExecutionService(db, **keys)" in src


@pytest.mark.parametrize("rel", ["app/services/ichikijun_exit.py"])
def test_service_pure(rel):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    mods = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not any(b in m for m in mods for b in ("execution_service", "database", "redis"))


def test_fix478_other_value_error_is_not_no_position(monkeypatch):
    """🩹 Fix 478: 「position side does not match」 같은 다른 ValueError 는 끝내지 않고 재시도(열린 포지션 방치 금지)."""
    from app.services.execution_service import is_no_position_error
    assert is_no_position_error(ValueError("Exchange has no SHORT position for X; cancelled pending orders and marked STOPPED."))
    assert not is_no_position_error(ValueError("Order's position side does not match user's setting."))
    assert not is_no_position_error(ValueError("Cannot close position now"))
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    for f in ("api/v1/strategies/lifecycle.py", "workers/ichikijun_exit_worker.py"):
        src = (root / f).read_text(encoding="utf-8")
        assert '"no" in str(ve).lower()' not in src and "is_no_position_error(ve)" in src, f

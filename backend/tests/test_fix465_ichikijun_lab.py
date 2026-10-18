"""🗾 Fix 465 — 일목 기준선 변형 실험실 (사장님 10/18 「가상매매로 … 승률이 제일 높은 방법을 지속적으로 찾아서 업데이트」)."""
from __future__ import annotations

import ast
import pathlib
import random
import sys
from types import SimpleNamespace

import pytest

from app.services import ichikijun_lab as LAB
from app.services import ichimoku_kijun as IK

ROOT = pathlib.Path(IK.__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "entry_condition_study"))
import ichikijun_ref as REF  # noqa: E402

H = 3_600_000


def _walk(seed: int, n: int = 1500, step: int = 4 * H) -> list[list]:
    """추세 구간이 섞인 무작위 행보 klines (신호가 나도록 드리프트를 바꿔 가며)."""
    rng = random.Random(seed)
    p, out = 100.0, []
    drift = 0.0
    for i in range(n):
        if i % 60 == 0:
            drift = rng.choice((-0.004, 0.0, 0.004))
        o = p
        c = max(0.01, o * (1 + drift + rng.gauss(0, 0.02)))
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.008)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, 0.008)))
        v = rng.uniform(500, 1500) * (2.0 if abs(c - o) / o > 0.02 else 1.0)
        out.append([i * step, f"{o}", f"{h}", f"{lo}", f"{c}", f"{v}"])
        p = c
    return out


def _bars(kl):
    B = IK.bars_from(kl)
    assert B is not None
    return B


def _btc_map(B):
    s = IK.sma(B.c, IK.BTC_SMA)
    return {t: (B.c[i] > s[i]) if s[i] is not None else None for i, t in enumerate(B.ts)}


# ───────── 1. 참조 구현과 판정 일치 ─────────
@pytest.mark.parametrize("flt,over", [("src", {}), ("loose", {"vol_filter": False, "obv_filter": False})])
def test_signal_matches_reference(flt, over):
    total = 0
    for seed in range(6):
        kl, btc = _walk(seed), _walk(100 + seed)
        B, BT = _bars(kl), _bars(btc)
        up = _btc_map(BT)
        o, h, lo, c, v = ([float(b[i]) for b in kl] for i in (1, 2, 3, 4, 5))
        ind = REF.indicators(o, h, lo, c, v)
        p = {**REF.DEFAULTS, **over}
        for j in range(IK.min_bars(), len(c)):
            for side in ("LONG", "SHORT"):
                a, da = IK.signal(B, j, side, up.get(B.ts[j]), flt)
                b, db = REF.signal(o, h, lo, c, v, j, side, up.get(B.ts[j]), p, ind)
                assert a == b, (seed, j, side)
                if a:
                    total += 1
                    assert da["stop"] == db["stop"]
    assert total > 0                       # 실제로 신호가 나는 데이터로 비교했다


def test_btc_unknown_blocks_entry():
    B = _bars(_walk(1))
    for j in range(IK.min_bars(), len(B.c)):
        assert IK.signal(B, j, "LONG", None)[0] is False
        assert IK.signal(B, j, "SHORT", None)[0] is False


def test_bars_from_rejects_bad_values():
    kl = _walk(2, 80)
    kl[10][4] = "nan"
    assert IK.bars_from(kl) is None
    kl = _walk(2, 80)
    kl[5][3] = "0"
    assert IK.bars_from(kl) is None


# ───────── 2. 변형표 ─────────
def test_variants_table():
    keys = [v.key for v in IK.VARIANTS]
    assert len(keys) == 36 == len(set(keys))
    assert IK.SOURCE_KEY in IK.BY_KEY
    s = IK.BY_KEY[IK.SOURCE_KEY]
    assert (s.iv, s.flt, s.ent, s.rr, s.kijun_exit) == ("1d", "src", "now", 2.0, True)
    assert {v.iv for v in IK.VARIANTS} == {"1h", "4h", "1d"}
    assert all(len(k) <= 24 for k in keys)        # 테이블 컬럼 길이


# ───────── 3. 되돌림 진입 = 신호 뒤 1~5봉 안 첫 닿음 봉 ─────────
def test_pullback_entry_is_first_touch_after_recent_signal():
    found = 0
    for seed in range(6):
        B, BT = _bars(_walk(seed)), _bars(_walk(100 + seed))
        up = _btc_map(BT)
        at = lambda i, B=B: up.get(B.ts[i])  # noqa: E731
        kj = B.ind["kj"]
        for var in (IK.BY_KEY["4h_src_pb_r2"], IK.BY_KEY["4h_loose_pb_r2"]):
            for side in ("LONG", "SHORT"):
                for k in range(IK.min_bars() + 6, len(B.c)):
                    ok, stop, j = IK.entry_at(B, k, side, var, at)
                    if not ok:
                        continue
                    found += 1
                    assert k - IK.PB_BARS <= j < k
                    assert IK.signal(B, j, side, at(j), var.flt)[0]
                    # j 와 k 사이에 더 최근 신호 없음 · 앞선 닿음 없음
                    assert not any(IK.signal(B, x, side, at(x), var.flt)[0] for x in range(j + 1, k))
                    touch = (lambda m: B.lo[m] <= kj[m] * 1.005 and B.c[m] > kj[m]) if side == "LONG" else \
                            (lambda m: B.h[m] >= kj[m] * 0.995 and B.c[m] < kj[m])
                    assert touch(k) and not any(touch(m) for m in range(j + 1, k))
                    assert stop == (min(B.lo[k], B.lo[k - 1]) if side == "LONG" else max(B.h[k], B.h[k - 1]))
    assert found > 0


# ───────── 4. 정산 ─────────
def _mk(rows):
    """rows = [(o,h,l,c)] → Bars (거래량 1)."""
    return _bars([[i * H, f"{o}", f"{h}", f"{lo}", f"{c}", "1"] for i, (o, h, lo, c) in enumerate(rows)])


def test_simulate_sl_tp_same_bar_kj_time_open():
    base = [(100, 100, 100, 100)] * 30
    # 진입 j=29 종가 100, 손절폭 5% → 손절 95 · 2R 익절 110
    B = _mk(base + [(100, 101, 94, 100)])
    assert IK.simulate(B, 29, "LONG", 0.05, 2.0, False)["exit"] == "SL"
    B = _mk(base + [(100, 111, 99, 108)])
    r = IK.simulate(B, 29, "LONG", 0.05, 2.0, False)
    assert (r["exit"], r["r"], r["bars"]) == ("TP", 2.0, 1)
    B = _mk(base + [(100, 111, 94, 100)])                      # 같은 봉 손절·익절 = 손절
    assert IK.simulate(B, 29, "LONG", 0.05, 2.0, False)["exit"] == "SL"
    B = _mk(base + [(100, 101, 96, 97)])                       # 기준선 100 아래 종가 → 기준선 청산
    r = IK.simulate(B, 29, "LONG", 0.05, 2.0, True)
    assert r["exit"] == "KJ" and r["r"] == pytest.approx(-0.6)
    assert IK.simulate(B, 29, "LONG", 0.05, 2.0, False)["status"] == "OPEN"
    B = _mk(base + [(100, 101, 99, 100)] * 60)
    r = IK.simulate(B, 29, "LONG", 0.05, 2.0, False)
    assert (r["exit"], r["bars"]) == ("TIME", 60)
    # SHORT 거울 + 결정성
    B = _mk(base + [(100, 101, 89, 90)])
    assert IK.simulate(B, 29, "SHORT", 0.05, 2.0, False) == IK.simulate(B, 29, "SHORT", 0.05, 2.0, False)
    assert IK.simulate(B, 29, "SHORT", 0.05, 2.0, False)["exit"] == "TP"


def test_pullback_boundary_symmetric():
    B = _mk([(100, 100, 100, 100)] * 30)
    B.ind["kj"][29] = 100.0
    B.lo[29], B.c[29] = 100.5, 101.0                  # 정확히 +0.5% = 닿음 (부동소수 100*1.005 = 100.49999… 함정)
    assert IK._touch(B, 29, True)
    B.h[29], B.c[29] = 99.5, 99.0
    assert IK._touch(B, 29, False)


def test_clamp_and_cost():
    assert IK.clamp_stop(100, 99) == (pytest.approx(0.01), False)
    assert IK.clamp_stop(100, 70) == (0.15, True)
    assert IK.clamp_stop(100, 99.9) == (0.003, False)          # 하한 클램프는 표식 안 함(상한만 — 기획서)
    assert IK.clamp_stop(100, 100) == (0.003, False)           # 손절폭 0 도 예외 없이 0.3%
    assert IK.net_r(2.0, 0.05, 0.1) == pytest.approx(1.98)


# ───────── 5. 순위표·챔피언 ─────────
P = LAB.params_from(None)


def _rows(var, side, edges, days, base=0.0):
    out = []
    for d in range(days):
        ts = d * 86_400_000
        for i, e in enumerate(edges):
            sym = f"S{i}"
            key = f"{var}|{side}|{sym}|{ts}"
            out.append({"kind": "sig", "variant": var, "side": side, "symbol": sym, "entry_bar_ts": ts,
                        "r_net": base + e, "pair_key": key})
            out.append({"kind": "rand", "variant": var, "side": side, "symbol": "R", "entry_bar_ts": ts,
                        "r_net": base, "pair_key": key})
    return out


def test_board_ranks_by_lower_bound_not_win_rate():
    rows = (_rows("a", "LONG", [0.3, -0.1], 25)            # 승률 50% · 차이 +0.10 꾸준
            + _rows("b", "LONG", [0.05, 0.05], 25, base=-0.2)   # 승률 0% (r_net −0.15) 인데 차이 +0.05
            + _rows("c", "SHORT", [3.0, -2.6], 25)          # 평균 차이 +0.2 지만 들쭉날쭉 → 같은 날 평균은 꾸준
            + _rows("d", "LONG", [1.0, 1.0], 5))             # 진입일 5 → 자격 미달
    board = LAB.build_board(rows, P)
    by = {r["variant"]: r for r in board}
    assert by["d"]["score"] is None and board[-1]["variant"] == "d"
    assert by["a"]["win"] == 0.5 and by["b"]["win"] == 0.0
    assert by["a"]["edge"] == pytest.approx(0.10) and by["b"]["edge"] == pytest.approx(0.05)
    assert [r["variant"] for r in board if r["score"] is not None][0] in ("a", "c")
    assert by["a"]["score"] > by["b"]["score"]


def test_board_reproducible():
    rows = _rows("a", "LONG", [0.3, -0.5, 0.1], 30)
    assert LAB.build_board(rows, P) == LAB.build_board(list(reversed(rows)), P)


def test_champion_needs_streak_days():
    def board(a, b):
        return [{"variant": "A", "side": "LONG", "score": a, "win": .4, "avg_r": .1, "edge": .1, "n": 40, "days": 25},
                {"variant": "B", "side": "SHORT", "score": b, "win": .5, "avg_r": .2, "edge": .2, "n": 40, "days": 25}]
    champ, st, ch = LAB.update_champion(None, sorted(board(0.10, 0.05), key=lambda r: -r["score"]), None, P, "d1")
    assert ch and champ["variant"] == "A"
    b2 = sorted(board(0.10, 0.20), key=lambda r: -r["score"])
    champ, st, ch = LAB.update_champion(champ, b2, st, P, "d2")
    assert not ch and champ["variant"] == "A" and st["count"] == 1
    champ, st, ch = LAB.update_champion(champ, b2, st, P, "d2")          # 같은 날 다시 = 세지 않음
    assert not ch and st["count"] == 1
    champ, st, ch = LAB.update_champion(champ, b2, st, P, "d3")
    assert not ch and st["count"] == 2
    champ, st, ch = LAB.update_champion(champ, b2, st, P, "d4")
    assert ch and champ["variant"] == "B" and champ["prev"] == "A|LONG" and st == {}


def test_champion_margin_and_reset():
    b = [{"variant": "B", "side": "SHORT", "score": 0.11, "win": .5, "avg_r": .2, "edge": .2, "n": 40, "days": 25},
         {"variant": "A", "side": "LONG", "score": 0.10, "win": .4, "avg_r": .1, "edge": .1, "n": 40, "days": 25}]
    prev = {"variant": "A", "side": "LONG", "score": 0.10, "since": "d0"}
    champ, st, ch = LAB.update_champion(prev, b, {"key": "B|SHORT", "count": 2, "day": "d1"}, P, "d2")
    assert not ch and champ["variant"] == "A" and st == {}           # 차이 0.01 < margin 0.02 → 연속 끊김
    assert LAB.update_champion(None, [{**b[0], "score": None}], None, P, "d1") == (None, {}, False)


def test_params_bounds():
    p = LAB.params_from(lambda k: {"ichilab_top_n": "9999", "ichilab_cost_pct": "0.2", "ichilab_min_days": "x"}.get(k))
    assert p["ichilab_top_n"] == 40 and p["ichilab_cost_pct"] == 0.2 and p["ichilab_min_days"] == 20


# ───────── 6. 워커 (가짜 DB·거래소·Redis) ─────────
class _Redis:
    def __init__(self):
        self.d = {}

    def get(self, k):
        return self.d.get(k)

    def setex(self, k, _ttl, v):
        self.d[k] = v


class _DB:
    def __init__(self):
        self.rows = []

    def execute(self, _q):
        rows = [r for r in self.rows if r.status == "OPEN"]
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))

    def add(self, row):
        self.rows.append(row)


class _BC:
    def __init__(self, data):
        self.data = data

    def get_24hr_ticker(self):
        return [{"symbol": s, "quoteVolume": str(1000 - i)} for i, s in enumerate(self.data)]

    def get_klines(self, *, symbol, interval, limit):
        return [list(b) for b in self.data[symbol]] + [[self.data[symbol][-1][0] + 4 * H, "1", "1", "1", "1", "1"]]


def test_worker_records_signal_pair_then_settles(monkeypatch):
    from app.workers import ichikijun_lab_worker as W
    n = 200
    data = {s: _walk(i, n) for i, s in enumerate(("BTCUSDT", "AAAUSDT", "BBBUSDT", "CCCUSDT"))}
    target = data["AAAUSDT"][-1][0]
    now_ms = target + 4 * H + W.SETTLE_MS + 1
    fire = {"on": True}

    def fake_entry(B, k, side, var, at):
        if fire["on"] and var.key == "4h_src_now_r2" and side == "LONG" and B.ts[k] == target and B.c[0] == float(data["AAAUSDT"][0][4]):
            return True, B.c[k] * 0.95, k
        return False, None, None
    monkeypatch.setattr(IK, "entry_at", fake_entry)
    db, r, bc, stat = _DB(), _Redis(), _BC(data), {}
    assert W.process_interval(db, bc, r, "4h", now_ms, P, stat) is True
    sig = [x for x in db.rows if x.kind == "sig"]
    rnd = [x for x in db.rows if x.kind == "rand"]
    assert len(sig) == 1 and len(rnd) == 1
    assert sig[0].symbol == "AAAUSDT" and rnd[0].pair_symbol == "AAAUSDT" and rnd[0].symbol != "AAAUSDT"
    assert float(sig[0].stop_pct) == pytest.approx(5.0) and rnd[0].stop_pct == sig[0].stop_pct
    # 짝은 재현 가능
    assert W._pair_pick("4h_src_now_r2", "LONG", "AAAUSDT", target, ["AAAUSDT", "BBBUSDT", "CCCUSDT", "BTCUSDT"], set()) == rnd[0].symbol
    # 같은 봉 다시 = 처리 안 함 (Redis 기록 뒤)
    r.setex(W.K_LAST.format(iv="4h"), 0, str(target))
    assert W.process_interval(db, bc, r, "4h", now_ms, P, {}) is False
    # 다음 봉: 10% 급락 → 두 행 모두 손절 · 열린 신호가 있는 동안 겹침 없음
    fire["on"] = True
    for s in data:
        last = float(data[s][-1][4])
        data[s] = data[s] + [[target + 4 * H, f"{last}", f"{last}", f"{last * 0.8}", f"{last * 0.85}", "1"]]
    st2 = {}
    assert W.process_interval(db, bc, r, "4h", now_ms + 4 * H, P, st2) is True
    assert all(x.status == "CLOSED" and x.exit_reason == "SL" for x in sig + rnd)
    assert float(sig[0].r_net) == pytest.approx(-1.0 - 0.001 / 0.05)


def test_worker_closes_gone_rows():
    from app.workers import ichikijun_lab_worker as W
    data = {s: _walk(i, 200) for i, s in enumerate(("BTCUSDT", "AAAUSDT"))}
    target = data["AAAUSDT"][-1][0]
    now = target + 4 * H + W.SETTLE_MS + 1
    db = _DB()
    old = SimpleNamespace(kind="sig", variant="4h_src_now_r2", side="LONG", interval="4h", symbol="DEADUSDT",
                          entry_bar_ts=target - 80 * 4 * H, stop_pct=5, status="OPEN", bars_held=0)
    fresh = SimpleNamespace(**{**vars(old), "entry_bar_ts": target - 20 * 4 * H})
    db.rows += [old, fresh]
    bc = _BC(data)
    bc.get_klines = lambda **kw: [] if kw["symbol"] == "DEADUSDT" else _BC(data).get_klines(**kw)
    st = {}
    assert W.process_interval(db, bc, _Redis(), "4h", now, P, st) is True
    assert (old.status, old.exit_reason) == ("CLOSED", "GONE") and fresh.status == "OPEN" and st["gone"] == 1


def test_worker_skips_when_btc_missing():
    from app.workers import ichikijun_lab_worker as W
    data = {"AAAUSDT": _walk(1, 200)}
    bc = _BC(data)
    bc.get_klines = lambda **kw: [] if kw["symbol"] == "BTCUSDT" else _BC(data).get_klines(**kw)
    now = data["AAAUSDT"][-1][0] + 4 * H + W.SETTLE_MS + 1
    st = {}
    assert W.process_interval(_DB(), bc, _Redis(), "4h", now, P, st) is False and "BTC" in st["skip"]


# ───────── 7. 주문 모듈 금지 ─────────
@pytest.mark.parametrize("rel", ["app/services/ichimoku_kijun.py", "app/services/ichikijun_lab.py",
                                 "app/workers/ichikijun_lab_worker.py"])
def test_no_order_imports(rel):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    bad = ("execution_service", "surge_ladder_entry", "order", "tp_sl")
    assert not any(b in x for x in names for b in bad), names

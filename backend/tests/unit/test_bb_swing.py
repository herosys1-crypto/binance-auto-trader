"""🌊 볼밴 스윙 (2026-09-14 사장님) — 판정 순수 함수 + 워커 배선 핀 (docs/spec/BB_SWING_STRATEGY_2026-09-14.md).

반박 검증(2026-09-14)에서 옛 테스트가 변이 12개 중 11개를 통과시켰다 — 경계·기준값 대조를 넣어 그 변이들을 잡는다.
"""
from __future__ import annotations

import ast
import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app.services import bb_swing_rules as R

APP = Path(__file__).resolve().parents[2] / "app"
FLAT = [100.0 if i % 2 == 0 else 100.1 for i in range(40)]
SHORT_OK = FLAT + [105.0, 110.0, 108.0]


class _DB:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, _m, key):
        return type("Row", (), {"value": self.kv[key]})() if key in self.kv else None


def _fn_src(path: Path, name: str) -> str:
    src = path.read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == name)
    return ast.get_source_segment(src, fn)


# ── 설정 ─────────────────────────────────────────────────────────────────
def test_defaults_shadow_and_split_consistent():
    assert R.SETTINGS["bb_swing_mode"][0] == "shadow"
    assert R.mode_of(_DB()) == "shadow"
    assert R.mode_of(_DB(bb_swing_mode="ON")) == "on"
    assert R.mode_of(_DB(bb_swing_mode="yes")) == "shadow"          # 모르는 값 = 기본(주문 없음)
    assert R.sides_of(_DB()) == {"SHORT", "LONG"}
    assert R.SETTINGS["bb_swing_support_tol_pct"][0] == "0"         # 백테스트와 같은 정의
    assert R.SETTINGS["bb_swing_capitals"][0] == "10,100,200"       # 사장님 2026-09-15
    assert R.setting_float(_DB(bb_swing_sl_roi="abc"), "bb_swing_sl_roi", 1, 90) == 10.0
    assert R.setting_float(_DB(bb_swing_tp1_pct="999"), "bb_swing_tp1_pct", 1, 50) == 5.0
    assert R.tp_percents(5) == [5, 10, 15, 20]
    assert "macd" not in R.INDICATORS and R.indicator_of(_DB(bb_swing_short_indicator="macd"), "bb_swing_short_indicator") == "rsi"
    from app.workers import pump_split_entry_worker as PS
    caps = PS._parse_capitals(R.SETTINGS["bb_swing_capitals"][0])
    steps = PS._parse_steps(R.SETTINGS["bb_swing_steps"][0])
    sl = PS._parse_sl_roi(R.SETTINGS["bb_swing_sl_roi"][0])
    assert PS.check_no_dead_stage(caps, steps, sl, R.LEVERAGE)[0]


# ── 지표 정의 = 기존 코드·차트와 같아야 한다 ─────────────────────────────
def test_bands_match_existing_analyzer_population_sd():
    from app.services.bb_4h_band_analyzer import BB4HBandAnalyzer
    series = [100 + ((i * 37) % 11) - 5 + i * 0.3 for i in range(60)]
    mid, up, lo = R.bands(series)
    m2, u2, l2 = BB4HBandAnalyzer.bollinger(series)
    for i in range(19, 60):
        assert mid[i] == pytest.approx(float(m2[i]), rel=1e-9)
        assert up[i] == pytest.approx(float(u2[i]), rel=1e-9)
        assert lo[i] == pytest.approx(float(l2[i]), rel=1e-9)
    w = series[40:60]
    m = sum(w) / 20
    sd_pop = (sum((x - m) ** 2 for x in w) / 20) ** 0.5
    assert up[59] == pytest.approx(m + 2 * sd_pop)                  # 표본표준편차(n-1) 변이를 잡는다


def test_rsi_is_wilder():
    c = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28,
         46.00, 46.03, 46.41, 46.22, 45.64]
    r = R.rsi(c)
    assert r[13] is None and r[14] == pytest.approx(70.46, abs=0.05)   # Wilder 교과서 예제
    assert r[19] == pytest.approx(57.92, abs=0.3)


def test_uptrend_uses_ema20_over_ema50():
    up = [100.0 + i for i in range(80)]
    assert R.uptrend_4h(up)[0] is True
    assert R.uptrend_4h([200.0 - i for i in range(80)])[0] is False
    assert R.uptrend_4h(up[:59])[0] is False
    # 긴 하락 뒤 짧은 반등: EMA20 은 EMA30 위로 올라왔지만 EMA50 아래 → 상승중 아님 (EMA50→30 변이를 잡는다)
    s = [200.0 - i for i in range(100)] + [100.0 + 4.0 * i for i in range(11)]
    e20, e30, e50 = R.ema(s, 20)[-1], R.ema(s, 30)[-1], R.ema(s, 50)[-1]
    assert e20 > e30 and e20 < e50
    assert R.uptrend_4h(s)[0] is False


# ── SHORT: 상단 밖 → 최고점에서 꺾임 + RSI 고점 ──────────────────────────
def test_short_peak_turn_with_rsi():
    base, why, d = R.short_signal(SHORT_OK, persist=2, indicator="rsi", rsi_high=70)
    assert base is not None, why
    assert d["run"] == 3 and d["extreme"] == 110.0
    assert base < Decimal("108")                                     # 판정봉 상단


def test_short_boundaries():
    assert R.short_signal(FLAT + [105.0, 110.0, 112.0], indicator="none")[0] is None   # 최고점 갱신 중
    assert R.short_signal(FLAT + [105.0, 110.0, 110.0], indicator="none")[0] is None   # 최고와 같음 = 꺾임 아님
    assert R.short_signal(FLAT + [100.05, 106.0], persist=1, indicator="none")[0] is None  # 밖 1봉 (persist 1 이어도 최소 2)
    assert R.short_signal(SHORT_OK, persist=4, indicator="none")[0] is None
    assert R.short_signal(FLAT[:20], indicator="none")[0] is None


def test_short_rsi_needs_level_and_falling_now():
    base, _w, _d = R.short_signal(SHORT_OK, indicator="rsi", rsi_high=70)
    assert base is not None
    r = R.rsi(SHORT_OK)
    top = max(x for x in r[-4:-1] if x is not None)
    assert R.short_signal(SHORT_OK, indicator="rsi", rsi_high=top)[0] is not None      # 경계 = 통과 (>=)
    assert R.short_signal(SHORT_OK, indicator="rsi", rsi_high=top + 0.01)[0] is None
    # 종가는 최고보다 낮지만 RSI 는 아직 오르는 중 → 막는다 (「지금 하락」 조건 제거 변이를 잡는다)
    rising = FLAT + [105.0, 112.0, 108.0, 109.0]
    assert R.short_signal(rising, indicator="none")[0] is not None
    assert R.short_signal(rising, indicator="rsi", rsi_high=50)[0] is None


# ── LONG: 하단 지지 ──────────────────────────────────────────────────────
def _lows(cs):
    return [c - 0.02 for c in cs]


def test_long_support_touch_boundary_and_units():
    closes = FLAT + [100.05]
    lo = R.bands(closes)[2][-1]
    assert R.long_signal(closes, _lows(FLAT) + [lo], tol_pct=0.0, indicator="none")[0] is not None        # 정확히 닿음
    assert R.long_signal(closes, _lows(FLAT) + [lo * 1.0005], tol_pct=0.0, indicator="none")[0] is None   # 안 닿음
    assert R.long_signal(closes, _lows(FLAT) + [lo * 1.0005], tol_pct=0.1, indicator="none")[0] is not None  # 0.1% 허용 안
    assert R.long_signal(closes, _lows(FLAT) + [lo * 1.0015], tol_pct=0.1, indicator="none")[0] is None      # 허용은 % 단위 (1+tol 변이)


def test_long_close_must_be_above_lower_and_touch_uses_low():
    lows = _lows(FLAT)
    assert R.long_signal(FLAT + [95.0], lows + [94.0], indicator="none")[0] is None            # 하단 아래 마감
    lo = R.bands(FLAT + [99.0])[2][-1]
    assert 99.0 < lo                                                                       # 이 봉은 하단 아래 마감
    closes = FLAT + [100.05]
    lo2 = R.bands(closes)[2][-1]
    assert R.long_signal(closes, lows + [lo2 + 0.03], indicator="none")[0] is None          # 종가로 접촉 판정하는 변이를 잡는다
    assert R.long_signal(closes, lows + [97.0], indicator="rsi", rsi_low=1.0)[0] is None     # 저점 신호 없음
    assert R.long_signal(closes, lows, indicator="none")[0] is None                          # 길이 불일치


# ── 워커 순수 함수 ───────────────────────────────────────────────────────
def test_worker_completed_fresh_and_same_bar():
    from app.workers import bb_swing_worker as W
    bucket = 2_000_000
    start = bucket * W.BAR_MS
    now = start + 10_000
    done = [start - W.BAR_MS, 0, 0, 0, 0, 0, start - 1]
    live = [start, 0, 0, 0, 0, 0, start + W.BAR_MS - 1]
    assert W._completed([done, live], now) == [done]                 # 진행 중 봉 제거 (open_time 로 보는 변이를 잡는다)
    assert W._is_fresh_15m([done], bucket) is True
    stale = [start - 2 * W.BAR_MS, 0, 0, 0, 0, 0, start - W.BAR_MS - 1]
    assert W._is_fresh_15m([stale], bucket) is False                 # 캐시의 옛 스냅샷
    assert W._resolve_same_bar([("SHORT", 1, ""), ("LONG", 1, "")]) == []
    assert W._resolve_same_bar([("LONG", 1, "")]) == [("LONG", 1, "")]
    from app.services.split_entry_executor import anchor_base
    steps = [Decimal("3"), Decimal("5"), Decimal("7")]
    assert anchor_base(97.0, "LONG", steps) == pytest.approx(Decimal("100"))
    assert anchor_base(103.0, "SHORT", steps) == pytest.approx(Decimal("100"))


# ── 워커 배선 ────────────────────────────────────────────────────────────
def test_worker_order_shadow_guard_open_then_flip():
    wk = APP / "workers" / "bb_swing_worker.py"
    run = _fn_src(wk, "run_bb_swing_once")
    i_shadow = run.find('if mode != "on" or halted:')
    assert 0 < run.find("halt_enabled(db)") < i_shadow < run.find("_enter(db")   # Fix 371 중단 중 = 그림자
    assert 0 < run.find("_resolve_same_bar(sigs)") < i_shadow
    assert run.count("_completed(bc.get_klines") == 2                 # 15m · 4H 둘 다
    assert "nx=True" in run and "_is_fresh_15m(kl, bucket)" in run and ".isascii()" in run
    enter = _fn_src(wk, "_enter")
    i_guard = enter.find("_guards_ok(db, account")
    i_open = enter.find("open_split_position(")
    i_flip = enter.find("_flip_close(db, account")
    assert 0 < i_guard < i_open < i_flip                              # 새 방향이 열린 뒤에만 반대 청산
    ex = APP / "services" / "split_entry_executor.py"
    op = _fn_src(ex, "open_split_position")
    i_create = op.find("create_strategy_instance(")
    i_verify = op.find("verify_stage_plans(plans")
    i_start = op.find(".start_stage1(")
    assert 0 < i_create < i_verify < i_start                          # 생성 → 죽은 단계 검산 → 1차 주문
    assert "capital_management_mode=SPLIT_ENTRY_MODE" in op
    assert "si.force_sl_enabled_override = True" in op
    assert "SPLIT_START_FAILED" in op and "create_blocked" in op
    flip = _fn_src(wk, "_flip_close")
    assert 'quantity=Decimal("0")' in flip and ".status" not in flip  # 거래소 실수량 · 상태 덮어쓰기 없음
    assert wk.read_text(encoding="utf-8").count(".start_stage1(") == 0
    assert ex.read_text(encoding="utf-8").count(".start_stage1(") == 1


def test_family_split_learning_bucket_and_no_reentry_martingale():
    from app.services.strategy_family import SPLIT, family_of
    assert family_of(NS(capital_management_mode="split_entry")) == SPLIT
    from app.services.chart_learning_trades import FAMILY_B_BBSPLIT, FAMILY_C_OTHER, classify_family
    assert classify_family(template_name=None, strategy_type="bb_swing", capital_management_mode="split_entry") == FAMILY_C_OTHER
    assert classify_family(template_name=None, strategy_type="pump_split", capital_management_mode="split_entry") == FAMILY_B_BBSPLIT
    rr = (APP / "workers" / "realtime_reentry_worker.py").read_text(encoding="utf-8")
    pats = re.findall(r"strategy_type\.like\('([^']+)%'\)", rr)
    assert pats and not any(R.STRATEGY_TYPE.startswith(p) for p in pats)
    ps = (APP / "workers" / "pump_split_entry_worker.py").read_text(encoding="utf-8")
    assert "StrategyTemplate.strategy_type == STRATEGY_TYPE" in ps    # 볼밴 분할 24h 예산에 스윙이 섞이지 않게


def test_scheduler_job_registered():
    sr = (APP / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    assert 'id="bb_swing"' in sr and "run_bb_swing_once" in sr

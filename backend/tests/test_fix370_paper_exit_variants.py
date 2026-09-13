"""🧪 Fix 370 — 가상 엔진 청산 개선 변형 (사장님 2026-09-14 「개선안을 만들어서 수익이 더 높아 질수 있게 기획해서 개발해줘」).

9/14 분석: 손절의 38~46% 가 +5% 앞섰다가 −25 · LONG 42% 가 TP1 없이 48h 만료(평균 −4.8).
  live_be10    = TP1 전 최고 ROI +10 → 손절 본전
  live_lock5   = TP1 전 최고 ROI +5 → 손절 −10
  live_stale24 = 24h 봉 마감에 TP1 없고 ROI ≤ 0 → 청산
레버 2 → 가격 1% = ROI 2%.
"""
from pathlib import Path

from app.services import paper_trading as PT

ROOT = Path(__file__).resolve().parents[1] / "app"


def _bar(ts, o, h, l, c, v=1000.0):
    return [ts, o, h, l, c, v]


def _run(side, bars, **kw):
    return PT.run_live_like(side, 100.0, bars, tp1_pct=15.0, variants=(), **kw)


def test_engine_set_and_variant_definitions():
    assert PT.EXIT_VARIANT_ENGINES == ("live_be10", "live_lock5", "live_stale24")
    assert PT.EXIT_VARIANTS["live_be10"] == {"protect_at": 10.0, "protect_stop_roi": 0.0}
    assert PT.EXIT_VARIANTS["live_lock5"] == {"protect_at": 5.0, "protect_stop_roi": -10.0}
    assert PT.EXIT_VARIANTS["live_stale24"] == {"stale_bars": 96}
    assert PT.VERSION == 2, "엔진 VERSION 을 올리면 백필 전체 재계산이 돈다 (2코어 VPS) — 새 변형은 새 건부터"


def test_be10_moves_stop_to_breakeven_after_plus10():
    # bar0 고가 105.5 = ROI +11 (TP1 107.5 미도달) → bar1 저가 99.5 가 본전(100) 을 깬다
    bars = [_bar(0, 100.0, 105.5, 100.5, 105.0), _bar(1, 105.0, 105.2, 99.5, 100.0), _bar(2, 100, 101, 99, 100)]
    be = _run("LONG", bars, **PT.EXIT_VARIANTS["live_be10"])
    base = _run("LONG", bars)
    assert be["hit"] == "PROTECT" and be["exit_bar"] == 1 and be["roi"] == 0.0
    assert base["hit"] == "OPEN", "보호 없는 live 는 −25 까지 기다린다"


def test_same_bar_arm_and_break_is_scored_pessimistically():
    # 한 봉 안에서 +12 고가와 99 저가가 같이 나오면 순서를 모른다 → 고점 먼저 가정 = 보호 청산 (변형에 공짜 옵션 금지, 반박 검증 M2)
    r = _run("LONG", [_bar(0, 100.0, 106.0, 99.0, 100.0)], **PT.EXIT_VARIANTS["live_be10"])
    assert r["hit"] == "PROTECT" and r["exit_bar"] == 0 and r["roi"] == 0.0 and r["ambig_arm"] is True
    # 같은 봉에서 문턱만 넘고 보호선은 안 깼으면 청산 없음 — 다음 봉부터 보호
    r2 = _run("LONG", [_bar(0, 100.0, 106.0, 100.2, 105.0), _bar(1, 105.0, 105.5, 101.0, 102.0)], **PT.EXIT_VARIANTS["live_be10"])
    assert r2["hit"] == "OPEN" and r2["ambig_arm"] is False
    assert "ambig_arm" not in _run("LONG", [_bar(0, 100.0, 106.0, 99.0, 100.0)]), "보호 없는 엔진엔 표식 없음"


def test_old_report_only_uses_engines_every_row_has():
    """반박 검증 H1: 새 변형은 새 행에만 있어 옛 보고서에 나란히 놓으면 다른 행 집합끼리 비교가 된다."""
    assert PT.REPORT_V2_ENGINES == ("house", "live", "live_sl15")
    src = (ROOT / "services" / "paper_trading.py").read_text(encoding="utf-8")
    i_b = src.find("def build_report(")
    assert "for eng in ENGINES" not in src[i_b:src.find("def _f(", i_b)]


def test_lock5_caps_loss_at_minus10_after_plus5():
    bars = [_bar(0, 100.0, 103.0, 100.2, 102.0), _bar(1, 102.0, 102.1, 94.0, 94.5)]      # +6 뒤 −12 급락
    r = _run("LONG", bars, **PT.EXIT_VARIANTS["live_lock5"])
    assert r["hit"] == "PROTECT" and r["roi"] == -10.0
    no_arm = _run("LONG", [_bar(0, 100.0, 102.0, 100.2, 101.0), _bar(1, 101.0, 101.1, 94.0, 94.5)], **PT.EXIT_VARIANTS["live_lock5"])
    assert no_arm["hit"] == "OPEN", "+4 만 갔으면 보호 없음 (손절 −25 = 87.5 미도달)"


def test_protect_short_side_mirrors():
    # SHORT: bar0 저가 94.5 = ROI +11 → bar1 고가 100.5 가 본전을 깬다
    bars = [_bar(0, 100.0, 99.5, 94.5, 95.0), _bar(1, 95.0, 100.5, 94.8, 100.0)]
    r = _run("SHORT", bars, **PT.EXIT_VARIANTS["live_be10"])
    assert r["hit"] == "PROTECT" and r["exit_bar"] == 1 and r["roi"] == 0.0


def test_protect_does_not_apply_after_tp1():
    # TP1(107.5) 을 먼저 찍으면 보호가 아니라 기존 트레일링이 관리한다
    bars = [_bar(0, 100.0, 108.0, 100.5, 107.0), _bar(1, 107.0, 107.2, 99.0, 99.5)]
    r = _run("LONG", bars, **PT.EXIT_VARIANTS["live_be10"])
    assert r["tp1_hit"] is True and r["hit"] == "TRAIL"


def test_stale24_exits_flat_trade_at_24h_but_not_a_winner():
    flat_down = [_bar(i, 100.0, 100.3, 99.6, 99.9) for i in range(120)]
    r = _run("LONG", flat_down, **PT.EXIT_VARIANTS["live_stale24"])
    assert r["hit"] == "STALE" and r["exit_bar"] == 95 and r["done"] is True and r["roi"] < 0
    flat_up = [_bar(i, 100.0, 100.5, 99.8, 100.2) for i in range(120)]
    r2 = _run("LONG", flat_up, **PT.EXIT_VARIANTS["live_stale24"])
    assert r2["hit"] == "OPEN", "24h 에 ROI > 0 이면 계속 들고 간다"
    base = _run("LONG", flat_down)
    assert base["hit"] == "OPEN", "기본 live 는 48h 까지"


def test_manage_trade_computes_new_engines():
    allk = [_bar(1_700_000_000_000 + i * 900_000, 100.0, 100.5, 99.5, 100.0) for i in range(320)]
    k4h = [_bar(1_700_000_000_000 + i * 14_400_000, 100.0, 101, 99, 100.0) for i in range(22)]
    s = PT.Series.build(allk, k4h)
    j = 200
    t = {"side": "LONG", "entry_price": float(s.allk[j][4]), "entry_bar_ts": int(s.allk[j][0]), "tp1_pct": 3.0, "chg_24h": 1.0}
    res = PT.manage_trade(t, s)
    assert set(res["engines"]) == set(PT.ENGINES)
    assert res["engines"]["live_stale24"]["hit"] == "STALE"          # 평탄 = 24h 에 ROI 0 → 조기 청산
    assert res["status"] == "OPEN", "다른 엔진이 안 끝났으면 행은 열린 채 (live 48h)"


def test_no_real_order_path_imported():
    src = (ROOT / "services" / "paper_trading.py").read_text(encoding="utf-8")
    for bad in ("execution_service", "place_order", "ExecutionService"):
        assert bad not in src
    i = src.find("EXIT_VARIANTS: dict")
    assert i > 0 and "Claude가 정함" in src[i - 600:i], "값을 고른 주체 표기 (규칙 4)"

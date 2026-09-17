"""🎯 Fix 375 (2026-09-17 사장님) — 차트 자리 진입 게이트.

사장님: "켜면 안 되는 규칙 가족 … 좋은 방향으로 할수 있게 차트를 분석하고 진입할수 있어야지"
        "모든 매매에서 포지션진입조건을 찾아서 성공하는 방향으로 포지션 진입으로 수정할수 있게 정리해줘"

고정하는 것:
  ① 판정 규칙 (SHORT = 16시간 고점 −3% 이내 & 일봉 추세 UP 아님 / LONG = 24h −5% 이하 또는 5분 고점 대비 −4% 이하)
  ② 모르면 막는다 (게이트 on + 차트 값 없음 = 진입 안 함) · shadow/off 는 막지 않는다
  ③ chart_state 에 from_hi_pct/from_lo_pct 가 분석과 같은 창으로 붙는다 (1h 16봉 · 5m 48봉)
  ④ 규칙 가족 12종 모두 게이트 설정(기본 on) · 워커가 on 이면 막고 shadow 기록에 판정을 남긴다
  ⑤ 보고서 P5·P6 — 게이트 값이 있는 새 행만 판정 (분석에 쓴 옛 행은 universe 밖)
"""
import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app.services import chart_state as CS
from app.services import entry_conditions as EC
from app.services import rule_families as RF

APP = Path(__file__).resolve().parents[1] / "app"


def snap(h1=None, m5=None, trend=None):
    return {"chart_state": {"h1": {"from_hi_pct": h1}, "m5": {"from_hi_pct": m5}, "d1": {"bb": {"trend": trend}}}}


# ── ① 판정 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("h1, trend, verdict", [
    (-1.0, "FLAT", "pass"), (-3.0, "DOWN", "pass"),        # 경계 −3% 포함
    (-3.01, "FLAT", "fail"),                               # 고점에서 너무 내려옴 = 떨어진 뒤 추격 (off8·신저점 이탈이 진 이유)
    (-0.5, "UP", "fail"),                                  # 일봉 상승 추세 SHORT 금지
    (None, "FLAT", "unknown"), (-1.0, None, "unknown"),
])
def test_short_rule(h1, trend, verdict):
    assert EC.evaluate("SHORT", snap(h1=h1, trend=trend))["verdict"] == verdict


@pytest.mark.parametrize("chg, m5, verdict", [
    (-5.0, None, "pass"),       # 24h 급락 뒤 (m5 없어도 통과)
    (2.0, -4.0, "pass"),        # 5분 조정 뒤
    (-4.9, -3.9, "fail"),       # 둘 다 아님 = 오르는 중 추격 LONG
    (None, None, "unknown"),
])
def test_long_rule(chg, m5, verdict):
    assert EC.evaluate("LONG", snap(m5=m5), chg_24h=chg)["verdict"] == verdict


def test_long_reads_chg24_from_snapshot_when_not_given():
    assert EC.evaluate("LONG", {**snap(), "chg_24h": -7})["verdict"] == "pass"


def test_fail_reasons_are_human_readable():
    r = EC.evaluate("SHORT", snap(h1=-6.0, trend="UP"))
    assert r["verdict"] == "fail" and len(r["why"]) == 2 and "일봉 추세 UP" in r["why"][1]


# ── ② 모드 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("mode, verdict, blocked", [
    ("on", "pass", False), ("on", "fail", True), ("on", "unknown", True),   # 모르면 막는다
    ("shadow", "fail", False), ("shadow", "unknown", False), ("off", "fail", False),
])
def test_blocks(mode, verdict, blocked):
    assert EC.blocks(mode, {"verdict": verdict}) is blocked


class _DB:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, _m, key):
        v = self.kv.get(key)
        return None if v is None else NS(value=v)


def test_params_override_and_bad_values():
    p = EC.params(_DB(entry_chart_gate_params=json.dumps({"short_max_below_high_pct": 2, "long_min_drop_24h_pct": 999,
                                                          "short_block_d1_trend": ["up", "flat"]})))
    assert p["short_max_below_high_pct"] == 2.0
    assert p["long_min_drop_24h_pct"] == EC.DEFAULT_PARAMS["long_min_drop_24h_pct"]      # 범위 밖 → 기본
    assert p["short_block_d1_trend"] == ["UP", "FLAT"]
    assert EC.params(_DB(entry_chart_gate_params="{깨진")) == EC.DEFAULT_PARAMS           # 손상 → 기본
    assert EC.evaluate("SHORT", snap(h1=-2.5, trend="DOWN"), p=p)["verdict"] == "fail"


# ── ③ chart_state 필드 ─────────────────────────────────────────────────
def _bars(n, hi_at=None):
    out = []
    for k in range(n):
        h = 120.0 if k == hi_at else 101.0
        out.append([k, 100.0, h, 99.0, 100.0 + (k % 2) * 0.1, 1.0])
    return out


def test_hilo_position_matches_analysis_window():
    bars = _bars(60, hi_at=50)                     # 마지막 16봉(44~59) 안에 고점 120
    r = CS.hilo_position(bars, 16)
    assert r["from_hi_pct"] == pytest.approx((bars[-1][4] / 120 - 1) * 100, abs=1e-3)
    assert r["from_lo_pct"] == pytest.approx((bars[-1][4] / 99 - 1) * 100, abs=1e-3)
    assert CS.hilo_position(_bars(60, hi_at=10), 16)["from_hi_pct"] > -1   # 창 밖 고점은 안 본다
    assert CS.hilo_position(bars[:10], 16) == {}


def test_block_carries_window_per_interval():
    assert CS.HILO_BARS["1h"] == 16 and CS.HILO_BARS["5m"] == 48
    b = CS._block("1h", _bars(60, hi_at=55), CS.THRESHOLDS)
    assert b["hilo_bars"] == 16 and b["from_hi_pct"] < -10
    assert "from_hi_pct" not in CS._block("1h", _bars(10), CS.THRESHOLDS)        # 봉 부족 = 기록 안 함


# ── ④ 규칙 가족 · 워커 ────────────────────────────────────────────────
def test_all_twelve_families_have_gate_default_on():
    for f in RF.FAMILIES:
        assert RF.SETTINGS[f"{f.key}_chart_gate"][0] == "on"
        assert RF.chart_gate_of(_DB(), f.key) == "on"
        assert RF.chart_gate_of(_DB(**{f"{f.key}_chart_gate": "shadow"}), f.key) == "shadow"
        assert RF.chart_gate_of(_DB(**{f"{f.key}_chart_gate": "maybe"}), f.key) == "on"   # 손상 → 기본


def _worker_run(monkeypatch, rows, gate_mode="on"):
    import tests.test_queue3_rule_families as Q
    from app.workers import rule_family_worker as W
    Q._no_orders(monkeypatch)
    db = Q._DB(**{f"{f.key}_mode": "shadow" for f in RF.FAMILIES},
               **{f"{f.key}_chart_gate": gate_mode for f in RF.FAMILIES})
    return Q._run(monkeypatch, db, rows)


def test_worker_gate_on_blocks_bad_chart_and_records_verdict(monkeypatch):
    import tests.test_queue3_rule_families as Q
    rows = [
        Q._row(1, "off8_267", "SHORT", ["UP24"], snapshot=snap(h1=-9.0, trend="FLAT")),     # 이미 떨어짐 → 막음
        Q._row(2, "off8_267", "SHORT", ["UP24"], sym="BBBUSDT", snapshot=snap(h1=-1.0, trend="DOWN")),  # 고점 근처 → 통과
        Q._row(3, "off8_267", "SHORT", ["UP24"], sym="CCCUSDT", snapshot={}),              # 차트 없음 → 막음
    ]
    red, st = _worker_run(monkeypatch, rows)
    bad = json.loads(red.store["rf:shadow:rf_off8:AAAUSDT:1"])
    ok = json.loads(red.store["rf:shadow:rf_off8:BBBUSDT:2"])
    none = json.loads(red.store["rf:shadow:rf_off8:CCCUSDT:3"])
    assert bad["would_enter"] is False and bad["blocks"] == ["chart_gate"] and bad["chart_gate"]["verdict"] == "fail"
    assert ok["would_enter"] is True and ok["chart_gate"]["verdict"] == "pass"
    assert none["blocks"] == ["chart_gate"] and none["chart_gate"]["verdict"] == "unknown"


def test_worker_gate_shadow_only_records(monkeypatch):
    import tests.test_queue3_rule_families as Q
    rows = [Q._row(1, "surge_start_346", "LONG", ["DOWN"], snapshot=snap(m5=-1.0), chg_24h=3.0)]
    red, st = _worker_run(monkeypatch, rows, gate_mode="shadow")
    p = json.loads(red.store["rf:shadow:rf_surge_long:AAAUSDT:1"])
    assert p["would_enter"] is True and p["chart_gate"]["mode"] == "shadow" and p["chart_gate"]["verdict"] == "fail"


def test_worker_gate_off_skips_evaluation(monkeypatch):
    import tests.test_queue3_rule_families as Q
    rows = [Q._row(1, "surge_start_346", "LONG", ["DOWN"], snapshot={}, chg_24h=None)]
    red, _ = _worker_run(monkeypatch, rows, gate_mode="off")
    p = json.loads(red.store["rf:shadow:rf_surge_long:AAAUSDT:1"])
    assert p["would_enter"] is True and p["chart_gate"] == {"mode": "off"}


def test_on_order_path_honours_gate(monkeypatch):
    """on 모드(실주문 경로)도 같은 blocks 를 본다 — 게이트 불충족이면 주문 함수를 부르지 않는다."""
    import tests.test_queue3_rule_families as Q
    calls = Q._no_orders(monkeypatch)
    db = Q._DB(rf_off8_mode="on", rf_off8_entry="single", rf_off8_chart_gate="on")
    rows = [Q._row(1, "off8_267", "SHORT", ["UP24"], snapshot=snap(h1=-9.0, trend="FLAT"))]
    _, st = Q._run(monkeypatch, db, rows)
    assert calls == [] and st["entered"] == 0 and st["fam"]["rf_off8"] == {"chart_gate": 1}


# ── ⑤ 보고서 P5·P6 ────────────────────────────────────────────────────
def test_report_p5_p6_use_only_rows_with_gate_values():
    from tests.test_fix370_paper_report_v3 import _mk, _report, dt
    from app.services import paper_report_v3 as PR3
    day = date(2026, 9, 24)

    def mk(sym, side, gate):
        r = _mk(sym, side, "myrule", 3.0, dt(day, 1, 0))
        r["gate"] = gate
        return r
    rows = [mk(f"OLD{i}USDT", "SHORT", {}) for i in range(3)]                                       # 옛 행 = universe 밖
    rows += [mk(f"NH{i}USDT", "SHORT", {"h1_from_hi": -1.0, "d1_trend": "FLAT"}) for i in range(2)]  # 통과
    rows += [mk(f"FA{i}USDT", "SHORT", {"h1_from_hi": -8.0, "d1_trend": "FLAT"}) for i in range(4)]  # 불통과
    rows += [mk(f"LD{i}USDT", "LONG", {"m5_from_hi": -1.0, "chg24": -6.0}) for i in range(2)]        # 급락 뒤 통과
    rows += [mk(f"LU{i}USDT", "LONG", {"m5_from_hi": -1.0, "chg24": 4.0}) for i in range(3)]         # 불통과
    rows += [mk(f"LO{i}USDT", "LONG", {"chg24": -9.0}) for i in range(2)]                           # m5 없음 = 옛 행
    rep = _report(rows, now=dt(day, 12, 0))
    p5 = rep["blocks"]["all"]["filters"]["SHORT"]["P5_short_near_high_not_d1_up"]
    p6 = rep["blocks"]["all"]["filters"]["LONG"]["P6_long_after_drop_or_pullback"]
    assert (p5["universe"]["n"], p5["kept"]["n"], p5["excluded"]["n"]) == (6, 2, 4)
    assert (p6["universe"]["n"], p6["kept"]["n"], p6["excluded"]["n"]) == (5, 2, 3)
    assert "g_h1_from_hi" in (APP / "services" / "paper_report_v3.py").read_text(encoding="utf-8")
    assert PR3.render_markdown_v3(rep)


def test_control_room_exposes_gate():
    from app.services import auto_control as AC
    wl = AC.whitelist()
    for f in RF.FAMILIES:
        assert wl[f"{f.key}_chart_gate"].kind == "gate3"
    c = wl["entry_chart_gate_params"]
    assert c.clean('{"short_max_below_high_pct": 2}') == '{"short_max_below_high_pct": 2}'
    with pytest.raises(ValueError):
        c.clean("[1,2]")
    js = (APP / "static" / "js" / "auto-control.js").read_text(encoding="utf-8")
    assert "gate3" in js and "차트 게이트를 푸는" in js

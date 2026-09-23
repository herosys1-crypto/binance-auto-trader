"""🎯 Fix 377 (2026-09-18 사장님) — 상승 초입 LONG(surge_start_346 · rf_surge_long) 전용 진입 조건.

사장님: "청산된 1건은 조건에 막혔던 상승 초입 LONG인데, +21.7%로 이겼습니다 … 이부분 전략을 자세히 분석해고
        가상매매를 통해서 전략을 완성해줘"

분석 결과 (docs/learning/SURGE_START_LONG_2026-09-18.md · 가상 1,239건):
  · 그 한 건(AVAUSDT, 24h +38.6%)에서 나온 가설 「급등 뒤 1시간 되돌림 LONG」은 **검증에서 뒤집혔다**
    (발견 무작위 대비 +9.6 → 검증 −5.0). 그래서 채택하지 않았다.
  · 두 기간 모두 방향이 같았던 것만 남겼다 = ① 1시간 고점 바로 밑 추격 금지 ② 24h 과열(≥20%) 금지 ③ 24h 0~5% 미동 제외.
    검증 통과 31% · ROI +3.08 (막힌 쪽 −0.24) · 무작위 대비 +2.19 (막힌 쪽 −1.07) · 5일 모두 양수.

여기서 고정하는 것:
  ① 가족 전용 조건 판정 (경계값 · 모름) ② 가족 전용은 rf_surge_long 에만 적용 ③ 설정으로 숫자 변경
  ④ 워커·실매매 게이트가 가족을 넘긴다 ⑤ 보고서 P7 사전등록 필터 ⑥ 그 AVAUSDT 사례는 여전히 막힌다(과열)
"""
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app.services import entry_conditions as EC

APP = Path(__file__).resolve().parents[1] / "app"
FAM = "rf_surge_long"


def snap(h1=None, m5=None, trend=None):
    return {"chart_state": {"h1": {"from_hi_pct": h1}, "m5": {"from_hi_pct": m5}, "d1": {"bb": {"trend": trend}}}}


def ev(h1, chg, **kw):
    return EC.evaluate("LONG", snap(h1=h1), chg_24h=chg, family=FAM, **kw)


# ── ① 판정 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("h1, chg, verdict, why_has", [
    (-2.0, -6.0, "pass", None),                 # 되돌림 있고 · 과열 아님 · 미동 아님
    (-1.5, 8.0, "pass", None),                  # 경계 −1.5 포함
    (-1.4, 8.0, "fail", "추격"),                 # 고점 바로 밑
    (-5.0, 20.0, "fail", "과열"),                # 경계 20 포함해서 막음
    (-5.0, 19.9, "pass", None),
    (-5.0, 0.0, "fail", "미동"),                 # 0 포함
    (-5.0, 4.9, "fail", "미동"),
    (-5.0, 5.0, "pass", None),                  # 5 는 통과
    (-5.0, -0.1, "pass", None),
    (None, -6.0, "unknown", "no_chart"),
    (-5.0, None, "unknown", "no_chart"),
])
def test_surge_rule(h1, chg, verdict, why_has):
    r = ev(h1, chg)
    assert r["verdict"] == verdict, r
    if why_has:
        assert any(why_has in w for w in r["why"]), r["why"]


def test_two_reasons_at_once():
    r = ev(-0.5, 30.0)
    assert r["verdict"] == "fail" and len(r["why"]) == 2


def test_rule_name_is_reported():
    assert ev(-2.0, -6.0)["rule"] == "surge_pullback"
    assert "rule" not in EC.evaluate("LONG", snap(m5=-9.0), chg_24h=-6.0)      # 가족 없으면 방향 공통


# ── ② 적용 범위 ─────────────────────────────────────────────────────────
def test_only_surge_family_has_override():
    assert EC.FAMILY_RULES == {FAM: "surge_pullback"}
    # 다른 LONG 가족은 방향 공통 조건 그대로 (24h −5% 이하 = 통과)
    r = EC.evaluate("LONG", snap(h1=-0.1), chg_24h=-6.0, family="rf_bottom_long")
    assert r["verdict"] == "pass" and r["why"] == ["24h 급락 뒤"]
    # 같은 값이라도 상승 초입 가족은 고점 추격으로 막힌다
    assert ev(-0.1, -6.0)["verdict"] == "fail"


def test_generic_long_unchanged_for_surge_family_inputs():
    """방향 공통 조건(Fix 375)은 그대로 — 상승 초입만 더 좁다."""
    g = EC.evaluate("LONG", snap(h1=-0.1, m5=-5.0), chg_24h=2.0)
    assert g["verdict"] == "pass"                     # 5분 조정 뒤
    assert ev(-0.1, 2.0)["verdict"] == "fail"


# ── ③ 설정 ──────────────────────────────────────────────────────────────
class _DB:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, _m, key):
        v = self.kv.get(key)
        return None if v is None else NS(value=v)


def test_params_are_settings():
    for k, v in (("surge_min_pullback_1h_pct", 1.5), ("surge_max_chg24_pct", 20.0)):
        assert EC.DEFAULT_PARAMS[k] == v
    assert EC.DEFAULT_PARAMS["surge_dead_zone_chg24"] == [0.0, 5.0]
    p = EC.params(_DB(entry_chart_gate_params=json.dumps({"surge_max_chg24_pct": 30})))
    assert p["surge_max_chg24_pct"] == 30.0
    assert ev(-5.0, 25.0, p=p)["verdict"] == "pass"          # 과열 문턱을 올리면 통과
    assert ev(-5.0, 25.0)["verdict"] == "fail"


# ── ④ 배선 ──────────────────────────────────────────────────────────────
def test_worker_and_live_gate_pass_family():
    w = (APP / "workers" / "rule_family_worker.py").read_text(encoding="utf-8")
    assert "family=fam.key" in w
    g = (APP / "services" / "chart_gate_live.py").read_text(encoding="utf-8")
    assert "family=fam.key" in g and "family=fam_key" in g and "family=family" in g
    assert 'f":{family}" if family and family in EC.FAMILY_RULES' in g, "가족 전용 조건은 캐시 키도 달라야 한다"


def test_worker_records_family_rule_verdict(monkeypatch):
    import tests.test_queue3_rule_families as Q
    from app.services import rule_families as RF
    Q._no_orders(monkeypatch)
    db = Q._DB(**{f"{f.key}_mode": "shadow" for f in RF.FAMILIES})
    rows = [Q._row(1, "surge_start_346", "LONG", ["DOWN"], snapshot=snap(h1=-0.5), chg_24h=-8.0),   # 추격 → 막힘
            Q._row(2, "surge_start_346", "LONG", ["DOWN"], sym="BBBUSDT", snapshot=snap(h1=-4.0), chg_24h=-8.0)]
    red, _ = Q._run(monkeypatch, db, rows)
    a = json.loads(red.store["rf:shadow:rf_surge_long:AAAUSDT:1"])
    b = json.loads(red.store["rf:shadow:rf_surge_long:BBBUSDT:2"])
    assert a["chart_gate"]["verdict"] == "fail" and a["chart_gate"]["rule"] == "surge_pullback"
    assert a["blocks"] == ["chart_gate"] and b["chart_gate"]["verdict"] == "pass" and b["would_enter"] is True


# ── ⑤ 보고서 P7 ─────────────────────────────────────────────────────────
def test_report_p7_pre_registered():
    from tests.test_fix370_paper_report_v3 import _mk, _report, dt
    from datetime import date
    day = date(2026, 9, 25)

    def mk(sym, gate):
        r = _mk(sym, "LONG", "myrule", 3.0, dt(day, 1, 0))
        r["gate"] = gate
        return r
    rows = [mk(f"OLD{i}USDT", {}) for i in range(3)]                                        # 옛 행 = universe 밖
    rows += [mk(f"OK{i}USDT", {"h1_from_hi": -3.0, "chg24": -8.0}) for i in range(4)]        # 통과
    rows += [mk(f"CHASE{i}USDT", {"h1_from_hi": -0.5, "chg24": -8.0}) for i in range(2)]     # 고점 추격
    rows += [mk(f"HOT{i}USDT", {"h1_from_hi": -6.0, "chg24": 25.0}) for i in range(2)]       # 과열
    rows += [mk(f"FLAT{i}USDT", {"h1_from_hi": -6.0, "chg24": 2.0}) for i in range(3)]       # 미동 구간
    rep = _report(rows, now=dt(day, 12, 0))
    p7 = rep["blocks"]["all"]["filters"]["LONG"]["P7_long_no_high_chase"]
    assert (p7["universe"]["n"], p7["kept"]["n"], p7["excluded"]["n"]) == (11, 4, 7)


# ── ⑥ 그 사례 ───────────────────────────────────────────────────────────
def test_the_avausdt_case_is_still_blocked_as_overheated():
    """사장님이 물으신 +21.7% 건 (AVAUSDT 09-17 05:45 · 24h +38.6% · 1시간 고점 −12.6%).
    되돌림은 충분하지만 24h 과열이라 막힌다 — 같은 자리(24h ≥ 20%)는 두 기간 모두 손실이었다."""
    r = ev(-12.588, 38.6)
    assert r["verdict"] == "fail" and "과열" in r["why"][0]

"""🗺 Fix 387 (2026-09-20 사장님) — 기회지도 S4(급반등 꼭대기 SHORT)를 실매매 규칙 가족으로 등록.

사장님: "S4만 실매매로 켤 수 있는지 검토해줘" → 「등록하고 지금 켜기까지」

근거: 기회 지도 83,927 자리 — S4 는 하락장·상승장 **모두** 승률 71~73% · ROI +4.34~+5.02 · 손절률 14~15%.
      가상매매 첫날(9/19) 마감 25건 ROI +2.07 (같은 시간 무작위 SHORT −8.65).
여기서 고정하는 것:
  ① 가족 = 가상 규칙 zone_s4_spike_top_short 그대로 ② 검증한 청산과 같게 단일 10 USDT · TP 15/20/25/30 · 손절 −25
  ③ 차트 게이트는 기록만 (S4 신호의 84% 를 막고 성적 차이는 작았다) ④ **코드 기본값은 shadow** — 켜는 건 사장님
  ⑤ 관제실 줄·순서 ⑥ 하루 최대·동시 보유·쿨다운 한도 ⑦ 가족 판정(배지·하루 최대)이 새 종류를 안다
"""
from types import SimpleNamespace as NS

from app.services import auto_control as AC
from app.services import auto_family_registry as AF
from app.services import rule_families as RF


class _DB:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, _m, key):
        v = self.kv.get(key)
        return None if v is None else NS(value=v)


def test_family_uses_the_paper_rule():
    f = RF.FAMILY_BY_KEY["rf_zone_s4"]
    assert (f.rule, f.side, f.stype, f.prefix) == ("zone_s4_spike_top_short", "SHORT", "rf_zone_s4", "RF_ZONES4")
    from app.services import chart_learning as CL
    assert any(r.key == f.rule and r.side == "SHORT" for r in CL.RULES), "가상 규칙이 그대로 판정한다"


def test_exits_match_what_was_validated():
    db = _DB()
    assert RF.entry_of(db, "rf_zone_s4") == "single"          # 분할(TP1 5·손절 10) 아님
    assert RF.SETTINGS["rf_zone_s4_capital_usdt"][0] == "10"
    assert RF.SETTINGS["rf_zone_s4_sl_roi"][0] == "25"
    assert RF.SETTINGS["rf_tp_percents"][0] == "15,20,25,30" and RF.SETTINGS["rf_leverage"][0] == "2"


def test_chart_gate_records_only_and_mode_stays_shadow_in_code():
    assert RF.chart_gate_of(_DB(), "rf_zone_s4") == "shadow"
    assert RF.SETTINGS["rf_zone_s4_mode"][0] == "shadow", "실주문은 사장님이 관제실에서 켠다"
    assert RF.mode_of(_DB(rf_zone_s4_mode="on"), "rf_zone_s4") == "on"


def test_limits():
    assert RF.SETTINGS["rf_zone_s4_max_concurrent"][0] == "2"
    assert RF.SETTINGS["rf_zone_s4_cooldown_hours"][0] == "4"
    assert AC.whitelist()["daily_max_rf_zone_s4"].default == "1"      # 하루 최대 1건


def test_control_room_line_and_order():
    wl = AC.whitelist()
    for k in ("rf_zone_s4_mode", "rf_zone_s4_chart_gate", "rf_zone_s4_entry", "rf_zone_s4_capital_usdt",
              "rf_zone_s4_sl_roi", "daily_max_rf_zone_s4", "rf_zone_s4_loss_breaker"):
        assert k in wl, k
    n, sec = AC.line_order()["rf_zone_s4"]
    assert sec.startswith("⑤") and n == max(x for x, _ in AC.line_order().values()) - 2   # 규칙 가족 묶음 끝
    assert any(p.fam == "rf_zone_s4" for p in AC.panels())


def test_family_registry_knows_the_new_type():
    fam = AF.family_for(strategy_type="rf_zone_s4", template_name="RF_ZONES4_AAAUSDT", entry_origin=None)
    assert fam is not None and fam.key == "rf_zone_s4" and "S4" in fam.label
    from app.services.single_entry_guard import SINGLE_ENTRY_STRATEGY_TYPES
    assert "rf_zone_s4" in SINGLE_ENTRY_STRATEGY_TYPES, "단일 진입 가드가 새 종류를 알아야 한다"

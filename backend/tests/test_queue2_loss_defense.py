"""🛡 대기열 2 손실 방어 (2026-09-12 사장님 승인, docs/spec/PENDING_DEV_QUEUE_2026-09-12.md)

2① 수동 「💉 포지션 추가」에도 추가 뒤 손절 −5 (manual_add_after_sl_enabled, 기본 0)
   — 시장가 · 이익 구간 · 인스턴스 손절이 명시적으로 켜진 경우만 (반박 검증 2026-09-13 반영)
2② LONG 자동 추가는 허용 국면(기본 MKT_UP)일 때만 (pyramid_require_breadth_up, 기본 1) — 값 없음·오래됨 = 허용
"""
import ast
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS

from app.workers import success_pyramiding_worker as W

ROOT = Path(__file__).resolve().parents[1] / "app"
NOW = datetime(2026, 9, 12, 20, 0, tzinfo=timezone.utc)
OBV = NS(trigger_mode="OBV_REVERSE")
LEGACY = NS(trigger_mode="PRICE_DOWN_PCT")
ON = {"manual_add_after_sl_enabled": "1"}


class _DB:
    def __init__(self, **kv):
        self.kv = kv
        self.committed = 0

    def get(self, _m, key):
        return type("R", (), {"value": self.kv[key]})() if key in self.kv else None

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass


def _si(side="LONG", tpl=OBV, on=True, roi="25"):
    return NS(id=1, symbol="XUSDT", side=side, strategy_template=tpl,
              force_sl_enabled_override=on, force_sl_roi_override=None if roi is None else Decimal(roi))


# ── 2① ──────────────────────────────────────────────────────────────────
def test_2_1_default_off_changes_nothing():
    si = _si()
    db = _DB()
    assert W.apply_manual_add_sl(db, si, avg_before=1.0, ref_price=1.1) == (None, "off")
    assert si.force_sl_roi_override == Decimal("25") and db.committed == 0


def test_2_1_profit_zone_market_add_sets_after_add_stop():
    # BTR #4436 식: 추가 전 평단 ~0.05083 에 0.06596 시장가 추가 (이익 구간)
    db = _DB(**ON)
    si = _si()
    assert W.apply_manual_add_sl(db, si, avg_before=Decimal("0.05083"), ref_price=Decimal("0.06596")) == (5.0, "applied")
    assert si.force_sl_roi_override == Decimal("5.0") and si.force_sl_enabled_override is True and db.committed == 1
    # SOPH #4479 식: +1.6% 추가 (override True/25)
    assert W.apply_manual_add_sl(_DB(**ON), _si(), avg_before=0.004344, ref_price=0.0044115, order_type="market") == (5.0, "applied")
    assert W.apply_manual_add_sl(_DB(**ON), _si(side="SHORT"), avg_before=1.0, ref_price=0.98) == (5.0, "applied")
    # 저장값 0 (손절 꺼짐과 같은 값) 은 「더 짧음」이 아니다 → 조인다
    zero = _si(roi="0")
    assert W.apply_manual_add_sl(_DB(**ON), zero, avg_before=1.0, ref_price=1.1) == (5.0, "applied")


def test_2_1_loss_zone_add_keeps_stop():
    # USELESS #4434: 평단 0.27806 에 0.26144 추가 = ROI −12% → −5 를 걸면 즉시 손절
    for side, avg, px in (("LONG", 0.27806, 0.26144), ("SHORT", 1.0, 1.02)):
        si = _si(side=side)
        db = _DB(**ON)
        assert W.apply_manual_add_sl(db, si, avg_before=avg, ref_price=px) == (None, "loss_zone")
        assert si.force_sl_roi_override == Decimal("25") and db.committed == 0


def test_2_1_limit_add_is_skipped():
    # 반박 검증: 시장가 위 매수 지정가는 시장가에 즉시 체결(손실 구간일 수 있음) · 미체결·취소돼도 −5 가 남는다
    si = _si()
    assert W.apply_manual_add_sl(_DB(**ON), si, avg_before=100.0, ref_price=100.0, order_type="LIMIT") == (None, "limit_skipped")
    assert si.force_sl_roi_override == Decimal("25")


def test_2_1_respects_explicit_off_and_does_not_create_override():
    off = _si(on=False, roi=None)              # 사장님 「이 전략만 강제청산 끔」 / Fix 367 손절 없음
    assert W.apply_manual_add_sl(_DB(**ON), off, avg_before=1.0, ref_price=1.1) == (None, "sl_not_explicit_on")
    assert off.force_sl_enabled_override is False and off.force_sl_roi_override is None
    inherit = _si(on=None, roi=None)           # 전역 상속 — override 를 만들면 stage_trigger _sl_explicit(Fix 323)가 바뀐다
    assert W.apply_manual_add_sl(_DB(**ON), inherit, avg_before=1.0, ref_price=1.1) == (None, "sl_not_explicit_on")
    assert inherit.force_sl_enabled_override is None and inherit.force_sl_roi_override is None


def test_2_1_guards_family_scope_and_tighter_stop():
    assert W.apply_manual_add_sl(_DB(**ON), _si(), avg_before=None, ref_price=1.0) == (None, "no_price")
    assert W.apply_manual_add_sl(_DB(**ON), _si(), avg_before=1.0, ref_price=None) == (None, "no_price")
    tight = _si(roi="3")
    assert W.apply_manual_add_sl(_DB(**ON), tight, avg_before=1.0, ref_price=1.1) == (None, "already_tighter")
    assert tight.force_sl_roi_override == Decimal("3")
    # 가족별: 기본 scope=obv 면 기존 방식(PRICE_DOWN_PCT = BTR #4436) 제외, scope=all 이면 적용
    leg = _si(tpl=LEGACY, roi="100")
    assert W.apply_manual_add_sl(_DB(**ON), leg, avg_before=1.0, ref_price=1.1) == (None, "not_applied")
    assert leg.force_sl_roi_override == Decimal("100")
    assert W.apply_manual_add_sl(_DB(pyramid_after_add_sl_scope="all", **ON), leg, avg_before=1.0, ref_price=1.1) == (5.0, "applied")
    assert W.apply_manual_add_sl(_DB(pyramid_after_add_sl_roi="0", **ON), _si(), avg_before=1.0, ref_price=1.1) == (None, "not_applied")


def test_2_1_endpoint_wiring_order():
    src = (ROOT / "api" / "v1" / "strategies" / "lifecycle.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "add_position_to_strategy")
    body = ast.get_source_segment(src, fn)
    i_avg = body.find("_avg_before = strategy.avg_entry_price")
    i_add = body.find("execution_service.add_position_now(")
    i_refresh = body.find("db.refresh(strategy)")
    i_sl = body.find("apply_manual_add_sl(")
    assert 0 < i_avg < i_add < i_refresh < i_sl, "주문 전 평단 → 추가 주문 → 자본 커밋 → 추가 뒤 손절"
    assert "avg_before=_avg_before" in body and "order_type=payload.order_type" in body and "{sl_note}" in body


# ── 2② ──────────────────────────────────────────────────────────────────
def _breadth(tag, minutes_ago=5):
    return json.dumps({"at": (NOW - timedelta(minutes=minutes_ago)).isoformat(), "breadth": 0.6, "tag": tag})


def test_2_2_long_add_only_in_allowed_regime():
    assert W._breadth_gate_long(_DB(market_breadth_last=_breadth("MKT_UP")), now=NOW) == (True, "tag=MKT_UP")
    assert W._breadth_gate_long(_DB(market_breadth_last=_breadth("MKT_DOWN")), now=NOW) == (False, "tag=MKT_DOWN")
    assert W._breadth_gate_long(_DB(market_breadth_last=_breadth("MKT_FLAT")), now=NOW) == (False, "tag=MKT_FLAT")
    assert W._breadth_gate_long(_DB(market_breadth_last=_breadth("MKT_DOWN"), pyramid_require_breadth_up="1"), now=NOW) == (False, "tag=MKT_DOWN")
    # 허용 국면 설정 (재측정 근거: 9/10 이후 MKT_FLAT·MKT_DOWN 추가 lot 도 양수 → 넓히기는 설정 한 줄)
    wide = {"pyramid_breadth_allow_tags": "MKT_UP, mkt_flat"}
    assert W._breadth_gate_long(_DB(market_breadth_last=_breadth("MKT_FLAT"), **wide), now=NOW) == (True, "tag=MKT_FLAT")
    assert W._breadth_gate_long(_DB(market_breadth_last=_breadth("MKT_DOWN"), **wide), now=NOW) == (False, "tag=MKT_DOWN")
    assert W._breadth_allowed_tags(_DB(pyramid_breadth_allow_tags="garbage")) == {"MKT_UP"}
    assert W._breadth_allowed_tags(_DB()) == {"MKT_UP"}


def test_2_2_fail_open_and_switch():
    assert W._breadth_gate_long(_DB(), now=NOW) == (True, "breadth_missing")
    none_tag = json.dumps({"at": NOW.isoformat(), "breadth": None, "tag": None})
    assert W._breadth_gate_long(_DB(market_breadth_last=none_tag), now=NOW) == (True, "breadth_missing")
    assert W._breadth_gate_long(_DB(market_breadth_last=_breadth("MKT_DOWN", minutes_ago=61)), now=NOW) == (True, "breadth_stale")
    assert W._breadth_gate_long(
        _DB(market_breadth_last=_breadth("MKT_DOWN", minutes_ago=61), pyramid_breadth_max_age_min="120"), now=NOW) == (False, "tag=MKT_DOWN")
    assert W._breadth_gate_long(_DB(market_breadth_last="{broken"), now=NOW) == (True, "breadth_error")
    assert W._breadth_gate_long(_DB(market_breadth_last=_breadth("MKT_DOWN"), pyramid_require_breadth_up="0"), now=NOW) == (True, "require_off")


def test_2_2_publisher_key_and_tag_match():
    src = (ROOT / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    assert f'BREADTH_SETTING_KEY = "{W.BREADTH_LAST_KEY}"' in src
    from app.services.paper_trading import breadth_tag
    assert breadth_tag(0.61) == "MKT_UP" and breadth_tag(0.5) == "MKT_FLAT" and breadth_tag(0.3) == "MKT_DOWN"
    assert set(W.BREADTH_TAGS) == {"MKT_UP", "MKT_FLAT", "MKT_DOWN"}


def test_2_2_worker_wiring_after_peak_tracking_long_only():
    s = (ROOT / "workers" / "success_pyramiding_worker.py").read_text(encoding="utf-8")
    i_side = s.find('_bump("side_not_allowed")')
    i_peak = s.find("peak = _update_peak_price(", i_side)
    i_trail = s.find('_bump("trailing_imminent")', i_peak)
    i_long = s.find('if str(si.side).upper() == "LONG":', i_trail)
    i_gate = s.find("_breadth_gate_long(db)", i_trail)
    i_br = s.find('_bump("breadth_not_up")')
    i_ticker = s.find("# 급등/급락 필터 (헌법 64!)")
    assert 0 < i_side < i_peak < i_trail < i_long < i_gate < i_br < i_ticker, "고점 추적은 게이트에 막혀도 계속된다 (반박 검증)"
    assert s.count('_bump("breadth_not_up")') == 1
    i_loop_end = s.find('_reason_str = " ".join(')
    i_warn = s.find('_reasons.get("breadth_unknown_allowed")')
    assert 0 < i_br < i_warn < i_loop_end + 400, "국면 값이 없어 게이트가 무력하면 사이클마다 경고 1줄"

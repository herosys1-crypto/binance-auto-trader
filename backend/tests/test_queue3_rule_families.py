"""🎯 대기열 3A·3B·3D — 가상매매 채택 규칙의 「규칙 가족」 러너 (docs/spec/PENDING_DEV_QUEUE_2026-09-12.md §3).

신호 = 가상매매 실시간 진입 행(paper_trades, source=live). 기본 shadow(주문 없음). on 이면 create_surge_position.
반박 검증(2026-09-13) 반영: 반대 방향 차단 · 전체 자동진입 OFF 존중 · 그림자도 같은 검사 + 전용 쿨다운 · SET NX.
(3C 다일 조정 반등 자리는 tests/test_fix352_multiday_pullback.py)
"""
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app.services import rule_families as RF
from app.workers import rule_family_worker as W

ROOT = Path(__file__).resolve().parents[1] / "app"
NOW = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)


class _DB:
    def __init__(self, **kv):
        self.kv = kv
        self.rolled = 0

    def get(self, _m, key):
        v = self.kv.get(key)
        return None if v is None else type("R", (), {"value": v})()

    def rollback(self):
        self.rolled += 1

    def close(self):
        pass


class _Redis:
    def __init__(self):
        self.store = {}

    def get(self, k):
        return self.store.get(k)

    def set(self, k, v, nx=False, ex=None):
        if nx and k in self.store:
            return None
        self.store[k] = v
        return True

    def setex(self, k, ttl, v):
        self.store[k] = v


# ── 설정 · 판정 ──────────────────────────────────────────────────────────
def test_defaults_are_shadow_and_spec_places():
    db = _DB()
    assert all(RF.mode_of(db, f.key) == "shadow" for f in RF.FAMILIES)
    assert RF.places_of(db, "rf_s2_short") == {"UP24", "UP35_DOWN24"}
    assert RF.places_of(db, "rf_bottom_long") == {"LIVE_OK"}
    assert RF.places_of(db, "rf_surge_long") == {"DOWN24"}
    assert RF.setting_float(db, "rf_s2_short_capital_usdt") == 10 and RF.setting_float(db, "rf_bottom_long_sl_roi") == 25
    assert RF.setting(db, "rf_allow_hedge") == "0"
    assert RF.tp_percents(db) == (15.0, 20.0, 25.0, 30.0)
    assert RF.mode_of(_DB(rf_s2_short_mode="ON"), "rf_s2_short") == "on"
    assert RF.mode_of(_DB(rf_s2_short_mode="garbage"), "rf_s2_short") == "shadow"
    assert RF.places_of(_DB(rf_surge_long_places="nope"), "rf_surge_long") == {"DOWN24"}
    assert RF.places_of(_DB(rf_surge_long_places="down24, live_ok"), "rf_surge_long") == {"DOWN24", "LIVE_OK"}
    assert RF.tp_percents(_DB(rf_tp_percents="30,20,10,5")) == (15.0, 20.0, 25.0, 30.0)     # 역순 = 기본
    for key in RF.SETTINGS:                                                                   # 설정마다 출처 표기
        assert RF.SETTINGS[key][2]


def test_family_rules_match_paper_registry_and_groups():
    from app.services.chart_learning import RULES
    from app.services.paper_trading import GROUP_KEYS
    by = {r.key: r.side for r in RULES}
    for f in RF.FAMILIES:
        assert by.get(f.rule) == f.side, f.rule
    assert set(RF.PLACE_TOKENS) == set(GROUP_KEYS)


def test_decide_place_side_staleness():
    fresh = NOW - timedelta(minutes=5)
    surge = RF.FAMILY_BY_KEY["rf_surge_long"]
    assert RF.decide(_DB(), surge, {"side": "LONG", "tags": ["DOWN"], "opened_at": fresh}, now=NOW)[0] == "go"
    assert RF.decide(_DB(), surge, {"side": "LONG", "tags": ["UP"], "opened_at": fresh}, now=NOW)[0] == "skip_place"
    assert RF.decide(_DB(), surge, {"side": "SHORT", "tags": ["DOWN"], "opened_at": fresh}, now=NOW)[0] == "skip_side"
    assert RF.decide(_DB(), surge, {"side": "LONG", "tags": ["DOWN"], "opened_at": NOW - timedelta(minutes=21)}, now=NOW)[0] == "skip_stale"
    assert RF.decide(_DB(), surge, {"side": "LONG", "tags": ["DOWN"], "opened_at": fresh.replace(tzinfo=None)}, now=NOW)[0] == "go"
    s2 = RF.FAMILY_BY_KEY["rf_s2_short"]
    assert RF.decide(_DB(), s2, {"side": "SHORT", "tags": ["UP5D", "DOWN"], "opened_at": fresh}, now=NOW)[0] == "go"   # UP35_DOWN24
    assert RF.decide(_DB(), s2, {"side": "SHORT", "tags": ["UP"], "opened_at": fresh}, now=NOW)[0] == "go"
    assert RF.decide(_DB(), s2, {"side": "SHORT", "tags": ["DOWN"], "opened_at": fresh}, now=NOW)[0] == "skip_place"
    bottom = RF.FAMILY_BY_KEY["rf_bottom_long"]
    assert RF.decide(_DB(), bottom, {"side": "LONG", "tags": ["DOWN", "LIVE_OK"], "opened_at": fresh}, now=NOW)[0] == "go"
    assert RF.decide(_DB(), bottom, {"side": "LONG", "tags": ["DOWN"], "opened_at": fresh}, now=NOW)[0] == "skip_place"


def test_stop_helpers():
    fam = RF.FAMILY_BY_KEY["rf_s2_short"]
    assert RF.sl_price_pct(_DB(), fam, 2) == 12.5                         # ROI 25 ÷ 레버 2 → create_surge_position 이 × 2
    assert RF.sl_price_pct(_DB(rf_s2_short_sl_roi="0"), fam, 2) is None
    highs = [100, 101, 102, 103, 104, 105, 106, 110]
    assert RF.swing8_stop_pct(highs, 108.9, lo=0.3, hi=15) == pytest.approx((110 * 1.01 / 108.9 - 1) * 100)
    assert RF.swing8_stop_pct(highs[:7], 100, lo=0.3, hi=15) is None      # 봉 부족
    assert RF.swing8_stop_pct(highs, 111.0, lo=0.3, hi=15) is None        # 0.09% < 하한 → ROI 손절로
    assert RF.price_move_pct(100, 101) == pytest.approx(1.0) and RF.price_move_pct(0, 1) is None


# ── 러너 사이클 ──────────────────────────────────────────────────────────
# Fix 375·377: 기본 행은 차트 자리 게이트를 통과한다 — SHORT(16시간 고점 −2% · 일봉 FLAT) · LONG(24h −6%) ·
#   상승 초입 LONG 전용 조건(1시간 고점 −1.5% 이하 · 과열 아님 · 미동 구간 아님)도 통과한다.
_PASS_SNAP = {"chart_state": {"h1": {"from_hi_pct": -2.0}, "m5": {"from_hi_pct": -1.0}, "d1": {"bb": {"trend": "FLAT"}}}}


def _row(i, rule, side, tags, *, sym="AAAUSDT", age_min=5, entry="1.0", snapshot=_PASS_SNAP, chg_24h=-6.0):
    return NS(id=i, rule=rule, side=side, tags=tags, symbol=sym, entry_price=Decimal(entry),
              opened_at=datetime.now(timezone.utc) - timedelta(minutes=age_min), snapshot=snapshot, chg_24h=chg_24h)


def _run(monkeypatch, db, rows, *, red=None, guards=(True, "ok"), price=lambda s: 1.0,
         opposite=lambda db, sym, side: False, global_off=False, daily_full=False, halted=False, split_full=False):
    red = red if red is not None else _Redis()
    monkeypatch.setattr(W, "SessionLocal", lambda: db)
    monkeypatch.setattr(W, "get_redis_client", lambda: red)
    monkeypatch.setattr(W, "_new_rows", lambda _db, rules, since: [x for x in rows if x.rule in rules])
    monkeypatch.setattr(W, "_last_paper_open", lambda _db: "2026-09-13T00:00:00+00:00")
    monkeypatch.setattr(W, "_account", lambda _db: NS(id=1))
    monkeypatch.setattr(W, "_guards", lambda _db, acc, fam, sym: guards)
    monkeypatch.setattr(W, "_price", price)
    monkeypatch.setattr(W, "_opposite_active", opposite)
    monkeypatch.setattr(W, "_global_auto_off", lambda _db: global_off)
    monkeypatch.setattr(W, "_daily_full", lambda _db, fam: (daily_full, "오늘 테스트"))
    monkeypatch.setattr(W, "_halted", lambda _db: halted)
    monkeypatch.setattr("app.services.split_entry_executor.split_total_full", lambda _db: (split_full, "전체 테스트"))
    return red, W.run_rule_families_once()


def _no_orders(monkeypatch):
    calls = []
    monkeypatch.setattr("app.services.surge_ladder_entry.create_surge_position", lambda *a, **k: calls.append(k))
    return calls


def test_all_off_does_nothing(monkeypatch):
    off = {f"{f.key}_mode": "off" for f in RF.FAMILIES}
    red, st = _run(monkeypatch, _DB(**off), [_row(1, "surge_start_346", "LONG", ["DOWN"])])
    assert st["rows"] == 0 and red.store == {}


def test_shadow_would_enter_sets_shadow_only_cooldown_and_consumes_rows_once(monkeypatch):
    calls = _no_orders(monkeypatch)
    rows = [
        _row(1, "surge_start_346", "LONG", ["DOWN"]),                          # go → 그림자 진입 가능
        _row(2, "surge_start_346", "LONG", ["UP"], sym="BBBUSDT"),             # 자리 밖
        _row(3, "surge_start_346", "LONG", ["DOWN"], sym="CCCUSDT", age_min=30),   # 낡음
        _row(4, "surge_start_346", "LONG", ["DOWN"]),                          # 같은 심볼 → 그림자 쿨다운
    ]
    red, st = _run(monkeypatch, _DB(), rows)
    assert calls == [] and st["entered"] == 0 and st["shadow"] == 1
    assert st["fam"]["rf_surge_long"] == {"shadow_would_enter": 1, "skip_place": 1, "skip_stale": 1, "cooldown": 1}
    payload = json.loads(red.store["rf:shadow:rf_surge_long:AAAUSDT:1"])
    assert payload["would_enter"] is True and payload["blocks"] == [] and "DOWN24" in payload["groups"]
    assert "rf:cooldown:shadow:rf_surge_long:AAAUSDT" in red.store and "rf:cooldown:rf_surge_long:AAAUSDT" not in red.store
    _, st2 = _run(monkeypatch, _DB(), rows, red=red)                            # 같은 행은 다시 안 본다 (SET NX)
    assert st2["rows"] == 0


def test_shadow_runs_the_same_blocks_as_on_and_does_not_cool_down_blocked(monkeypatch):
    _no_orders(monkeypatch)
    rows = [_row(1, "surge_start_346", "LONG", ["DOWN"]), _row(2, "surge_start_346", "LONG", ["DOWN"])]
    red, st = _run(monkeypatch, _DB(), rows, guards=(False, "전용 상한 2/2"), price=lambda s: 1.05)   # 5% 움직임
    assert st["fam"]["rf_surge_long"] == {"shadow_drift": 2}                   # 막힌 그림자는 쿨다운을 걸지 않는다
    p = json.loads(red.store["rf:shadow:rf_surge_long:AAAUSDT:1"])
    assert p["would_enter"] is False and p["blocks"] == ["drift", "guards"] and p["guards_why"] == "전용 상한 2/2"
    assert not [k for k in red.store if k.startswith("rf:cooldown")]


def test_on_enters_through_create_surge_position_with_family_params(monkeypatch):
    calls = []

    def _create(db, **k):
        calls.append(k)
        return NS(id=777)
    monkeypatch.setattr("app.services.surge_ladder_entry.create_surge_position", _create)
    rows = [_row(10, "s2_hist_turn_down", "SHORT", ["UP"], sym="XUSDT", entry="2.0"),
            _row(11, "s2_hist_turn_down", "SHORT", ["UP"], sym="YUSDT", entry="2.0")]
    prices = {"XUSDT": 2.01, "YUSDT": 2.1}                                     # Y = 5% 움직임 → 주문 안 함
    red, st = _run(monkeypatch, _DB(rf_s2_short_mode="on", rf_s2_short_entry="single"), rows, price=lambda s: prices[s])
    assert st["entered"] == 1 and st["fam"]["rf_s2_short"] == {"entered": 1, "drift": 1}
    k = calls[0]
    assert (k["symbol"], k["side"], k["capital"], k["sl_price_pct"], k["leverage"], k["attempt_no"]) == ("XUSDT", "SHORT", 10.0, 12.5, 2, 1)
    assert (k["template_prefix"], k["strategy_type"]) == ("RF_S2SHORT", "rf_s2_hist_turn_down")
    assert (k["cap_key"], k["cap_default"], k["tp_percents"]) == ("rf_s2_short_max_concurrent", 2, (15.0, 20.0, 25.0, 30.0))
    assert "rf:cooldown:rf_s2_short:XUSDT" in red.store and "rf:cooldown:rf_s2_short:YUSDT" not in red.store


def test_on_blocks_opposite_side_and_global_off(monkeypatch):
    calls = _no_orders(monkeypatch)
    rows = [_row(30, "bottom_331", "LONG", ["LIVE_OK"], sym="HEDGEUSDT")]
    _, st = _run(monkeypatch, _DB(rf_bottom_long_mode="on"), rows, opposite=lambda db, sym, side: sym == "HEDGEUSDT")
    assert calls == [] and st["fam"]["rf_bottom_long"] == {"opposite_side_active": 1}
    _, st2 = _run(monkeypatch, _DB(rf_bottom_long_mode="on"), [_row(31, "bottom_331", "LONG", ["LIVE_OK"], sym="QUSDT")],
                  global_off=True)
    assert calls == [] and st2["fam"]["rf_bottom_long"] == {"global_auto_off": 1}
    _, st3 = _run(monkeypatch, _DB(rf_bottom_long_mode="on", rf_bottom_long_entry="single", rf_allow_hedge="1"), [_row(32, "bottom_331", "LONG", ["LIVE_OK"], sym="HEDGEUSDT")],
                  opposite=lambda db, sym, side: True)
    assert len(calls) == 1 and st3["fam"]["rf_bottom_long"] == {"entry_blocked": 1}          # 허용하면 가드까지 간다


def test_on_blocked_entry_is_not_retried_and_shadow_cooldown_does_not_block_on(monkeypatch):
    calls = []
    monkeypatch.setattr("app.services.surge_ladder_entry.create_surge_position", lambda db, **k: calls.append(k))   # None = 가드에 막힘
    red, st = _run(monkeypatch, _DB(), [_row(20, "bottom_331", "LONG", ["LIVE_OK"], sym="ZUSDT")])          # 그림자 → 그림자 쿨다운
    assert "rf:cooldown:shadow:rf_bottom_long:ZUSDT" in red.store
    rows = [_row(21, "bottom_331", "LONG", ["LIVE_OK"], sym="ZUSDT")]
    _, st = _run(monkeypatch, _DB(rf_bottom_long_mode="on", rf_bottom_long_entry="single"), rows, red=red)   # on 은 그림자 쿨다운에 안 막힘
    assert len(calls) == 1 and st["fam"]["rf_bottom_long"] == {"entry_blocked": 1}
    _, st2 = _run(monkeypatch, _DB(rf_bottom_long_mode="on", rf_bottom_long_entry="single"), rows, red=red)
    assert len(calls) == 1 and st2["rows"] == 0


# ── 배선 ────────────────────────────────────────────────────────────────
def test_registered_as_single_entry_and_scheduled_and_not_picked_by_reentry():
    from app.services.single_entry_guard import SINGLE_ENTRY_STRATEGY_TYPES, SINGLE_ENTRY_TEMPLATE_PREFIXES, is_single_entry
    assert RF.RF_STRATEGY_TYPES <= set(SINGLE_ENTRY_STRATEGY_TYPES)
    assert set(RF.RF_TEMPLATE_PREFIXES) <= set(SINGLE_ENTRY_TEMPLATE_PREFIXES)
    assert is_single_entry(NS(strategy_template=NS(strategy_type="whatever", name="RF_BOTTOM_ZUSDT_LONG_20260913_A1")))
    sr = (ROOT / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    assert 'id="rule_families"' in sr and "run_rule_families_once" in sr
    rr = (ROOT / "workers" / "realtime_reentry_worker.py").read_text(encoding="utf-8")
    assert "like('rf" not in rr and 'like("rf' not in rr, "재진입 화이트리스트에 규칙 가족을 넣지 않는다"
    ms = (ROOT / "services" / "managed_symbols.py").read_text(encoding="utf-8")
    assert 'StrategyTemplate.trigger_mode == "OBV_REVERSE"' in ms, "심볼 관리 명부는 OBV 템플릿만 등록"
    wk = (ROOT / "workers" / "rule_family_worker.py").read_text(encoding="utf-8")
    assert "create_surge_position(" in wk and "add_position_now" not in wk
    assert "nx=True" in wk and "is_account_banned(acc.id)" in wk
    ptw = (ROOT / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    assert "rule_famil" not in ptw and "create_surge_position" not in ptw, "가상매매는 주문 경로를 모른다"


# ── 2026-09-15 확장: 12 가족 · 분할 10/100/200 · 하루 최대 · 자동매매 중단 ──────────────
def test_2026_09_15_families_defaults_split_and_registry():
    db = _DB()
    assert len(RF.FAMILIES) == 12 and len({f.key for f in RF.FAMILIES}) == 12 and len({f.stype for f in RF.FAMILIES}) == 12
    assert all(RF.entry_of(db, f.key) == "split" for f in RF.FAMILIES)
    assert RF.entry_of(_DB(rf_off8_entry="SINGLE"), "rf_off8") == "single" and RF.entry_of(_DB(rf_off8_entry="x"), "rf_off8") == "split"
    assert all(RF.places_of(db, f.key) == {"ALL"} for f in RF.FAMILIES[3:])
    caps, steps, sl, tp1, trail, note = RF.split_config(db)
    assert [float(c) for c in caps] == [10, 100, 200] and [float(x) for x in steps] == [3, 5, 7] and float(sl) == 10
    assert (tp1, trail, note) == (5.0, 3.0, "설정 OK")
    caps2, *_rest, note2 = RF.split_config(_DB(rf_split_capitals="10,100", rf_split_tp1_pct="999"))
    assert [float(c) for c in caps2] == [10, 100, 200] and "자본" in note2 and _rest[2] == 5.0
    for i, a in enumerate(RF.RF_TEMPLATE_PREFIXES):            # 전용 슬롯은 ilike 접두사로 센다 — 서로 접두사가 되면 안 된다
        assert not any(b != a and b.startswith(a) for b in RF.RF_TEMPLATE_PREFIXES), a
    from app.services import auto_family_registry as AF
    for f in RF.FAMILIES:
        af = AF.family_for(strategy_type=f.stype, template_name=f"{f.prefix}_XUSDT", entry_origin=None)
        assert af is not None and af.key == f.key and af.label == f.label


def test_on_split_goes_through_shared_executor_with_10_100_200(monkeypatch):
    calls = []

    def _open(db, acc, **k):
        calls.append(k)
        return NS(id=900), "entered", ""
    monkeypatch.setattr("app.services.split_entry_executor.open_split_position", _open)
    single = _no_orders(monkeypatch)
    rows = [_row(40, "off8_267", "SHORT", ["UP"], sym="OFFUSDT", entry="2.0")]
    red, st = _run(monkeypatch, _DB(rf_off8_mode="on"), rows, price=lambda s: 2.01)
    assert single == [] and st["entered"] == 1 and st["fam"]["rf_off8"] == {"entered": 1}
    k = calls[0]
    assert (k["symbol"], k["side"], k["price"], k["strategy_type"], k["name_prefix"]) == ("OFFUSDT", "SHORT", 2.01, "rf_off8_267", "RF_OFF8_")
    assert [float(c) for c in k["caps"]] == [10, 100, 200] and float(k["sl_roi"]) == 10 and k["tp1"] == 5.0 and k["label"] == "정점 대비 −8% SHORT"
    assert "rf:cooldown:rf_off8:OFFUSDT" in red.store


def test_split_guard_and_start_failure_and_daily_max_and_halt(monkeypatch):
    opened = []
    monkeypatch.setattr("app.services.split_entry_executor.open_split_position",
                        lambda db, acc, **k: (opened.append(k) or (None, "start_failed", "chg24 gate")))
    rows = [_row(50, "pullback_331", "LONG", ["UP"], sym="PBUSDT")]
    _, st = _run(monkeypatch, _DB(rf_pullback_long_mode="on"), rows, guards=(False, "킬스위치 ON"))
    assert opened == [] and st["fam"]["rf_pullback_long"] == {"guards": 1}               # 가드가 먼저
    red, st2 = _run(monkeypatch, _DB(rf_pullback_long_mode="on"), [_row(51, "pullback_331", "LONG", ["UP"], sym="PBUSDT")])
    assert len(opened) == 1 and st2["fam"]["rf_pullback_long"] == {"start_failed": 1}
    assert "rf:cooldown:rf_pullback_long:PBUSDT" in red.store                            # 실패 뒤 재시도 금지
    _, st3 = _run(monkeypatch, _DB(rf_pullback_long_mode="on"), [_row(52, "pullback_331", "LONG", ["UP"], sym="P2USDT")], daily_full=True)
    assert len(opened) == 1 and st3["fam"]["rf_pullback_long"] == {"daily_max": 1}       # 하루 최대 = 주문 없음
    red4, st4 = _run(monkeypatch, _DB(rf_pullback_long_mode="on"), [_row(53, "pullback_331", "LONG", ["UP"], sym="P3USDT")], halted=True)
    assert len(opened) == 1 and st4["shadow"] == 1 and st4["halted"] is True             # 중단 중 = 그림자 기록
    p = json.loads(red4.store["rf:shadow:rf_pullback_long:P3USDT:53"])
    assert p["halted"] is True and p["entry_mode"] == "split" and "rf:cooldown:shadow:rf_pullback_long:P3USDT" in red4.store
    _, st5 = _run(monkeypatch, _DB(rf_pullback_long_mode="on"), [_row(54, "pullback_331", "LONG", ["UP"], sym="P4USDT")], split_full=True)
    assert len(opened) == 1 and st5["fam"]["rf_pullback_long"] == {"split_total_full": 1}   # 전체 분할 상한 (H1)
    _, st6 = _run(monkeypatch, _DB(rf_pullback_long_mode="on", rf_split_capitals="10,100"), [_row(55, "pullback_331", "LONG", ["UP"], sym="P5USDT")])
    assert len(opened) == 1 and st6["fam"]["rf_pullback_long"] == {"split_config_invalid": 1}  # 설정 손상 = 기본값으로 거래 안 함 (L2)

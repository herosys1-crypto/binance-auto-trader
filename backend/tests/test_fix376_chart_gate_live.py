"""🎯 Fix 376 (2026-09-17 사장님 「실매매 워커에도 차트 게이트 적용해줘」) — 실매매 자동 전략 생성 지점의 차트 자리 게이트.

고정하는 것:
  ① 모드 우선순위 (가족 키 → chart_gate_default → on) · 손상 값 무시
  ② 사람 전략·규칙 가족은 보지 않는다(봉 조회도 안 함) · off 는 조회 안 함
  ③ on + 차트 자리 아님/모름 = ValueError(「차트 자리 게이트」) → is_limit_error 가 「다음에 다시」로 분류
  ④ shadow = 막지 않고 기록 · 판정 캐시(5분, 모름 1분) · ban 중 조회 안 함 · 조회 실패 = unknown
  ⑤ 실제 봉 → chart_state → entry_conditions 판정이 Fix 375 와 같다
  ⑥ 배선: create_strategy_instance 에서 계좌 조회·하루 최대 앞(중단 중이면 판정 생략) · 관리 재진입 사전 확인 · 관제실 칸
"""
import json
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app.services import auto_family_registry as AF
from app.services import chart_gate_live as G

APP = Path(__file__).resolve().parents[1] / "app"


@pytest.fixture(autouse=True)
def _real_mode():
    prev = G.FORCE_MODE
    G.FORCE_MODE = None
    yield
    G.FORCE_MODE = prev


class _DB:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, _m, key):
        v = self.kv.get(key)
        return None if v is None else NS(value=v)


class _Redis:
    def __init__(self):
        self.store, self.ttl = {}, {}

    def get(self, k):
        return self.store.get(k)

    def setex(self, k, ttl, v):
        self.store[k], self.ttl[k] = v, ttl


# ── 봉 합성 ─────────────────────────────────────────────────────────────
H = 3_600_000


def _series(n, step, start_close, drift, *, last_hi=None):
    now = int(time.time() * 1000)
    t0 = (now // step) * step - step * n          # 마지막 봉까지 모두 닫힘
    out, c = [], start_close
    for k in range(n):
        o = c
        c = c * (1 + drift)
        hi = max(o, c) * 1.001
        if last_hi is not None and k == n - 3:
            hi = last_hi
        out.append([t0 + k * step, o, hi, min(o, c) * 0.999, c, 100.0])
    return out


class _Client:
    """1d 는 하락 추세, 1h 는 고점 근처(SHORT 자리), 5m 은 평탄."""
    def __init__(self, *, d1_drift=-0.01, h1_last_hi=None, h1_drift=0.0, boom=False):
        self.calls = []
        self.kw = dict(d1_drift=d1_drift, h1_last_hi=h1_last_hi, h1_drift=h1_drift)
        self.boom = boom

    def get_klines(self, *, symbol, interval, limit):
        self.calls.append(interval)
        if self.boom:
            raise RuntimeError("418 banned")
        if interval == "1d":
            return _series(limit, 86_400_000, 100.0, self.kw["d1_drift"])
        if interval == "1h":
            return _series(limit, H, 100.0, self.kw["h1_drift"], last_hi=self.kw["h1_last_hi"])
        return _series(limit, 300_000, 100.0, 0.0)


# ── ① 모드 ──────────────────────────────────────────────────────────────
def test_mode_precedence():
    assert G.mode_for(_DB(), "top_short") == "on"
    assert G.mode_for(_DB(chart_gate_default="shadow"), "top_short") == "shadow"
    assert G.mode_for(_DB(chart_gate_default="shadow", top_short_chart_gate="off"), "top_short") == "off"
    assert G.mode_for(_DB(top_short_chart_gate="maybe", chart_gate_default="off"), "top_short") == "off"


# ── ② 대상 ──────────────────────────────────────────────────────────────
def _no_fetch(monkeypatch):
    monkeypatch.setattr(G, "judge", lambda *a, **k: pytest.fail("봉을 조회하면 안 된다"))


def test_human_and_rule_family_are_skipped(monkeypatch):
    _no_fetch(monkeypatch)
    assert G.check(_DB(), strategy_type="DYNAMIC_x", template_name="_quick_1", entry_origin="manual_modal",
                   symbol="AUSDT", side="SHORT", exchange_account_id=1) is None
    assert G.check(_DB(), strategy_type="rf_off8_267", template_name="RF_OFF8_A", entry_origin=None,
                   symbol="AUSDT", side="SHORT", exchange_account_id=1) is None


def test_off_does_not_fetch(monkeypatch):
    _no_fetch(monkeypatch)
    r = G.check(_DB(top_short_chart_gate="off"), strategy_type="auto_bb_break_SAJANGNIM_TOP", template_name="x",
                entry_origin=None, symbol="AUSDT", side="SHORT", exchange_account_id=1)
    assert r == {"mode": "off", "family": "top_short"}


# ── ③ 막힘 ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("verdict", ["fail", "unknown"])
def test_on_blocks_with_soft_error(monkeypatch, verdict):
    monkeypatch.setattr(G, "judge", lambda *a, **k: {"verdict": verdict, "why": ["x"], "features": {}, "source": "t"})
    with pytest.raises(ValueError) as ei:
        G.check(_DB(), strategy_type="auto_bb_break_SAJANGNIM_BOTTOM", template_name="x", entry_origin=None,
                symbol="AUSDT", side="LONG", exchange_account_id=1)
    assert G.is_gate_error(ei.value) and AF.is_limit_error(ei.value)       # 「다음에 다시」 분류
    assert "bottom_long_chart_gate" in str(ei.value)


def test_on_pass_returns_verdict(monkeypatch):
    monkeypatch.setattr(G, "judge", lambda *a, **k: {"verdict": "pass", "why": [], "features": {}, "source": "t"})
    r = G.check(_DB(), strategy_type="pump_split_x", template_name="x", entry_origin=None,
                symbol="AUSDT", side="LONG", exchange_account_id=1)
    assert r["verdict"] == "pass" and r["family"] == "pump_split" and r["mode"] == "on"


def test_shadow_records_and_does_not_block(monkeypatch):
    red = _Redis()
    monkeypatch.setattr("app.core.redis_client.get_redis_client", lambda: red)
    monkeypatch.setattr(G, "judge", lambda *a, **k: {"verdict": "fail", "why": ["y"], "features": {}, "source": "t"})
    r = G.check(_DB(chart_gate_default="shadow"), strategy_type="auto_bb_break_SAJANGNIM_TOP", template_name="x",
                entry_origin=None, symbol="AUSDT", side="SHORT", exchange_account_id=1)
    assert r["verdict"] == "fail"
    keys = [k for k in red.store if k.startswith("chart_gate:shadow:top_short:AUSDT:")]
    assert len(keys) == 1 and json.loads(red.store[keys[0]])["side"] == "SHORT"


# ── ④ 판정·캐시·ban ────────────────────────────────────────────────────
def test_judge_short_near_high_in_downtrend_passes_and_caches(monkeypatch):
    red, bc = _Redis(), _Client(d1_drift=-0.02)
    monkeypatch.setattr("app.core.api_backoff.is_account_banned", lambda *a, **k: False)
    r = G.judge(_DB(), symbol="AUSDT", side="SHORT", exchange_account_id=1, client=bc, redis_client=red)
    assert r["verdict"] == "pass" and r["source"] == "fetch" and sorted(bc.calls) == ["1d", "1h", "5m"]
    assert red.ttl["chart_gate:live:AUSDT:SHORT"] == G.CACHE_TTL
    r2 = G.judge(_DB(), symbol="AUSDT", side="SHORT", exchange_account_id=1, client=bc, redis_client=red)
    assert r2["source"] == "cache" and len(bc.calls) == 3                  # 다시 조회하지 않는다


def test_judge_short_after_drop_fails(monkeypatch):
    monkeypatch.setattr("app.core.api_backoff.is_account_banned", lambda *a, **k: False)
    bc = _Client(d1_drift=-0.02, h1_last_hi=120.0)                        # 16시간 안 고점 120 → 지금 100 = −16%
    r = G.judge(_DB(), symbol="BUSDT", side="SHORT", exchange_account_id=1, client=bc, redis_client=_Redis())
    assert r["verdict"] == "fail" and r["features"]["h1_from_hi_pct"] < -3


def test_judge_short_in_daily_uptrend_fails(monkeypatch):
    monkeypatch.setattr("app.core.api_backoff.is_account_banned", lambda *a, **k: False)
    r = G.judge(_DB(), symbol="CUSDT", side="SHORT", exchange_account_id=1, client=_Client(d1_drift=0.03),
                redis_client=_Redis())
    assert r["verdict"] == "fail" and r["features"]["d1_trend"] == "UP"


def test_judge_long_uses_24h_drop_from_1h_bars(monkeypatch):
    monkeypatch.setattr("app.core.api_backoff.is_account_banned", lambda *a, **k: False)
    r = G.judge(_DB(), symbol="DUSDT", side="LONG", exchange_account_id=1, client=_Client(h1_drift=-0.004),
                redis_client=_Redis())
    assert r["features"]["chg_24h"] < -5 and r["verdict"] == "pass"
    r2 = G.judge(_DB(), symbol="EUSDT", side="LONG", exchange_account_id=1, client=_Client(h1_drift=0.001),
                 redis_client=_Redis())
    assert r2["verdict"] == "fail"


def test_ban_and_fetch_error_are_unknown(monkeypatch):
    red = _Redis()
    monkeypatch.setattr("app.core.api_backoff.is_account_banned", lambda *a, **k: True)
    bc = _Client()
    r = G.judge(_DB(), symbol="FUSDT", side="SHORT", exchange_account_id=1, client=bc, redis_client=red)
    assert r["verdict"] == "unknown" and bc.calls == [] and "chart_gate:live:FUSDT:SHORT" not in red.store
    monkeypatch.setattr("app.core.api_backoff.is_account_banned", lambda *a, **k: False)
    r2 = G.judge(_DB(), symbol="FUSDT", side="SHORT", exchange_account_id=1, client=_Client(boom=True), redis_client=red)
    assert r2["verdict"] == "unknown" and red.ttl["chart_gate:live:FUSDT:SHORT"] == G.CACHE_TTL_UNKNOWN


def test_chg24_helper():
    bars = [[0, 0, 0, 0, 100.0 + k, 0] for k in range(30)]
    assert G._chg24_from_1h(bars) == pytest.approx((129 / 105 - 1) * 100)
    assert G._chg24_from_1h(bars[:10]) is None


def test_precheck_skips_rule_family_and_off(monkeypatch):
    _no_fetch(monkeypatch)
    assert G.precheck(_DB(), fam_key="rf_off8", symbol="A", side="SHORT") == (False, {"mode": "on"})
    assert G.precheck(_DB(managed_reentry_chart_gate="off"), fam_key="managed_reentry", symbol="A", side="LONG")[0] is False


# ── ⑥ 배선 ──────────────────────────────────────────────────────────────
def test_create_strategy_instance_order():
    src = (APP / "services" / "strategy_service.py").read_text(encoding="utf-8")
    i_gate = src.index("_chart_gate376(self.db")
    i_acct = src.index("acct = client.get_account()")
    i_halt = src.index("_halt_create371(self.db")
    i_daily = src.index("_daily_check(self.db")
    i_new = src.index("instance = StrategyInstance(")
    # 반박 검증 9/17 #4: 계좌 조회 앞. 중단 여부는 게이트 안에서 먼저 본다(test_halted_skips_fetch) → 중단 중엔 봉 조회 없음.
    assert i_gate < i_acct < i_halt < i_daily < i_new, "차트 게이트 → 계좌 조회 → 중단 게이트 → 하루 최대(잠금) → 생성"
    assert src.count("StrategyInstance(") == 1 or "instance = StrategyInstance(" in src


def test_only_one_place_constructs_strategy_instances():
    """자동 전략이 게이트를 우회해 생성될 길이 없어야 한다."""
    hits = []
    for p in APP.rglob("*.py"):
        if "models" in p.parts:
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            s = line.strip()
            if "StrategyInstance(" in s and not s.startswith("#") and "isinstance" not in s and "select(" not in s:
                hits.append(f"{p.relative_to(APP).as_posix()}:{n}")
    assert hits == ["services/strategy_service.py:" + hits[0].split(":")[1]] and len(hits) == 1, hits


def test_managed_symbol_prechecks_before_spending_limits():
    src = (APP / "workers" / "managed_symbol_worker.py").read_text(encoding="utf-8")
    assert src.index("_CG.precheck(") < src.index("MS.bump_daily(now)") and '_skip("chart_gate")' in src


def test_control_room_has_live_gate_rows():
    from app.services import auto_control as AC
    wl = AC.whitelist()
    for k in ("top_short", "bottom_long", "bb_reentry", "unified_15m", "pump_split", "managed_reentry", "fujimoto", "mach7"):
        assert wl[f"{k}_chart_gate"].kind == "gate3"
    assert wl["chart_gate_default"].default == "on"


# ── 반박 검증(9/17) 반영 ──────────────────────────────────────────────
def test_halted_skips_fetch(monkeypatch):
    _no_fetch(monkeypatch)
    from app.services import auto_trading_halt as H
    prev, H.FORCE_HALT = H.FORCE_HALT, True
    try:
        assert G.check(_DB(), strategy_type="auto_bb_break_SAJANGNIM_TOP", template_name="x", entry_origin=None,
                       symbol="AUSDT", side="SHORT", exchange_account_id=1) is None
    finally:
        H.FORCE_HALT = prev


def test_gate_runs_before_account_fetch():
    src = (APP / "services" / "strategy_service.py").read_text(encoding="utf-8")
    assert src.index("_chart_gate376(self.db") < src.index("acct = client.get_account()")


def test_long_reason_numbers_are_rounded_and_classified():
    from app.services import entry_conditions as EC
    from app.workers.realtime_reentry_worker import _classify_entry_error
    r = EC.evaluate("LONG", {"chart_state": {"m5": {"from_hi_pct": -2.4130999}}}, chg_24h=1.1305)
    msg = f"⛔ [{G.BLOCK_TAG}] 저점 LONG AUSDT LONG 차트 자리 아님 — {r['why'][0]}"
    assert "130" not in r["why"][0] and _classify_entry_error(msg) == "chart_gate"
    assert _classify_entry_error("⛔ [가족별 일 최대 진입] x") == "family_daily_max"


def test_short_no_daily_trend_policy():
    from app.services import entry_conditions as EC
    s = {"chart_state": {"h1": {"from_hi_pct": -1.0}, "d1": {}}}
    assert EC.evaluate("SHORT", s)["verdict"] == "unknown"
    assert EC.evaluate("SHORT", s, p={"short_allow_no_daily_trend": True})["verdict"] == "pass"


class _TDB:
    def __init__(self, tpls):
        self.tpls = tpls

    def get(self, _m, key):
        return self.tpls.get(int(key))


def test_managed_entry_family_matches_creation():
    from app.services.managed_symbols import entry_family_key
    human = NS(id=1, side="LONG", strategy_type="DYNAMIC_LONG", name="_quick_20260901")
    clone = NS(id=2, side="SHORT", strategy_type="DYNAMIC_SHORT", name="_quick_m20260917_SHORT")
    db = _TDB({1: human, 2: clone})
    ms = NS(templates={}, strategy_template_id=1)
    assert entry_family_key(db, ms, "LONG") == "human_template_auto"       # 같은 방향 = 사람 템플릿 재사용
    assert entry_family_key(db, ms, "SHORT") == "managed_reentry"          # 복제될 것
    assert entry_family_key(db, NS(templates={"SHORT": 2}, strategy_template_id=1), "SHORT") == "managed_reentry"
    src = (APP / "workers" / "managed_symbol_worker.py").read_text(encoding="utf-8")
    assert "fam_key=_fam_key" in src and "count_today(db, _fam_key)" in src


def test_gate_only_rows_and_state(db_session=None):
    from app.services import auto_control as AC
    wl = AC.whitelist()
    for k in ("human_template_auto", "pending_hc", "rt_lastchance", "obv_hold", "bb_break", "sajangnim_top", "chart_pattern"):
        assert wl[f"{k}_chart_gate"].kind == "gate3"
    pyr = [p for p in AC.panels() if p.fam == "success_reentry"][0]
    assert "피라미딩 추가 주문" in pyr.ctls[0].help

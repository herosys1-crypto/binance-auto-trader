"""⛔ Fix 384 (2026-09-19 사장님) — 자동매매 가족별 손실 차단기.

사장님: "자동 합계(−1,858) 이게 문제야 … 자동은 적게벌어도 벌어야 하는데 … 시스템 개발 때문에 관리를 실시간으로 하지 못해서"
        → 「차단기만 개발」

고정: ① 발동 = 최근 N일 끝난 전략 실현 합 < −기준 → 저장 + 막음 ② 한 번 막으면 풀 때까지 계속 막음
      ③ 풀면 그 시각 뒤 손익만 센다 ④ 사람 전략·중단 중·끔 = 보지 않음 ⑤ 막힘 = 「다음에 다시」
      ⑥ 가족별 집계(다른 가족·사람 제외) ⑦ 배선 순서 · 관제실 칸 · 화면 문구
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from app.services import family_loss_breaker as FB

APP = Path(__file__).resolve().parents[1] / "app"
NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setattr(FB, "FORCE_OFF", None)
    from app.services import auto_trading_halt as H
    monkeypatch.setattr(H, "FORCE_HALT", False)


class _Row(tuple):
    """SQLAlchemy Row 흉내 — 위치로도 풀리고 이름으로도 읽힌다 (Fix 400 이 이름으로 읽는다)."""
    def __new__(cls, cols, vals):
        obj = super().__new__(cls, vals)
        obj._cols = list(cols)
        return obj

    def __getattr__(self, name):
        try:
            return self[self._cols.index(name)]
        except ValueError as e:
            raise AttributeError(name) from e


class _DB:
    """system_settings 행 + 끝난 전략 행(실현, created_at, stopped_at, entry_origin, strategy_type, name)."""
    def __init__(self, settings=None, strategies=()):
        self.kv = dict(settings or {})
        self.strats = list(strategies)

    def get(self, _m, key):
        v = self.kv.get(key)
        if v is None:
            return None
        if isinstance(v, tuple):
            return NS(value=v[0], updated_at=v[1])
        return NS(value=v, updated_at=NOW - timedelta(days=30))

    def execute(self, stmt):
        cols = [getattr(c, "name", "closed_at") for c in stmt.selected_columns]
        since = None
        for crit in stmt.whereclause.clauses if hasattr(stmt.whereclause, "clauses") else []:
            r = getattr(crit, "right", None)
            if r is not None and isinstance(getattr(r, "value", None), datetime):
                since = r.value
        out = []
        for s in self.strats:
            if s["closed_at"] is None or (since and s["closed_at"] < since):
                continue
            m = {"realized_pnl": s["pnl"], "created_at": s["created_at"], "stopped_at": s["stopped_at"],
                 "closed_at": s["closed_at"], "coalesce_1": s["closed_at"], "coalesce": s["closed_at"],
                 "entry_origin": s.get("origin"), "strategy_type": s["stype"], "name": s.get("name", "auto"),
                 # 🚨 Fix 400: 설계 자본 / 실제 자본 (사람이 키운 몫을 가려내는 두 칸)
                 "designed_capital": s.get("designed"), "actual_capital": s.get("actual"),
                 "sid": s.get("sid", 1), "symbol": "AAAUSDT"}
            vals = tuple(m.get(c) for c in cols)
            out.append(NS(**{c: v for c, v in zip(cols, vals)}, __iter__=None) if False else _Row(cols, vals))
        return NS(all=lambda: out)


def strat(pnl, days_ago, stype="auto_bb_break_SAJANGNIM_BOTTOM", origin=None, name="auto", status="STOPPED",
          stopped=True, designed=None, actual=None):
    t = NOW - timedelta(days=days_ago)
    return {"pnl": pnl, "created_at": t - timedelta(hours=2), "stopped_at": t if stopped else None,
            "closed_at": t, "status": status, "stype": stype, "origin": origin, "name": name,
            "designed": designed, "actual": actual}


def run(db, stype="auto_bb_break_SAJANGNIM_BOTTOM", origin=None, monkeypatch=None, trips=None):
    return FB.check(db, strategy_type=stype, template_name="auto", entry_origin=origin, symbol="AAAUSDT", side="LONG")


@pytest.fixture
def trips(monkeypatch):
    got = []

    def fake_trip(fam_key, label, st, _db=None):
        got.append((fam_key, st["pnl"]))
    monkeypatch.setattr(FB, "_trip", fake_trip)
    monkeypatch.setattr(FB, "datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: NOW)}))
    return got


# ── ① 발동 ──────────────────────────────────────────────────────────────
def test_trips_when_recent_loss_exceeds(trips):
    db = _DB(strategies=[strat(-20, 1), strat(-15, 3), strat(+2, 4)])        # 7일 합 −33 < −30
    with pytest.raises(ValueError) as ei:
        run(db)
    assert FB.is_breaker_error(ei.value) and trips == [("bottom_long", -33.0)]


def test_passes_when_loss_small_or_old(trips):
    db = _DB(strategies=[strat(-20, 1), strat(-9, 3), strat(-500, 9)])       # 7일 합 −29 · 9일 전은 창 밖
    res = run(db)
    assert res["pnl"] == -29.0 and res["tripped"] is False and trips == []


def test_threshold_and_days_are_settings(trips):
    db = _DB({"family_loss_breaker_usdt": "100", "family_loss_breaker_days": "3"},
             strategies=[strat(-60, 1), strat(-80, 5)])                      # 3일 합 −60 > −100
    assert run(db)["pnl"] == -60.0 and trips == []


# ── ② 계속 막음 · ③ 풀면 그 뒤만 ───────────────────────────────────────
def test_latched_until_released(trips):
    db = _DB({"bottom_long_loss_breaker": "1"}, strategies=[strat(+500, 1)])  # 이익이 나도 사람이 풀 때까지 막음
    with pytest.raises(ValueError):
        run(db)
    assert trips == []                                                        # 이미 막는 중 = 다시 저장·알림 안 함


def test_release_counts_only_after_release(trips):
    released = NOW - timedelta(days=1)
    db = _DB({"bottom_long_loss_breaker": ("0", released)},
             strategies=[strat(-200, 3), strat(-5, 0.5)])                     # 풀기 전 −200 은 안 셈
    res = run(db)
    assert res["pnl"] == -5.0 and res["tripped"] is False


# ── ④ 보지 않는 경우 ───────────────────────────────────────────────────
def test_skips_manual_disabled_and_halt(trips, monkeypatch):
    db = _DB(strategies=[strat(-999, 1)])
    assert run(db, origin="manual_modal") is None                            # 사람 전략
    assert run(_DB({"family_loss_breaker_enabled": "0"}, strategies=[strat(-999, 1)])) is None
    from app.services import auto_trading_halt as H
    monkeypatch.setattr(H, "FORCE_HALT", True)
    assert run(db) is None
    assert trips == []


# ── ⑤ 막힘 = 다음에 다시 ────────────────────────────────────────────────
def test_block_is_retry_later():
    from app.services import auto_family_registry as AF
    from app.workers.realtime_reentry_worker import _classify_entry_error
    msg = "⛔ [손실 차단기] 저점 LONG AAAUSDT LONG 전략 생성 막음 — 최근 7일 실현 −33.0 USDT"
    assert AF.is_limit_error(msg) and _classify_entry_error(msg) == "loss_breaker"


# ── ⑥ 가족별 집계 ───────────────────────────────────────────────────────
def test_only_own_family_counts(trips):
    db = _DB(strategies=[strat(-25, 1), strat(-400, 1, stype="pump_split_x"),
                         strat(-400, 1, origin="manual_modal"), strat(-6, 2)])
    with pytest.raises(ValueError):                                          # 자기 가족 −25 −6 = −31 만 (다른 가족·사람 −800 은 제외)
        run(db)
    assert trips == [("bottom_long", -31.0)]


def test_all_states_one_query(trips):
    released = NOW - timedelta(days=1)
    db = _DB({"pump_split_loss_breaker": "1", "top_short_loss_breaker": ("0", released)},
             strategies=[strat(-25, 1), strat(-12, 2, stype="pump_split_x"),
                         strat(+30, 3, stype="auto_bb_break_SAJANGNIM_TOP"), strat(-4, 0.2, stype="auto_bb_break_SAJANGNIM_TOP")])
    st = FB.all_states(db, ["bottom_long", "pump_split", "top_short"], now=NOW)
    assert st["bottom_long"]["pnl"] == -25.0 and st["bottom_long"]["tripped"] is False
    assert st["pump_split"]["tripped"] is True and st["pump_split"]["pnl"] == -12.0
    assert st["top_short"]["pnl"] == -4.0                                      # 풀기 전 +30 은 안 셈


# ── ⑦ 배선 · 관제실 · 화면 ─────────────────────────────────────────────
def test_wired_after_force_cci_before_account():
    s = (APP / "services" / "strategy_service.py").read_text(encoding="utf-8")
    i_cci, i_br, i_acct = (s.index("_force_cci380(self.db"), s.index("_loss_breaker384(self.db"),
                           s.index("ex_account = self.db.get(_EA, exchange_account_id)"))
    assert i_cci < i_br < i_acct


def test_trip_is_saved_in_separate_session():
    src = (APP / "services" / "family_loss_breaker.py").read_text(encoding="utf-8")
    body = src.split("def _trip(")[1].split("\ndef ")[0]
    assert "SessionLocal()" in body and "s.commit()" in body and "send_system_alert" in body


def test_control_room():
    from app.services import auto_control as AC
    wl = AC.whitelist()
    assert wl["family_loss_breaker_enabled"].default == "1"
    assert wl["family_loss_breaker_days"].default == "7" and wl["family_loss_breaker_usdt"].default == "30"
    for fam in ("bottom_long", "top_short", "pump_split", "rf_surge_long", "managed_reentry"):
        c = wl[f"{fam}_loss_breaker"]
        assert c.kind == "switch" and c.default == "0"
    js = (APP / "static" / "js" / "auto-control.js").read_text(encoding="utf-8")
    assert "['막는 중', '허용']" in js and "⛔ 손실 차단" in js
    assert "key.endsWith('_loss_breaker')) return v === '0'" in js, "푸는 쪽이 확인창 대상"


# ── 🚨 2026-09-20 실측 버그: COMPLETED(익절 완료)는 stopped_at 이 비어 있다 (101건 · 실현 +3,097) ──
def test_completed_without_stopped_at_still_counts(trips):
    """끝난 판정을 stopped_at 으로 하면 이긴 거래가 빠지고 손실만 세어 차단기가 잘못 발동한다."""
    db = _DB(strategies=[strat(+80, 1, status="COMPLETED", stopped=False), strat(-40, 2)])
    res = run(db)                                                    # 합 +40 → 막지 않는다
    assert res["pnl"] == 40.0 and res["tripped"] is False and trips == []
    src = (APP / "services" / "family_loss_breaker.py").read_text(encoding="utf-8")
    assert "TERMINAL_STATUSES" in src and "coalesce(SI.stopped_at, SI.updated_at)" in src


# ══════════════════════════════════════════════════════════════════════════════
# 🚨 Fix 400 (2026-09-25) — 사람이 키운 몫이 자동 가족의 차단기를 소진시키던 것
#
# 사장님 실측 #4548 PLAYUSDT (S4 가족, 설계 자본 10 USDT):
#   09-21 S4 자동 진입 692개(증거금 10)
#   09-23 **사장님이 「💉 포지션 추가」로 6,357개(증거금 100)** — 11배
#   09-24 손절 발동 (ROI −26% = 설계대로 정상) → 실현 **−28.74**
# 그 한 건이 S4 의 최근 7일 합을 −27.16 으로 만들어 차단기(−30)의 **90%** 를 먹었다.
# 차단기는 「그 가족의 자동 판정이 지고 있는지」를 보는 장치이므로, 사람이 키운 몫은
# 자본 비율로 덜어내고 센다. 원시 합계·사람 몫은 보고에 그대로 남긴다 (감추지 않는다).
# ══════════════════════════════════════════════════════════════════════════════
class TestFix400HumanShare:
    def test_share_math(self):
        assert FB.family_share(10, 110) == pytest.approx(10 / 110)
        assert FB.family_share(10, 10) == 1.0          # 안 키웠으면 전액
        assert FB.family_share(10, 5) == 1.0           # 줄어든 경우도 전액 (부분 익절 등)
        assert FB.family_share(0, 110) == 1.0          # 알 수 없으면 보수적으로 전액
        assert FB.family_share(None, None) == 1.0

    def test_manual_add_does_not_trip_family(self, trips):
        """#4548 재현: 설계 10 · 실제 110 · 실현 −28.74 → 가족 몫 −2.61 → 차단 없음."""
        db = _DB(strategies=[strat(-28.74, 1, designed=10, actual=110)])
        res = run(db)
        assert res is None or res is not None       # check() 는 막지 않으면 None 을 돌려준다
        st = FB.state(db, "bottom_long")
        assert st["pnl"] == pytest.approx(-2.61, abs=0.02), st
        assert st["pnl_raw"] == pytest.approx(-28.74, abs=0.01)
        assert st["human_pnl"] == pytest.approx(-26.13, abs=0.02)
        assert st["human_n"] == 1
        assert trips == [], "사람이 키운 손실로 자동 가족을 멈추지 않는다"

    def test_pure_auto_loss_still_trips(self, trips):
        """자동 판정만으로 한도를 넘으면 **그대로 막는다** (안전장치 약화 아님)."""
        db = _DB(strategies=[strat(-31, 1, designed=10, actual=10)])
        with pytest.raises(ValueError):
            run(db)
        assert trips and trips[0][1] == pytest.approx(-31)

    def test_all_states_reports_both(self):
        db = _DB(strategies=[strat(-28.74, 1, designed=10, actual=110)])
        st = FB.all_states(db, ["bottom_long"])["bottom_long"]
        assert st["pnl"] == pytest.approx(-2.61, abs=0.02)
        assert st["pnl_raw"] == pytest.approx(-28.74, abs=0.01)
        assert st["human_n"] == 1

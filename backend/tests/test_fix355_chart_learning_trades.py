"""📚 Fix 355 — 실매매(strategy_instances/orders/risk_events) × 차트 학습 일지 라벨 조인.

사장님 2026-09-07: "분석하지 않은 포지션 실패와 성공을 분석해서 우리 시스템로직에서
반영할수 있는 데이터로 만들어줘"
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.models.order import Order
from app.models.risk_event import RiskEvent
from app.services import chart_learning as CL
from app.services import chart_learning_trades as CLT

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
UTC = timezone.utc
T0 = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)


def _order(purpose, status, created_at, *, updated_at=None, avg_price=None, executed_qty=None,
           client_order_id="c1") -> Order:
    return Order(purpose=purpose, status=status, created_at=created_at, updated_at=updated_at or created_at,
                 avg_price=avg_price, executed_qty=executed_qty, client_order_id=client_order_id,
                 symbol="BTCUSDT", side="BUY", position_side="LONG", order_type="MARKET")


def _event(event_type, created_at, event_payload=None) -> RiskEvent:
    return RiskEvent(event_type=event_type, created_at=created_at, event_payload=event_payload,
                     severity="INFO", title="x")


# ── 에피소드 분리 (함정 1) ────────────────────────────────────────────

def test_episode_entry_fills_는_재사용_인스턴스의_옛_체결을_제외한다():
    started = T0 + timedelta(days=5)
    orders = [
        _order("ENTRY", "FILLED", T0, avg_price=1.0, executed_qty=10),           # 옛 사이클 진입
        _order("EXIT", "FILLED", T0 + timedelta(hours=1), avg_price=1.1, executed_qty=10),  # 옛 사이클 종료(재사용 경계)
        _order("ENTRY", "FILLED", started + timedelta(minutes=1), avg_price=2.0, executed_qty=5),  # 이번 에피소드
        _order("ENTRY", "FILLED", started + timedelta(minutes=5), avg_price=2.2, executed_qty=5),
    ]
    fills = CLT.episode_entry_fills(orders, started)
    assert len(fills) == 2 and all(o.created_at > started - timedelta(minutes=10) - timedelta(hours=100) for o in fills)
    assert fills[0].created_at == started + timedelta(minutes=1)


def test_episode_entry_fills_는_10분_이내_EXIT는_경계로_안_본다():
    started = T0 + timedelta(days=5)
    orders = [
        _order("ENTRY", "FILLED", started - timedelta(minutes=30), avg_price=1.0, executed_qty=10),
        _order("EXIT", "FILLED", started - timedelta(minutes=5), avg_price=1.1, executed_qty=10),  # 10분 이내 = 경계 아님
    ]
    # started 직전 5분 EXIT 는 "started-10분" 보다 뒤이므로 옛 사이클 경계로 안 잡히고,
    # 그 앞의 ENTRY 는 여전히 "이번 에피소드"로 남는다(실제로는 already-closed 지만 이 함수의 책임 밖).
    fills = CLT.episode_entry_fills(orders, started)
    assert len(fills) == 1


def test_weighted_entry_price_는_체결_가중평균():
    fills = [
        _order("ENTRY", "FILLED", T0, avg_price=10.0, executed_qty=1.0),
        _order("ENTRY", "FILLED", T0, avg_price=20.0, executed_qty=3.0),
    ]
    price, notional = CLT.weighted_entry_price(fills)
    assert abs(price - 17.5) < 1e-9        # (10*1+20*3)/4
    assert abs(notional - 70.0) < 1e-9


# ── 종료 사유 우선순위 (문서 §5-2, 함정 4) ────────────────────────────

def _reason(status, orders, events, entry_at=T0, stopped_at=None, now=None):
    return CLT.derive_close_reason(status=status, orders=orders, events=events, entry_at=entry_at,
                                   stopped_at=stopped_at, now=now or T0 + timedelta(hours=5))


def test_OPEN_이_최우선():
    reason, *_ = _reason("STAGE2_OPEN", [], [_event("FORCE_STOP_LOSS_TRIGGERED", T0)])
    assert reason == "OPEN"          # 진행중 status 면 SL 이벤트가 있어도 OPEN


def test_FORCE_SL_은_30분_이내_종료면_FORCE_SL_30분_넘으면_DELAYED():
    exit_at = T0 + timedelta(minutes=20)
    orders = [_order("EXIT", "FILLED", exit_at, updated_at=exit_at, avg_price=1.0, executed_qty=1.0)]
    reason, resolved_exit, last_exit, detail = _reason(
        "STOPPED", orders, [_event("FORCE_STOP_LOSS_TRIGGERED", T0)], entry_at=T0 - timedelta(minutes=1))
    assert reason == "FORCE_SL" and detail["force_sl_to_exit_min"] == 20.0

    exit_at2 = T0 + timedelta(minutes=90)
    orders2 = [_order("EXIT", "FILLED", exit_at2, updated_at=exit_at2, avg_price=1.0, executed_qty=1.0)]
    reason2, *_ = _reason("STOPPED", orders2, [_event("FORCE_STOP_LOSS_TRIGGERED", T0)], entry_at=T0 - timedelta(minutes=1))
    assert reason2 == "FORCE_SL_DELAYED"


def test_MANUAL_TP_는_COMPLETED가_아닐때만():
    reason, *_ = _reason("STOPPED", [], [_event("MANUAL_TP", T0)])
    assert reason == "MANUAL_TP"
    reason2, *_ = _reason("COMPLETED", [], [_event("MANUAL_TP", T0)])
    assert reason2 == "TP_COMPLETE"          # COMPLETED 가 MANUAL_TP 보다 우선(문서 순서)


def test_ZOMBIE_MANUAL_CLEANUP():
    reason, *_ = _reason("MANUAL_CLEANUP_REQUIRED", [], [])
    assert reason == "ZOMBIE_MANUAL_CLEANUP"
    reason2, *_ = _reason("STOPPED", [], [_event("ZOMBIE_GUARDIAN_FORCE_STOP", T0)])
    assert reason2 == "ZOMBIE_MANUAL_CLEANUP"


def test_EXIT_체결_없으면_외부청산_또는_미상():
    reason_ext, *_ = _reason("STOPPED", [], [_event("RECONCILE_FLAT_POSITION_CLEANUP", T0, {"old_status": "STOPPING"})])
    assert reason_ext == "EXTERNAL_CLOSE_NO_DB_EXIT"
    reason_none, *_ = _reason("STOPPED", [], [])
    assert reason_none == "NO_EXIT_FILL"


def test_STOP_UNLOGGED_은_reconcile_old_status가_STOPPING일때():
    exit_at = T0 + timedelta(minutes=10)
    orders = [_order("EXIT", "FILLED", exit_at, updated_at=exit_at, avg_price=1.0, executed_qty=1.0)]
    events = [_event("RECONCILE_FLAT_POSITION_CLEANUP", exit_at, {"old_status": "STOPPING"})]
    reason, *_ = _reason("STOPPED", orders, events, entry_at=T0)
    assert reason == "STOP_UNLOGGED"

    events_tp = events + [_event("TP_EXECUTION_AUDIT", exit_at, {"level": 1})]
    reason_tp, *_ = _reason("STOPPED", orders, events_tp, entry_at=T0)
    assert reason_tp == "STOP_UNLOGGED_TP_PARTIAL"


def test_EXTERNAL_CLOSE_는_reconcile_old_status가_STOPPING이_아닐때():
    exit_at = T0 + timedelta(minutes=10)
    orders = [_order("EXIT", "FILLED", exit_at, updated_at=exit_at, avg_price=1.0, executed_qty=1.0)]
    events = [_event("RECONCILE_FLAT_POSITION_CLEANUP", exit_at, {"old_status": "STAGE2_OPEN"})]
    reason, *_ = _reason("STOPPED", orders, events, entry_at=T0)
    assert reason == "EXTERNAL_CLOSE"


def test_TP_PARTIAL_THEN_STOP_과_기본_STOP_UNLOGGED():
    exit_at = T0 + timedelta(minutes=10)
    orders = [_order("EXIT", "FILLED", exit_at, updated_at=exit_at, avg_price=1.0, executed_qty=1.0)]
    reason_tp, *_ = _reason("STOPPED", orders, [_event("TP_EXECUTION_AUDIT", exit_at, {"level": 1})], entry_at=T0)
    assert reason_tp == "TP_PARTIAL_THEN_STOP"
    reason_none, *_ = _reason("STOPPED", orders, [], entry_at=T0)
    assert reason_none == "STOP_UNLOGGED"


# ── 가족 분류 ─────────────────────────────────────────────────────────

def test_classify_family():
    assert CLT.classify_family(template_name="_quick_short", strategy_type="X", capital_management_mode="fixed") == "MANUAL"
    assert CLT.classify_family(template_name="t", strategy_type="DYNAMIC_SHORT", capital_management_mode="fixed") == "MANUAL"
    assert CLT.classify_family(template_name="t", strategy_type="X", capital_management_mode="stage_ladder") == "A_LADDER"
    assert CLT.classify_family(template_name="t", strategy_type="X", capital_management_mode="split_entry") == "B_BBSPLIT"
    assert CLT.classify_family(template_name="t", strategy_type="pump_split", capital_management_mode="fixed") == "B_BBSPLIT"
    assert CLT.classify_family(template_name="t", strategy_type="X", capital_management_mode="fixed") == "C_OTHER"


# ── build_episode: dust 무효화 ──────────────────────────────────────

class _Inst:
    def __init__(self, **kw):
        self.id = 1
        self.symbol = "BTCUSDT"
        self.side = "LONG"
        self.status = "STOPPED"
        self.started_at = T0
        self.stopped_at = None
        self.realized_pnl = 0.0
        self.leverage = 2
        self.avg_entry_price = None
        self.start_price = 100.0
        self.capital_management_mode = "fixed"
        self.__dict__.update(kw)


def test_build_episode_는_dust를_무효화한다():
    entry_at = T0 + timedelta(minutes=1)
    orders = [_order("ENTRY", "FILLED", entry_at, updated_at=entry_at, avg_price=1.0, executed_qty=1.0)]  # 명목 1 USDT
    row = CLT.build_episode(_Inst(realized_pnl=0.1), orders, [], template_name="t", strategy_type="x",
                            now=T0 + timedelta(hours=1))
    assert row["close_reason"] == "NO_EXIT_FILL" and row["valid_trade"] is False
    assert "dust" in row["entry_src"]


def test_build_episode_는_체결_없으면_무효():
    row = CLT.build_episode(_Inst(), [], [], template_name="t", strategy_type="x", now=T0 + timedelta(hours=1))
    assert row["valid_trade"] is False and row["n_entry_fills"] == 0


def test_build_episode_유효_매매_필드():
    entry_at = T0 + timedelta(minutes=1)
    exit_at = T0 + timedelta(hours=2)
    orders = [
        _order("ENTRY", "FILLED", entry_at, updated_at=entry_at, avg_price=100.0, executed_qty=1.0),
        _order("EXIT", "FILLED", exit_at, updated_at=exit_at, avg_price=110.0, executed_qty=1.0),
    ]
    row = CLT.build_episode(_Inst(status="COMPLETED", realized_pnl=10.0), orders, [], template_name="t",
                            strategy_type="x", now=exit_at + timedelta(minutes=1))
    assert row["valid_trade"] is True and row["close_reason"] == "TP_COMPLETE"
    assert row["entry_price"] == 100.0 and row["exit_price"] == 110.0
    assert row["price_roi_pct"] == 10.0 and row["margin_roi_pct"] == 20.0
    assert row["win"] is True and row["hold_hours"] is not None and row["family"] == "C_OTHER"


# ── 조인 상태 분류 ────────────────────────────────────────────────────

class _CldRow:
    def __init__(self, outcome_status="DONE", outcome=None):
        self.outcome_status = outcome_status
        self.outcome = outcome


def test_classify_join():
    assert CLT.classify_join(None, any_row_that_day=False) == "NO_SNAPSHOT_THAT_DAY"
    assert CLT.classify_join(None, any_row_that_day=True) == "SYMBOL_NOT_IN_UNIVERSE"
    assert CLT.classify_join(_CldRow(outcome_status="PENDING", outcome=None), any_row_that_day=True) == "ROW_PENDING_OR_EXPIRED"
    assert CLT.classify_join(_CldRow(outcome_status="DONE", outcome={}), any_row_that_day=True) == "ROW_PENDING_OR_EXPIRED"
    assert CLT.classify_join(_CldRow(outcome_status="DONE", outcome={"peak": {}}), any_row_that_day=True) == "JOINED"


# ── cld 열 계산 (timing_vs_extreme / hours_to_extreme, 문서 §3) ──────

def _outcome(entry_price=100.0, peak_bar=8, peak_pct=5.0, trough_bar=40, trough_pct=-3.0):
    rules = {r.key: None for r in CL.RULES}
    rules["toprev_331"] = {"hours": 0.5, "roi": -1.0, "hit": "SL"}
    rules["s1_breakdown"] = {"hours": 5.0, "roi": 2.0, "hit": "TP"}
    rules["pullback_331"] = {"hours": 0.5, "roi": 1.0, "hit": "TP"}
    return {
        "entry_price": entry_price,
        "peak": {"bar": peak_bar, "hours": round((peak_bar + 1) * 0.25, 2), "pct": peak_pct, "drop_after_pct": -1.0},
        "trough": {"bar": trough_bar, "hours": round((trough_bar + 1) * 0.25, 2), "pct": trough_pct, "rise_after_pct": 2.0},
        "baseline": {"LONG": [0.1] * 8, "SHORT": [-0.1] * 8},
        "at_snapshot": {"LONG": {"roi": 1.0}, "SHORT": {"roi": -1.0}},
        "rules": rules,
    }


def test_compute_cld_metrics_timing_BEFORE_AT_AFTER_SHORT():
    outcome = _outcome()
    # peak bar=8 -> hours=2.25
    before = CLT.compute_cld_metrics(side="SHORT", entry_at=T0 + timedelta(hours=1.0), entry_price=100.0,
                                     snapshot_at=T0, outcome=outcome, fwd_bars=None)
    assert before["timing_vs_extreme"] == "BEFORE" and before["hours_to_extreme"] == 1.25
    assert before["any_rule_before"] is True and "toprev_331" in before["rules_fired_before_entry"]
    assert "s1_breakdown" in before["rules_fired_after_entry"]

    at = CLT.compute_cld_metrics(side="SHORT", entry_at=T0 + timedelta(hours=2.1), entry_price=100.0,
                                 snapshot_at=T0, outcome=outcome, fwd_bars=None)
    assert at["entry_bar"] == 8 and at["timing_vs_extreme"] == "AT"

    after = CLT.compute_cld_metrics(side="SHORT", entry_at=T0 + timedelta(hours=3.0), entry_price=100.0,
                                    snapshot_at=T0, outcome=outcome, fwd_bars=None)
    assert after["timing_vs_extreme"] == "AFTER"


def test_compute_cld_metrics_BEFORE_WINDOW_AFTER_WINDOW():
    outcome = _outcome()
    before_window = CLT.compute_cld_metrics(side="LONG", entry_at=T0 - timedelta(hours=1), entry_price=100.0,
                                            snapshot_at=T0, outcome=outcome, fwd_bars=None)
    assert before_window["timing_vs_extreme"] == "BEFORE_WINDOW" and before_window["entry_bucket"] == "<0"

    after_window = CLT.compute_cld_metrics(side="LONG", entry_at=T0 + timedelta(hours=25), entry_price=100.0,
                                           snapshot_at=T0, outcome=outcome, fwd_bars=None)
    assert after_window["timing_vs_extreme"] == "AFTER_WINDOW" and after_window["entry_bucket"] == ">=24h"


def test_compute_cld_metrics_entry_vs_peak_trough_pct():
    outcome = _outcome(entry_price=100.0, peak_pct=5.0, trough_pct=-3.0)
    m = CLT.compute_cld_metrics(side="SHORT", entry_at=T0 + timedelta(hours=1.0), entry_price=100.0,
                                snapshot_at=T0, outcome=outcome, fwd_bars=None)
    # peak_price = 100*1.05 = 105 -> entry_vs_peak_pct = 100/105-1 = -4.7619%
    assert abs(m["entry_vs_peak_pct"] - (-4.7619)) < 1e-3
    m2 = CLT.compute_cld_metrics(side="LONG", entry_at=T0 + timedelta(hours=1.0), entry_price=100.0,
                                 snapshot_at=T0, outcome=outcome, fwd_bars=None)
    # trough_price = 100*0.97 = 97 -> entry_vs_trough_pct = 100/97-1 = +3.0928%
    assert abs(m2["entry_vs_trough_pct"] - 3.0928) < 1e-3


def test_compute_cld_metrics_label_sim_uses_같은_잣대():
    outcome = _outcome()
    up_bars = [[0, 100 + i, 100 + i, 100 + i, 100 + i, 1.0] for i in range(1, 20)]
    m = CLT.compute_cld_metrics(side="LONG", entry_at=T0 + timedelta(hours=1.0), entry_price=100.0,
                                snapshot_at=T0, outcome=outcome, fwd_bars=up_bars)
    assert m["label_sim_from_entry"]["hit"] in ("TP", "SL", "TIME")
    assert m["label_sim_from_entry"] == CL.sim("LONG", 100.0, up_bars[m["entry_bar"] + 1:])


# ── summarize / render_markdown ──────────────────────────────────────

def _row(*, family, side, win, pnl, join="JOINED", timing="BEFORE", hte=-10.0, bucket="9-24h", roi=None):
    return {
        "family": family, "side": side, "valid_trade": True, "join": join, "win": win,
        "realized_pnl": pnl, "price_roi_pct": roi if roi is not None else pnl,
        "close_reason": "TP_COMPLETE" if win else "FORCE_SL",
        "cld": ({"timing_vs_extreme": timing, "hours_to_extreme": hte, "entry_bucket": bucket}
               if join == "JOINED" else None),
    }


def test_summarize_가족x방향_전후_구간():
    rows = [
        _row(family="A_LADDER", side="SHORT", win=True, pnl=10.0, timing="BEFORE", hte=-10.0, bucket="9-24h"),
        _row(family="A_LADDER", side="SHORT", win=False, pnl=-5.0, timing="AFTER", hte=3.0, bucket="0-3h"),
        _row(family="C_OTHER", side="LONG", win=False, pnl=-2.0, join="SYMBOL_NOT_IN_UNIVERSE"),
        {**_row(family="MANUAL", side="LONG", win=None, pnl=0.0), "valid_trade": False},   # 무효
    ]
    s = CLT.summarize(rows)
    assert s["meta"]["n_instances"] == 4 and s["meta"]["n_valid"] == 3 and s["meta"]["n_invalid"] == 1
    assert s["family_side"]["A_LADDER/SHORT"]["n"] == 2 and s["family_side"]["A_LADDER/SHORT"]["win"] == 1
    assert s["timing_before_after"]["SHORT"]["BEFORE"]["n"] == 1
    assert s["timing_before_after"]["SHORT"]["AFTER"]["n"] == 1
    assert s["hours_to_extreme"]["SHORT"]["[-24,-6)"]["n"] == 1
    assert s["hours_to_extreme"]["SHORT"]["[1,6)"]["n"] == 1
    assert s["entry_bucket"]["SHORT"]["9-24h"]["n"] == 1 and s["entry_bucket"]["SHORT"]["0-3h"]["n"] == 1
    # SYMBOL_NOT_IN_UNIVERSE 는 join!=JOINED 라 timing/hours/entry_bucket 집계에서 빠지지만 family_side 에는 남는다.
    assert s["family_side"]["C_OTHER/LONG"]["n"] == 1

    md = CLT.render_markdown(s)
    assert "가족×방향" in md and "hours_to_extreme" in md and "A_LADDER/SHORT" in md


# ── 배선 ─────────────────────────────────────────────────────────────

def test_배선_CLI():
    s = (APP / "workers" / "chart_learning_worker.py").read_text(encoding="utf-8")
    assert "from app.services import chart_learning_trades as CLT" in s
    assert '"trades"' in s and "CLT.build_trade_dataset" in s and "CLT.summarize" in s


def test_배선_API():
    s = (APP / "api" / "v1" / "chart_learning.py").read_text(encoding="utf-8")
    assert "from app.services import chart_learning_trades as CLT" in s
    assert '"/trades"' in s and '"/trades.md"' in s


def test_모듈_문서화_사장님_지시와_데이터_함정():
    s = (APP / "services" / "chart_learning_trades.py").read_text(encoding="utf-8")
    assert "분석하지 않은 포지션 실패와 성공을 분석해서" in s
    assert "데이터 함정 6가지" in s
    for i in range(1, 7):
        assert f"{i}. " in s

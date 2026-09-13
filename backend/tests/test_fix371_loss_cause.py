"""📉 Fix 371b 손실 원인 학습 — 체결 재생 배분 · 출처 매칭 · 태그 규칙 (반박 검증 C 반영).

사례: 9/13 KOMAUSDT #4500 (1단계 100 + 자동 수익 추가 300) · 哈基米USDT #4483.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql

from app.services import loss_cause as LC

APP = Path(__file__).resolve().parents[1] / "app"
T0 = datetime(2026, 9, 12, 19, 58, tzinfo=timezone.utc)


def _t(m, s=0):
    return T0 + timedelta(minutes=m, seconds=s)


def _entry(m, qty, px, stage=None, otype="MARKET", cid="KOMAUSDT_ADHOC_M_ab12", s=0):
    return {"t": _t(m, s), "qty": qty, "price": px, "stage_no": stage, "order_type": otype, "client_order_id": cid}


def _exit(m, qty, px):
    return {"t": _t(m), "qty": qty, "price": px}


def _koma(exit_px=0.015974, auto_gap_sec=2):
    entries = [_entry(0, 11442, 0.0174535, stage=1, otype="LIMIT", cid="KOMAUSDT_ENTRY1_x"), _entry(137, 31872, 0.0188303)]
    ents = LC.mark_entry_origins(entries, [_t(137, auto_gap_sec)], match_sec=LC.THRESHOLDS["add_match_sec"], manual_strategy=True)
    return {"side": "LONG", "family": "legacy_manual", "entry_origin": "manual_modal", "force_sl_enabled": False,
            "pnl_usdt": (11442 + 31872) * (exit_px - 0.018467), "close_reason": "SL", "max_profit_roi": 15.8, "max_loss_roi": -27.4,
            "entries": ents, "exits": [_exit(2000, 43314, exit_px)]}


# ── 체결 재생 ────────────────────────────────────────────────────────────
def test_koma_auto_add_is_primary_and_attribution_from_fill_replay():
    r = LC.classify(_koma())
    codes = {t["code"] for t in r["tags"]}
    assert r["primary"] == "AUTO_ADD_LOSS"
    assert {"AUTO_ADD_LOSS", "GAVE_BACK_PROFIT", "STOP_LOSS_HIT"} <= codes
    assert r["add_loss_usdt"] == pytest.approx(31872 * (0.015974 - 0.0188303), abs=0.01)   # ≈ −91.0 (9/14 분석값)
    assert r["closed_ratio"] == pytest.approx(1.0) and r["approx"] is False


def test_partial_take_profit_is_allocated_by_holding_share_not_final_price():
    # 반박 검증 C 2번 사례: 1단계 100 @1.0 · 자동 추가 100 @1.2 (평단 1.1) · TP1 60 @1.25 · 나머지 140 @0.9
    ents = LC.mark_entry_origins([_entry(0, 100, 1.0, stage=1), _entry(10, 100, 1.2, cid="X_ADHOC_AM_1")], [], match_sec=600, manual_strategy=False)
    rp = LC.replay("LONG", ents, [_exit(20, 60, 1.25), _exit(30, 140, 0.9)])
    add = next(l for l in rp["lots"] if l["origin"] == "auto_add")
    assert add["pnl"] == pytest.approx(30 * 0.05 + 70 * (0.9 - 1.2))   # = −19.5 (옛 근사 100×(0.9−1.2)=−30 아님)
    assert rp["pnl_gross"] == pytest.approx(60 * 0.15 + 140 * (0.9 - 1.1))


def test_missing_exit_fills_do_not_invent_add_loss():
    f = _koma()
    f["exits"] = []
    r = LC.classify(f)
    assert r["primary"] == "ADD_UNATTRIBUTED" and r["add_loss_usdt"] is None
    assert "AUTO_ADD_LOSS" not in {t["code"] for t in r["tags"]}


def test_short_direction_zone_and_sign():
    ents = LC.mark_entry_origins([_entry(0, 10, 100.0, stage=1), _entry(5, 10, 95.0)], [], match_sec=600, manual_strategy=True)
    r = LC.classify({"side": "SHORT", "pnl_usdt": -70, "max_profit_roi": 12, "entries": ents, "exits": [_exit(9, 20, 101.0)]})
    t = next(t for t in r["tags"] if t["code"] == "MANUAL_ADD_PROFIT_ZONE_LOSS")    # SHORT 평단 100 → 95 추가 = 이익 구간
    assert t["usdt"] == pytest.approx(10 * (95.0 - 101.0))
    assert r["primary"] == "MANUAL_ADD_PROFIT_ZONE_LOSS"


# ── 출처 매칭 ────────────────────────────────────────────────────────────
def test_origin_suffix_nearest_one_to_one_and_unknown():
    entries = [_entry(0, 1, 1.0, stage=1),
               _entry(10, 1, 1.1, cid="S_ADHOC_AM_1"),                  # 접미사 = 자동 (기록 1개 소비)
               _entry(11, 1, 1.1),                                       # 옛 접미사 · 남은 기록과 최근접 매칭
               _entry(12, 1, 1.1),                                       # 기록이 다 소비됨 → 사람 전략 아니면 출처 미상
               _entry(13, 1, 1.1, otype="LIMIT", cid="S_ADHOC_L_2")]     # 지정가는 자동 기록과 매칭하지 않는다
    auto = [_t(10, 5), _t(11, 400)]
    got = [e["origin"] for e in LC.mark_entry_origins(entries, auto, match_sec=600, manual_strategy=False)]
    assert got == ["plan", "auto_add", "auto_add", "unknown_add", "unknown_add"]
    got_manual = [e["origin"] for e in LC.mark_entry_origins(entries, auto, match_sec=600, manual_strategy=True)]
    assert got_manual[3:] == ["manual_add", "manual_add"]
    # 창 밖(>600초)이면 자동으로 보지 않는다
    assert LC.mark_entry_origins([_entry(0, 1, 1.0)], [_t(11)], match_sec=600, manual_strategy=True)[0]["origin"] == "manual_add"


def test_hakimi_auto_add_and_manual_average_down_are_separated():
    entries = [_entry(0, 4864, 0.04111, stage=1, otype="LIMIT", cid="H_ENTRY1_1"), _entry(1457, 13945, 0.0429636),
               _entry(3000, 6116, 0.0327, otype="LIMIT", cid="H_ADHOC_L_2")]
    ents = LC.mark_entry_origins(entries, [_t(1457, 90)], match_sec=600, manual_strategy=True)
    r = LC.classify({"side": "LONG", "pnl_usdt": -300.0, "max_profit_roi": 8.96, "max_loss_roi": -45, "force_sl_enabled": False,
                     "entries": ents, "exits": [_exit(4000, 24925, 0.0300)]})
    by = {t["code"]: t for t in r["tags"]}
    assert by["AUTO_ADD_LOSS"]["usdt"] == pytest.approx(13945 * (0.0300 - 0.0429636), abs=0.01)
    assert by["MANUAL_AVG_DOWN_LOSS"]["usdt"] == pytest.approx(6116 * (0.0300 - 0.0327), abs=0.01)
    assert "NEVER_IN_PROFIT" not in by and "GAVE_BACK_PROFIT" not in by


# ── 태그 규칙 ────────────────────────────────────────────────────────────
def test_cleanup_reason_is_not_primary_and_external_close_is_last():
    ents = LC.mark_entry_origins([_entry(0, 1, 1.2, stage=1)], [], match_sec=600, manual_strategy=False)
    r = LC.classify({"side": "LONG", "pnl_usdt": -50, "close_reason": "FLAT_CLEANUP", "max_profit_roi": 1.0, "max_loss_roi": -30,
                     "entries": ents, "exits": [_exit(5, 1, 1.0)]})
    assert r["primary"] == "NEVER_IN_PROFIT" and "CLOSE_REASON_UNKNOWN" in {t["code"] for t in r["tags"]}
    r2 = LC.classify({"side": "LONG", "pnl_usdt": -50, "close_reason": "EXTERNAL_CLOSE", "max_profit_roi": 12, "max_loss_roi": -30,
                      "entries": ents, "exits": [_exit(5, 1, 1.0)]})
    assert r2["primary"] == "GAVE_BACK_PROFIT"


def test_roi_missing_and_reset_add_do_not_claim_never_in_profit():
    ents = LC.mark_entry_origins([_entry(0, 1, 1.0, stage=1)], [], match_sec=600, manual_strategy=True)
    r = LC.classify({"side": "LONG", "pnl_usdt": -5, "entries": ents, "exits": [_exit(1, 1, 0.9)]})
    assert {t["code"] for t in r["tags"]} == {"ROI_RECORD_MISSING", "UNCLASSIFIED"} and r["primary"] == "UNCLASSIFIED"
    with_add = _koma()
    with_add["max_profit_roi"] = None                                      # reset 추가가 최고 ROI 를 지운 경우
    assert "NEVER_IN_PROFIT" not in {t["code"] for t in LC.classify(with_add)["tags"]}


def test_deep_drawdown_surge_chase_ladder():
    ents = LC.mark_entry_origins([_entry(0, 1, 1.2, stage=1), _entry(60, 1, 1.1, stage=2)], [], match_sec=600, manual_strategy=True)
    r = LC.classify({"side": "LONG", "pnl_usdt": -50, "max_profit_roi": 0.5, "max_loss_roi": -80, "force_sl_enabled": False,
                     "entry_ctx": {"pump_dump": {"change_pct": 22.0, "tf": "5m", "window": "1h"}},
                     "entries": ents, "exits": [_exit(90, 2, 0.8)]})
    assert {"DEEP_DRAWDOWN_NO_STOP", "SURGE_CHASE_ENTRY", "LADDER_AVERAGING_LOSS", "NEVER_IN_PROFIT"} <= {t["code"] for t in r["tags"]}
    assert r["primary"] == "DEEP_DRAWDOWN_NO_STOP"
    short = LC.classify({"side": "SHORT", "pnl_usdt": -5, "max_profit_roi": 5, "max_loss_roi": -10,
                         "entry_ctx": {"pump_dump": {"change_pct": 22.0}}})
    assert "SURGE_CHASE_ENTRY" not in {t["code"] for t in short["tags"]}          # SHORT 은 급등 추격 아님


def test_small_losses_and_wins_are_not_tagged():
    assert LC.classify({"side": "LONG", "pnl_usdt": -0.4})["tags"] == []
    assert LC.classify({"side": "LONG", "pnl_usdt": 3.2})["tags"] == []
    assert LC.classify({"side": "LONG", "pnl_usdt": None})["tags"] == []


def test_thresholds_override_from_settings():
    class _DB:
        def get(self, _m, key):
            return type("R", (), {"value": '{"gave_back_roi": 20, "junk": 1, "never_profit_roi": "x"}'})() if key == LC.S_THRESH else None
    th = LC.thresholds(_DB())
    assert th["gave_back_roi"] == 20.0 and "junk" not in th and th["never_profit_roi"] == LC.THRESHOLDS["never_profit_roi"]
    assert "GAVE_BACK_PROFIT" not in {t["code"] for t in LC.classify(_koma(), th)["tags"]}


def test_aggregate_and_markdown():
    items = [{"id": 4500, "symbol": "KOMAUSDT", "side": "LONG", "exit_time": None, "result": LC.classify(_koma())},
             {"id": 7, "symbol": "X", "side": "LONG", "exit_time": None, "result": LC.classify({"side": "LONG", "pnl_usdt": 2})}]
    rep = LC.aggregate(items, days=30)
    assert rep["n_loss"] == 1 and rep["actions"][0]["code"] == "AUTO_ADD_LOSS"
    assert rep["by_code"]["AUTO_ADD_LOSS"]["attributed_usdt"] < -90
    md = LC.render_markdown(rep)
    assert "자동 수익 추가분이 손실로 뒤집힘" in md and "KOMAUSDT" in md


# ── SQL · 배선 ───────────────────────────────────────────────────────────
def test_sql_statements_compile_for_postgres_and_skip_heavy_columns():
    scan = str(LC.scan_stmt(version=1, min_loss=1.0, limit=200).compile(dialect=postgresql.dialect()))
    assert "progression" not in scan and "exit_context" not in scan and "LIMIT" in scan
    assert "trade_learning_records.insights" in scan and "->>" in scan           # 태깅 여부를 SQL 에서 거른다 (파이썬 전량 로드 금지)
    save = str(LC.save_stmt(1, {"v": 1, "tags": []}).compile(dialect=postgresql.dialect()))
    assert "jsonb_set" in save and "{loss_causes}" in save
    rep = str(LC.report_stmt(version=1, cutoff=T0).compile(dialect=postgresql.dialect()))
    assert "progression" not in rep and "trade_learning_records.insights" in rep and "->>" in rep


def test_every_code_has_label_and_apply_and_recommended_keys_exist_elsewhere():
    for code, c in LC.CAUSES.items():
        assert c["label"] and c["apply"], code
    others = "\n".join(p.read_text(encoding="utf-8") for p in APP.rglob("*.py") if p.name != "loss_cause.py")
    for key in ("pyramid_after_add_sl_scope", "manual_add_after_sl_enabled", "stage_trim_before_next_enabled", "legacy_ladder_force_sl_enabled"):
        assert key in others, key


def test_auto_add_orders_carry_distinct_suffix():
    src = (APP / "services" / "execution_service.py").read_text(encoding="utf-8")
    assert 'suffix="ADHOC_M" if _manual371 else "ADHOC_AM"' in src and 'suffix="ADHOC_L" if _manual371 else "ADHOC_AL"' in src
    assert all(s.startswith("_ADHOC_A") for s in LC.AUTO_SUFFIXES)


def test_wiring_scheduler_and_api():
    sr = (APP / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    assert 'guarded_job("loss_cause", 600, _loss_cause)' in sr and "run_loss_cause_once" in sr
    tl = (APP / "api" / "v1" / "trade_learning.py").read_text(encoding="utf-8")
    assert '@router.get("/loss-causes")' in tl

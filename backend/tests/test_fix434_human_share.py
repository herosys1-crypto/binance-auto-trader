"""Fix 434 — 실현 손익을 「시스템 몫 / 사람 💉 추가 몫 / 출처 모름」으로 나누기 (보고 전용)."""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from app.services import human_share as HS

T0 = datetime(2026, 9, 21, 15, 0, tzinfo=timezone.utc)
ROOT = pathlib.Path(HS.__file__).resolve().parents[2]


def _e(cid, qty, px, *, t=T0, stage=None, ot="MARKET"):
    return {"t": t, "qty": qty, "price": px, "stage_no": stage, "order_type": ot, "client_order_id": cid}


def _x(qty, px, t):
    return {"t": t, "qty": qty, "price": px}


def test_origin_classification():
    assert HS.origin_of(_e("PLAYUSDT_ENTRY1_ab", 1, 1, stage=1)) == "plan"
    assert HS.origin_of(_e("PLAYUSDT_ENTRY1_ab", 1, 1)) == "plan"                                  # stage 비어도 ENTRY = 시스템
    assert HS.origin_of(_e("PLAYUSDT_ADHOC_AM_x", 1, 1)) == "auto_add"
    assert HS.origin_of(_e("PLAYUSDT_ADHOC_M_x", 1, 1)) == "manual_add"
    assert HS.origin_of(_e("PLAYUSDT_ADHOC_L_x", 1, 1, ot="LIMIT")) == "manual_add"
    assert HS.origin_of(_e("X_ADHOC_M_y", 1, 1, t=datetime(2026, 9, 13, 23, 59, tzinfo=timezone.utc))) == "unknown"   # Fix 371 전 = 공용
    assert HS.origin_of(_e("X_ADHOC_M_y", 1, 1, t=datetime(2026, 9, 20))) == "manual_add"                         # tz 없음 = UTC
    assert HS.origin_of(_e("weird", 1, 1)) == "unknown"


def test_playusdt_like_human_add_takes_the_loss():
    """#4548 모양: SHORT 10U 시스템 진입 → 사람이 11배 추가 → 손절. 사람 몫이 대부분."""
    ent = [_e("PLAY_ENTRY1_a", 692, 0.02887, stage=1),
           _e("PLAY_ADHOC_M_b", 6357, 0.03146, t=T0 + timedelta(days=2))]
    ex = [_x(7049, 0.0353, T0 + timedelta(days=3))]
    gross = (0.02887 - 0.0353) * 692 + (0.03146 - 0.0353) * 6357
    realized = gross - 0.3                                                          # 수수료
    s = HS.split("SHORT", ent, ex, realized)
    assert s["method"] == "replay" and s["human_n"] == 1
    assert s["system"] + s["human"] + s["unknown"] == pytest.approx(s["realized"], abs=1e-9)   # 합 보존
    assert s["realized"] == pytest.approx(realized, abs=1e-4)
    sys_notional = 692 * 0.02887
    tot = sys_notional + 6357 * 0.03146
    assert s["system"] == pytest.approx((0.02887 - 0.0353) * 692 - 0.3 * sys_notional / tot, abs=1e-3)
    assert s["human"] < s["system"] < 0


def test_no_human_no_change():
    s = HS.split("LONG", [_e("A_ENTRY1_x", 10, 1.0, stage=1), _e("A_ADHOC_AM_y", 5, 0.9)], [_x(15, 1.1, T0 + timedelta(hours=1))], 1.23)
    assert (s["system"], s["human"], s["unknown"], s["method"]) == (1.23, 0.0, 0.0, "none")


def test_partial_close_falls_back_to_notional():
    ent = [_e("A_ENTRY1_x", 10, 1.0, stage=1), _e("A_ADHOC_M_y", 30, 1.0, t=T0 + timedelta(hours=1))]
    s = HS.split("LONG", ent, [_x(5, 1.1, T0 + timedelta(hours=2))], 4.0)            # 40개 중 5개만 청산
    assert s["method"] == "notional" and s["human"] == pytest.approx(3.0) and s["system"] == pytest.approx(1.0)


def test_none_and_empty_safe():
    s = HS.split("LONG", [], [], None)
    assert s["realized"] == 0.0 and s["system"] == 0.0
    s2 = HS.split("LONG", [_e("A_ADHOC_M_y", 0, 0)], [], 2.0)                      # 명목 0
    assert s2["system"] == 2.0 and s2["method"] == "none"


def test_unknown_bucket_before_fix371():
    old = datetime(2026, 9, 1, tzinfo=timezone.utc)
    ent = [_e("A_ENTRY1_x", 10, 1.0, stage=1, t=old), _e("A_ADHOC_M_y", 10, 1.0, t=old + timedelta(hours=1))]
    s = HS.split("LONG", ent, [_x(20, 0.9, old + timedelta(hours=2))], -2.0)
    assert s["human"] == 0.0 and s["unknown"] == pytest.approx(-1.0) and s["system"] == pytest.approx(-1.0)


def test_reports_use_split():
    lbf = (ROOT / "scripts" / "entry_condition_study" / "live_by_family.py").read_text(encoding="utf-8")
    cgr = (ROOT / "scripts" / "entry_condition_study" / "council_gate_report.py").read_text(encoding="utf-8")
    assert "HS.split_for(" in lbf and "시스템 몫" in lbf
    assert "HS.split_for(" in cgr and "시스템 몫" in cgr
    src = (ROOT / "app" / "services" / "human_share.py").read_text(encoding="utf-8")
    assert "commit" not in src and "update(" not in src.lower().replace("strategy_config", "")


def test_split_for_isolates_bad_rows(monkeypatch):
    class _DB:
        def execute(self, stmt):
            class R:
                def all(self_inner):
                    return [(1, "ENTRY", None, "MARKET", "A_ADHOC_M_x", 5, 1.0, None, T0, T0),
                            (2, "ENTRY", 1, "MARKET", "B_ENTRY1_x", 5, 1.0, None, T0, T0)]
            return R()
    real = HS.split
    monkeypatch.setattr(HS, "split", lambda side, e, x, rp: (_ for _ in ()).throw(RuntimeError("boom")) if side == "BAD" else real(side, e, x, rp))
    out = HS.split_for(_DB(), [(1, "BAD", 3.0), (2, "LONG", 1.0)])
    assert out[1]["method"] == "error" and out[1]["system"] == 3.0
    assert out[2]["method"] == "none" and out[2]["system"] == 1.0

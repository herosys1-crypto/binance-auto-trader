"""📅 Fix 461 — 사무실 「오늘 하루 1번 잡」 표 (사장님 10/15 「실장님 승인으로 모두 개발 완료」)."""
from __future__ import annotations

import pathlib
from datetime import datetime

from app.services import office_board as OB

APP = pathlib.Path(OB.__file__).resolve().parents[1]


def _ts(md_hm: str) -> float:
    """'10-15 08:30' (KST) → epoch."""
    return datetime.strptime("2026-" + md_hm, "%Y-%m-%d %H:%M").replace(tzinfo=OB.KST).timestamp()


def _row(rows, job):
    return next(r for r in rows if r["job"] == job)


NOW = _ts("10-15 13:00")


def test_states():
    recs = {
        "daily_briefing": {"s": _ts("10-15 07:30"), "e": _ts("10-15 07:31"), "st": "ok"},
        "strategy_council": {"s": _ts("10-15 09:40"), "e": _ts("10-15 09:41"), "st": "err", "err": "Boom: " + "x" * 300},
        "paper_retention": {"s": _ts("10-15 12:59"), "st": "run"},
        "symbol_sync_daily": {"s": _ts("10-14 12:00"), "e": _ts("10-14 12:01"), "st": "ok"},      # 어제만 → 놓침?
        "verdict_report": {"s": _ts("10-14 10:20"), "e": _ts("10-14 10:20"), "st": "ok"},         # 정해진 날만 → 해당 없음
    }
    rows = OB.daily_table(recs, {"suggestion_daily_predict": NOW + 7300}, NOW)
    assert [r["job"] for r in rows] == [d.job for d in OB.DAILY_JOBS] and len(rows) == 11   # Fix 465 ichikijun_board
    assert _row(rows, "daily_briefing")["state"] == "done" and _row(rows, "daily_briefing")["today"]
    c = _row(rows, "strategy_council")
    assert c["state"] == "failed" and c["err"].startswith("Boom") and len(c["err"]) == 120
    assert _row(rows, "paper_retention")["state"] == "running"
    assert _row(rows, "symbol_sync_daily")["state"] == "missed" and _row(rows, "symbol_sync_daily")["err"] is None
    assert _row(rows, "verdict_report")["state"] == "skip"
    p = _row(rows, "suggestion_daily_predict")
    assert p["state"] == "later" and p["next"] == "2시간 뒤" and p["last"] is None
    assert _row(rows, "memory_consolidator")["state"] == "unknown"           # 기록 없음 · 예정 지남
    assert _row(rows, "daily_briefing")["last"] == "10-15 07:30" and _row(rows, "daily_briefing")["err"] is None


def test_grace_minutes():
    recs = {"symbol_sync_daily": {"s": _ts("10-14 12:00"), "e": _ts("10-14 12:01"), "st": "ok"}}
    assert _row(OB.daily_table(recs, {}, _ts("10-15 12:09")), "symbol_sync_daily")["state"] == "later"
    assert _row(OB.daily_table(recs, {}, _ts("10-15 12:11")), "symbol_sync_daily")["state"] == "missed"


def test_today_is_kst_date():
    # UTC 23:30 = KST 다음날 08:30 — KST 07:30 시작 기록은 오늘
    now = _ts("10-16 08:30")
    recs = {"daily_briefing": {"s": _ts("10-16 07:30"), "e": _ts("10-16 07:31"), "st": "ok"},
            "daily_summary": {"s": _ts("10-15 23:59"), "e": _ts("10-16 00:00"), "st": "ok"}}
    rows = OB.daily_table(recs, {}, now)
    assert _row(rows, "daily_briefing")["today"] and _row(rows, "daily_briefing")["state"] == "done"
    assert _row(rows, "daily_summary")["state"] == "missed"                   # 10/15 23:59 시작 = 어제


def test_build_has_daily_and_keeps_rest():
    d0 = OB.build(recs={}, extras={}, now=NOW)
    assert len(d0["daily"]) == 11 and {"rooms", "counts", "at", "jobs_recorded", "other_errors"} <= set(d0)
    assert [r["label"] for r in d0["rooms"]] == ["지휘실", "실주문 매매실", "가상매매 연구실", "학습실", "감시실"]


def test_html():
    html = (APP / "static" / "office.html").read_text(encoding="utf-8")
    assert "오늘 하루 1번 잡" in html and "function renderDaily(" in html and "renderDaily(d.daily)" in html
    for lab in ("완료", "작업 중", "실패", "놓침?", "예정", "해당 없음", "기록 없음"):
        assert lab in html
    i = html.index("function renderDaily(")
    body = html[i:html.index("function render()", i)]
    assert body.count("esc(") >= 8 and "overflow-x:auto" in html


def test_broken_records_do_not_break():
    recs = {"daily_briefing": {"s": "abc", "st": "ok"}, "strategy_council": {"s": float("nan"), "st": "ok"},
            "paper_retention": {"st": "ok"}, "symbol_sync_daily": {"s": _ts("10-15 12:00"), "e": "x", "st": "ok"}}
    rows = OB.daily_table(recs, {}, NOW)
    assert _row(rows, "daily_briefing")["state"] == "unknown" and _row(rows, "strategy_council")["state"] == "unknown"
    assert _row(rows, "paper_retention")["state"] == "unknown"                 # 시작 시각 없는 기록 = 기록 없음
    assert _row(rows, "symbol_sync_daily")["state"] == "done"                  # 끝 시각만 깨지면 시작 기준으로 판정
    assert len(OB.build(recs={"memory_consolidator": {"s": object(), "st": "ok"}}, extras={}, now=NOW)["daily"]) == 11


def test_stale_run_from_yesterday_is_missed():
    recs = {"symbol_sync_daily": {"s": _ts("10-14 12:00"), "st": "run"}}      # 어제 죽어 run 이 남음
    assert _row(OB.daily_table(recs, {}, NOW), "symbol_sync_daily")["state"] == "missed"


def test_error_text_kept_raw():
    recs = {"daily_briefing": {"s": _ts("10-15 07:30"), "e": _ts("10-15 07:31"), "st": "err", "err": "A\n  B"}}
    assert _row(OB.daily_table(recs, {}, NOW), "daily_briefing")["err"] == "A\n  B"


def test_nan_inf_end_and_next_only_affect_that_row():
    recs = {"daily_briefing": {"s": _ts("10-15 07:30"), "e": "NaN", "st": "ok"},
            "daily_report": {"s": _ts("10-15 09:00"), "e": float("inf"), "st": "ok"}}
    rows = OB.daily_table(recs, {"strategy_council": float("nan"), "paper_retention": "inf"}, NOW)
    assert len(rows) == 11
    assert _row(rows, "daily_briefing")["state"] == "done" and _row(rows, "daily_briefing")["ago"].endswith("전")
    assert _row(rows, "daily_report")["state"] == "done"
    assert _row(rows, "strategy_council")["next"] == "—" and _row(rows, "paper_retention")["next"] == "—"

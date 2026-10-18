"""10/17 분석관 지적 — 성적표 「오늘 시장폭 구간」 을 지금 시장폭(regime_24h)으로 + 판정 스크립트 동점 고정·날 단위(반박 감사)."""
import pathlib

from app.workers import strategy_council_worker as W

SCRIPTS = pathlib.Path(W.__file__).resolve().parents[2] / "scripts" / "entry_condition_study"


def _rep(br):
    return {"params": {"lo": 0.4, "hi": 0.6}, "regime_24h": {"breadth": br},
            "E_today": {"d": "2026-10-17", "current_b": "high",
                        "cells": [{"rule": "a", "side": "LONG", "b": "high", "edge": 2.0},
                                  {"rule": "b", "side": "SHORT", "b": "low", "edge": 1.0}]}}


def test_live_bucket_replaces_closed_day_bucket():
    rep = _rep(0.3)
    W.apply_live_bucket(rep)
    E = rep["E_today"]
    assert E["current_b"] == "low" and E["current_b_closed"] == "high" and E["cells"][0]["b"] == "low"


def test_live_bucket_noop_without_breadth():
    rep = _rep(None)
    W.apply_live_bucket(rep)
    assert rep["E_today"]["current_b"] == "high" and "current_b_closed" not in rep["E_today"]
    W.apply_live_bucket({})                                           # 깨진 입력도 예외 없음


def test_judgement_scripts_fixed():
    for f in ("council_realistic_2026_10_16.py", "strategy_audit_2026_10_16.py", "long_trend_k_2026_10_16.py"):
        assert "ORDER BY opened_at, md5(symbol)" in (SCRIPTS / f).read_text(encoding="utf-8"), f
    k = (SCRIPTS / "long_trend_k_2026_10_16.py").read_text(encoding="utf-8")
    assert "sorted(k, key=lambda x: x[0])" in k                       # 동점에서 수익 낮은 행을 고르던 것
    s4 = (SCRIPTS / "s4_exit_compare_2026_10_17.py").read_text(encoding="utf-8")
    assert "def day_means(" in s4 and 'day_verdict("L 판정", d, min_days=12, min_pairs=100)' in s4
    assert 'day_verdict("S4 판정", s4, min_days=15)' in s4
    nb = (SCRIPTS / "neutral_basket_2026_10_16.py").read_text(encoding="utf-8")
    assert "ORDER BY opened_at, md5(symbol)" in nb and "sorted(pairs, key=lambda x: x[0])" in nb   # 10/18: 무작위 하루 1건 −13 의 원인

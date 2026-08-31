"""🚨 Fix 227 — OBV 게이트가 **부호를 버려서** 명세와 정반대로 동작했다.

## 이 파일 자신의 명세 (obv_gate.py 맨 위 docstring)

    "4H OBV 매우 큰 **음수** = LONG 금지 (세력 이탈!)"
    "4H OBV 매우 큰 **양수** = SHORT 금지 (세력 매집!)"

## 그런데 코드는

    ratio = abs(obv_now) / ...          ← 부호 소실
    if direction == "down" and ratio >= 0.6:  →  LONG 차단

`direction` 은 **최근 20봉 기울기**, `ratio` 는 **전체 누적의 절대값**이라 창이 다르다.
그래서 이런 상태가 만들어진다:

    obv_now  = +49,000,000   (13일 매집 극단 = 세력이 사 모으는 중)
    direction= 'down'        (최근 20봉만 하락)
    → LONG 차단, 로그는 "극단 하락 (obv=+49000000)"  ← 양수인데 「하락」

## 사장님 원칙 (2026-08-30)

    "볼밴 하단까지 갔다가도 **obv가 강하면 이것도 다시 상승으로 전환**된다고 봐야해"

OBV 가 가장 강할 때가 LONG 자리인데, 바로 그때 시스템이 LONG 을 막고 있었다.
"""
from __future__ import annotations

import app.services.obv_gate as gate

EXTREME = gate.OBV_EXTREME_RATIO


def _patch(monkeypatch, direction, ratio, obv_now):
    monkeypatch.setattr(
        gate, "_get_obv_direction_4h",
        lambda bc, symbol: (direction, ratio, obv_now),
    )


def test_strong_accumulation_no_longer_blocks_long(monkeypatch):
    """🚨 핵심 — 누적 OBV 가 **양수 극단**인데 최근만 하락: LONG 을 막으면 안 된다.

    사장님이 말씀하신 「볼밴 하단까지 갔지만 OBV 가 강해 다시 오를 자리」가 이것이다.
    """
    _patch(monkeypatch, "down", +0.61, 49_000_000)
    ok, why = gate.check_obv_gate(object(), "TESTUSDT", "LONG")
    assert ok, f"매집 극단에서 LONG 이 막혔다: {why}"


def test_real_distribution_still_blocks_long(monkeypatch):
    """진짜 세력 이탈(누적 OBV 음수 극단 + 하락)은 그대로 막아야 한다."""
    _patch(monkeypatch, "down", -0.61, -49_000_000)
    ok, why = gate.check_obv_gate(object(), "TESTUSDT", "LONG")
    assert not ok, "세력 이탈인데 LONG 이 통과했다"
    assert "극단 하락" in why


def test_strong_accumulation_still_blocks_short(monkeypatch):
    """반대쪽 명세도 지켜야 한다 — 매집 극단에서 SHORT 금지."""
    _patch(monkeypatch, "up", +0.61, 49_000_000)
    ok, why = gate.check_obv_gate(object(), "TESTUSDT", "SHORT")
    assert not ok, "매집 극단인데 SHORT 가 통과했다"
    assert "SHORT skip" in why and "OBV" in why


def test_strong_distribution_no_longer_blocks_short(monkeypatch):
    """대칭 — 누적이 음수 극단인데 최근만 상승: SHORT 를 막으면 안 된다."""
    _patch(monkeypatch, "up", -0.61, -49_000_000)
    ok, why = gate.check_obv_gate(object(), "TESTUSDT", "SHORT")
    assert ok, f"이탈 극단에서 SHORT 가 막혔다: {why}"


def test_non_extreme_passes_both_ways(monkeypatch):
    """극단이 아니면 방향만으로는 막지 않는다 (Fix 141 의도 유지)."""
    for side, direction, ratio in (
        ("LONG", "down", -0.30),
        ("SHORT", "up", +0.30),
    ):
        _patch(monkeypatch, direction, ratio, 1_000_000)
        ok, _ = gate.check_obv_gate(object(), "TESTUSDT", side)
        assert ok, f"{side} 가 극단도 아닌데 막혔다"


def test_unknown_is_fail_open(monkeypatch):
    """데이터 부족은 통과 — 게이트 오류로 전 종목이 멈추면 안 된다."""
    _patch(monkeypatch, "unknown", 0.0, 0.0)
    ok, why = gate.check_obv_gate(object(), "TESTUSDT", "LONG")
    assert ok and "unknown" in why


def test_old_behaviour_really_was_backwards():
    """음성 대조군 (헌법 170) — 옛 식이 실제로 부호를 잃는지 보여준다.

    이게 성립하지 않으면 Fix 227 은 고칠 게 없었다는 뜻이다.
    """
    obv_now, denom = 49_000_000.0, 80_000_000.0
    old = abs(obv_now) / denom          # 옛 코드
    new = obv_now / denom               # Fix 227
    assert old >= EXTREME, "옛 식이 극단 판정에 걸리지 않는다 = 대조군 무효"
    assert new > 0, "새 식은 매집을 양수로 본다"
    assert not (new <= -EXTREME), "새 식에서는 LONG 차단 조건이 성립하지 않아야 한다"


# ── Fix 245: SHORT 만 더 일찍 막는다 (실측) ──────────────────────────

def test_short_threshold_is_tighter_than_long():
    """🚨 실측 — 진 SHORT 의 4H OBV 중앙값이 0.39~0.53 인데 공통 임계는 0.6 이었다.

    즉 **한 건도 못 걸렀다**. 사장님 사상 ④ ("obv가 하락하지 않으면 결국 obv 방향으로
    간다")가 데이터로 확인됐으므로 SHORT 만 승/패 중앙값 사이로 조인다.
    LONG 은 0.6 그대로 — 「급락 후 반등」 진입을 막지 않기 위해서다(Fix 141).
    """
    assert gate.OBV_SHORT_EXTREME_RATIO == 0.35
    assert gate.OBV_SHORT_EXTREME_RATIO < gate.OBV_EXTREME_RATIO
    # 승자 중앙값(0.238~0.331) 위 / 패자 중앙값(0.391~0.530) 아래
    assert 0.331 < gate.OBV_SHORT_EXTREME_RATIO < 0.391


def test_losing_short_profile_is_now_blocked(monkeypatch):
    """실측 패자 중앙값(0.39 / 0.53)이 실제로 걸러지는가."""
    for ratio in (0.391, 0.530):
        _patch(monkeypatch, "up", ratio, 30_000_000)
        ok, why = gate.check_obv_gate(object(), "TESTUSDT", "SHORT")
        assert not ok, f"진 SHORT 프로파일 ratio={ratio} 가 통과했다: {why}"


def test_winning_short_profile_still_passes(monkeypatch):
    """🚨 과하게 조이면 유일하게 버는 전략(AUTO_BB S, 손익비 2.60)이 죽는다."""
    for ratio in (0.238, 0.331):
        _patch(monkeypatch, "up", ratio, 20_000_000)
        ok, why = gate.check_obv_gate(object(), "TESTUSDT", "SHORT")
        assert ok, f"이긴 SHORT 프로파일 ratio={ratio} 가 막혔다: {why}"


def test_long_gate_unchanged_by_the_short_tightening(monkeypatch):
    """LONG 은 영향받지 않아야 한다 — 급락 후 반등 진입 보호."""
    _patch(monkeypatch, "down", -0.40, -20_000_000)
    ok, _why = gate.check_obv_gate(object(), "TESTUSDT", "LONG")
    assert ok, "LONG 이 SHORT 임계에 잘못 걸렸다"

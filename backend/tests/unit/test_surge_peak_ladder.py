"""🎯 Fix 267 — 급등 정점 SHORT, 이기면 늘리고 지면 다시.

## 사장님 지시 (2026-09-01)

  "당일 급등하는 1위 10위까지만 모니터링하고 우리로직상 최고점에 조정 시작할 심볼에
   1단계 500 진입하고 손절 -5%에서 청산하고 ... 2단계 1000 ... -10%면 청산"
  정정: "두번 실패하면 **250**인거야. 당연히 **첫진입부터 성공해서 포지션 추가**를 하고 싶은거야"
  선택: "**C**로 시작해 실적 보고 B → A"

## 이 파일이 지키는 것

  ① **손절은 가격 기준**이다. 250 이 그 증거 (50 + 200).
     코드의 override 는 ROI 기준이므로 반드시 변환해야 한다.
  ② **정점 즉시 진입 금지** — 실측 11건 승률 **0.0%**, 건당 -133.70.
     「정점 대비 8% 하락」이 이 설계의 핵심이고 빼면 -44.33/건이 된다.
  ③ **C 안 = 추가 절반 + 손실 고정**. 손실을 완전 고정하면(x1.0) 수익이 사라진다(-2.33).
  ④ 다수결 금지 (Fix 250), 결측은 통과로 세지 않음 (자본이 나가는 판정).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.surge_peak_ladder import (
    ADD_CAPITAL_RATIO,
    BAR_MINUTES,
    CAPITAL_LADDER,
    DROP_MIN_PCT,
    MAX_ADDS,
    SL_PRICE_LADDER,
    STALL_BARS,
    add_step,
    cycle_worst_case_loss,
    evaluate_surge_entry,
    sl_roi_for_price_pct,
    update_peak,
)

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
STALLED = NOW - timedelta(minutes=STALL_BARS * BAR_MINUTES + 1)
FRESH = NOW - timedelta(minutes=1)


def _ev(**kw):
    base = dict(
        rank=3, chg_24h=35.0, quote_volume=50_000_000.0,
        mark=91.0, peak=100.0,            # 정점 대비 9% 하락
        peak_seen_at=STALLED, bb4h_broken=True, obv_extreme_up=False, now=NOW,
    )
    base.update(kw)
    return evaluate_surge_entry(**base)


# ───────────────────────── ① 손절은 가격 기준

def test_price_pct_converts_to_roi_by_leverage():
    """🚨 사장님 -5% 는 **가격** 5% 다. 코드 override 는 ROI 기준."""
    assert sl_roi_for_price_pct(5.0, 2.0) == 10.0
    assert sl_roi_for_price_pct(10.0, 2.0) == 20.0
    # 레버리지가 바뀌어도 손실 금액이 유지되도록 역산한다
    assert sl_roi_for_price_pct(5.0, 3.0) == 15.0
    assert sl_roi_for_price_pct(5.0, 1.0) == 5.0


def test_bad_inputs_return_none_not_zero():
    """0 을 돌려주면 「손절 없음」이 되어 자본이 무방비가 된다."""
    for a, b in ((None, 2), (5, None), (0, 2), (5, 0), ("x", 2)):
        assert sl_roi_for_price_pct(a, b) is None


def test_two_failures_cost_exactly_250():
    """🚨 사장님 전제 검산 — 「두번 실패하면 250」.

        500  x 2x = 명목 1,000 -> 가격 5%  = -50
        1000 x 2x = 명목 2,000 -> 가격 10% = -200
    """
    lev = 2.0
    a1 = CAPITAL_LADDER[0] * lev * SL_PRICE_LADDER[0] / 100
    a2 = CAPITAL_LADDER[1] * lev * SL_PRICE_LADDER[1] / 100
    assert a1 == 50.0 and a2 == 200.0
    assert a1 + a2 == 250.0


def test_third_attempt_returns_to_first_settings():
    """원문 「다시 **같은 조건의 로직으로** 진행」 = 1시도 설정 복귀."""
    assert CAPITAL_LADDER[2] == CAPITAL_LADDER[0]
    assert SL_PRICE_LADDER[2] == SL_PRICE_LADDER[0]
    assert cycle_worst_case_loss(2.0) == 300.0     # 50 + 200 + 50


# ───────────────────────── ③ C 안 = 추가 절반 + 손실 고정

def test_add_uses_half_capital():
    """사장님 선택 C — 추가 자본은 1시도 자본의 **절반**."""
    assert ADD_CAPITAL_RATIO == 0.5
    s = add_step(base_capital=500, current_capital=500,
                 base_sl_price_pct=5.0, leverage=2.0, adds_done=0)
    assert s["add_capital"] == 250.0
    assert s["new_capital"] == 750.0


def test_add_keeps_the_loss_amount_fixed():
    """🚨 C 안의 핵심 — 자본이 늘어도 **손절 금액은 그대로**.

    자본 500 -> 750 이면 ROI 를 10% -> 6.67% 로 줄여 손실을 50 에 묶는다.
    """
    s1 = add_step(base_capital=500, current_capital=500,
                  base_sl_price_pct=5.0, leverage=2.0, adds_done=0)
    assert abs(s1["base_loss_usdt"] - 50.0) < 1e-9
    # 손실 = 자본 x 레버 x (ROI/레버) /100 = 자본 x ROI/100
    loss1 = s1["new_capital"] * s1["new_sl_roi"] / 100
    assert abs(loss1 - 50.0) < 1e-6

    s2 = add_step(base_capital=500, current_capital=s1["new_capital"],
                  base_sl_price_pct=5.0, leverage=2.0, adds_done=1)
    assert s2["new_capital"] == 1000.0
    loss2 = s2["new_capital"] * s2["new_sl_roi"] / 100
    assert abs(loss2 - 50.0) < 1e-6, "추가할수록 손실이 커지면 250 이 깨진다"


def test_add_is_capped_at_two():
    assert MAX_ADDS == 2
    assert add_step(base_capital=500, current_capital=1000,
                    base_sl_price_pct=5.0, leverage=2.0, adds_done=2) is None


def test_add_rejects_garbage():
    for kw in ({"base_capital": None}, {"leverage": 0}, {"current_capital": -1}):
        args = dict(base_capital=500, current_capital=500,
                    base_sl_price_pct=5.0, leverage=2.0, adds_done=0)
        args.update(kw)
        assert add_step(**args) is None


# ───────────────────────── ② 정점 즉시 진입 금지

def test_entry_requires_drop_from_peak():
    """🚨 실측: 정점 대비 0~1% 진입은 **11건 승률 0.0%**, 건당 -133.70.

    이 조건을 빼면 사다리 전체가 -44.33/건이 된다.
    """
    assert DROP_MIN_PCT == 8.0
    v = _ev(mark=99.5)                     # 0.5% 하락 = 사실상 정점
    assert not v.ok
    assert v.checks["정점대비 하락"] is False


def test_entry_ok_after_enough_drop():
    v = _ev()
    assert v.ok, (v.reason, v.checks, v.detail)
    assert v.detail["drop_pct"] >= DROP_MIN_PCT


def test_still_making_new_highs_is_not_a_correction():
    """방금 신고점을 찍었으면 「조정 시작」이 아니다."""
    v = _ev(peak_seen_at=FRESH)
    assert not v.ok and v.checks["갱신 정지"] is False


def test_rank_and_liquidity_are_required():
    assert not _ev(rank=11).ok
    assert not _ev(rank=None).ok
    assert not _ev(chg_24h=5.0).ok
    assert not _ev(quote_volume=1_000_000.0).ok


# ───────────────────────── ④ 다수결 금지 · fail-closed

def test_no_majority_vote():
    """🚨 Fix 250 — 「N중 M」이 정의 조건을 덮어쓴 사고를 겪었다."""
    v = _ev(mark=99.5)                     # 하락만 실패, 나머지 전부 통과
    assert sum(1 for r in v.checks.values() if r is True) >= 4
    assert not v.ok, "다수결로 통과했다"


def test_missing_signals_do_not_pass():
    """결측은 통과로 세지 않는다 — 자본이 나가는 판정이다."""
    assert not _ev(bb4h_broken=None).ok
    assert not _ev(obv_extreme_up=None).ok
    assert not _ev(peak_seen_at=None).ok
    assert not _ev(peak=None).ok


def test_obv_extreme_up_blocks():
    """사상 ④ — OBV 가 극단 상승이면 SHORT 자리가 아니다."""
    v = _ev(obv_extreme_up=True)
    assert not v.ok and v.checks["OBV"] is False


def test_bb4h_is_recent_experience_not_current_state():
    """🚨 「지금 상단 밖」을 요구하면 되돌아온 자리에서 진입할 수 없다 (Fix 249 함정).

    되돌림(mark 가 정점보다 한참 아래)과 동시에 성립해야 한다.
    """
    v = _ev(mark=85.0, bb4h_broken=True)   # 15% 되돌린 상태인데도
    assert v.ok, "되돌림과 4H 조건이 서로를 막는다"


# ───────────────────────── 신고점 추적

def test_peak_tracks_the_high_for_short():
    """SHORT 이므로 **고가**가 불리 방향 극값이다."""
    assert update_peak(100.0, 101.0) == (101.0, True)
    assert update_peak(100.0, 99.0) == (100.0, False)
    assert update_peak(None, 100.0) == (100.0, True)
    assert update_peak(100.0, None)[0] == 100.0
    assert update_peak(100.0, "없음")[0] == 100.0


# ───────────────────────── 배선 (소스 검사)

from pathlib import Path  # noqa: E402

BACKEND = Path(__file__).resolve().parents[2]
WORKER = BACKEND / "app" / "workers" / "surge_peak_ladder_worker.py"
SCHED = BACKEND / "app" / "workers" / "scheduler_runner.py"
CHART = BACKEND / "app" / "services" / "chart_analyzer.py"


def _code(p: Path) -> str:
    return "\n".join(
        ln for ln in p.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_worker_is_registered_and_not_commented_out():
    """🚨 Fix 256 — 꺼진 워커에 배선하면 0사이클이다."""
    code = _code(SCHED)
    assert 'id="surge_peak_ladder"' in code, "스케줄 등록이 없다"
    assert "run_surge_peak_ladder_once" in code


def test_default_mode_is_off():
    """랭킹 계열 워커 7종에 enable 게이트가 하나도 없다.

    명시하지 않으면 배포 즉시 자금이 나간다.
    """
    code = _code(WORKER)
    assert 'DEFAULT_MODE = "off"' in code
    assert 'SETTING_KEY = "surge_ladder_mode"' in code
    assert 'if mode == "off":' in code


def test_uses_the_real_bollinger_key():
    """🚨 실제로 잡은 버그 — 키는 `bb_up_last` 이고 `bb_up` 은 없다.

    `bb_up` 으로 쓰면 항상 None -> 조건이 영원히 미충족 -> 진입 수학적 불가
    (Fix 249 와 같은 함정).
    """
    code = _code(WORKER)
    assert 'a.get("bb_up_last")' in code
    assert 'a.get("bb_up")' not in code
    # 그 키가 실제로 존재하는지도 확인한다
    assert '"bb_up_last"' in CHART.read_text(encoding="utf-8")


def test_reuses_rank_map_instead_of_new_ranking():
    """「급등 1~10위」는 이미 있다 — 6가지로 갈라진 기준을 또 만들지 않는다."""
    code = _code(WORKER)
    assert "from app.services.market_movers import rank_map" in code
    assert "rank_map(tickers, TOP_N)" in code


def test_state_is_persisted_in_db_not_redis():
    """🚨 redis 에 volume/appendonly 가 없다 — 재기동 한 번이면 시도 카운터가 0 이 되어
    이미 크게 잃은 심볼에 다시 자본이 나간다 (사상 ⑦ 자동 재현 경로)."""
    code = _code(WORKER)
    assert "SurgeLadderState" in code
    assert "attempt_no" in code
    src = WORKER.read_text(encoding="utf-8")
    i = src.index("attempt_no")
    assert "setex" not in src[max(0, i - 400): i], "시도 카운터를 Redis 에 두고 있다"


ENTRY = BACKEND / "app" / "services" / "surge_ladder_entry.py"


def test_on_uses_dedicated_entry_not_the_shared_funnel():
    """🚨 공용 관문(_create_auto_bb_strategy)을 타면 구조적 차단 5건에 걸려 0건이 된다."""
    code = _code(WORKER)
    assert "create_surge_position" in code
    # 문서(주석·docstring)에는 이름이 나올 수 있으니 **호출 형태**로 검사한다
    assert "_create_auto_bb_strategy(db" not in code, "공용 관문을 호출하고 있다"


def test_dedicated_path_still_keeps_the_real_guards():
    """우회하는 것은 차단 5건뿐 — 안전장치는 전부 통과해야 한다."""
    code = _code(ENTRY)
    for token in ("AccountKillSwitchService", "is_account_banned",
                  "check_balance_block", "_has_active_same_symbol",
                  "get_surge_max_concurrent"):
        assert token in code, f"{token} 검사가 없다"


def test_guard_failures_are_fail_closed():
    """자본이 나가는 판정이므로 확인 실패는 「막는다」로 떨어져야 한다."""
    src = ENTRY.read_text(encoding="utf-8")
    i = src.index("킬스위치 확인 실패")
    assert "return False" in src[max(0, i - 200): i + 200]
    j = src.index("def count_surge_active")
    assert "MAX_CONCURRENT_DEFAULT" in src[j: j + 1200], "집계 실패가 fail-open 이다"


def test_template_name_match_is_case_insensitive():
    """🚨 Fix 265 재발 방지 — 템플릿 이름은 대문자로 저장된다."""
    code = _code(ENTRY)
    assert ".ilike(" in code and ".like(f\"{TEMPLATE_PREFIX}" not in code


def test_add_resets_the_stop_loss():
    """🚨 추가 후 손절 ROI 를 안 낮추면 손실 상한(250)이 깨진다."""
    code = _code(ENTRY)
    i = code.index("def add_to_surge_position")
    body = code[i:]
    assert "force_sl_roi_override" in body
    assert "손실 상한이 깨졌다" in ENTRY.read_text(encoding="utf-8")


def test_template_is_single_stage():
    """🚨 다단계면 risk_service v130 가드에 걸려 강제손절이 보류된다."""
    code = _code(ENTRY)
    assert '"stages_count": 1' in code


def test_counters_and_reasons_exist():
    """🚨 Fix 255/258/264 — 「안 도는 것」과 「조건 미달」이 구별돼야 한다."""
    code = _code(WORKER)
    for k in ('"eval"', '"hit"', '"shadow"', '"err"', '"miss"'):
        assert k in code
    assert "평가=%d 적중=%d" in WORKER.read_text(encoding="utf-8")


def test_screen_wiring_reuses_existing_key():
    """pump_top:scanned:{symbol} 모양으로 쓰면 /v219-monitoring 이 UI 작업 0으로 읽는다."""
    assert '"pump_top:scanned:{sym}"' in WORKER.read_text(encoding="utf-8")

"""📐 Fix 260 — 「최고점으로 가다가 주춤할때 2단계 / 다시 최고점 → 꺾이면 3단계」.

## 사장님 verbatim (2026-09-01)

    "2단계부터는 차트와 보조지표가 조정으로 바뀌면이 아니라 **최고점에서 들어가야** 하는데
     **최고점으로 가다가 주춤할때 2단계 진입**
     그리고 **다시 최고점으로 가면 다시 대기해서 꺾이면 3단계 진입**으로 해줘"

이 파일이 지키는 것 (전부 과거에 한 번씩 사고가 났던 항목):

  ① **LONG 의 극값은 신저점이다.** 가격 최고점으로 잡으면 가격 트리거와 방향이
     반대가 되어 두 조건이 동시에 참일 수 없다 = 영원히 진입 불가.
  ② **「가다가」(신고점 도달)를 빼면 규칙이 무너진다.** 실측 -20.94 vs +97.4.
  ③ **「주춤」과 「꺾임」의 강도가 다르다.** 같은 임계면 원문 오독.
  ④ **3단계는 재갱신을 요구한다.** 2단계 조건의 반복이 아니다.
  ⑤ **다수결 금지** — 「N중 M」이 정의 조건을 덮어쓴 사고(Fix 250)를 겪었다.
  ⑥ **Fix 218 과 대체 관계** — 둘 다 걸면 Fix 249 처럼 0건이 된다.
  ⑦ **MARKET 발주** — LIMIT 이면 미체결인데 단계만 소진된다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.peak_stall import (
    BAR_MINUTES,
    RENEW_EPS_RATIO,
    STALL_BARS,
    STALL_MIN_RATIO,
    TURN_MIN_RATIO,
    evaluate_peak_stall,
    gap_pct_between,
    update_extreme,
)

BACKEND = Path(__file__).resolve().parents[2]
WORKER = BACKEND / "app" / "workers" / "stage_trigger_worker.py"
EXEC = BACKEND / "app" / "services" / "execution_service.py"

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
STALLED = NOW - timedelta(minutes=STALL_BARS * BAR_MINUTES + 1)
FRESH = NOW - timedelta(minutes=1)
GAP = 2.0   # 사다리 간격 % (3/5/7 실측 1.94~2.11)


def _ev(**kw):
    base = dict(
        side="SHORT", stage_no=2, mark=100.0, trigger_price=100.0,
        ext=102.0, ext_seen_at=STALLED, renewed=False, gap_pct=GAP, now=NOW,
    )
    base.update(kw)
    return evaluate_peak_stall(**base)


# ───────────────────────── 2단계 = 「최고점으로 가다가 주춤할때」

def test_short_peak_then_stall_enters():
    """SHORT: 신고점 102(>=trigger 100) 찍고 100 으로 되돌아왔고 갱신이 멈췄다."""
    v = _ev()
    assert v.ok, (v.reason, v.checks, v.detail)
    # 되돌림 = (102-100)/102 = 1.96% >= 0.40*2.0 = 0.80%
    assert v.detail["pull_pct"] > GAP * STALL_MIN_RATIO


def test_long_extreme_is_the_LOW_not_the_high():
    """🚨 ①  LONG 의 「최고점」 = **신저점**이다.

    LONG 단계2 트리거는 진입가 **아래**(-2%)에 깔린다(실측 #1923 0GUSDT).
    극값을 가격 최고점으로 잡으면 가격 트리거와 방향이 반대라 진입이 불가능해진다.
    """
    # 신저점 98 이 트리거 100 을 (아래로) 통과했고, 100 으로 되돌아옴
    v = evaluate_peak_stall(
        side="LONG", stage_no=2, mark=100.0, trigger_price=100.0,
        ext=98.0, ext_seen_at=STALLED, renewed=False, gap_pct=GAP, now=NOW,
    )
    assert v.ok, (v.reason, v.checks)
    assert v.detail["pull_pct"] > 0, "LONG 되돌림이 음수 = 부호가 뒤집혔다"

    # 반대로 LONG 에서 「가격 최고점」을 극값으로 주면 통과하면 안 된다
    bad = evaluate_peak_stall(
        side="LONG", stage_no=2, mark=100.0, trigger_price=100.0,
        ext=102.0, ext_seen_at=STALLED, renewed=False, gap_pct=GAP, now=NOW,
    )
    assert not bad.ok, "LONG 이 가격 최고점으로도 통과했다 = 부호 정의가 깨졌다"


def test_signs_are_mirror_images():
    """SHORT/LONG 이 완전한 거울상이어야 한다 (부호 분기가 한 곳뿐이라는 증거).

    ⚠️ pull 은 **극값으로 나눈** 비율이라, 같은 절대 차이를 주면 분모가 달라
       1.96% vs 2.04% 로 갈린다. 그건 정상이다. 진짜 거울상을 보려면
       극값 대비 **같은 비율**만큼 되돌아온 지점을 줘야 한다.
    """
    pull = 2.0
    s = _ev(side="SHORT", ext=102.0, trigger_price=100.0, mark=102.0 * (1 - pull / 100))
    l = evaluate_peak_stall(
        side="LONG", stage_no=2, trigger_price=100.0,
        ext=98.0, mark=98.0 * (1 + pull / 100),
        ext_seen_at=STALLED, renewed=False, gap_pct=GAP, now=NOW,
    )
    assert s.ok == l.ok is True
    assert abs(s.detail["pull_pct"] - pull) < 1e-9
    assert abs(l.detail["pull_pct"] - pull) < 1e-9


# ───────────────────────── ② 「가다가」 = 신고점 도달

def test_extreme_must_reach_the_trigger():
    """🚨 ②  이 조건을 빼면 규칙이 무너진다 (실측 -20.94 vs +97.4).

    극값이 트리거에 못 미쳤으면 「최고점으로 **가다가**」가 아니다.
    """
    v = _ev(ext=100.5, trigger_price=101.0, mark=99.0)
    assert not v.ok
    assert v.checks["신고점 도달"] is False


def test_mark_below_trigger_is_fine_when_extreme_reached():
    """🚨 핵심 — mark 는 trigger 아래여도 된다.

    기존 `should_fire = mark >= trigger` 로는 되돌림이 **수학적으로 통과 불가**였다.
    극값 기준으로 재기 때문에 되돌아온 자리에서도 진입할 수 있다.
    """
    v = _ev(ext=103.0, trigger_price=102.0, mark=101.0)   # mark < trigger
    assert v.ok, (v.reason, v.checks)


# ───────────────────────── 「주춤」

def test_shallow_pullback_is_not_a_stall():
    """되돌림이 임계 미만이면 아직 주춤이 아니다."""
    v = _ev(ext=102.0, mark=101.95)      # 0.05% 되돌림
    assert not v.ok and v.checks["되돌림"] is False


def test_still_making_new_highs_is_not_a_stall():
    """방금 극값을 갱신했으면 「주춤」이 아니다 (아직 올라가는 중)."""
    v = _ev(ext_seen_at=FRESH)
    assert not v.ok and v.checks["갱신 정지"] is False


def test_missing_seen_at_does_not_pass():
    """결측을 통과로 세지 않는다."""
    v = _ev(ext_seen_at=None)
    assert not v.ok and v.checks["갱신 정지"] is None


# ───────────────────────── 3단계 = 「다시 최고점으로 가면 다시 대기해서 꺾이면」

def test_stage3_requires_renewal():
    """🚨 ④  3단계는 2단계의 반복이 아니다 — **다시** 최고점을 갱신해야 한다."""
    kw = dict(stage_no=3, ext=104.0, trigger_price=102.0, mark=100.0)
    assert _ev(renewed=True, **kw).ok
    v = _ev(renewed=False, **kw)
    assert not v.ok and v.checks["재갱신"] is False


def test_turn_is_deeper_than_stall():
    """🚨 ③  「꺾임」(3단계) > 「주춤」(2단계). 같은 임계면 원문 오독이다."""
    assert TURN_MIN_RATIO > STALL_MIN_RATIO
    # 2단계는 통과하지만 3단계는 통과 못 하는 되돌림 폭이 존재해야 한다
    pull_pct = (STALL_MIN_RATIO + TURN_MIN_RATIO) / 2 * GAP
    ext = 100.0
    mark = ext * (1 - pull_pct / 100)
    assert _ev(stage_no=2, ext=ext, trigger_price=99.0, mark=mark).ok
    v3 = _ev(stage_no=3, ext=ext, trigger_price=99.0, mark=mark, renewed=True)
    assert not v3.ok and v3.checks["되돌림"] is False


# ───────────────────────── ⑤ 다수결 금지

def test_no_majority_vote():
    """🚨 ⑤  Fix 250 — 「N중 M」이 정의 조건을 덮어쓴 사고를 겪었다.

    3개 중 2개만 맞아도 통과하면 안 된다.
    """
    v = _ev(ext=102.0, mark=101.99, ext_seen_at=STALLED)   # 도달O 정지O 되돌림X
    assert sum(1 for r in v.checks.values() if r is True) >= 2
    assert not v.ok, "다수결로 통과했다"


# ───────────────────────── 극값 갱신

def test_update_extreme_short_takes_max_long_takes_min():
    assert update_extreme("SHORT", 100.0, 101.0, GAP)[0] == 101.0
    assert update_extreme("SHORT", 100.0, 99.0, GAP)[0] == 100.0
    assert update_extreme("LONG", 100.0, 99.0, GAP)[0] == 99.0
    assert update_extreme("LONG", 100.0, 101.0, GAP)[0] == 100.0


def test_renewal_needs_a_meaningful_move():
    """틱 노이즈로 재갱신이 남발되면 「다시 최고점으로 가면」이 무의미해진다."""
    eps = GAP * RENEW_EPS_RATIO          # 0.30%
    _, tiny = update_extreme("SHORT", 100.0, 100.0 + 100 * eps / 100 * 0.5, GAP)
    _, real = update_extreme("SHORT", 100.0, 100.0 * (1 + eps / 100 * 2), GAP)
    assert tiny is False and real is True


def test_update_extreme_seeds_and_survives_garbage():
    assert update_extreme("SHORT", None, 100.0, GAP) == (100.0, False)
    assert update_extreme("SHORT", 100.0, None, GAP)[0] == 100.0
    assert update_extreme("SHORT", 100.0, "없음", GAP)[0] == 100.0


# ───────────────────────── gap

def test_gap_is_derived_from_the_plan_rows():
    """설정(3/5/7)이 아니라 **DB 의 trigger_price 두 개**에서 간격을 얻는다.

    재앵커(Fix 209)가 실체결가 기준으로 다시 깔아두므로 그 비가 곧 간격이고,
    설정과 DB 가 어긋나도 판정이 흔들리지 않는다.
    """
    assert abs(gap_pct_between(100.0, 102.0, "SHORT") - 2.0) < 1e-9
    assert abs(gap_pct_between(100.0, 98.0, "LONG") - 2.0) < 1e-9
    # 사다리가 뒤집힌 경우 = 판정 불가 (호출자가 기존 경로로 폴백)
    assert gap_pct_between(100.0, 98.0, "SHORT") is None
    assert gap_pct_between(None, 102.0, "SHORT") is None


def test_missing_inputs_never_pass():
    for kw in ({"gap_pct": None}, {"ext": None}, {"trigger_price": None}, {"mark": None}):
        assert not _ev(**kw).ok


# ───────────────────────── 배선 (소스 검사)

def _code() -> str:
    return "\n".join(
        ln for ln in WORKER.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_wired_before_the_should_fire_gate():
    """🚨 판정이 `if not should_fire: continue` **앞**에 있어야 한다.

    뒤에 있으면 되돌아온 mark 가 그 줄에서 먼저 죽어 판정에 도달조차 못 한다.
    """
    code = _code()
    i_gate = code.index("evaluate_peak_stall")
    i_cont = code.index("if not should_fire:")
    assert i_gate < i_cont


def test_fix218_is_skipped_when_enabled():
    """🚨 ⑥  Fix 218 과는 **대체 관계**다. 둘 다 걸면 Fix 249 처럼 0건이 된다."""
    code = _code()
    assert "if _is_split and next_stage_no >= 2 and not _ps_on:" in code


def test_not_wired_into_the_dead_fix55_block():
    """🚨 Fix 55/114 블록은 현재 운영 조합 전부에서 **실행되지 않는 죽은 코드**다.

    조건이 `not _is_split and not _is_price_mode and not _is_obv_mode` 인데
    split 템플릿은 trigger_mode 기본값이 PRICE_DOWN_PCT 라 _is_price_mode=True.
    거기 넣으면 0사이클이다 (Fix 256 과 같은 사고).
    """
    src = WORKER.read_text(encoding="utf-8")
    dead = src.index("and not _is_price_mode")
    assert src.index("evaluate_peak_stall") < dead


def test_forces_market_order():
    """🚨 ⑦  LIMIT 이면 미체결인데 current_stage 는 오르고 reconcile 이
    is_triggered 를 거짓 회복시켜 **자본 없이 단계만 소진**된다."""
    assert "force_market=_ps_force_market" in _code()
    e = EXEC.read_text(encoding="utf-8")
    assert "force_market: bool = False" in e
    assert "if stage_plan.trigger_price is None or force_market:" in e


def test_flag_is_assigned_before_every_use():
    """🚨 NameError 방지 — 과거에 두 진입 경로 중 하나만 고쳐 터뜨린 적이 있다."""
    lines = WORKER.read_text(encoding="utf-8").splitlines()
    first_assign = min(i for i, l in enumerate(lines, 1) if "_ps_on = False" in l)
    uses = [i for i, l in enumerate(lines, 1) if "_ps_on" in l]
    assert min(uses) >= first_assign
    fm = [i for i, l in enumerate(lines, 1) if "_ps_force_market" in l]
    fm_assign = min(i for i, l in enumerate(lines, 1) if "_ps_force_market = False" in l)
    assert min(fm) >= fm_assign


def test_default_off_and_single_switch():
    """헌법 161 — 스위치 하나로 통째 롤백."""
    code = _code()
    assert 'get_bool("split_peak_stall_enabled", False)' in code


def test_fails_open_to_the_existing_path():
    """🚨 Fix 252 — 판정 하나가 진입을 통째로 멈추면 안 된다."""
    src = WORKER.read_text(encoding="utf-8")
    i = src.index("Fix260/peak-stall] #%s 판정 실패")
    assert "기존 경로 유지" in src[i: i + 200]


def test_counters_exist():
    """🚨 Fix 255/258 — 「안 도는 것」과 「조건 미달」이 구별돼야 한다."""
    code = _code()
    for k in ("ps_eval", "ps_reach", "ps_hit", "ps_err", "ps_miss"):
        assert f'"{k}"' in code
    assert "Fix260 평가=" in WORKER.read_text(encoding="utf-8")


def test_price_not_reached_now_leaves_a_reason():
    """`if not should_fire` 는 원래 로그도 Redis 기록도 없었다 (헌법 93)."""
    src = WORKER.read_text(encoding="utf-8")
    i = src.index("if not should_fire:")
    assert "가격 미도달" in src[i: i + 700]

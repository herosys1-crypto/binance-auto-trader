"""🚨 Fix 262/263 — 재진입이 9일째 0건이던 원인과 전용 동시 슬롯.

## 실측 (2026-09-01, VPS)

    _auto_bb_reset_at()          = 2026-08-23 07:34   ← **8.7일 전**
    _count_reentry_used_today()  = 20  / 한도 20      → remaining 0
    RT_REENTRY suggestion 전 기간 = 20건               ← 그게 전부 「오늘 것」
    실제 재진입 전략 (5일)        = **0건**

「일일 한도」인데 기준 시각이 저장된 리셋 값에 **영원히** 고정돼,
8/23 이후 누적 20건을 매일 「오늘 20건」으로 세고 있었다.
그래서 재진입은 8/23 이후 **한 번도 일어나지 않았다.**

같은 함수를 신규 진입 카운터도 쓴다: `_count_used_slots() = 591` (하루 상한 20).

## 고친 뒤 (같은 시점 재측정)

    _count_used_slots         591 → 21   (21 > 20 이라 신규 진입은 여전히 차단 = 무변화)
    _count_reentry_used_today  20 → 0    (재진입만 풀린다)

## 사장님 지시 (2026-09-01)

    "재진입은 일 10개로 해줘 **일 최대 동시 포지션에서 10개는 가능하게** 해줘"
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
API = BACKEND / "app" / "api" / "v1" / "strategy_suggestions.py"
WORKER = BACKEND / "app" / "workers" / "realtime_reentry_worker.py"


class _Row:
    def __init__(self, value):
        self.value = value


class _DB:
    """SystemSetting 만 흉내내는 최소 스텁."""

    def __init__(self, value=None):
        self._v = value

    def get(self, model, key):
        return _Row(self._v) if self._v is not None else None


def _kst_midnight(now=None):
    now = now or datetime.now(timezone.utc)
    kst = now + timedelta(hours=9)
    mid = kst.replace(hour=0, minute=0, second=0, microsecond=0)
    return (mid - timedelta(hours=9)).replace(tzinfo=timezone.utc)


def _reset_at(value):
    from app.api.v1.strategy_suggestions import _auto_bb_reset_at
    return _auto_bb_reset_at(_DB(value))


# ───────────────────────── Fix 262: 「일일」이 진짜 일일이어야 한다

def test_stale_reset_no_longer_wins():
    """🚨 이게 실제 사고다 — 8일 전 리셋 값이 「오늘」 행세를 했다."""
    stale = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    assert _reset_at(stale) == _kst_midnight(), "옛 리셋 값이 아직도 이긴다"


def test_todays_reset_is_respected():
    """사장님이 오늘 리셋을 누르셨으면 그 시각부터 센다 (원 의도 보존)."""
    later = _kst_midnight() + timedelta(hours=3)
    assert _reset_at(later.isoformat()) == later


def test_no_row_falls_back_to_kst_midnight():
    assert _reset_at(None) == _kst_midnight()


def test_broken_value_falls_back_not_crashes():
    assert _reset_at("이건 날짜가 아니다") == _kst_midnight()


def test_naive_datetime_is_treated_as_utc():
    """tzinfo 없는 값과 비교하면 TypeError 로 죽는다 — 그걸 막는다."""
    naive = (datetime.now(timezone.utc) - timedelta(days=3)).replace(tzinfo=None)
    assert _reset_at(naive.isoformat()) == _kst_midnight()


def test_result_is_always_timezone_aware():
    for v in (None, "깨진값", (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()):
        assert _reset_at(v).tzinfo is not None


# ───────────────────────── Fix 263: 재진입 전용 동시 슬롯

def test_default_slots_is_ten():
    """사장님 「동시 포지션에서 10개는 가능하게」."""
    from app.workers.realtime_reentry_worker import (
        REENTRY_CONCURRENT_SLOTS_DEFAULT, _get_reentry_concurrent_slots,
    )
    assert REENTRY_CONCURRENT_SLOTS_DEFAULT == 10
    assert _get_reentry_concurrent_slots(_DB(None)) == 10
    assert _get_reentry_concurrent_slots(_DB("4")) == 4
    assert _get_reentry_concurrent_slots(_DB("0")) == 0        # 0 = 명시 OFF 존중


def test_counting_failure_is_fail_closed():
    """🚨 자본이 나가는 판정이라, 셀 수 없으면 「꽉 참」으로 본다."""
    from app.workers.realtime_reentry_worker import (
        REENTRY_CONCURRENT_SLOTS_DEFAULT, _count_active_reentry,
    )

    class _Boom:
        def execute(self, *a, **k):
            raise RuntimeError("DB 끊김")

    assert _count_active_reentry(_Boom()) == REENTRY_CONCURRENT_SLOTS_DEFAULT


# ───────────────────────── 배선

def _code() -> str:
    return "\n".join(
        ln for ln in WORKER.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_global_cap_no_longer_hard_blocks_reentry():
    """옛 코드는 전체 상한이 차면 재진입을 **통째로** 막았다 (return _finish).

    사장님 지시가 「동시 포지션에서 10개는 가능하게」이므로,
    전용 슬롯이 남아 있으면 전체 상한과 무관하게 진행해야 한다.
    """
    code = _code()
    assert 'return _finish(f"동시보유 상한 (Fix112): {_slot_why}")' not in code, (
        "전체 상한이 아직도 재진입을 통째로 막는다"
    )
    assert "재진입 전용 동시 슬롯 소진" in code


def test_loop_budget_uses_reentry_room_not_global_room():
    """루프 예산이 전역 여유가 아니라 **전용 슬롯 여유**로 묶여야 한다."""
    code = _code()
    assert "_slot_room = _re_room" in code
    assert "_slot_room = _cap - _act" not in code


def test_slot_check_runs_before_any_entry():
    """슬롯 판정이 실제 진입(_create_auto_bb_strategy)보다 **앞**에 있어야 한다.

    ⚠️ 처음엔 첫 `for` 와 비교했는데, 파일 위쪽 헬퍼의 for 를 잡아 잘못 실패했다.
       앵커는 「자본이 나가는 지점」이어야 한다.
    """
    code = _code()
    assert code.index("_count_active_reentry(db)") < code.index("_create_auto_bb_strategy(")


def test_evidence_is_recorded_next_to_the_change():
    """값만 바뀌고 근거가 사라지면 다음 사람이 또 뒤집는다."""
    src = WORKER.read_text(encoding="utf-8")
    for token in ("Fix 263", "동시 포지션에서 10개는 가능하게"):
        assert token in src
    api = API.read_text(encoding="utf-8")
    for token in ("Fix 262", "8.7일 전", "영구 소진", "max(stored, kst_midnight)"):
        assert token in api, f"근거 주석에 '{token}' 이 없다"

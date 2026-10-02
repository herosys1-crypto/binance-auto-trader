"""Fix 410 — 「자동 진입 누락」 CRITICAL 오탐 수정 (Duel auto-entry-missed, 리드 병합).

지속 2분 · 단계 워커 차단 사유면 INFO · Redis 로 확인 불가면 WARN(별도 유형) · 교차 감사 지적(옛 표식·소수 초·미래 시각·빈 사유·깨진 값) 고정.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest

from app.workers import setting_preservation_agent as A

T0 = datetime(2026, 10, 3, 0, 0, 0, tzinfo=timezone.utc)


class FakeRedis:
    def __init__(self):
        self.d: dict[str, str] = {}
        self.fail_get = self.fail_set = self.fail_del = False

    def get(self, k):
        if self.fail_get:
            raise ConnectionError("get down")
        return self.d.get(k)

    def setex(self, k, ttl, v):
        if self.fail_set:
            raise ConnectionError("set down")
        self.d[k] = v

    def delete(self, k):
        if self.fail_del:
            raise ConnectionError("del down")
        self.d.pop(k, None)


class FakeDB:
    def __init__(self, plans):
        self.plans = plans

    def execute(self, _stmt):
        return NS(scalars=lambda: NS(all=lambda: self.plans))


def strat(side="LONG", status="STAGE2_OPEN", sid=4562):
    return NS(id=sid, symbol="AAAUSDT", side=side, status=status, strategy_type="DYNAMIC_LONG",
              entry_origin="manual_modal", template_name="m", created_at=T0 - timedelta(days=1), updated_at=T0)


def run(r, mark, now, *, side="LONG", trigger=100, stage=3, status="STAGE2_OPEN"):
    db = FakeDB([NS(stage_no=stage, trigger_price=trigger)])
    return A._check_auto_entry_silent_bug(db, strat(side, status), mark, redis=r, now=now)


def block(r, *, stage=3, at=None, reason="4H OBV 하락 지속", sid=4562):
    r.d[A._BLOCK_KEY.format(sid=sid)] = json.dumps({"reason": reason, "stage_no": stage,
                                                   "blocked_at": (at or T0).isoformat(), "detail": {}})


def types(bugs):
    return [(b["type"], b["severity"]) for b in bugs]


def test_grace_two_minutes_then_critical():
    r = FakeRedis()
    assert run(r, 99, T0) == []                                     # 처음 닿음 → 표식만
    assert A._REACHED_KEY.format(sid=4562, stage=3) in r.d
    assert run(r, 99, T0 + timedelta(minutes=1)) == []
    out = run(r, 99, T0 + timedelta(minutes=2))
    assert types(out) == [("AUTO_ENTRY_MISSED", "CRITICAL")] and "2분째" in out[0]["msg"]


def test_fractional_seconds_not_rounded_up():
    """GPT 감사: 정수 초로 버리면 119.2초가 120초로 → 2분 전 CRITICAL."""
    r = FakeRedis()
    run(r, 99, T0 + timedelta(milliseconds=900))
    assert run(r, 99, T0 + timedelta(minutes=2, milliseconds=100)) == []


def test_leaving_trigger_resets_count():
    r = FakeRedis()
    run(r, 99, T0)
    assert run(r, 101, T0 + timedelta(minutes=3)) == []            # 떨어짐 → 표식 삭제
    assert A._REACHED_KEY.format(sid=4562, stage=3) not in r.d
    assert run(r, 99, T0 + timedelta(minutes=6)) == []              # 다시 닿음 → 처음부터
    assert run(r, 99, T0 + timedelta(minutes=7)) == []
    assert types(run(r, 99, T0 + timedelta(minutes=8))) == [("AUTO_ENTRY_MISSED", "CRITICAL")]


def test_stale_marker_after_failed_delete_is_not_persistence():
    """GPT 감사 치명: 떨어졌을 때 삭제가 실패하면 옛 표식이 남아, 나중에 다시 닿는 순간 즉시 CRITICAL 이었다."""
    r = FakeRedis()
    run(r, 99, T0)
    r.fail_del = True
    run(r, 101, T0 + timedelta(minutes=3))                          # 삭제 실패
    r.fail_del = False
    assert run(r, 99, T0 + timedelta(minutes=30)) == []             # 관측이 7분 넘게 끊겼다 → 다시 센다


def test_block_reason_same_stage_is_info():
    r = FakeRedis()
    run(r, 99, T0)
    block(r, at=T0 + timedelta(minutes=1))
    out = run(r, 99, T0 + timedelta(minutes=3))
    assert types(out) == [("AUTO_ENTRY_BLOCKED", "INFO")] and "4H OBV 하락 지속" in out[0]["msg"]


@pytest.mark.parametrize("at_offset_s, stage, expect", [
    (-11 * 60, 3, "AUTO_ENTRY_MISSED"),     # 11분 전 = 낡음
    (-3 * 60, 5, "AUTO_ENTRY_MISSED"),      # 다른 단계
    (-3 * 60, 0, "AUTO_ENTRY_BLOCKED"),     # 단계 0 = 전략 전체 차단
    (+30, 3, "AUTO_ENTRY_BLOCKED"),         # Claude 감사 치명: 방금 덮어쓴 약간 미래 시각도 유효
    (+10 * 60, 3, "AUTO_ENTRY_MISSED"),     # 터무니없는 미래는 버림
])
def test_block_validity(at_offset_s, stage, expect):
    r = FakeRedis()
    run(r, 99, T0)
    now = T0 + timedelta(minutes=3)
    block(r, stage=stage, at=now + timedelta(seconds=at_offset_s))
    assert run(r, 99, now)[0]["type"] == expect


def test_empty_reason_still_counts_as_block():
    r = FakeRedis()
    run(r, 99, T0)
    block(r, reason="", at=T0 + timedelta(minutes=2))
    out = run(r, 99, T0 + timedelta(minutes=3))
    assert types(out) == [("AUTO_ENTRY_BLOCKED", "INFO")] and "(사유 미기재)" in out[0]["msg"]


@pytest.mark.parametrize("raw", ["{broken", json.dumps([1]), json.dumps({"stage_no": "9" * 4301, "blocked_at": T0.isoformat()}),
                                 json.dumps({"stage_no": 3, "blocked_at": "2026-10-03T00:02:00"}),          # 시간대 없음
                                 json.dumps({"stage_no": 3, "blocked_at": "0001-01-01T00:00:00+01:00"}),    # 범위 끝
                                 json.dumps({"stage_no": True, "blocked_at": T0.isoformat()}), b"\xff\xfe"])
def test_broken_block_values_mean_no_reason_and_never_raise(raw):
    r = FakeRedis()
    run(r, 99, T0)
    r.d[A._BLOCK_KEY.format(sid=4562)] = raw
    assert run(r, 99, T0 + timedelta(minutes=3))[0]["type"] == "AUTO_ENTRY_MISSED"


def test_redis_missing_or_failing_is_warn_with_separate_type():
    """Claude 감사: WARN 이 CRITICAL 과 같은 유형이면 dedup(30분)이 진짜 CRITICAL 을 막는다."""
    assert types(run(None, 99, T0)) == [("AUTO_ENTRY_UNVERIFIED", "WARN")]
    r = FakeRedis()
    r.fail_get = True
    assert types(run(r, 99, T0)) == [("AUTO_ENTRY_UNVERIFIED", "WARN")]
    r2 = FakeRedis()
    run(r2, 99, T0)

    class HalfBroken(FakeRedis):           # 표식은 되는데 차단 사유 읽기만 실패
        def get(self, k):
            if k.startswith("stage_trigger_block"):
                raise ConnectionError("down")
            return super().get(k)
    h = HalfBroken()
    h.d = dict(r2.d)
    assert types(run(h, 99, T0 + timedelta(minutes=3))) == [("AUTO_ENTRY_UNVERIFIED", "WARN")]


def test_short_side_and_status_filter_unchanged():
    r = FakeRedis()
    assert run(r, 101, T0, side="SHORT") == [] and run(r, 101, T0 + timedelta(minutes=2), side="SHORT")[0]["severity"] == "CRITICAL"
    assert run(FakeRedis(), 99, T0, status="COMPLETED") == []
    assert run(FakeRedis(), 101, T0) == []                          # LONG 미도달


def test_naive_now_treated_as_utc():
    r = FakeRedis()
    run(r, 99, T0.replace(tzinfo=None))
    assert types(run(r, 99, (T0 + timedelta(minutes=2)).replace(tzinfo=None))) == [("AUTO_ENTRY_MISSED", "CRITICAL")]


def test_caller_passes_redis():
    import pathlib
    src = pathlib.Path(A.__file__).read_text(encoding="utf-8")
    assert "_check_auto_entry_silent_bug(db, s, mark, redis=redis)" in src
    assert A._BLOCK_KEY == "stage_trigger_block:strategy:{sid}"
    from app.workers import stage_trigger_worker as STW
    assert STW._BLOCK_REASON_KEY == A._BLOCK_KEY                     # 두 워커가 같은 키를 본다


def test_record_failure_rolls_back_session():
    """Gemini 심판: 위험 이벤트 저장 실패 뒤 rollback 이 없어 세션이 오염 → 같은 사이클 나머지 전략 검사 마비."""
    import pathlib
    from app.workers import silent_bug_detector as SB
    for mod, tag in ((A, "setting-preserve"), (SB, "silent-bug")):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        i = src.index(f'logger.error("[{tag}] 기록/알림 실패')
        assert "db.rollback()" in src[i:i + 300], mod.__name__

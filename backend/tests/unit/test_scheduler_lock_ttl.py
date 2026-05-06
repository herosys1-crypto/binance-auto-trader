"""Scheduler 의 guarded_job lock TTL 이 Interval 보다 짧은지 검증.

배경 (2026-05-06 #103 trailing 자동 발동 지연 추정):
  scheduler_runner.py 에서 `add_job(guarded_job(name, ttl_seconds, fn), trigger=
  IntervalTrigger(seconds=N))` 패턴. acquire_job_lock 가 ttl_seconds 동안 lock 유지.
  ttl_seconds >= N 이면 다음 호출이 lock 만료 X 라 skip → 사이클 ½ 빈도.

  이 테스트는 scheduler_runner.py 를 정적 분석해 모든 add_job 호출의 lock TTL <
  IntervalTrigger seconds 임을 보장. 미래에 누군가 ttl 늘리면 즉시 발견.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


def _scheduler_runner_path() -> Path:
    return Path(__file__).resolve().parents[2] / "app" / "workers" / "scheduler_runner.py"


def _extract_add_job_lines() -> list[str]:
    """scheduler_runner.py 에서 scheduler.add_job(...) 호출 라인만 추출."""
    src = _scheduler_runner_path().read_text(encoding="utf-8")
    return [ln for ln in src.splitlines() if "scheduler.add_job" in ln]


# 정규식 — guarded_job("name", TTL, fn) + IntervalTrigger(seconds=N) 추출
_TTL_PATTERN = re.compile(r'guarded_job\("([^"]+)",\s*(\d+),')
_INTERVAL_SEC_PATTERN = re.compile(r"IntervalTrigger\(seconds=(\d+)\)")
_INTERVAL_MIN_PATTERN = re.compile(r"IntervalTrigger\(minutes=(\d+)\)")


def test_each_interval_job_has_ttl_less_than_interval():
    """Interval(seconds=N) 으로 등록된 job 의 lock TTL 은 N 보다 짧아야 함.

    아니면 사이클 ½ 빈도가 됨 (lock 이 다음 사이클까지 살아있어 skip).
    """
    failures = []
    for line in _extract_add_job_lines():
        ttl_match = _TTL_PATTERN.search(line)
        sec_match = _INTERVAL_SEC_PATTERN.search(line)
        if not (ttl_match and sec_match):
            continue
        name = ttl_match.group(1)
        ttl = int(ttl_match.group(2))
        interval = int(sec_match.group(1))
        if ttl >= interval:
            failures.append(
                f"  job '{name}': lock TTL {ttl}s >= Interval {interval}s "
                f"→ 사이클 ½ 빈도 (lock 이 다음 호출까지 살아있어 skip)"
            )
    assert not failures, (
        "다음 job 들의 lock TTL 이 Interval >= 라 사이클 빈도 ½:\n" + "\n".join(failures) +
        "\nFix: guarded_job(...) 의 ttl_seconds 를 Interval seconds 미만으로 줄이세요."
    )


def test_each_minute_interval_job_has_reasonable_ttl():
    """Interval(minutes=N) job 의 lock TTL 은 N분 보다 짧아야 함 (초 단위 비교)."""
    failures = []
    for line in _extract_add_job_lines():
        ttl_match = _TTL_PATTERN.search(line)
        min_match = _INTERVAL_MIN_PATTERN.search(line)
        if not (ttl_match and min_match):
            continue
        name = ttl_match.group(1)
        ttl = int(ttl_match.group(2))
        interval_sec = int(min_match.group(1)) * 60
        if ttl >= interval_sec:
            failures.append(
                f"  job '{name}': lock TTL {ttl}s >= Interval {interval_sec}s ({min_match.group(1)}min)"
            )
    assert not failures, "분 단위 Interval job 의 TTL 검증 실패:\n" + "\n".join(failures)


def test_tp_sl_specifically_has_short_lock():
    """tp_sl job 은 critical (10s 사이클로 trailing 평가) — TTL <= 8s 권장."""
    found_tp_sl = False
    for line in _extract_add_job_lines():
        ttl_match = _TTL_PATTERN.search(line)
        if not ttl_match or ttl_match.group(1) != "tp_sl":
            continue
        found_tp_sl = True
        ttl = int(ttl_match.group(2))
        sec_match = _INTERVAL_SEC_PATTERN.search(line)
        assert sec_match, "tp_sl 은 IntervalTrigger(seconds=...) 사용해야 함"
        interval = int(sec_match.group(1))
        assert ttl < interval, (
            f"tp_sl job: TTL {ttl}s >= Interval {interval}s — trailing 자동 발동 지연 위험"
        )
        # 권장: TTL 이 Interval 의 80% 이하 (5-06 fix 후 8s/10s = 80%)
        assert ttl <= int(interval * 0.8) + 1, (
            f"tp_sl TTL {ttl}s 가 Interval {interval}s 의 80% ({int(interval*0.8)}s) 넘음 — race 위험"
        )
    assert found_tp_sl, "tp_sl job 등록 검출 실패 — scheduler_runner.py 변경?"

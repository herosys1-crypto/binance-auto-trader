"""Fix 460 — 「KST hh:mm」 이라 적은 하루 1번 잡이 컨테이너 UTC 로 9시간 늦게 돌던 것 (Fix 459 배포 뒤 「다음 실행」 표시로 발견)."""
from __future__ import annotations

import pathlib
import re
from datetime import datetime, timedelta, timezone

from apscheduler.triggers.cron import CronTrigger

SRC = (pathlib.Path(__file__).resolve().parents[1] / "app" / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
KST = timezone(timedelta(hours=9))


def test_three_jobs_pinned_to_kst():
    for job, hm in (("paper_retention", (12, 40)), ("strategy_council", (9, 40)), ("verdict_report", (10, 20))):
        i = SRC.index(f'guarded_job("{job}"')
        m = re.search(r"CronTrigger\(hour=(\d+), minute=(\d+), timezone=\"Asia/Seoul\"\)", SRC[i:i + 300])
        assert m and (int(m.group(1)), int(m.group(2))) == hm, job


def test_trigger_fires_at_kst_wall_clock():
    t = CronTrigger(hour=10, minute=20, timezone="Asia/Seoul")
    now = datetime(2026, 10, 14, 22, 50, tzinfo=timezone.utc)          # KST 10/15 07:50
    nxt = t.get_next_fire_time(None, now)
    assert nxt.astimezone(KST).strftime("%m-%d %H:%M") == "10-15 10:20"
    assert nxt.astimezone(timezone.utc).strftime("%H:%M") == "01:20"


def test_kst_comment_needs_timezone_or_utc_note():
    """주석에 「KST hh:mm」 을 적은 CronTrigger 는 timezone="Asia/Seoul" 이거나 같은 곳에 UTC 환산이 있어야 한다(컨테이너 = UTC)."""
    lines = SRC.splitlines()
    bad = []
    for i, line in enumerate(lines):
        if "CronTrigger(" in line and "timezone=" not in line:
            win = "\n".join(lines[max(0, i - 12): i + 1])
            if re.search(r"KST\s*\d{1,2}:\d{2}", win) and "UTC" not in win:
                bad.append(i + 1)
    assert not bad, f"KST 로 적었는데 시간대·UTC 환산 없음: 줄 {bad}"

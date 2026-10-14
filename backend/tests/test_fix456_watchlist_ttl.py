"""🩺 Fix 456 — 감시 목록 TTL > 갱신 주기 (10/14 점검: TTL 15분 = 주기 15분이라 하루 31번 「없음」)."""
import pathlib
import re

from app.workers import realtime_watchlist_worker as RW


def test_ttl_longer_than_schedule_interval():
    src = (pathlib.Path(RW.__file__).resolve().parents[1] / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    i = src.index('id="realtime_watchlist"') if 'id="realtime_watchlist"' in src else src.index("realtime_watchlist")
    m = re.search(r"IntervalTrigger\(minutes=(\d+)\)", src[i - 600:i + 600])
    assert m, "감시 목록 스케줄을 찾지 못함"
    assert RW.WATCHLIST_TTL_SEC >= int(m.group(1)) * 60 + 300

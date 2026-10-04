"""Fix 420 — 배포 재시작 때 스케줄러 ~15초 공백 제거.

운영 docker events(10/04 04:28): 옛 프로세스 SIGTERM 무시(PID 1) → 10초 뒤 SIGKILL(137) → 리더 잠금 잔존
→ 새 프로세스 「another node is leader; exiting」 5회 → 잠금 만료 뒤 리더. 그 사이 compose exec 검사기도 죽음.
"""
from __future__ import annotations

import signal

import pytest

from app.workers import scheduler_runner as R
from app.workers.distributed_scheduler_guard import DistributedSchedulerGuard


class FakeRedis:
    def __init__(self):
        self.now = 0.0
        self.data = {}

    def sleep(self, sec):
        self.now += sec

    def get(self, k):
        v, exp = self.data.get(k, (None, None))
        if exp is not None and exp <= self.now:
            self.data.pop(k, None)
            return None
        return v

    def set(self, k, v, nx=False, ex=None):
        if nx and self.get(k) is not None:
            return False
        self.data[k] = (v.encode() if isinstance(v, str) else v, self.now + ex if ex else None)
        return True

    def expire(self, k, sec):
        v = self.get(k)
        if v is None:
            return False
        self.data[k] = (v, self.now + sec)
        return True

    def delete(self, *ks):
        n = 0
        for k in ks:
            n += self.data.pop(k, None) is not None
        return n

    def eval(self, script, numkeys, key, owner):
        assert numkeys == 1 and "get" in script and "del" in script
        cur = self.get(key)
        if cur is not None and cur.decode() == owner:
            return self.delete(key)
        return 0


def guard_on(r):
    return DistributedSchedulerGuard(r)


# ── release_leader ──────────────────────────────────────────────────────
def test_release_only_my_lock():
    r = FakeRedis()
    me, other = guard_on(r), guard_on(r)
    other.node_id = "other-node"
    assert me.try_become_leader()
    assert other.release_leader() is False and r.get("sched:leader") is not None   # 남의 잠금은 그대로
    assert me.release_leader() is True and r.get("sched:leader") is None
    assert other.try_become_leader()                                                # 새 프로세스가 즉시 리더


def test_release_never_touches_job_locks():
    r = FakeRedis()
    g = guard_on(r)
    g.try_become_leader()
    g.acquire_job_lock("tp_sl", 60)
    g.release_leader()
    assert r.get("sched:job:tp_sl") is not None       # 진행 중 실주문 잡의 이중 실행 방지 장치 유지


def test_release_error_returns_false():
    class Bad(FakeRedis):
        def eval(self, *a, **k):
            raise ConnectionError("down")
    assert guard_on(Bad()).release_leader() is False


# ── wait_for_leader ─────────────────────────────────────────────────────
def test_wait_until_stale_lock_expires():
    r = FakeRedis()
    old = guard_on(r)
    old.node_id = "killed-node"
    old.try_become_leader()                           # SIGKILL 로 남은 잠금 (TTL 30)
    r.now = 15                                        # 15초 경과 (운영 실측과 같은 지점)
    assert R.wait_for_leader(guard_on(r), monotonic=lambda: r.now, sleep=r.sleep) is True
    assert r.now <= 32                                # 잠금 만료 직후 리더 (예전엔 종료·재시작 반복)


def test_wait_gives_up_when_real_leader_alive():
    r = FakeRedis()
    live = guard_on(r)
    live.node_id = "live-node"
    live.try_become_leader()

    def sleep_and_refresh(sec):
        r.sleep(sec)
        live.refresh_leader()                         # 살아 있는 리더는 계속 연장
    assert R.wait_for_leader(guard_on(r), monotonic=lambda: r.now, sleep=sleep_and_refresh) is False
    assert r.now >= R.LEADER_WAIT_SECONDS


def test_wait_survives_redis_error():
    r = FakeRedis()
    g = guard_on(r)
    calls = {"n": 0}
    orig = g.try_become_leader

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("blip")
        return orig()
    g.try_become_leader = flaky
    assert R.wait_for_leader(g, monotonic=lambda: r.now, sleep=r.sleep) is True


# ── 신호 처리기 ─────────────────────────────────────────────────────────
class FakeScheduler:
    def __init__(self, calls):
        self.calls = calls

    def shutdown(self, wait=True):
        self.calls.append(("shutdown", wait))

    def add_listener(self, fn, mask):
        self.calls.append(("listener", mask))


def _handler(raise_errors=False):
    calls = []
    r = FakeRedis()
    g = guard_on(r)
    g.try_become_leader()
    if raise_errors:
        g.release_leader = lambda: (_ for _ in ()).throw(RuntimeError("x"))

    def set_health(flag, client):
        calls.append(("health", flag, client is r))
        if raise_errors:
            raise RuntimeError("health down")
    spawned = []
    h, stopping, cleanup = R.make_shutdown_handler(g, r, FakeScheduler(calls), set_health, spawn=spawned.append)
    return h, stopping, cleanup, spawned, calls, r


def test_signal_hands_cleanup_to_thread_and_cleans_in_order():
    h, stopping, cleanup, spawned, calls, r = _handler()
    h(signal.SIGTERM, None)
    assert stopping.is_set() and len(spawned) == 1    # 처리기 자체는 잠금 작업을 하지 않는다 (교착 방지)
    assert r.get("sched:leader") is not None          # 아직 정리 전
    spawned[0]()
    assert r.get("sched:leader") is None              # ① 리더 잠금 해제
    seq = [c for c in calls if c[0] != "listener"]
    assert seq == [("health", False, True), ("shutdown", False)]   # ② health 삭제 ③ wait=False 로 블로킹 해제
    assert cleanup.done.is_set()                      # 메인은 이걸 기다린 뒤 끝난다


def test_main_waits_for_cleanup_before_exit():
    import inspect
    src = inspect.getsource(R.start_scheduler)
    assert src.index("_cleanup.done.wait(") > src.index("scheduler.start()")


def test_signal_twice_is_safe():
    h, stopping, cleanup, spawned, calls, r = _handler()
    h(signal.SIGTERM, None)
    h(signal.SIGINT, None)
    assert len(spawned) == 1


def test_cleanup_swallows_errors_and_still_shuts_down():
    h, stopping, cleanup, spawned, calls, r = _handler(raise_errors=True)
    h()
    spawned[0]()                                      # 예외가 밖으로 나오지 않는다
    assert ("shutdown", False) in calls


def test_heartbeat_stops_after_signal():
    import threading
    r = FakeRedis()
    writes = []
    r.setex = lambda k, ttl, v: writes.append(k)
    stop = threading.Event()
    stop.set()
    R._scheduler_heartbeat_loop(r, stop)              # 종료 뒤엔 health 키를 되살리지 않고 바로 끝난다
    assert writes == []


def test_runner_wiring():
    import inspect
    src = inspect.getsource(R.start_scheduler)
    assert "wait_for_leader(guard)" in src
    assert "signal.signal(signal.SIGTERM, _on_signal)" in src
    assert "args=(redis_client, _stopping)" in src
    assert "release_job" not in src and "sched:job" not in src   # 잡 잠금은 건드리지 않는다

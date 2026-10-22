"""Fix 483 — 리더 잠금이 사라져도 스케줄러가 다시 잡는다 (사장님 10/23 「1번 리더 자가 회복」).

10/22 01:49 UTC Redis 가 외부 공격으로 비워져 sched:leader 가 사라졌고, 옛 refresh_leader 는 「내 값일 때만 연장」이라
다시 잡지 않아 21:50 까지 모든 잡이 「리더 아님」으로 건너뜀. 하트비트는 그동안에도 health "1" 을 써서 정지를 가렸다.
"""
from __future__ import annotations

import threading

from app.workers import scheduler_runner as R
from app.workers.distributed_scheduler_guard import DistributedSchedulerGuard
from tests.test_fix420_scheduler_graceful import FakeRedis as _Fake420


class FakeRedis(_Fake420):
    def setex(self, k, sec, v):
        return self.set(k, v, ex=sec)

KEY = "sched:leader"


def val(r, k=KEY):
    v = r.get(k)
    return v.decode() if isinstance(v, bytes) else v


def test_lua_text_pins():
    lua = DistributedSchedulerGuard._REFRESH_LUA
    assert "'NX', 'EX'" in lua and "ARGV[3] == '0'" in lua and "return 2" in lua and "return 0" in lua
    assert "del" not in lua                                    # 남의 잠금을 지우거나 덮어쓰는 경로 없음


def test_my_lock_extended():
    r = FakeRedis()
    g = DistributedSchedulerGuard(r)
    assert g.try_become_leader()
    r.now = 20
    assert g.refresh_leader() is True and g.reacquired == 0
    r.now = 45                                                 # 연장 안 됐으면 30 에 만료됐을 것
    assert val(r) == g.node_id


def test_missing_lock_reacquired(caplog):
    r = FakeRedis()
    g = DistributedSchedulerGuard(r)
    assert g.try_become_leader()
    r.data.clear()                                             # 10/22 처럼 Redis 가 비워짐
    with caplog.at_level("WARNING"):
        assert g.refresh_leader() is True
    assert val(r) == g.node_id and g.reacquired == 1
    assert any("다시 잡음" in m for m in caplog.messages)
    assert g.refresh_leader() is True and g.reacquired == 1    # 다음부터는 평범한 연장


def test_other_leader_never_overwritten():
    r = FakeRedis()
    other = DistributedSchedulerGuard(r)
    other.node_id = "other-node"
    assert other.try_become_leader()
    me = DistributedSchedulerGuard(r)
    assert me.refresh_leader() is False and val(r) == "other-node" and me.reacquired == 0


def test_redis_error_returns_false_without_raising(caplog):
    class Boom(FakeRedis):
        def eval(self, *a, **k):
            raise ConnectionError("down")
    g = DistributedSchedulerGuard(Boom())
    with caplog.at_level("WARNING"):
        for _ in range(25):
            assert g.refresh_leader() is False
    assert sum("리더 잠금 확인 실패" in m for m in caplog.messages) == 2   # 1회째 + 20회째만 (로그 폭주 방지)


def test_no_reacquire_after_release():
    r = FakeRedis()
    g = DistributedSchedulerGuard(r)
    assert g.try_become_leader()
    assert g.release_leader() is True
    assert g.refresh_leader() is False and val(r) is None      # 종료 중엔 새 프로세스에 양보
    new = DistributedSchedulerGuard(r)
    assert new.try_become_leader()                             # Fix 420 그대로: 새 프로세스는 즉시 리더


def _one_beat(r, guard):
    stop = threading.Event()

    class Once:
        def is_set(self):
            return stop.is_set()

        def wait(self, _sec):
            stop.set()
    R._scheduler_heartbeat_loop(r, Once(), guard)


def test_heartbeat_health_only_when_leader():
    r = FakeRedis()
    g = DistributedSchedulerGuard(r)
    g.try_become_leader()
    r.data.clear()
    _one_beat(r, g)                                            # 하트비트가 사라진 잠금을 다시 잡고 health 1
    assert val(r) == g.node_id and val(r, R.HEALTH_KEY_SCHEDULER_LEADER) == "1"

    other = FakeRedis()
    o = DistributedSchedulerGuard(other)
    o.node_id = "other-node"
    o.try_become_leader()
    other.set(R.HEALTH_KEY_SCHEDULER_LEADER, "1", ex=60)
    _one_beat(other, DistributedSchedulerGuard(other))         # 리더 아님 → health 지움 (정지를 가리지 않게)
    assert other.get(R.HEALTH_KEY_SCHEDULER_LEADER) is None


def test_heartbeat_without_guard_keeps_old_behavior():
    r = FakeRedis()
    _one_beat(r, None)
    assert val(r, R.HEALTH_KEY_SCHEDULER_LEADER) == "1"


def test_heartbeat_wired_with_guard():
    import pathlib
    src = pathlib.Path(R.__file__).read_text(encoding="utf-8")
    assert 'args=(redis_client, _stopping, guard), daemon=True, name="scheduler-heartbeat"' in src


def test_release_waits_for_inflight_refresh():
    """교차 감사(GPT): refresh 의 인수 구성~eval 과 release 의 플래그·삭제가 같은 잠금으로 직렬화돼야 한다."""
    r = FakeRedis()
    g = DistributedSchedulerGuard(r)
    g.try_become_leader()
    done = threading.Event()
    with g._lock:                                              # refresh 가 진행 중인 상태를 흉내
        t = threading.Thread(target=lambda: (g.release_leader(), done.set()))
        t.start()
        assert not done.wait(0.2)                              # release 는 refresh 가 끝날 때까지 기다린다
    t.join(2)
    assert done.is_set() and g.stopping and val(r) is None
    assert g.refresh_leader() is False and val(r) is None

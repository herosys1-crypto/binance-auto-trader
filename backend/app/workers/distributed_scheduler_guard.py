from datetime import datetime, timezone
import logging
import socket
import threading

logger = logging.getLogger(__name__)


class DistributedSchedulerGuard:
    def __init__(self, redis_client, leader_ttl_seconds: int = 30) -> None:
        self.redis = redis_client
        self.leader_ttl_seconds = leader_ttl_seconds
        self.node_id = f"{socket.gethostname()}-{datetime.now(timezone.utc).timestamp()}"
        self.reacquired = 0          # 🩹 Fix 483: 잠금이 사라져 다시 잡은 횟수
        self.stopping = False        # release_leader 뒤엔 다시 잡지 않는다 (새 프로세스에 양보)
        self._fail_streak = 0
        self._lock = threading.Lock()   # 잡 스레드·하트비트 스레드·종료 처리가 같이 부른다

    def try_become_leader(self) -> bool:
        return bool(self.redis.set("sched:leader", self.node_id, nx=True, ex=self.leader_ttl_seconds))

    # 🩹 Fix 483 (2026-10-23 사장님 「1번 리더 자가 회복」): 10/22 Redis 가 외부 공격으로 비워져 잠금이 사라졌는데
    #   옛 refresh 는 「내 값일 때만 연장」이라 다시 잡지 않음 → 20시간 모든 잡이 「리더 아님」.
    #   한 번의 Lua 로: 내 값 → 연장(1) · 키 없음 → NX 로 다시 잡음(2) · 남의 값 → 0 (절대 덮어쓰지 않음).
    #   (옛 v127 bytes/str 문제는 Lua 안 비교라 생기지 않는다)
    _REFRESH_LUA = (
        "local cur = redis.call('get', KEYS[1]) "
        "if cur == ARGV[1] then redis.call('expire', KEYS[1], ARGV[2]) return 1 end "
        "if not cur and ARGV[3] == '0' then "
        "  if redis.call('set', KEYS[1], ARGV[1], 'NX', 'EX', ARGV[2]) then return 2 end "
        "end "
        "return 0"
    )

    def refresh_leader(self) -> bool:
        with self._lock:
            try:
                res = int(self.redis.eval(self._REFRESH_LUA, 1, "sched:leader", self.node_id,
                                          self.leader_ttl_seconds, "1" if self.stopping else "0"))
            except Exception as e:  # noqa: BLE001 — 잡 경로로 예외를 던지지 않는다 (= 리더 아님)
                self._fail_streak += 1
                if self._fail_streak == 1 or self._fail_streak % 20 == 0:
                    logger.warning("[Fix483] 리더 잠금 확인 실패 — 연속 %d회 (%s)", self._fail_streak, type(e).__name__)
                return False
            self._fail_streak = 0
            if res == 2:
                self.reacquired += 1
                logger.warning("[Fix483] 리더 잠금이 사라져 다시 잡음 (node=%s · %d번째)", self.node_id, self.reacquired)
            return res in (1, 2)

    # ⏱ Fix 420: 정상 종료 때 내 리더 잠금만 원자적으로 지운다 (남의 잠금은 절대 X). 잡 잠금은 건드리지 않는다.
    _RELEASE_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0"

    def release_leader(self) -> bool:
        with self._lock:                             # Fix 483: 진행 중인 refresh 와 엇갈려 지운 뒤 다시 잡는 일이 없게
            self.stopping = True                     # 이 뒤로는 refresh 가 다시 잡지 않는다
            try:
                return bool(self.redis.eval(self._RELEASE_LUA, 1, "sched:leader", self.node_id))
            except Exception:
                return False

    def acquire_job_lock(self, job_name: str, ttl_seconds: int) -> bool:
        return bool(self.redis.set(f"sched:job:{job_name}", self.node_id, nx=True, ex=ttl_seconds))

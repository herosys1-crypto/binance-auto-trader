from datetime import datetime, timezone
import socket

class DistributedSchedulerGuard:
    def __init__(self, redis_client, leader_ttl_seconds: int = 30) -> None:
        self.redis = redis_client
        self.leader_ttl_seconds = leader_ttl_seconds
        self.node_id = f"{socket.gethostname()}-{datetime.now(timezone.utc).timestamp()}"

    def try_become_leader(self) -> bool:
        return bool(self.redis.set("sched:leader", self.node_id, nx=True, ex=self.leader_ttl_seconds))

    def refresh_leader(self) -> bool:
        # 🚨 2026-07-24 v127 CRITICAL fix: bytes/str 비교 silent bug!
        #   옛 silent bug: redis.get() = bytes 반환 → self.node_id = str → 항상 != → refresh 항상 False!
        #   = leader 30초 만료 → 모든 job = leader 아님 → 자동 진입/reconcile/TP/SL 전면 정지!
        current = self.redis.get("sched:leader")
        if isinstance(current, bytes):
            current = current.decode("utf-8")
        if current != self.node_id:
            return False
        self.redis.expire("sched:leader", self.leader_ttl_seconds)
        return True

    def acquire_job_lock(self, job_name: str, ttl_seconds: int) -> bool:
        return bool(self.redis.set(f"sched:job:{job_name}", self.node_id, nx=True, ex=ttl_seconds))

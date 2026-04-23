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
        current = self.redis.get("sched:leader")
        if current != self.node_id:
            return False
        self.redis.expire("sched:leader", self.leader_ttl_seconds)
        return True

    def acquire_job_lock(self, job_name: str, ttl_seconds: int) -> bool:
        return bool(self.redis.set(f"sched:job:{job_name}", self.node_id, nx=True, ex=ttl_seconds))

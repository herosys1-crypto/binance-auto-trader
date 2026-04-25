import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

# logging.basicConfig 호출 (이게 없으면 APScheduler/우리 logger.info 가 stdout 에 안 보임)
import app.core.logging  # noqa: F401
from app.core.crypto import decrypt_text
from app.core.redis_client import get_redis_client
from app.observability.metrics import scheduler_leader_status
from app.workers.distributed_scheduler_guard import DistributedSchedulerGuard
from app.workers.keepalive_worker import run_keepalive_once
from app.workers.reconcile_worker import run_position_reconcile_once
from app.workers.run_workers import run_symbol_sync_once, run_tp_sl_once

logger = logging.getLogger(__name__)


def start_scheduler() -> None:
    scheduler = BlockingScheduler(timezone="Asia/Seoul")
    redis_client = get_redis_client()
    guard = DistributedSchedulerGuard(redis_client)
    if not guard.try_become_leader():
        print("[scheduler] another node is leader; exiting")
        scheduler_leader_status.set(0)
        return
    print("[scheduler] became leader, registering jobs")
    scheduler_leader_status.set(1)

    def guarded_job(job_name: str, ttl_seconds: int, fn):
        def _wrapped():
            if not guard.refresh_leader():
                scheduler_leader_status.set(0)
                return
            scheduler_leader_status.set(1)
            if not guard.acquire_job_lock(job_name, ttl_seconds):
                return
            fn()
        return _wrapped

    scheduler.add_job(guarded_job("listenkey_keepalive", 120, lambda: run_keepalive_once(decrypt_text)), trigger=IntervalTrigger(minutes=30), id="listenkey_keepalive", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(guarded_job("position_reconcile", 55, lambda: run_position_reconcile_once(decrypt_text)), trigger=IntervalTrigger(minutes=1), id="position_reconcile", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(guarded_job("tp_sl", 20, run_tp_sl_once), trigger=IntervalTrigger(seconds=10), id="tp_sl", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(guarded_job("symbol_sync_daily", 3600, run_symbol_sync_once), trigger=CronTrigger(hour=3, minute=0), id="symbol_sync_daily", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.start()

if __name__ == "__main__":
    start_scheduler()

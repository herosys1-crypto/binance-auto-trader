import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

# logging.basicConfig 호출 (이게 없으면 APScheduler/우리 logger.info 가 stdout 에 안 보임)
import app.core.logging  # noqa: F401
from app.core.crypto import decrypt_text
from app.core.redis_client import get_redis_client
from app.observability.metrics import scheduler_leader_status
from app.workers.auto_reentry_worker import run_auto_reentry_once
from app.workers.daily_loss_aggregator import run_daily_loss_check_once
from app.workers.distributed_scheduler_guard import DistributedSchedulerGuard
from app.workers.keepalive_worker import run_keepalive_once
from app.workers.reconcile_worker import run_position_reconcile_once
from app.workers.run_workers import run_symbol_sync_once, run_tp_sl_once
from app.workers.stage_trigger_worker import run_stage_trigger_once

logger = logging.getLogger(__name__)


# Redis heartbeat 키 — API process 가 폴링해서 Prometheus gauge 갱신
HEALTH_KEY_SCHEDULER_LEADER = "health:scheduler:leader"
HEALTH_TTL_SECONDS = 60


def _set_scheduler_health(is_leader: bool, redis_client=None) -> None:
    try:
        client = redis_client or get_redis_client()
        if is_leader:
            client.setex(HEALTH_KEY_SCHEDULER_LEADER, HEALTH_TTL_SECONDS, "1")
        else:
            client.delete(HEALTH_KEY_SCHEDULER_LEADER)
    except Exception:  # pragma: no cover
        pass


def _scheduler_heartbeat_loop(redis_client) -> None:
    """30초마다 Redis 에 scheduler heartbeat 갱신 — 별도 thread."""
    import time
    while True:
        try:
            redis_client.setex(HEALTH_KEY_SCHEDULER_LEADER, HEALTH_TTL_SECONDS, "1")
        except Exception as e:
            logger.warning("scheduler heartbeat thread 실패: %s", e)
        time.sleep(30)


def start_scheduler() -> None:
    import threading

    scheduler = BlockingScheduler(timezone="Asia/Seoul")
    redis_client = get_redis_client()
    guard = DistributedSchedulerGuard(redis_client)
    if not guard.try_become_leader():
        print("[scheduler] another node is leader; exiting")
        scheduler_leader_status.set(0)
        _set_scheduler_health(False, redis_client)
        return
    print("[scheduler] became leader, registering jobs")
    scheduler_leader_status.set(1)
    _set_scheduler_health(True, redis_client)

    # heartbeat thread (job 주기와 별개로 30초 보장)
    hb_thread = threading.Thread(target=_scheduler_heartbeat_loop, args=(redis_client,), daemon=True, name="scheduler-heartbeat")
    hb_thread.start()
    print("[scheduler] heartbeat thread started")

    def guarded_job(job_name: str, ttl_seconds: int, fn):
        def _wrapped():
            if not guard.refresh_leader():
                scheduler_leader_status.set(0)
                _set_scheduler_health(False, redis_client)
                return
            scheduler_leader_status.set(1)
            _set_scheduler_health(True, redis_client)  # heartbeat 갱신
            if not guard.acquire_job_lock(job_name, ttl_seconds):
                return
            fn()
        return _wrapped

    scheduler.add_job(guarded_job("listenkey_keepalive", 120, lambda: run_keepalive_once(decrypt_text)), trigger=IntervalTrigger(minutes=30), id="listenkey_keepalive", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(guarded_job("position_reconcile", 55, lambda: run_position_reconcile_once(decrypt_text)), trigger=IntervalTrigger(minutes=1), id="position_reconcile", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(guarded_job("tp_sl", 20, run_tp_sl_once), trigger=IntervalTrigger(seconds=10), id="tp_sl", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(guarded_job("symbol_sync_daily", 3600, run_symbol_sync_once), trigger=CronTrigger(hour=3, minute=0), id="symbol_sync_daily", replace_existing=True, max_instances=1, coalesce=True)
    # 재진입 자동화 — 매 30초마다 검사 (lock TTL 25s 로 중복 방지)
    scheduler.add_job(guarded_job("auto_reentry", 25, lambda: run_auto_reentry_once(decrypt_text)), trigger=IntervalTrigger(seconds=30), id="auto_reentry", replace_existing=True, max_instances=1, coalesce=True)
    # Stage 2~N 자동 진입 트리거 감시 — 매 10초 (Critical: 이전엔 stage 1 만 자동, 2~N 은 수동 필요했던 버그 fix)
    scheduler.add_job(guarded_job("stage_trigger", 8, lambda: run_stage_trigger_once(decrypt_text)), trigger=IntervalTrigger(seconds=10), id="stage_trigger", replace_existing=True, max_instances=1, coalesce=True)
    # Daily loss limit 체크 — 매 1분 (settings.daily_loss_limit_usdt 미설정 시 no-op).
    # audit 2026-05-04: AccountDailyLossLimiter 가 호출되는 곳 0건이라 안전장치 무력 상태였음.
    scheduler.add_job(guarded_job("daily_loss_check", 50, run_daily_loss_check_once), trigger=IntervalTrigger(minutes=1), id="daily_loss_check", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.start()

if __name__ == "__main__":
    start_scheduler()

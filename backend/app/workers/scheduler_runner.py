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
from app.workers.binance_changelog_monitor import run_binance_changelog_monitor_once
from app.workers.daily_loss_aggregator import run_daily_loss_check_once
from app.workers.distributed_scheduler_guard import DistributedSchedulerGuard
from app.workers.daily_summary_worker import run_daily_summary_once
from app.workers.endpoint_health_monitor import run_endpoint_health_monitor_once
from app.workers.keepalive_worker import run_keepalive_once
from app.workers.reconcile_worker import run_position_reconcile_once
from app.workers.run_workers import run_symbol_sync_once, run_tp_sl_once
from app.workers.stage_trigger_worker import run_stage_trigger_once
from app.workers.self_check_worker import run_self_check_once  # 🌟 v17: silent bug 자동 차단
from app.workers.trade_anomaly_monitor import run_trade_anomaly_monitor_once  # 🌟 v20: TP 청산 silent bug 자동 차단
from app.workers.stage_calc_audit_worker import run_stage_calc_audit_once  # 🌟 v44: 단계 계산 사상 자동 검증 (= Phase 3 작은 시작!)
from app.workers.silent_bug_detector import run_silent_bug_detector_once  # 🌟 v45: 잠재 silent bug 자동 감지 (= Phase 3 worker 2!)
from app.workers.user_intent_validator import run_user_intent_validator_once  # 🌟 v46: 사장님 의도 vs 실제 검증 (= Phase 3 worker 3!)
from app.workers.edit_mode_validator import run_edit_mode_validator_once  # 🌟 v47: 「수정 모드」 결과 자동 검증 (= Phase 3 worker 4!)
from app.workers.spec_audit_worker import run_spec_audit_once  # 🌟 v48: 코드 ↔ spec 동기 검증 (= Phase 3 worker 5!)

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
    # 🌟 2026-06-09 v17 (사장님 헌법 6+7번): Self-Check Worker = 매 1시간 자기 검증
    # = silent bug 자동 차단 (= reserved 계산 일치, stage_plans 무결성, DB ↔ 거래소)
    # = 사장님 자본 보호 자동화 (= 사람 의존 X)
    scheduler.add_job(guarded_job("self_check", 300, run_self_check_once), trigger=IntervalTrigger(hours=1), id="self_check", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-06-10 v20 사장님 critical (= TP 청산 silent bug 영구 차단):
    # 사장님 사상: "왜 이런 일이 일어나면 안 되는 부분이잖아" (VELVETUSDT TP1 전량 청산)
    # = TP 청산 직후 = tp_sl_orchestrator 가 TP_EXECUTION_AUDIT RiskEvent 자동 기록
    # = 이 worker = 매 5분 분석 + CRITICAL = 즉시 Telegram (1h dedup)
    # = 사장님 자본 보호 = silent bug 즉시 감지
    scheduler.add_job(guarded_job("trade_anomaly_monitor", 60, run_trade_anomaly_monitor_once), trigger=IntervalTrigger(minutes=5), id="trade_anomaly_monitor", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-06-11 v44 Phase 3 작은 시작: 단계 계산 사상 자동 검증 (= 사장님 추천!)
    # 사장님 spec: docs/spec/stage_calculation_spec_2026-06-11.md
    # = 매 5분 = 모든 활성 strategy 단계 계산 = 사장님 사상 검증
    # = SHORT 오름차순 / LONG 내림차순 검증
    # = 위배 시 = RiskEvent CRITICAL + Telegram 즉시!
    scheduler.add_job(guarded_job("stage_calc_audit", 60, run_stage_calc_audit_once), trigger=IntervalTrigger(minutes=5), id="stage_calc_audit", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-06-11 v45 Phase 3 worker 2: silent_bug_detector (= 사장님 추천!)
    # = 매 1분 = NULL field + Position 불일치 등 = 자동 감지!
    # = 30분 dedup + Telegram 즉시 알림!
    scheduler.add_job(guarded_job("silent_bug_detector", 50, run_silent_bug_detector_once), trigger=IntervalTrigger(minutes=1), id="silent_bug_detector", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-06-11 v46 Phase 3 worker 3: user_intent_validator (= 사장님 옵션 vs 실제 적용 검증!)
    scheduler.add_job(guarded_job("user_intent_validator", 60, run_user_intent_validator_once), trigger=IntervalTrigger(minutes=5), id="user_intent_validator", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-06-11 v47 Phase 3 worker 4: edit_mode_validator (= 「수정 모드」 누적 사상 자동 검증!)
    scheduler.add_job(guarded_job("edit_mode_validator", 60, run_edit_mode_validator_once), trigger=IntervalTrigger(minutes=5), id="edit_mode_validator", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-06-11 v48 Phase 3 worker 5: spec_audit_worker (= 코드 ↔ spec 정적 분석!)
    scheduler.add_job(guarded_job("spec_audit", 300, run_spec_audit_once), trigger=IntervalTrigger(hours=1), id="spec_audit", replace_existing=True, max_instances=1, coalesce=True)
    # 2026-05-09 (rate limit 178건 사후): 1m → 2m 주기 변경. bulk fetch 최적화와 함께
    # API 호출 부담 ~80% 감소 (5 strategy × 60/m × 1 호출 = 300/h → 1 × 30/h = 30/h).
    # main loop 가 1 호출로 모든 active strategy 의 positionRisk 한 번에 가져옴.
    scheduler.add_job(guarded_job("position_reconcile", 110, lambda: run_position_reconcile_once(decrypt_text)), trigger=IntervalTrigger(minutes=2), id="position_reconcile", replace_existing=True, max_instances=1, coalesce=True)
    # 2026-05-06 fix: lock TTL 20s + Interval 10s 였는데 lock 이 다음 사이클까지 살아있어
    # 실제로는 20s 마다 1번만 실행 (½ 빈도). #103 trailing 자동 발동 지연 원인 추정.
    # lock TTL 8s 로 변경 → Interval 10s 보다 짧아 매 사이클 정상 실행.
    # run_tp_sl_once 자체는 보통 1~5s 소요 (active strategy 수 따라), 8s 충분.
    scheduler.add_job(guarded_job("tp_sl", 8, run_tp_sl_once), trigger=IntervalTrigger(seconds=10), id="tp_sl", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(guarded_job("symbol_sync_daily", 3600, run_symbol_sync_once), trigger=CronTrigger(hour=3, minute=0), id="symbol_sync_daily", replace_existing=True, max_instances=1, coalesce=True)
    # 재진입 자동화 — 매 30초마다 검사 (lock TTL 25s 로 중복 방지)
    scheduler.add_job(guarded_job("auto_reentry", 25, lambda: run_auto_reentry_once(decrypt_text)), trigger=IntervalTrigger(seconds=30), id="auto_reentry", replace_existing=True, max_instances=1, coalesce=True)
    # Stage 2~N 자동 진입 트리거 감시 — 매 10초 (Critical: 이전엔 stage 1 만 자동, 2~N 은 수동 필요했던 버그 fix)
    scheduler.add_job(guarded_job("stage_trigger", 8, lambda: run_stage_trigger_once(decrypt_text)), trigger=IntervalTrigger(seconds=10), id="stage_trigger", replace_existing=True, max_instances=1, coalesce=True)
    # Daily loss limit 체크 — 매 1분 (settings.daily_loss_limit_usdt 미설정 시 no-op).
    # audit 2026-05-04: AccountDailyLossLimiter 가 호출되는 곳 0건이라 안전장치 무력 상태였음.
    scheduler.add_job(guarded_job("daily_loss_check", 50, run_daily_loss_check_once), trigger=IntervalTrigger(minutes=1), id="daily_loss_check", replace_existing=True, max_instances=1, coalesce=True)
    # 2026-06-01 신설 — Binance 공식 API CHANGELOG / WebSocket Change Notice 자동 모니터링.
    # 2026-04-23 WebSocket /ws/ → /private/ws/ 마이그레이션 같은 외부 변경을 우리가 모니터링 안 해
    # mainnet 진입 시 모든 chain 문제 한꺼번에 가시화된 사고 재발 방지. 매 6시간 hash 비교.
    scheduler.add_job(guarded_job("binance_changelog_monitor", 300, run_binance_changelog_monitor_once), trigger=IntervalTrigger(hours=6), id="binance_changelog_monitor", replace_existing=True, max_instances=1, coalesce=True)
    # 2026-06-01 신설 — Endpoint Health (user-stream WebSocket / ORDER 이벤트 수신 / REST ping).
    # silent failure (연결은 되지만 이벤트 0건) 자동 감지. 매 30분.
    scheduler.add_job(guarded_job("endpoint_health_monitor", 300, run_endpoint_health_monitor_once), trigger=IntervalTrigger(minutes=30), id="endpoint_health_monitor", replace_existing=True, max_instances=1, coalesce=True)
    # 2026-06-03 신설 — 일일 운영 요약 (KST 00:00 = UTC 15:00). 사장님 운영 추적 가시화.
    # 어제 신규/종료 strategy + 실현 손익 + SL/크라이시스 + 현재 상태 → 텔레그램.
    scheduler.add_job(guarded_job("daily_summary", 300, run_daily_summary_once), trigger=CronTrigger(hour=15, minute=0), id="daily_summary", replace_existing=True, max_instances=1, coalesce=True)
    # System heartbeat — 24/7 운영 신뢰성 알림 (2026-05-07).
    # settings.heartbeat_interval_hours 양수일 때만 등록. 비활성 default → 스케줄 등록 0.
    from app.core.config import settings as _cfg
    hb_hours = _cfg.heartbeat_interval_hours
    if hb_hours and hb_hours > 0:
        from app.workers.heartbeat_worker import run_heartbeat_once
        scheduler.add_job(
            guarded_job("heartbeat", 60, run_heartbeat_once),
            trigger=IntervalTrigger(hours=hb_hours),
            id="heartbeat", replace_existing=True, max_instances=1, coalesce=True,
        )
    # 일일 운영 보고 — 매일 KST 09:00 (UTC 00:00) 1회 (2026-05-09 Layer 3).
    # 사용자가 health_check 안 돌려도 자동으로 「전일 24h 요약」 텔레그램 받음.
    # settings.daily_report_enabled (default True) — False 면 등록 X.
    if getattr(_cfg, "daily_report_enabled", True):
        from app.workers.daily_report_worker import run_daily_report_once
        scheduler.add_job(
            guarded_job("daily_report", 300, run_daily_report_once),
            trigger=CronTrigger(hour=0, minute=0),  # UTC 00:00 = KST 09:00
            id="daily_report", replace_existing=True, max_instances=1, coalesce=True,
        )
    scheduler.start()

if __name__ == "__main__":
    start_scheduler()

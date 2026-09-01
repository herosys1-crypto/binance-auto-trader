import logging
from datetime import datetime, timedelta, timezone   # Fix 219: 발화 시각 오프셋

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
from app.workers.auto_fix_proposer import run_auto_fix_proposer_once  # 🌟 v49: 자동 fix 제안 (= Phase 3 worker 6!)
from app.workers.memory_consolidator import run_memory_consolidator_once  # 🌟 v50: 매일 학습 + 메모리 갱신 (= Phase 3 100% 완성!)
from app.workers.mainnet_safety_worker import run_mainnet_safety_check_once  # 🌟 v51: mainnet 안전 점검 (= #23 옛 미해결!)
from app.workers.settings_sync_worker import run_settings_sync_once  # 🌟 v52: settings 일관성 (= #125 옛 미해결!)
from app.workers.setting_preservation_agent import run_setting_preservation_once  # 🌟 v54: 사장님 처음 세팅 영구 유지 (= EVAAUSDT #149 사건!)
from app.workers.telegram_retry_worker import run_telegram_retry_once  # 🌟 v56: 사장님 Telegram 실패 알림 자동 재시도!
from app.workers.reentry_alert_watcher import run_reentry_alert_watcher  # 🌟 v130: 재진입 알람 (OBV+RSI+10% 신호!)
from app.workers.pump_bb_middle_watcher import run_pump_bb_watcher  # 🌟 v131: 급등+BB중단 알람!
from app.workers.tp_miss_detector_worker import run_tp_miss_detector_once  # 🌟 v57: TP 단계 도달 + 자동 진입 X = critical 감지! (사장님 ESPORTSUSDT #182!)
from app.workers.liquidation_risk_worker import run_liquidation_risk_once  # 🚨 v58: Liquidation 사전 알림! (사장님 SYNUSDT -585 USDT 손실!)

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

    # ═══════════════════════════════════════════════════════════════════════
    # 🚨 Fix 139 (2026-08-26): guarded_job 의 무로그 return 2개 (헌법 80)
    #
    # 사장님 "이익일때 추가 300씩 두번 진입도 하는거지?" 를 확인하려는데
    # success_pyramiding 로그가 한 줄도 없었다. 워커 자체는 등록돼 있는데도.
    #
    # 원인: 아래 두 return 이 아무 로그를 남기지 않는다.
    #   (1) refresh_leader 실패 = 이 컨테이너가 리더가 아님
    #   (2) acquire_job_lock 실패 = 이전 실행이 아직 락을 쥐고 있음
    # success_pyramiding 은 락 TTL 25s / 주기 30s 라, 한 번이라도 25초를 넘기면
    # 그 뒤로 계속 건너뛸 수 있고 「워커가 죽었는지 조용한지」 구별이 불가능하다.
    # 이 클래스의 침묵이 이번 세션에서만 4번 나왔다 (Fix 103/109/121/138).
    #
    # 매 skip 마다 로그하면 41개 job × 고빈도 = spam 이므로,
    # 「연속 skip 횟수」를 세어 처음과 20회마다만 남긴다 (지속 이상만 눈에 띄게).
    # ═══════════════════════════════════════════════════════════════════════
    _skip_streak: dict[str, int] = {}

    def _note_skip(job_name: str, why: str) -> None:
        n = _skip_streak.get(job_name, 0) + 1
        _skip_streak[job_name] = n
        if n == 1 or n % 20 == 0:
            logger.warning(
                "[scheduler] job '%s' 건너뜀 (%s) — 연속 %d회", job_name, why, n,
            )

    def guarded_job(job_name: str, ttl_seconds: int, fn):
        def _wrapped():
            if not guard.refresh_leader():
                scheduler_leader_status.set(0)
                _set_scheduler_health(False, redis_client)
                _note_skip(job_name, "리더 아님")
                return
            scheduler_leader_status.set(1)
            _set_scheduler_health(True, redis_client)  # heartbeat 갱신
            if not guard.acquire_job_lock(job_name, ttl_seconds):
                _note_skip(job_name, f"락 점유 중 (ttl={ttl_seconds}s)")
                return
            _skip_streak.pop(job_name, None)      # 정상 실행 = 연속 카운터 리셋
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
    # 🌟 2026-06-11 v49 Phase 3 worker 6: auto_fix_proposer (= 자동 fix 제안!)
    scheduler.add_job(guarded_job("auto_fix_proposer", 60, run_auto_fix_proposer_once), trigger=IntervalTrigger(minutes=5), id="auto_fix_proposer", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-06-11 v50 Phase 3 worker 7 (= 100% 완성!): memory_consolidator (매일 KST 03:00!)
    scheduler.add_job(guarded_job("memory_consolidator", 600, run_memory_consolidator_once), trigger=CronTrigger(hour=18, minute=0), id="memory_consolidator", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-06-11 v51 신: mainnet_safety_worker (= #23 옛 미해결 = mainnet 진입 직전 점검!)
    scheduler.add_job(guarded_job("mainnet_safety", 300, run_mainnet_safety_check_once), trigger=IntervalTrigger(hours=1), id="mainnet_safety", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-06-11 v52 신: settings_sync_worker (= #125 옛 미해결!)
    scheduler.add_job(guarded_job("settings_sync", 300, run_settings_sync_once), trigger=IntervalTrigger(hours=1), id="settings_sync", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-06-15 v54 신: setting_preservation_agent (= 사장님 EVAAUSDT #149 자동 진입 미발동 사건!)
    # 사장님 사상: '수정모드 + 포지션추가 + 증거금추가 = 중간 진행 시 = 처음 세팅과 문제 X!'
    scheduler.add_job(guarded_job("setting_preservation", 120, run_setting_preservation_once), trigger=IntervalTrigger(minutes=3), id="setting_preservation", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-06-16 v56 신: telegram_retry_worker (= 사장님 Telegram 실패 알림 자동 재시도!)
    # 사장님 critical: '[send_error] HTTPSConnectionPool' = Telegram 일시 끊김 = 사장님 알림 X!
    scheduler.add_job(guarded_job("telegram_retry", 120, run_telegram_retry_once), trigger=IntervalTrigger(minutes=5), id="telegram_retry", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-06-18 v57 신: tp_miss_detector_worker (= 사장님 ESPORTSUSDT #182 TP2/TP3 누락 사건!)
    # 사장님: '결과 좋은 게 문제가 아니야! 실제 수익은 더 많았어야!'
    scheduler.add_job(guarded_job("tp_miss_detector", 90, run_tp_miss_detector_once), trigger=IntervalTrigger(minutes=2), id="tp_miss_detector", replace_existing=True, max_instances=1, coalesce=True)
    # 🚨 2026-06-19 v58 신: liquidation_risk_worker (= 사장님 SYNUSDT Liquidation -585 USDT 손실!)
    # 사장님: SL -100% = Liquidation 보다 먼저 발동 X = 사장님 자본 손실!
    # 신: ROI -70% 도달 시 = 즉시 critical 알림!
    scheduler.add_job(guarded_job("liquidation_risk", 50, run_liquidation_risk_once), trigger=IntervalTrigger(minutes=1), id="liquidation_risk", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-08-06 v130 신: reentry_alert_watcher (= 사장님 요구 = OBV+RSI+10% 신호 알림!)
    # 강제 종료된 심볼 = 4H OBV/RSI 반전 + 10% 이동 시 = 알람!
    # 사장님이 = 알람 선택 = 신 전략 즉시 생성!
    def _reentry_alert_wrap():
        from app.core.database import SessionLocal
        from app.core.crypto import decrypt_text as _dec
        with SessionLocal() as _db:
            run_reentry_alert_watcher(_db, _dec)
    # 사장님 (2026-08-21): 매 5분 → 매 2분! (빠른 시장 = 실시간 감지!)
    scheduler.add_job(guarded_job("reentry_alert", 100, _reentry_alert_wrap), trigger=IntervalTrigger(minutes=2), id="reentry_alert", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-08-09 v131 신: pump_bb_middle_watcher (= 사장님 요구!)
    # 급등 top 50 종목 = 4H 최고점 = BB중단(20MA!) ±5% 근접 = 알람!
    # 10분마다 실행 (자원 절약!)
    def _pump_bb_wrap():
        from app.core.database import SessionLocal
        from app.core.crypto import decrypt_text as _dec
        with SessionLocal() as _db:
            run_pump_bb_watcher(_db, _dec)
    scheduler.add_job(guarded_job("pump_bb_watcher", 540, _pump_bb_wrap), trigger=IntervalTrigger(minutes=10), id="pump_bb_watcher", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-08-11 v132 신: Strategy Suggestion Team!
    # 사장님 요구: 매일 자동 예측 → 전략 draft 제안 → 사장님 결정!
    # 06:30 UTC = 매일 예측! (Team Lead 통해 EventBus로!)
    def _suggestion_daily_predict():
        from app.core.database import SessionLocal
        from app.core.crypto import decrypt_text as _dec
        from app.agents.strategy_suggestion_team.team_lead import StrategySuggestionTeamLead
        with SessionLocal() as _db:
            StrategySuggestionTeamLead().run_daily_prediction(_db, _dec)
    scheduler.add_job(
        guarded_job("suggestion_daily_predict", 1800, _suggestion_daily_predict),
        trigger=CronTrigger(hour=6, minute=30),
        id="suggestion_daily_predict",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # 매 1시간 = 자동 삭제 (24h 미실행!)
    def _suggestion_cleanup():
        from app.core.database import SessionLocal
        from app.agents.strategy_suggestion_team.team_lead import StrategySuggestionTeamLead
        with SessionLocal() as _db:
            StrategySuggestionTeamLead().run_hourly_cleanup(_db)
    scheduler.add_job(
        guarded_job("suggestion_cleanup", 300, _suggestion_cleanup),
        trigger=IntervalTrigger(hours=1),
        id="suggestion_cleanup",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # 매일 07:00 = 자동 실행 배치! (사장님 옵션 ON 시!)
    def _suggestion_auto_execute():
        from app.core.database import SessionLocal
        from app.agents.strategy_suggestion_team.team_lead import StrategySuggestionTeamLead
        with SessionLocal() as _db:
            StrategySuggestionTeamLead().run_auto_execute(_db)
    scheduler.add_job(
        guarded_job("suggestion_auto_execute", 600, _suggestion_auto_execute),
        trigger=CronTrigger(hour=7, minute=0),
        id="suggestion_auto_execute",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # 🌅 매일 아침 브리핑! (KST 07:30 = UTC 22:30 = 사장님 요구!)
    # 사장님: "학습한 내용을 매일 아침에 간략하게 요점정리해서 브리핑해줘"
    def _daily_briefing():
        from app.core.database import SessionLocal
        from app.agents.strategy_suggestion_team.team_lead import StrategySuggestionTeamLead
        with SessionLocal() as _db:
            StrategySuggestionTeamLead().run_daily_briefing(_db)
    scheduler.add_job(
        guarded_job("daily_briefing", 300, _daily_briefing),
        trigger=CronTrigger(hour=22, minute=30),  # KST 07:30 = UTC 22:30
        id="daily_briefing",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # 🎓 v134 신 (2026-08-13 사장님!): 모든 거래 자동 학습!
    # 활성 전략 = on_entry/snapshot, STOPPED = on_exit + insights!
    def _learning_sync():
        from app.workers.learning_sync_worker import run_learning_sync
        run_learning_sync()
    scheduler.add_job(
        guarded_job("learning_sync", 240, _learning_sync),
        trigger=IntervalTrigger(minutes=5),
        id="learning_sync",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # 🎓 v135 (2026-08-13 사장님!): 예측 outcome 학습!
    # 예측된 카드 = 실제 시장 변동 학습 → 심볼별 성공률!
    def _prediction_outcome():
        from app.workers.prediction_outcome_worker import run_prediction_outcome
        run_prediction_outcome()
    scheduler.add_job(
        guarded_job("prediction_outcome", 900, _prediction_outcome),
        trigger=IntervalTrigger(hours=1),
        id="prediction_outcome",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # 🔬 v136 (2026-08-13 사장님!): 시장 관찰!
    # 매 4시간 = 상위 100 심볼 snapshot / 매 1시간 = 관찰 update!
    def _market_obs_snapshot():
        from app.workers.market_observation_worker import run_market_observation_snapshot
        run_market_observation_snapshot()
    scheduler.add_job(
        guarded_job("market_obs_snapshot", 600, _market_obs_snapshot),
        trigger=IntervalTrigger(hours=4),
        id="market_obs_snapshot",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    def _market_obs_update():
        from app.workers.market_observation_worker import run_market_observation_update
        run_market_observation_update()
    scheduler.add_job(
        guarded_job("market_obs_update", 300, _market_obs_update),
        trigger=IntervalTrigger(hours=1),
        id="market_obs_update",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # 🎓 v136 (2026-08-13 사장님!): Learning Team cycle!
    # 매 4시간 = 메모리 → 분석 → 학습!
    def _learning_team_cycle():
        from app.core.database import SessionLocal
        from app.agents.learning_team.team_lead import LearningTeamLead
        with SessionLocal() as _db:
            LearningTeamLead().run_learning_cycle(_db, days=30)
    scheduler.add_job(
        guarded_job("learning_team_cycle", 600, _learning_team_cycle),
        trigger=IntervalTrigger(hours=4),
        id="learning_team_cycle",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # ⛔ v224 통합 (2026-08-23 사장님!): auto_bb_breakdown = unified_15m_entry로 대체!
    # 사장님 verbatim: "지금까지 모든 자동매매는 오늘 15분 차트 급등과 급락한 심볼만
    #                  자동매매를 하는걸로 통합해서 운영할수 있게 하나도 통합정리해줘"
    # → 진입 소스는 unified_15m_entry 하나만! (아래 참조!)
    # 롤백 원할 시 = 아래 주석 해제 + unified_entry_enabled=0 세팅!
    # def _auto_bb_breakdown():
    #     from app.workers.auto_bb_breakdown_worker import run_auto_bb_breakdown
    #     run_auto_bb_breakdown()
    # scheduler.add_job(
    #     guarded_job("auto_bb_breakdown", 900, _auto_bb_breakdown),
    #     trigger=IntervalTrigger(hours=1),
    #     id="auto_bb_breakdown",
    #     replace_existing=True, max_instances=1, coalesce=True,
    # )
    # 🎓 v187 (2026-08-20 사장님!): 성공/실패 패턴 학습!
    # "성공과 실패에서 포지션 진입해야 할곳을 분석해서 학습해줘!"
    def _pattern_learning():
        from app.workers.pattern_learning_worker import run_pattern_learning
        run_pattern_learning()
    scheduler.add_job(
        guarded_job("pattern_learning", 300, _pattern_learning),
        trigger=IntervalTrigger(hours=1),
        id="pattern_learning",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # 🎯 v199 (2026-08-21 사장님!): 실시간 watchlist!
    # "급등후 급락 / 급락후 급등 / 급등 종목 실시간 모니터링!"
    def _realtime_watchlist():
        from app.workers.realtime_watchlist_worker import run_realtime_watchlist
        run_realtime_watchlist()
    scheduler.add_job(
        guarded_job("realtime_watchlist", 600, _realtime_watchlist),
        trigger=IntervalTrigger(minutes=15),  # 매 15분!
        id="realtime_watchlist",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # 🎯 사장님 사상 (2026-08-21): 실시간 재진입! 매 1분!
    # "포지션 실패한 심볼은 실시간 모니터링에 넣어서 짧은 시간 계속 모니터링!"
    # "익절도 마찬가지 = 상승시 다시 진입 + 하락시 -5% 청산!"
    # = Redis mark_price 조회 = API 부담 X!
    # 사장님 최종: 매 1분! (매우 짧게!)
    def _realtime_reentry():
        from app.workers.realtime_reentry_worker import run_realtime_reentry
        run_realtime_reentry()
    scheduler.add_job(
        guarded_job("realtime_reentry", 25, _realtime_reentry),  # lock TTL 25s (매 30초 실행!)
        trigger=IntervalTrigger(seconds=30),  # 사장님 (2026-08-21): 매 1분 → 매 30초 (빠른 시장!)
        id="realtime_reentry",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # 🎯 v218 (2026-08-22 사장님 verbatim!): 성공 피라미딩! 매 30초!
    # 사장님: "익절 시작하고 우리 로직으로 강력한 포지션 = 초기 시작금액으로 즉시 진입!
    #         다시 하락하면 -5% 우리 로직에 맞게 청산!"
    # = 활성 익절중 심볼 = 지속 신호 시 = 원 자본 신 strategy 추가!
    def _success_pyramiding():
        from app.workers.success_pyramiding_worker import run_success_pyramiding
        run_success_pyramiding()
    scheduler.add_job(
        guarded_job("success_pyramiding", 25, _success_pyramiding),
        trigger=IntervalTrigger(seconds=30),
        id="success_pyramiding",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # ⛔ v224 통합 (2026-08-23 사장님!): pending_hc_fast = unified_15m_entry로 대체!
    # 사장님 통합 요구 = 15m 급등/급락 유일 진입! (PENDING_HC 85%+ 소스는 병합됨.)
    # 롤백 시 = 아래 주석 해제 + unified_entry_enabled=0!
    # def _pending_hc_fast():
    #     from app.workers.pending_hc_fast_worker import run_pending_hc_fast
    #     run_pending_hc_fast()
    # scheduler.add_job(
    #     guarded_job("pending_hc_fast", 90, _pending_hc_fast),
    #     trigger=IntervalTrigger(minutes=2),
    #     id="pending_hc_fast",
    #     replace_existing=True, max_instances=1, coalesce=True,
    # )
    # ⛔ v224 통합 (2026-08-23 사장님!): pump_top_detector + auto_short_at_top = unified_15m_entry로 대체!
    # 사장님 verbatim (2026-08-23): "지금까지 모든 자동매매는 오늘 15분 차트 급등과 급락한 심볼만
    #                                자동매매를 하는걸로 통합해서 운영할수 있게 하나도 통합정리해줘"
    # v223 = 15m score + 1h/4h 역방향 검사가 unified_15m_entry 내부에서 실행됨.
    # PumpTopDetector.check_v223_15m_primary()는 여전히 unified 워커 안에서 호출됨.
    # 롤백 시 = 아래 주석 해제 + unified_entry_enabled=0!
    # def _pump_top_detector():
    #     from app.workers.pump_top_detector_worker import run_pump_top_detector
    #     run_pump_top_detector()
    # scheduler.add_job(
    #     guarded_job("pump_top_detector", 240, _pump_top_detector),
    #     trigger=IntervalTrigger(minutes=5),
    #     id="pump_top_detector",
    #     replace_existing=True, max_instances=1, coalesce=True,
    # )
    # def _auto_short_at_top():
    #     from app.workers.auto_short_at_top_worker import run_auto_short_at_top
    #     run_auto_short_at_top()
    # scheduler.add_job(
    #     guarded_job("auto_short_at_top", 25, _auto_short_at_top),
    #     trigger=IntervalTrigger(seconds=30),
    #     id="auto_short_at_top",
    #     replace_existing=True, max_instances=1, coalesce=True,
    # )
    # 🟢 LONG 저점 대칭 워커 (2026-08-24): v219 SHORT 정점 대칭 = LONG 저점 감지 + 자동 진입!
    # long_bottom_detector = 매 5분 = 저점 후보 감지 → Redis sajangnim:bottom_long:* 알람.
    # auto_long_at_bottom = 매 30초 = 24h ticker 스캔 → 조건 충족 시 LONG 자동 진입 + SL -5%.
    # daily_limit / _count_used_slots = auto_bb_breakdown 통합 counter 공유 (단일 진실!).
    # API (long_bottom_alerts / active_longs / monitoring_symbols_long / reentry_watch_long) +
    # UI (v219-monitoring-symbols-long / v219-reentry-watch-long / unified-15m-badge-long) 이미 준비 완료!
    def _long_bottom_detector():
        from app.workers.long_bottom_detector_worker import run_long_bottom_detector
        run_long_bottom_detector()
    # 🚨 Fix 219 (2026-08-30): pump_top_detector(:652) 와 **같은 분에 발화하지 않게** 민다.
    #   둘 다 5분 주기라 프로세스 시작 시각 기준으로 항상 같은 분에 함께 돌았다.
    #   Fix 217 로 감시 대상이 50 → 최대 100 심볼이 되면서 그 분의 weight 가
    #   심볼당 7(pump_top) + 6(long_bottom) 로 겹쳐 몰린다.
    #   150초 오프셋만 주면 피크가 그대로 반으로 갈라진다 — 동작 변화 0, 비용 0.
    #   ⚠️ 이 프로젝트는 2026-08-26 IP ban(418) 이력이 있다. 피크를 낮추는 게 최우선이다.
    scheduler.add_job(
        guarded_job("long_bottom_detector", 240, _long_bottom_detector),
        trigger=IntervalTrigger(
            minutes=5,
            start_date=datetime.now(timezone.utc) + timedelta(seconds=150),
        ),
        id="long_bottom_detector",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    def _auto_long_at_bottom():
        from app.workers.auto_long_at_bottom_worker import run_auto_long_at_bottom
        run_auto_long_at_bottom()
    scheduler.add_job(
        guarded_job("auto_long_at_bottom", 25, _auto_long_at_bottom),
        trigger=IntervalTrigger(seconds=30),
        id="auto_long_at_bottom",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # 🚨 v220 (2026-08-22 사장님 verbatim!): 자동 증거금 추가!
    # 사장님: "2단계 진입후 손실 30% 넘어가면 초기금액으로 증거금 추가
    #         3단계 진입전에 청산가를 높이고 심볼차트가 하락이 시작하면 3단계 진입
    #         최종청산가는 -80% 손실일때 청산"
    # 매 15초 = ROI < -30% 감지 → add_position_margin 자동 호출!
    # → 이 워커 = 증거금 추가만! 3단계 진입 = stage_trigger / -80% SL = evaluate_stop_loss.
    # Fix 51 (2026-08-24 사장님 감사 지적!): _auto_add_margin 중복 정리 완료 =
    #   원래 아래(orchestra_health 뒤)에 100% 동일한 두 번째 def+add_job 이 있었음
    #   (같은 함수명 + 같은 import + 같은 lock 이름 + 같은 job id + 같은 trigger).
    #   APScheduler replace_existing=True 로 뒤엣것이 앞엣것을 대체 = 실행은 1회였으나
    #   헌법 6번(단일 진실) + 헌법 63번(같은 이름 함수 재정의 금지) 위배 → 두 번째 블록 완전 제거.
    def _auto_add_margin():
        from app.workers.auto_add_margin_worker import run_auto_add_margin
        run_auto_add_margin()
    scheduler.add_job(
        guarded_job("auto_add_margin", 12, _auto_add_margin),
        trigger=IntervalTrigger(seconds=15),
        id="auto_add_margin",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # 🎼 v206 Phase 4 (2026-08-21 사장님!): 오케스트라 자동 진단 + 자동 fix!
    # "우리 에이전트 팀이 많은데 왜 이런 문제가?
    #  오케스트라 지휘자가 각각의 에이전트팀을 컨트롤!"
    def _orchestra_health():
        from app.workers.orchestra_health_worker import run_orchestra_health
        run_orchestra_health()
    scheduler.add_job(
        guarded_job("orchestra_health", 240, _orchestra_health),
        trigger=IntervalTrigger(minutes=5),  # 매 5분!
        id="orchestra_health",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # Fix 58 (2026-08-24): 마틴게일 gate 감시! 매 5분!
    # 사장님 사상: 자동 진입 후 → 마틴게일 gate (RSI/OBV/MACD/BB) 정상 동작 검증!
    # gate 오작동 (신호 없이 2단계 진입 or 신호 있어도 진입 X) = 즉시 알림!
    def _martingale_gate_validator():
        from app.workers.martingale_gate_validator_worker import run_martingale_gate_validator
        run_martingale_gate_validator()
    scheduler.add_job(
        guarded_job("martingale_gate_validator", 240, _martingale_gate_validator),
        trigger=IntervalTrigger(minutes=5),
        id="martingale_gate_validator",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # Fix 64 (2026-08-25): 실패 패턴 분석 (사장님 verbatim!)
    # 실패 데이터 스캔 → 공통 패턴 (심볼/시간대/지표) 추출 → 인사이트 생성!
    # 주기: 30분 (실패 데이터 = 자주 스캔 불필요!)
    def _failure_pattern_analyzer():
        from app.workers.failure_pattern_analyzer_worker import run_failure_pattern_analyzer
        run_failure_pattern_analyzer()
    scheduler.add_job(
        guarded_job("failure_pattern_analyzer", 1800, _failure_pattern_analyzer),
        trigger=IntervalTrigger(minutes=30),
        id="failure_pattern_analyzer",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # (Fix 51: _auto_add_margin 중복 블록 = 위 v220 블록으로 통합됨! 2026-08-24.)
    # (v219 pump_top_detector + auto_short_at_top = 위에 이미 등록됨! 중복 제거 2026-08-22.)
    # 🌟 v224 (2026-08-23 사장님 통합 요구!): 15m 급등/급락 = 유일한 진입!
    # 사장님 verbatim: "지금까지 모든 자동매매는 오늘 15분 차트 급등과 급락한 심볼만
    #                  자동매매를 하는걸로 통합해서 운영할수 있게 하나도 통합정리해줘"
    # 매 30초 = 상위 심볼 15m 급등/급락 감지 → v223 지표 확인 → 자동 진입!
    # SystemSetting "unified_entry_enabled" = 1 시만 실 진입!
    def _unified_15m_entry():
        from app.workers.unified_15m_entry_worker import run_unified_15m_entry
        run_unified_15m_entry()
    scheduler.add_job(
        guarded_job("unified_15m_entry", 25, _unified_15m_entry),
        trigger=IntervalTrigger(seconds=30),
        id="unified_15m_entry",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # 📊 v152 (2026-08-16 사장님!): Chart Pattern Learning Team!
    # 매 6시간 = 1달 4H 캔들 → 패턴 감지 → 저장 + outcome tracking!
    def _chart_pattern_scan():
        from app.core.database import SessionLocal
        from app.core.crypto import decrypt_text as _dec
        from app.agents.chart_pattern_learning_team.team_lead import ChartPatternLearningTeamLead
        with SessionLocal() as _db:
            ChartPatternLearningTeamLead().run_full_scan(_db, _dec, top_n=100)
    scheduler.add_job(
        guarded_job("chart_pattern_scan", 1800, _chart_pattern_scan),
        trigger=IntervalTrigger(hours=6),
        id="chart_pattern_scan",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # 2026-05-09 (rate limit 178건 사후): 1m → 2m 주기 변경. bulk fetch 최적화와 함께
    # API 호출 부담 ~80% 감소 (5 strategy × 60/m × 1 호출 = 300/h → 1 × 30/h = 30/h).
    # main loop 가 1 호출로 모든 active strategy 의 positionRisk 한 번에 가져옴.
    scheduler.add_job(guarded_job("position_reconcile", 110, lambda: run_position_reconcile_once(decrypt_text)), trigger=IntervalTrigger(minutes=2), id="position_reconcile", replace_existing=True, max_instances=1, coalesce=True)
    # 2026-05-06 fix: lock TTL 20s + Interval 10s 였는데 lock 이 다음 사이클까지 살아있어
    # 실제로는 20s 마다 1번만 실행 (½ 빈도). #103 trailing 자동 발동 지연 원인 추정.
    # lock TTL 8s 로 변경 → Interval 10s 보다 짧아 매 사이클 정상 실행.
    # run_tp_sl_once 자체는 보통 1~5s 소요 (active strategy 수 따라), 8s 충분.
    # 🌟 v171 (2026-08-17): API Ban 재발 방지! interval 10s → 15s (33% 감소!)
    # 사장님 8/17 21:50 UTC = API Ban -1003 여러 번 발생! 근본 = 너무 많은 호출!
    scheduler.add_job(guarded_job("tp_sl", 12, run_tp_sl_once), trigger=IntervalTrigger(seconds=15), id="tp_sl", replace_existing=True, max_instances=1, coalesce=True)
    scheduler.add_job(guarded_job("symbol_sync_daily", 3600, run_symbol_sync_once), trigger=CronTrigger(hour=3, minute=0), id="symbol_sync_daily", replace_existing=True, max_instances=1, coalesce=True)
    # 재진입 자동화 — 매 60초 (v171: 30s → 60s 감소! auto_reentry는 실시간 필요 X)
    scheduler.add_job(guarded_job("auto_reentry", 50, lambda: run_auto_reentry_once(decrypt_text)), trigger=IntervalTrigger(seconds=60), id="auto_reentry", replace_existing=True, max_instances=1, coalesce=True)
    # Stage 2~N 자동 진입 트리거 감시 — 매 15초 (v171: 10s → 15s 감소!)
    scheduler.add_job(guarded_job("stage_trigger", 12, lambda: run_stage_trigger_once(decrypt_text)), trigger=IntervalTrigger(seconds=15), id="stage_trigger", replace_existing=True, max_instances=1, coalesce=True)
    # 🔁 Fix 175 (2026-08-27 사장님): 사다리 전 단계 실패 → 대기 모니터링 → 처음부터 재시작 (최대 2회)
    #   사장님 verbatim: "이렇게까지 실패한 심볼은 대기모니터링헤서 다시 처음부터 포지션에 들어가면 좋겠는데"
    #   5분 주기 = 운영 진입 로직(15m 정점확인)이 15m 봉 기준이라 더 자주 볼 이유가 없다.
    def _ladder_restart():
        from app.workers.ladder_restart_worker import run_ladder_restart_once
        run_ladder_restart_once()
    scheduler.add_job(guarded_job("ladder_restart", 240, _ladder_restart), trigger=IntervalTrigger(seconds=300), id="ladder_restart", replace_existing=True, max_instances=1, coalesce=True)
    # 📊 Fix 179 (2026-08-27 사장님): 급등락 심볼 볼밴 이탈 분할 매수 (100/200/300)
    #   사장님 verbatim: "상승중인 심볼은 볼밴 하단 이탈 하면 분할 매수 1-3번 ...
    #                     긴상승에는 중단 이탈시 ... -5% 청산하고 tp1 익절도 5%부터 25%씩"
    #   15분 봉 기준 판정이므로 15분 주기. 기본 OFF (pump_split_enabled=1 로 켠다).
    def _pump_split():
        from app.workers.pump_split_entry_worker import run_pump_split_entry_once
        run_pump_split_entry_once()
    scheduler.add_job(guarded_job("pump_split", 780, _pump_split), trigger=IntervalTrigger(seconds=900), id="pump_split", replace_existing=True, max_instances=1, coalesce=True)

    # 📐 Fix 278 (2026-09-02 사장님): 볼밴 **중단선** 4종 = 별도 전략.
    #   "상승중 볼밴 중단지지와 중단저항 그리고 중단돌파 중단하락돌파에도
    #    우리 시스템로직이 상승과 하락이 판단되면 이것도 포지션에 진입해줘"
    #   "이전략은 15분 차트를 기준이야 1시간과 4시간은 참고용으로"
    #   15분봉 판정이므로 15분 주기. **기본 shadow**(자금 안 나감) — 헌법 161.
    def _bb_mid_line():
        from app.workers.bb_mid_line_worker import run_bb_mid_line_once
        run_bb_mid_line_once()
    scheduler.add_job(guarded_job("bb_mid_line", 780, _bb_mid_line), trigger=IntervalTrigger(seconds=900), id="bb_mid_line", replace_existing=True, max_instances=1, coalesce=True)
    # 📅 Fix 182 (2026-08-27 사장님): 예약 전략 — 조건 맞을 때 시스템이 대신 진입
    #   사장님 verbatim: "예약 전략으로 만들면 시스템이 진입가능할때
    #                     예약해 놓은 전략으로 진행할수 있게 예약기능을 만들어줘"
    #   판정이 15분 봉 기준(confirm_peak)이라 5분 주기면 충분. 기본 OFF.
    def _scheduled_entry():
        from app.workers.scheduled_entry_worker import run_scheduled_entry_once
        run_scheduled_entry_once()
    scheduler.add_job(guarded_job("scheduled_entry", 240, _scheduled_entry), trigger=IntervalTrigger(seconds=300), id="scheduled_entry", replace_existing=True, max_instances=1, coalesce=True)
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

    # ─────────── Fix 29 v228 (2026-08-23): 저항 반전 SHORT 2단계 자동 진입 ───────────
    def _resistance_reversal():
        from app.workers.resistance_reversal_worker import run_resistance_reversal_once
        run_resistance_reversal_once()

    scheduler.add_job(
        guarded_job("resistance_reversal", 25, _resistance_reversal),
        trigger=IntervalTrigger(seconds=30),
        id="resistance_reversal",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

    # Fix 31 v230 (2026-08-23): 4h + 반대 신뢰도 청산!
    # ═══════════════════════════════════════════════════════════════════════
    # 🚨 Fix 198 (2026-08-28): 사장님 결정으로 **명시적으로 끕니다.**
    #
    # 이 워커는 2026-08-23 배포 이후 **한 번도 동작한 적이 없습니다.**
    #   후보 조회에 `started_at.isnot(None)` 이 있는데 StrategyInstance.started_at 은
    #   채우는 코드가 아예 없어 전 1160건 NULL → 항상 0건 → 무로그 return.
    #   = 「등록은 됐는데 조건 때문에 우연히 안 도는」 상태였습니다.
    #
    # 그 상태가 가장 위험합니다 — 학습용으로 started_at 을 채우는 순간
    # 이 워커가 **아무 예고 없이 살아나** 4시간 경과 1단계 포지션을
    # 시장가 전량청산하기 시작합니다 (최대 50건/사이클).
    # 그래서 「기록을 채우는 것」과 「청산을 켜는 것」을 분리했고,
    # 사장님이 「끈다 + 학습용 기록만」을 선택하셨습니다.
    #
    # 다시 켜려면: 이 블록의 주석을 풀기 전에 4시간 규칙이 실제로 성과에
    # 도움이 되는지 데이터로 확인할 것 (지금은 근거가 없습니다).
    # ═══════════════════════════════════════════════════════════════════════
    # def _time_reverse_exit():
    #     from app.workers.time_reverse_exit_worker import run_time_reverse_exit_once
    #     run_time_reverse_exit_once()
    #
    # scheduler.add_job(
    #     guarded_job("time_reverse_exit", 240, _time_reverse_exit),
    #     trigger=IntervalTrigger(minutes=5),
    #     id="time_reverse_exit",
    #     replace_existing=True,
    #     max_instances=1,
    #     coalesce=True,
    # )
    logger.warning(
        "[scheduler] time_reverse_exit = 사장님 결정으로 비활성 (Fix 198). "
        "4시간 시간청산/반대신뢰도 청산은 동작하지 않습니다."
    )

    # Fix 42 (2026-08-23 사장님!): v219 재등록! (auto_short_at_top + pump_top_detector)
    # 위쪽 v224 통합 주석에서 비활성 처리됐던 워커 = 사장님 v219 유지 요구로 재등록.
    def _auto_short_at_top_v219():
        from app.workers.auto_short_at_top_worker import run_auto_short_at_top
        run_auto_short_at_top()
    scheduler.add_job(
        guarded_job("auto_short_at_top", 25, _auto_short_at_top_v219),
        trigger=IntervalTrigger(seconds=30),
        id="auto_short_at_top", replace_existing=True, max_instances=1, coalesce=True,
    )

    # 🎯 Fix 267 (2026-09-01 사장님): 급등 정점 SHORT 사다리 — 이기면 늘리고 지면 다시
    #   사장님: "당일 급등하는 1위 10위까지만 모니터링 ... 최고점에 조정 시작할 심볼에
    #            1단계 500 진입 ... 당연히 첫진입부터 성공해서 포지션 추가를 하고 싶은거야"
    #   🚨 **기본 OFF** (SystemSetting surge_ladder_mode = off|shadow|on).
    #      랭킹 계열 워커 7종에 enable 게이트가 하나도 없어서, 명시하지 않으면
    #      배포 즉시 자금이 나간다. 이 워커는 스스로 모드를 확인하고 off 면 즉시 반환한다.
    #   신고점 추적이 필요하므로 30초 주기 (15m 봉 안에서 극값을 놓치지 않도록).
    def _surge_peak_ladder():
        from app.workers.surge_peak_ladder_worker import run_surge_peak_ladder_once
        run_surge_peak_ladder_once()
    scheduler.add_job(
        guarded_job("surge_peak_ladder", 25, _surge_peak_ladder),
        trigger=IntervalTrigger(seconds=30),
        id="surge_peak_ladder", replace_existing=True, max_instances=1, coalesce=True,
    )

    def _pump_top_detector_v219():
        from app.workers.pump_top_detector_worker import run_pump_top_detector
        run_pump_top_detector()
    scheduler.add_job(
        guarded_job("pump_top_detector", 240, _pump_top_detector_v219),
        trigger=IntervalTrigger(minutes=5),
        id="pump_top_detector", replace_existing=True, max_instances=1, coalesce=True,
    )

    # Fix 62 (2026-08-24 사장님!): 급등 후 하락 초기 감지!
    # v219 = 완전 정점 (7/7) / Fix 62 = 하락 초기 (5/6) = 사장님 사상!
    def _pump_dump_early_detector():
        from app.workers.pump_dump_early_detector_worker import run_pump_dump_early_detector
        run_pump_dump_early_detector()
    scheduler.add_job(
        guarded_job("pump_dump_early_detector", 240, _pump_dump_early_detector),
        trigger=IntervalTrigger(minutes=5),
        id="pump_dump_early_detector",
        replace_existing=True, max_instances=1, coalesce=True,
    )

    # 🌟 Fix 67 (2026-08-25 사장님 신 사상 v2 = SHORT BB상단돌파 마틴게일!)
    # spec: bb_upper_breakout_short_v1_fix67_2026-08-25
    # 사장님 verbatim: "SHORT은 급등해서 볼밴 상단 돌파했을때 마틴게일 전략!
    #                   (확실한 수익을 낼수 있어!)"
    # = 매 5분 = 상위 심볼 스캔 → BB 상단 돌파 + 마틴게일 3중 지표 (RSI/MACD/볼륨)
    # → Redis alert (pump_top:alert:{symbol}:SHORT, source='bb_upper_breakout')
    # → auto_short_at_top_worker(진입 300 USDT + -5% SL)
    # → realtime_reentry_worker(마틴게일 300/600/1800 + Fix 53 라스트 챈스)
    # Fix 65 (obv_gate SHORT) + Fix 66 P1/P2 통합 (bidirectional_blocklist + pump_dump_regime).
    def _bb_upper_breakout_short():
        from app.workers.bb_upper_breakout_short_worker import run_bb_upper_breakout_short
        run_bb_upper_breakout_short()
    scheduler.add_job(
        guarded_job("bb_upper_breakout_short", 240, _bb_upper_breakout_short),
        trigger=IntervalTrigger(seconds=300),  # 매 5분!
        id="bb_upper_breakout_short",
        replace_existing=True, max_instances=1, coalesce=True,
    )

    # 🌟 Fix 74 (2026-08-25 사장님 헌법 77 = 15m MACD 히스토그램 pivot 반전 감지!)
    # spec: macd_reversal_15m_v1_fix74_2026-08-25
    # 사장님 verbatim: "15분 macd 히스토그램에서 최저점을 찍고 다시 반등하는 시점에서 롱포지션
    #                   진입하고 반대로 상승하다가 최고점을 찍고 다시 하락하는 시점에서 숏 포지션 진입!
    #                   4시간의 움직임도 같은 방향으로 흐를때는 성공률이 아주 높음!"
    # = 매 3분 = 상위 심볼 15m MACD 히스토그램 3봉 pivot 감지
    #   (LONG=hist[-3]>hist[-2]<hist[-1] & hist[-2]<0 = 저점 반등 / SHORT=hist[-3]<hist[-2]>hist[-1] & hist[-2]>0)
    # + 4H MACD 방향 필터 (같은 방향 시 confidence +0.05) + 볼륨 30%+ 증가 확인
    # + 헌법 64 준수 (24h ±15% 극단은 반대매매 방지 skip)
    # + Fix 65 obv_gate + Fix 66 P1 bidirectional_blocklist + P2 pump_dump_regime 통합
    # → Redis alert (SHORT=pump_top:alert:{symbol}:SHORT, LONG=sajangnim:bottom_long:{symbol})
    # → auto_short_at_top_worker / auto_long_at_bottom_worker (매 30초 consumer!)
    def _macd_reversal_15m():
        from app.workers.macd_reversal_15m_worker import run_macd_reversal_15m
        run_macd_reversal_15m()
    scheduler.add_job(
        guarded_job("macd_reversal_15m", 150, _macd_reversal_15m),
        trigger=IntervalTrigger(seconds=180),  # 매 3분!
        id="macd_reversal_15m",
        replace_existing=True, max_instances=1, coalesce=True,
    )

    # Fix 41 (2026-08-23 사장님!): 전고점 돌파 후 반전 마틴게일!
    def _peak_break_reversal():
        from app.workers.peak_break_reversal_worker import run_peak_break_reversal_once
        run_peak_break_reversal_once()
    scheduler.add_job(
        guarded_job("peak_break_reversal", 25, _peak_break_reversal),
        trigger=IntervalTrigger(seconds=30),
        id="peak_break_reversal",
        replace_existing=True, max_instances=1, coalesce=True,
    )

    # Fix 47 LONG 시스템 (long_bottom_detector + auto_long_at_bottom) =
    # 위쪽 (line ~382-399) 에서 이미 등록됨. 중복 등록 방지 = 여기서는 재등록 안 함.

    scheduler.start()

if __name__ == "__main__":
    start_scheduler()

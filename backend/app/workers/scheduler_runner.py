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
        from app.db.session import SessionLocal
        from app.core.crypto import decrypt_text as _dec
        with SessionLocal() as _db:
            run_reentry_alert_watcher(_db, _dec)
    scheduler.add_job(guarded_job("reentry_alert", 240, _reentry_alert_wrap), trigger=IntervalTrigger(minutes=5), id="reentry_alert", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-08-09 v131 신: pump_bb_middle_watcher (= 사장님 요구!)
    # 급등 top 50 종목 = 4H 최고점 = BB중단(20MA!) ±5% 근접 = 알람!
    # 10분마다 실행 (자원 절약!)
    def _pump_bb_wrap():
        from app.db.session import SessionLocal
        from app.core.crypto import decrypt_text as _dec
        with SessionLocal() as _db:
            run_pump_bb_watcher(_db, _dec)
    scheduler.add_job(guarded_job("pump_bb_watcher", 540, _pump_bb_wrap), trigger=IntervalTrigger(minutes=10), id="pump_bb_watcher", replace_existing=True, max_instances=1, coalesce=True)
    # 🌟 2026-08-11 v132 신: Strategy Suggestion Team!
    # 사장님 요구: 매일 자동 예측 → 전략 draft 제안 → 사장님 결정!
    # 06:30 UTC = 매일 예측! (Team Lead 통해 EventBus로!)
    def _suggestion_daily_predict():
        from app.db.session import SessionLocal
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
        from app.db.session import SessionLocal
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
        from app.db.session import SessionLocal
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
        from app.db.session import SessionLocal
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
        from app.db.session import SessionLocal
        from app.agents.learning_team.team_lead import LearningTeamLead
        with SessionLocal() as _db:
            LearningTeamLead().run_learning_cycle(_db, days=30)
    scheduler.add_job(
        guarded_job("learning_team_cycle", 600, _learning_team_cycle),
        trigger=IntervalTrigger(hours=4),
        id="learning_team_cycle",
        replace_existing=True, max_instances=1, coalesce=True,
    )
    # 🤖 v162 (2026-08-16 사장님!): BB 이탈 SUSTAINED 자동 진입!
    # 🎯 v190 (2026-08-20 사장님!): 매 1시간! MTA 소스 추가!
    # 🚨 v196 (2026-08-20 CRITICAL!): API Ban 사고! 매 4시간 복원!
    # 원인: v190 매 1h + MTA 3 프레임 = Binance IP Ban! (Way too many requests!)
    # (auto_bb_break_daily_limit 옵션에 따라!)
    def _auto_bb_breakdown():
        from app.workers.auto_bb_breakdown_worker import run_auto_bb_breakdown
        run_auto_bb_breakdown()
    scheduler.add_job(
        guarded_job("auto_bb_breakdown", 900, _auto_bb_breakdown),
        trigger=IntervalTrigger(hours=4),  # v196: 1h → 4h (Ban 방지!)
        id="auto_bb_breakdown",
        replace_existing=True, max_instances=1, coalesce=True,
    )
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
    # 📊 v152 (2026-08-16 사장님!): Chart Pattern Learning Team!
    # 매 6시간 = 1달 4H 캔들 → 패턴 감지 → 저장 + outcome tracking!
    def _chart_pattern_scan():
        from app.db.session import SessionLocal
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

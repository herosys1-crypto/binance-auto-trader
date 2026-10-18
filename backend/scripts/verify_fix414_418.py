"""Fix 414~418 배포 검사 — 파일/DB/Redis 읽기만. verify_fix364_deploy.py 가 check_fix414_418(...) 한 줄로 부른다.

코드 층: 각 Fix 의 필수 표식.
운영 층 (배포 = 프로세스 시작 이후만 본다 — 그 전 기록은 옛 코드 몫):
  414 MARTINGALE_GATE_MISSING · TP_EXECUTION_AUDIT CRITICAL 이 다시 나오는지 (나오면 표만, 원인 확인은 사람)
  416 최근 15분 바이낸스 요청 집계에서 실매매 거절(weight_throttled) vs 학습 양보(weight_throttled_low)
  417 ① 2단계+ 자동 회복(RECONCILE_TRIGGER_RECOVERED)이 체결 증거(fill_evidence=filled) 없이 나오면 FAIL
      ② STOPPING 이 처음 본 시각(Redis) 기준 10분 넘게 남아 있으면 FAIL (감지기는 5분에 MANUAL_CLEANUP 으로 뺀다)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

TITLE = "🧾 Fix 414~420 (CRITICAL 오탐 · 로그 · IP 우선순위 · reconcile 결함 · 화면 폴링 · 스케줄러 정상 종료)"

CODE_MARKERS = {
    "app/workers/martingale_gate_validator_worker.py": ("def _gate_not_applicable(",),                     # 414
    "app/workers/stage_trigger_worker.py": ("stage_trigger:fix55_gate_passed:sid:",),                          # 414
    "app/services/tp_sl_orchestrator.py": ("_qty_adjust_reason", "close_qty != _qty_adjust_close"),            # 414
    "app/workers/silent_bug_detector.py": ("types=%s first=%s",),                                              # 415
    "app/integrations/binance/weight_priority.py": ("LOW_PRIORITY_SCAN_BUDGET_PER_MIN = 1100", "def scan_throttled("),  # 416
    "app/integrations/binance/client.py": ("_scan_throttled(path, _wtotal, _wcaller", '"weight_throttled_low"'),        # 416
    "app/workers/reconcile_worker.py": (                                                                        # 417
        "def _stage_fill_evidence(", '_FILL_EVIDENCE_PROMOTE = frozenset({"stage1", "filled"})',
        "_stopping_snapshot = _snapshot_stopping(rows, _redis)", "snapshot=_stopping_snapshot",
    ),
    "app/static/js/live-pump-dump-alerts.js": ("if (!document.hidden) scanLivePumpDump();",),                  # 418
    "app/static/js/tp-sl-advisor.js": ("if (!document.hidden) scanTpSlAdvisor();",),                           # 418
    "app/workers/scheduler_runner.py": ("wait_for_leader(guard)", "signal.signal(signal.SIGTERM, _on_signal)",  # 420
                                        'guarded_job("strategy_council"',                                     # 430 스케줄
                                        "record_job_count(redis_client, job_name, _ok, _t1)",                 # 459 24h 오류
                                        'CronTrigger(hour=10, minute=20, timezone="Asia/Seoul")',
                                        'guarded_job("ichikijun_lab"'),                                     # 460 KST · 465 스케줄
    "app/workers/distributed_scheduler_guard.py": ("def release_leader(",),                                      # 420
    "app/workers/emapb_watch_worker.py": ("def scan_symbol(", "_send(db, r, fresh, iv)"),                       # 424 알림
    "app/api/v1/ema_pullback.py": ('APIRouter(prefix="/ema-pullback"',),                                         # 424 화면
    "app/services/ema_pullback.py": ('"emapb_interval": ("1d"', "def ready_state("),                             # 424 일봉
    "app/services/strategy_council.py": ("def build_report(", '"gap": (1, 10)'),                                 # 430 운영팀
    "app/workers/strategy_council_worker.py": ("council:latest", "stream_results"),                              # 430 워커
    "app/services/council_gate.py": ("def judge(", "council:gate:"),                                           # 433 기록 전용
    "app/workers/rule_family_worker.py": ("CG.judge(", "si = _enter_split(",                                   # 433 연결
                                          'blocks.append("regime_filter")', "RF.regime_filter_mode(db)"),       # 439 장세 필터
    "app/services/family_loss_breaker.py": ("def family_part(", "begin_nested",                                # 435 차단기 체결 기준
                                            "def limit_for(", "limit = limit_for(db, fam_key)"),               # 444 가족별 기준
    "app/services/human_share.py": ("def split_for(", '"fills": len(es)'),                                    # 434·435
    "app/services/consensus_long.py": ("def qualifies(", 'RULE_KEY = "consensus_long"'),                     # 437 합의 LONG
    "app/services/pump_top_short.py": ("def judge(", 'KEY_30 = "pumptop_short_30"'),                       # 438 급등 정점 SHORT
    "app/services/ext_regime.py": ("def chg24_from_bars(", "def breadth_now("),                              # 440 외부 장세 필터
    "app/workers/ext_family_loop.py": ('regime=payload["regime"]',),                                          # 440
    "app/services/mass_rebound.py": ("def detect(", "def retro_bars("),                                         # 442 동시 반등
    "app/services/kline_store.py": ("class RedisKlineStore", "def apply_settings("),                         # 446 일봉 캐시 보관
    "app/agents/orchestrator/receivers.py": ("def install(", "def prune_learning("),                         # 450 메시지 받는 쪽
    "app/agents/orchestrator/team_lead_base.py": ("def stoppable(", "key=f\"team:{self.TEAM}\""),          # 449
    "app/services/kline_incremental.py": ("def set_full_refresh(", "def _restore("),                             # 446
    "app/services/paper_trading.py": ('"live_trend": {"trend": "after_tp1"}', "def trend_lines_for("),         # 447 추세 보유 청산 기록
    "app/workers/paper_trading_worker.py": ("_CON.apply(fired, rule_side, breadth)",),                       # 437 가상 판정
    "app/services/rule_families.py": ('Family("rf_consensus_long"', '"rf_consensus_long_entry"',       # 437 가족
                                      "REVIEW_NOTES: dict[str, str] = {"),                                # 462 10/16 검토 설명
    "app/workers/verdict_report_worker.py": ('"jk": "jk_2026_11_15.py"',),                                  # 462 가설 J·K 자동 판정
    "app/services/office_board.py": ("def parse_counts(", "BLIP_MIN_RUNS = 10", "def parse_next_runs(",   # 459 사무실 24h 오류·다음 실행
                                      "def daily_table(", "DAILY_GRACE_MIN = 10",                        # 461 오늘 하루 1번 잡
                                      "def live_line(", "LIVE_FAIL_TTL = 60"),                            # 462 실주문 가족 한 줄
    "app/services/ichimoku_kijun.py": ("def entry_at(", 'SOURCE_KEY = "1d_src_now_r2kj"'),                # 465 일목 실험실 판정
    "app/services/ichikijun_lab.py": ("def build_board(", "def update_champion("),                         # 465 순위표·챔피언
    "app/workers/ichikijun_lab_worker.py": ("def process_interval(", "def run_ichikijun_board_once("),     # 465 워커
    "app/api/v1/ichikijun_lab.py": ('APIRouter(prefix="/ichikijun-lab"',),                                  # 465 화면
    "app/services/ichikijun_apply.py": ("def resolve_variant(", "def applied_report("),                   # 466 인스턴스 적용
    "app/workers/ichikijun_sched.py": ("def judge(", "def apply_overrides("),                             # 466 예약 판정
    "app/workers/scheduled_entry_worker.py": ("_IS466.judge(db, bc, _r466, si, _now_ms466)",),             # 466 분기
    "app/api/v1/strategies/crud.py": ("_IA466.parse_entry_signal(payload.entry_signal)",),               # 466 생성 검증
    "app/services/ichikijun_exit.py": ("def kijun_break(", 'MODE_DEFAULT = "shadow"'),                     # 467 기준선 청산 판정
    "app/workers/ichikijun_exit_worker.py": ("def run_ichikijun_exit_once(", "def _close("),                # 467 워커
}
STOPPING_STALE_SEC = 10 * 60      # Claude가 정함 — 감지 5분 + reconcile 2분 주기 두 번 여유
REQ_COUNT_KEY = "binance:reqcount:{minute}"   # client._REQ_COUNT_KEY 와 같은 값 (보관 15분)
FIRST_SEEN_PREFIX = "stopping_first_seen:"    # reconcile_worker.STOPPING_FIRST_SEEN_REDIS_PREFIX


def _text(v):
    return v.decode("utf-8") if isinstance(v, bytes) else str(v)


def _check_code(root, ok, fail):
    for rel, markers in CODE_MARKERS.items():
        try:
            src = (Path(root) / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            fail(f"코드 {rel}: 읽기 실패 — {e!r}")
            continue
        missing = [m for m in markers if m not in src]
        if missing:
            fail(f"코드 {rel}: 표식 없음 — {', '.join(missing)}")
        else:
            ok(f"코드 {rel}: 표식 확인")


def _epoch(dt):
    if dt is None:
        return None
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).timestamp()   # naive = UTC 로 저장된 값


def _ops_414(db, since, ok, skip):
    from sqlalchemy import text
    rows = db.execute(text(
        "select event_type, count(*) from risk_events where created_at >= :s and severity = 'CRITICAL' "
        "and event_type in ('MARTINGALE_GATE_MISSING','TP_EXECUTION_AUDIT') group by 1"), {"s": since}).fetchall()
    if rows:
        skip("414 배포 뒤 CRITICAL 재발: " + ", ".join(f"{r[0]} {r[1]}" for r in rows) + " — 건별 원인 확인 필요")
    else:
        ok("414 배포 뒤 마틴게일 게이트 · TP 감사 CRITICAL 0건")


def _ops_416(redis, start_epoch, ok, skip):
    if redis is None:
        skip("416 Redis 없음 → 요청 집계 생략")
        return
    now = int(time.time())
    live = low = minutes = 0
    for i in range(0, 15):                          # 현재 분 포함 (보관 15분)
        t = now - i * 60
        if start_epoch and (t // 60) * 60 < start_epoch:
            continue                                  # 시작 시각이 걸친 분·그 전 분 = 옛 프로세스 몫 → 제외
        m = time.strftime("%Y%m%d%H%M", time.gmtime(t))
        h = redis.hgetall(REQ_COUNT_KEY.format(minute=m)) or {}
        if h:
            minutes += 1
        for k, v in h.items():
            status = _text(k).split("|", 1)[-1]
            if status == "weight_throttled":
                live += int(v)
            elif status == "weight_throttled_low":
                low += int(v)
    if minutes == 0:
        skip("416 프로세스 시작 이후 요청 집계 분 없음 (배포 직후면 정상)")
        return
    msg = f"416 최근 {minutes}분: 학습 양보 {low}건 · 실매매 스캔 거절 {live}건"
    if live:
        skip(msg + " — 실매매 거절이 있다 = 학습 양보로도 모자란 분 (분별 확인)")
    else:
        ok(msg)


def _ops_417_promotion(db, since, ok, fail, skip):
    from sqlalchemy import text
    rows = db.execute(text(
        "select strategy_instance_id, event_payload from risk_events where created_at >= :s "
        "and event_type = 'RECONCILE_TRIGGER_RECOVERED'"), {"s": since}).fetchall()
    bad, unknown, n2 = [], [], 0
    for sid, payload in rows:
        p = payload or {}
        if isinstance(p, str):
            try:
                p = json.loads(p)
            except ValueError:
                p = {}
        if not isinstance(p, dict):       # Gemini: 리스트 등 dict 아닌 payload 가 AttributeError 로 검사를 깨지 않게 → 판정 불가로
            p = {}
        try:
            stage = int(p.get("stage_no"))
        except (TypeError, ValueError):
            unknown.append(f"#{sid}")
            continue
        if stage >= 2:
            n2 += 1
            if p.get("fill_evidence") != "filled":
                bad.append(f"#{sid} 단계 {stage} ({p.get('fill_evidence')})")
    if bad:
        fail("417① 체결 증거 없이 2단계+ 자동 승격: " + ", ".join(bad[:5]))
    else:
        ok(f"417① 자동 회복 {len(rows)}건 (2단계+ {n2}건, 전부 체결 증거)")
    if unknown:
        skip("417① 단계 번호를 읽을 수 없는 회복 이벤트: " + ", ".join(unknown[:5]))


def _ops_417_stopping(db, redis, start_epoch, ok, fail):
    from sqlalchemy import text
    stop = db.execute(text(
        "select id, symbol, updated_at from strategy_instances where status = 'STOPPING' and not is_archived")).fetchall()
    if not stop:
        ok("417② 지금 STOPPING 0건")
        return
    now = time.time()
    stale = []
    for sid, sym, upd in stop:
        first = None
        if redis is not None:
            try:
                raw = redis.get(f"{FIRST_SEEN_PREFIX}{sid}")
                first = float(_text(raw)) if raw is not None else None
            except Exception:  # noqa: BLE001
                first = None
        base = first if first is not None else _epoch(upd)
        if base is None:
            continue
        base = max(base, start_epoch)                 # 새 감지기가 돈 시간만 센다 (배포 전부터 STOPPING 이던 행 오탐 방지)
        if now - base > STOPPING_STALE_SEC:
            stale.append(f"#{sid} {sym} {int((now - base) // 60)}분")
    if stale:
        fail("417② STOPPING 이 새 감지기 아래서 10분 넘게 남음(감지기 미작동 의심): " + ", ".join(stale))
    else:
        ok(f"417② STOPPING {len(stop)}건 — 새 감지기 기준 10분 이내")


def _run(name, fn, db, fail):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        if db is not None:
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        fail(f"{name} 운영 층 조회 실패: {e!r}")


def check_fix414_418(ok, fail, skip, *, root, code_only, process_start_epoch=None, db=None, redis=None):
    print(f"\n{TITLE}")
    _check_code(root, ok, fail)
    if code_only:
        skip("--code-only: Fix 414~418 운영 층 생략")
        return
    if not process_start_epoch:
        # 감사: 기준을 모르면 옛 코드 몫을 새 배포 결함으로 오판한다 → 시작 시각 의존 검사는 하지 않는다
        skip("프로세스 시작 시각 모름 → Fix 414~418 운영 층 생략 (컨테이너 안에서 실행할 것)")
        return
    since = datetime.fromtimestamp(process_start_epoch, tz=timezone.utc)
    print(f"  ▸ 운영 층 기준 = 프로세스 시작 {since:%m-%d %H:%M} UTC 이후")
    if db is None:
        skip("DB 없음 → 414·417 운영 층 생략")
    else:
        _run("414", lambda: _ops_414(db, since, ok, skip), db, fail)
        _run("417①", lambda: _ops_417_promotion(db, since, ok, fail, skip), db, fail)
        _run("417②", lambda: _ops_417_stopping(db, redis, process_start_epoch, ok, fail), db, fail)
    _run("416", lambda: _ops_416(redis, process_start_epoch, ok, skip), None, skip)

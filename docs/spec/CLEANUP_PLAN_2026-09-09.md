# 코드 정리·최적화 계획 (2026-09-09 오후~)

> 사장님: "모니터링 등등 화면에 보여지는 모든 것들을 오늘 오후 이후로 시스템을 코드 정리 코드최적화를 한번 해야 할 것 같아"

전수 목록(화면 43 JS 모듈·단독 HTML 9·라우터 26/라우트 152·스케줄 잡 64+주석 6·설정 키 64 DB / ~150 코드)은 [A4 인벤토리](../learning/forensic_2026-09-09/A4_inventory.md). 여기는 **무엇을 어떤 순서로** 정리할지만.

## 원칙
1. 실자금 경로(3등급)는 이번 정리에서 **손대지 않는다.** 정리는 「부르는 곳 0곳」과 「꺼진 지 오래된 것」에서만.
2. 한 단계마다 테스트 + 라우트 목록 테스트 갱신 + VPS 배포 후 오류 0 확인, 그 다음 단계로.
3. 지우기 전에 사장님이 **화면에서 쓰는지**는 그 화면의 접근 기록(nginx 로그)으로 확인한다. 「내가 안 쓰는 것 같다」로 지우지 않는다.

## 1등급 — 지금 지워도 되는 것 (부르는 곳 0곳, 오늘 오후)

| 종류 | 대상 | 근거 |
|---|---|---|
| 워커 파일 4 | `auto_add_margin_worker.py`(376줄, Fix 340 이 잡 제거) · `pending_hc_fast_worker.py`(172) · `time_reverse_exit_worker.py`(170) · `realized_pnl_sync_worker.py`(133) | 스케줄 미등록 + import 0곳(테스트 3개만 참조 → 테스트 정리) |
| 고아 모듈 7 | `agents/coding_team/team_lead.py`, `agents/entry_team/stage_trigger_agent.py`, `agents/market_flow_team/daily_pump_dump_scanner.py`, `agents/planning_team/team_lead.py`, `agents/timezone_pattern_team/kst_pivot_recorder.py`, `core/exceptions.py`, `repositories/symbol_repository.py` | import 0곳 |
| 스케줄러 주석 블록 6 | `scheduler_runner.py` :336 :397 :412 :421 :495 :722 | 죽은 코드 |
| 라우트 16 | `/admin/diagnostic/{reserved,today-trades,main-account-readonly,binance-load}` · `/admin/orphan/*`(2, zombie_guardian 확인 뒤) · `/auth/login` · `/chart-patterns/recent` · `/events/by-strategy`(events.py 전체) · `/positions/by-strategy/{id}/latest` · `/reentry-alerts/settings` GET/PUT · `/pattern-learning/refresh` · `/suggestion-profiles/from-strategy/{id}` · `/trade-learning/prediction-outcome/recompute` · `/analysis/strategy/{id}` | 화면·문서·워커 어디서도 안 부름 |
| UI 코드 | `reentry-alerts.js` 설정 모달 코드(HTML 없음) + `reentry_auto_execute_*` 키 4 | 죽은 분기 |
| 잡+워커 | `failure_pattern_analyzer` (출력 읽는 곳 0) | 읽는 곳을 만들거나 끈다 |
| DB 행 2 | `pending_hc_fast_enabled`, `post_liquidation_analysis_v212` | 코드가 안 읽음 |

## 2등급 — 확인 뒤 정리 (며칠 안, 데이터 확인 필요)

| 대상 | 확인할 것 |
|---|---|
| `unified_15m_entry` 잡·워커·카드 절반·`unified_*` 키 4 | 08-23 부터 OFF(17일). 살릴지 지울지 결정 (7건 +72 만 돌았음). 카드 절반이 17일째 빈 채로 떠 있다 |
| `auto_bb_breakdown_worker.py` 2,297줄 | 진입 경로는 08-23 OFF 인데 `_count_used_slots` 등 헬퍼 5개를 11곳이 import → 헬퍼만 빼내고 2,000줄 제거 |
| `scheduled_entry` | 08-27 부터 OFF, 한 번도 안 켬 |
| `surge_peak_ladder`(shadow, 읽는 곳 0) · `bb_mid_line`(DB off) | shadow 기록 소비처 만들거나 끔 |
| 자동 제안 팀 4 잡(`suggestion_daily_predict/cleanup/auto_execute`, `daily_briefing`) | 30일 안 초안 0건이면 「🎯 자동 전략 제안」 카드는 자동매매 기록만 보여주는 상태 |
| `auto_reentry`(60초 구형) vs `realtime_reentry` | 실제로 도는 쪽 확인 후 하나 폐기 |
| 단독 페이지 5 (`perp-terminal.html` 링크 없음 · `bb-*-ranking.html` 3 · `multi-timeframe-ranking.html`) | nginx 14일 접근 기록 |
| `live-pump-dump` 60초 스캔 · `tp-sl-advisor` 2분 스캔 | API weight 소비 — 사장님 사용 여부 |
| 자기점검 워커 15 | 30일 안 RiskEvent 를 낸 것만 유지 |

## 3등급 — 손대지 않음 (실자금)
`execution_service` · `risk_service` · `tp_sl_orchestrator` · `stage_trigger_worker`(+ `stage_entry_signal/timing`, `stage_trim`, `capital_calculator`, `sajangnim_capital`, `position_limit`, 게이트 5종) · `run_workers`(tp_sl) · `reconcile_worker` · `stream_service` · user/mark 스트림 · `keepalive` · `daily_loss_aggregator` + 킬스위치 · `api_backoff` · `distributed_scheduler_guard` · `zombie_guardian` · 지금 거래 중인 진입 워커 9 · 전략 생성/수정 모달(`cm-*.js`, `strategies/*.py`).

## 설정 위생 (코드 정리와 같이)
- 반증된 게이트 둘이 아직 ON: `trend_4h_gate_enabled=1`(09-03 반증), `confluence_gate_enabled=true`(정점 SHORT +0.69/건 → 두 게이트 아래서 0승/26) — **사장님 결정** 사항으로 표시. 자동 재개 전에 정리.
- 캡 키 `sajangnim_top_short_daily_limit` 가 14일에 9번 바뀜(20→0→20→40→30→40→50→10→0→1). 09-07 19:14 사장님의 0 이 19:34 에 1 로 바뀐 주체 미상 → 설정 변경 이력 표(누가·언제·무엇) 신설이 필요하다(`updated_at` 은 raw SQL 갱신을 못 잡음).
- 코드 키 ~91개가 DB 행 없이 기본값으로 돌고, 비활성 코드만 읽는 DB 키 13개 → 설정 화면에 「살아 있는 키만」 보이게.

## 오늘 오후 실행 순서
1. 1등급 파일·라우트·주석 제거 → 라우트 목록 테스트 2개 갱신 → 전체 테스트 → 커밋.
2. VPS 배포(사장님) → 오류 0 확인 → 화면 3페이지 스모크.
3. 2등급 확인 쿼리(초안 제안 건수·nginx 접근·RiskEvent 30일)를 읽기 전용으로 돌려 표로 보고 → 사장님 결정 → 다음 단계.

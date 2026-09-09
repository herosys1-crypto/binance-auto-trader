# A4 — Screen / API / Worker / Settings inventory for cleanup (2026-09-09, read-only)

Repo: `.claude/worktrees/infallible-euler-6dc297` @ `0d174bf` (main). Data: `history_dump.json` (64 settings rows = **current** values, not a history), `history_enriched.json` (1,518 strategies). Method: regex/AST-free scans; scripts + JSON in this directory (`extract.py`, `routes.json`, `js_usages.json`, `jobs.json`, `jobs_commented.json`, `worker_analysis.json`, `redis_keys.json`, `settings_audit.json`, `setting_keys_code.json`, `orphan_modules.json`).

---

## (a) UI inventory

### a-1. Navigation model
- `page-router.js` knows exactly **3 hash pages**: `#dashboard`, `#ranking`, `#health` (`navigateTo()` whitelist). Everything else is a card, a modal, or a **standalone HTML page** opened by inline functions in `index.html` (`openPumpRanking / openBBReversal / openMultiTimeframe / openRealtimeMonitor / openLearningInsights / openBBMiddleRanking`, lines 2843–2911).
- `index.html` = 3,321 lines; 3 inline `<script>` blocks (475 lines) still hold `loadLiveStatus` (10 s poll), `openLiveDetailModal`, `toggleV219Card`, and the 6 page-openers.
- All **43** `js/*.js` modules are loaded by `<script>` tags (lines 2913–2959); none is unreferenced as a file.

### a-2. Standalone HTML pages (10 files)
| file | purpose | API | reachable from index? |
|---|---|---|---|
| `index.html` | login + dashboard/ranking/health | see cards | root (`/`, `/admin-ui`) |
| `pump-ranking.html` | 15m/24h pump ranking list | `GET /symbols/ranking` | yes (`openPumpRanking`) |
| `bb-reversal-ranking.html` | 4H BB reversal scan | `GET /bb-middle-scan/reversal` | yes |
| `bb-breakdown-ranking.html` | 4H BB breakdown scan | `GET /bb-middle-scan/breakdown` | yes |
| `bb-middle-ranking.html` | BB middle ±5% scan | `GET /bb-middle-scan/scan` | yes (`openBBMiddleRanking`) |
| `multi-timeframe-ranking.html` | MTF scan | `GET /multi-timeframe-scan/scan` | yes |
| `realtime-monitor.html` | v199 watchlist + orchestra status | `GET /realtime-monitor/dashboard`, `GET /orchestra/status` | yes |
| `learning-insights.html` | v187 pattern insights page | `GET /pattern-learning/insights` | yes |
| `analysis.html` | symbol detail analysis | `GET /analysis/symbol/{symbol}` | only from the 3 ranking pages |
| `perp-terminal.html` | futures terminal (2,600+ lines, `/terminal/*`, `/market/*`, `/orders`, `/positions/external`) | 6 terminal routes + market | **NO link from index.html or any js** — direct URL only (`docs/PERP_TERMINAL_2026-09-03.md`). It also calls a route that does not exist: `GET /exchange-accounts/{id}/binance-user-trades` (perp-terminal.html:2005, 404 handled with a fallback message). |

### a-3. Dashboard cards / panels (`page-dashboard`, index.html 984–1786) with polling and data source
| id (line) | title | loader / interval | API | producer of the data | status |
|---|---|---|---|---|---|
| card-system / card-balance / card-active / card-pnl / card-templates (995–1055) | 5 metric tiles | `refreshAll` (dashboard-refresh.js) | `/admin/system-health`, `/exchange-accounts/{id}/balance`, `/admin/stats`, `/admin/recent-activity` | live | OK |
| section-syshealth (1069) | 시스템 상태 grid | same | `/admin/system-health` | live (Redis health keys) | OK |
| live-status-card (1094) | 📊 지금 운영 상태 | inline `loadLiveStatus` **every 10 s** (3 calls) | `/strategies?limit=200`, `/strategy-suggestions/recent-auto?hours=24`, `/strategy-suggestions/auto-bb-limit` | live | **duplicate of section-strategies fetch** (strategies-list.js polls `/strategies` too) |
| unified-15m-monitoring-card (1108) | 🎯 v219 정점 SHORT / 저점 LONG 모니터링 & 세팅 | `loadUnified15mMonitoring` 30 s, `loadV219Monitoring` 30 s, `loadV219Settings`, `loadOBVStatus` 60 s, `loadAutoBBLimit` 60 s | `/strategy-suggestions/unified-15m/monitoring`, `/v219-monitoring`, `/sajangnim-settings`, `/obv-settings`, `/auto-bb-limit` | `unified_15m:monitoring` Redis key is written **only after** the `unified_entry_enabled` check (unified_15m_entry_worker.py:164 returns before the write at :597); DB has `unified_entry_enabled=0` since **2026-08-23** → the "unified" half has had no data for 17 days. `auto:unified_15m_entry` family = 7 trades, all on 2026-08-23. v219 half reads `pump_top:*`/`sajangnim:*` keys from live workers. `obv-settings` shows the 11 `auto_obv_*` keys that configure the **unscheduled** `auto_bb_breakdown_worker`. | **stale/partly dead** |
| live-pump-dump-card (1304) | 🚀 급등락 실시간 진입 | `scanLivePumpDump` **every 60 s** (DOMContentLoaded) | `GET /live-pump-dump/scan` (server-side market scan, 253-line router), `/analysis/symbol/{s}` | on-demand scan, no worker | heavy API load, no persistence |
| strategy-suggestions-card (1398) | 🎯 자동 전략 제안 | `loadStrategySuggestions` 30 s, `loadRecentAutoOutcomes` 30 s | `/strategy-suggestions`, `/recent-auto`, `/settings`, `/suggestion-profiles`, `trigger-now`, `briefing-now`, `dismiss-low-confidence`, `auto-bb-reset` | `suggestion_daily_predict` cron; dump: **all 968 suggestions are status EXECUTED** (auto records), 0 PENDING visible in dump → draft-suggestion flow output unknown | check |
| learn-analyze-combined-card (1434) → learning-insights-card (1444) | 🧠 학습 인사이트 | 5 min | `/trade-learning/insights`, `learning-cycle/run-now` | `learning_agent_insights` setting updated 2026-09-08 | live |
| prediction-stats-card (1468) | 🎓 예측 학습 통계 | 5 min | `/trade-learning/prediction-stats`, `prediction-outcome/run-now` | `prediction_outcome` job (1 h) → `suggestion_outcomes` table (row count unknown) | check |
| symbol-analyzer-card (1493) | 🔎 심볼 분석기 | 60 s | `/strategies`, `/suggestion-profiles`, `/analysis/symbol/{s}` | on demand | OK |
| tp-sl-advisor-card (1528) | 🎯 TP/SL 조정 제안 | **every 2 min** | `/trade-learning/tp-sl-advisor/scan`, `/trade-learning/summary` | on-demand scan | check usefulness |
| pump-bb-alerts-card (1557, hidden until data) | 🚨 급등+BB중단 알람 | 30 s | `/pump-bb-alerts`, `DELETE /pump-bb-alerts/{k}` | `pump_bb_watcher` job (10 min) → Redis `pump_bb_alerts:v1` | live; card text itself says "관찰용 (68% 관통)" |
| reentry-alerts-card (1576, hidden until data) | 🎯 재진입 알람 | 15 s | `/reentry-alerts`, `DELETE` | `reentry_alert` job (2 min) → Redis `reentry_alerts:v1` | live. **Settings modal is dead**: reentry-alerts.js references `reentry-settings`/`closeReentrySettingsModal` (3×) but index.html has 0 matching elements; routes `GET/PUT /reentry-alerts/settings` and keys `reentry_auto_execute_*` (4) have no UI |
| section-stats (1591) | 📊 운영 통계 | refreshAll | `/admin/stats`, `/admin/stats/breakdown`, `/admin/notifications-by-title` (stats-modals.js) | live | OK |
| section-favorites-sidebar (1670) | ⭐ 즐겨찾기 템플릿 | DOMContentLoaded | `/admin/strategy-templates/favorites`, `toggle-favorite` | live | OK |
| section-strategies (1685) | 🎯 전략 인스턴스 (main list, 1,420-line module) | `refreshStrategies` interval (strategies-list.js:1283) | `/strategies`, `/strategies/block-reasons`, `/reentry-alerts/watchlist`, `/exchange-accounts/{id}/binance-positions`, stage-plans, manual-tp, force-sl, tp1-threshold, trailing-retrace, restore | live | core |
| section-templates (2694) | 📋 전략 템플릿 | templates-panel.js | `/admin/strategy-templates`, `cleanup-quick`, `DELETE` | live | OK |
| detail-section (2725) | 📈 차트 + 단계별 진입가 | strategy-detail.js + chart-detail.js | `/strategies/{id}`, `/strategies/{id}/timeline`, `/orders/by-strategy/{id}`, `/market/klines`, `/market/ticker24h` | live | OK |
| external-positions card (js) | 📊 외부 포지션 | refreshAll | `/positions/external` | live | OK |
| page-ranking (1787) | 📈 시장 순위 | `loadRankingPage` | `/symbols/ranking` | live | **duplicates** ranking-modal.js (same endpoint, modal) and `pump-ranking.html` |
| page-health (1858) | 🩺 운영 점검 | `loadHealthDashboard` | `/admin/health/dashboard` | risk_events | OK |
| system banner (936) | zombie-guardian / kill-switch banner | system-banner.js | `/admin/system-status`, `POST /admin/kill-switch/{id}/disable` | live | **do not touch** |

Modals: `accounts-modal` (accounts-modal.js: `/exchange-accounts*`, `/admin/settings/whitelist`, `/admin/settings/force-sl`), `ap-modal` 포지션 추가 (add-position-modal.js), `create-modal` 새 전략 (9 `cm-*` modules: `/strategies/calculate`, `preview-inline`, `POST /strategies`, `/strategies/{id}/start`, `PATCH /strategies/{id}/settings`, `/strategies/{id}/blueprint`), plus JS-built modals: stats/notification, ranking, trade-history (`/orders`), symbol-trading (`/market/klines`, `/market/depth`), manual-TP (strategies-list), open-orders / add-untriggered-stages (strategy-actions: `trigger-next-stage`, `add-margin`, `add-untriggered-stages`, `recalc-untriggered-from-current`, `open-orders`, `force-stop`, `acknowledge-manual-cleanup`), suggestion settings / OBV / sajangnim settings (strategy-suggestions.js, 1,762 lines, 21 endpoints), live-detail (inline), block-detail (helpers.js, `peak-bypass`).

### a-4. UI candidates
- **Unreachable**: `perp-terminal.html` (no link anywhere); reentry-alerts settings modal (JS only, HTML gone); `favorite-templates.js` `closeTemplateFavoritePicker/_renderFavoriteCard` and `strategies-list.js` manual-TP modal helpers show as unreferenced by other files but are used internally (leave).
- **Duplicated**: ranking-modal.js ↔ ranking-page.js ↔ pump-ranking.html (3 renderers of `/symbols/ranking`); live-status-card ↔ section-strategies (two independent `/strategies` polls, 10 s + list interval); learning-insights **card** (`/trade-learning/insights`) ↔ learning-insights **page** (`/pattern-learning/insights`) — same title, different producers; symbol-trading-modal ↔ chart-detail (both kline charts); the 4-card "학습 & 분석 통합" block ↔ realtime-monitor.html/learning-insights.html.
- **Data that no longer updates**: unified-15m half of `unified-15m-monitoring-card` (worker OFF since 08-23); OBV-settings sub-panel (configures unscheduled worker); `chart-patterns` has API but **no screen at all**; `failure_pattern_analyzer` output has **no reader at all** (Redis `failure_analyzer:*`, 0 consumers); `bb_mid_line:signal:*` and `surge_ladder:shadow:*` shadow signals have 0 readers (invisible shadow modes).
- **Polling budget on one dashboard tab** (measured from `setInterval` calls): 10 s ×3 calls, 15 s ×1, 30 s ×6, 60 s ×4 (incl. a full market scan), 120 s ×1, 300 s ×2 → ≈ 1 request/second baseline plus the strategies list.

---

## (b) API inventory

26 routers included in `app/api/router.py`, **152 routes** in 32 files (`routes.json`). Route counts: strategy_suggestions 18, admin/monitoring 15, strategies/control 11, admin/operations 10, trade_learning 9, strategies/lifecycle 8, exchange_accounts 7, strategies/crud 7, admin/templates 6, terminal 6, chart_learning 5, reentry_alerts 5, market 4, paper_trading 4, suggestion_profiles 4, symbols 4, bb_middle_scan 3, chart_patterns 3, admin/export 2, admin/system 2, analysis 2, auth 2, orders 2, pattern_learning 2, positions 2, pump_bb_alerts 2, strategies/calculate 2, events 1, live_pump_dump 1, multi_timeframe_scan 1, orchestra_status 1, realtime_monitor 1. Plus `main.py`: `/`, `/admin-ui`, `/health`.

Static callers matched by literal path + method (`js_usages.json`, 199 literals). **113 routes have a UI caller; 39 have none** (after confirming `/admin/export/{kind}` via admin-shortcuts.js:21, `/strategies/{id}/peak-bypass` via helpers.js:421, `/strategies/{id}/timeline` via strategy-detail.js:20 are string-concatenated calls).

### b-1. No UI caller — INTERNAL / ADMIN (referenced from RUNBOOK, docs, memory, workers, tests) — keep, but mark as ops-only
| route | evidence |
|---|---|
| `POST /admin/kill-switch/{id}/enable` | RUNBOOK.md, integration test, DEVELOPMENT_SPEC (UI only has *disable*) |
| `GET /admin/diagnostic/api-ban`, `POST …/api-ban/reset` | memory ip_ban_spiral (2026-08-26 recovery procedure) |
| `GET /admin/diagnostic/strategy/{id}`, `…/strategy-history/{id}` | `trade_anomaly_monitor.py` prints these URLs in alerts |
| `GET /admin/diagnostic/auto-entry-status` | `stage_trigger_worker.py` message |
| `GET /admin/pyramid-status` | memory 2026-09-01 |
| `POST /admin/symbol-sync` | test_admin_module_split |
| `GET /admin/export/strategies|orders` | **called** (admin-shortcuts.js) — not dead |
| `GET /chart-learning/{status,report,report.md,trades,trades.md}` (5) | docs/learning DAY_01/02, curriculum (curl workflow) |
| `GET /paper-trading/{status,report,report.md,trades}` (4) | docs/spec/PAPER_TRADING_LEARNING_2026-09-08 |
| `GET /chart-patterns/summary`, `POST /chart-patterns/scan-now` | handoff docs; `chart_patterns` table (memory 09-03: 0 rows, misfire fixed by Fix 337 — current count unknown) |
| `GET /trade-learning/setup-stats`, `GET /trade-learning/records` | learning_sync_worker + strategy specs / memory |
| `GET /terminal/positions` | PERP_TERMINAL doc |
| `POST /strategy-suggestions/{id}/execute` | manual execution of a draft; `auto_manual_executor.py` calls the class method directly, UI has no button |

### b-2. No caller anywhere outside `app/api` + tests — DEAD candidates (16)
`GET /admin/diagnostic/reserved` (monitoring.py:881), `GET /admin/diagnostic/today-trades` (:1142), `GET /admin/diagnostic/main-account-readonly` (:1388), `GET /admin/diagnostic/binance-load` (:1533), `GET /admin/orphan/{id}` (operations.py:320), `POST /admin/orphan/{id}/{symbol}/{side}/ack` (:388), `POST /auth/login` (auth.py:12; UI uses `/auth/token`), `GET /chart-patterns/recent` (chart_patterns.py:95), `GET /events/by-strategy/{id}` (events.py:13 — whole router), `GET /positions/by-strategy/{id}/latest` (positions.py:22), `GET+PUT /reentry-alerts/settings` (reentry_alerts.py:146/166), `POST /pattern-learning/refresh` (:25), `GET /suggestion-profiles/from-strategy/{id}` (:251), `POST /trade-learning/prediction-outcome/recompute` (:153), `GET /analysis/strategy/{id}` (analysis.py:557).
Caveat: `tests/unit/test_admin_module_split.py` and `test_strategies_module_split.py` pin route lists — update them when removing. `orphan/*` overlaps zombie-guardian (`orphan_ack:*` Redis key read by `zombie_guardian.py`) — verify before deleting the ack route.

### b-3. UI → missing route
`perp-terminal.html:2005` `GET /exchange-accounts/{id}/binance-user-trades` → 404 (handled). Comments in the same file record two more removed routes (`/market/open-interest`, `…/binance-open-orders`).

---

## (c) Scheduler jobs (`app/workers/scheduler_runner.py`, BlockingScheduler `timezone="Asia/Seoul"`, `misfire_grace_time=300`)

**64 `add_job` statements** (`jobs.json`) — 63 unconditional + `heartbeat` (registered only if `settings.heartbeat_interval_hours` > 0; default `None` → not registered) — `daily_report` conditional on `daily_report_enabled` (default True → registered). **6 commented-out** (`jobs_commented.json`): `auto_bb_breakdown` (:336), `pending_hc_fast` (:397), old `pump_top_detector` (:412), old `auto_short_at_top` (:421), `auto_add_margin` (:495, Fix 340 폐지), `time_reverse_exit` (:722).

| job id | trigger | lock TTL | module.entry | output → consumer | flag |
|---|---|---|---|---|---|
| tp_sl | 15 s | 12 | run_workers.run_tp_sl_once → tp_sl_orchestrator | orders / positions | **REAL MONEY** |
| stage_trigger | 15 s | 12 | stage_trigger_worker | orders (stage 2..N) | **REAL MONEY** |
| position_reconcile | 2 min | 110 | reconcile_worker | Position, RiskEvent, Telegram | **REAL MONEY** |
| listenkey_keepalive | 30 min | 120 | keepalive_worker | StreamSession | stream infra |
| daily_loss_check | 1 min | 50 | daily_loss_aggregator | kill switch | **REAL MONEY** |
| auto_reentry | 60 s | 50 | auto_reentry_worker (222 L, legacy v7 reentry) | orders | real money; overlaps realtime_reentry (verify which path fires — memory 09-01: reentry via realtime_reentry) |
| realtime_reentry | 30 s | 25 | realtime_reentry_worker (1,807 L) | orders, `suggestion_type="bb4h_auto_entry"` (:1733), Redis `reentry:watchlist` (0 readers) | **REAL MONEY** — produces the `auto:bb4h_auto_entry` family (179 trades, −1,237.5) together with pyramiding |
| success_pyramiding | 30 s | 25 | success_pyramiding_worker (1,063 L) | orders, `suggestion_type="bb4h_auto_entry"` (:1002), Redis pyramid_* | **REAL MONEY**; keys `sajangnim_pyramid_trigger_roi=5` (DB), `pyramid_*` 8 keys default |
| auto_short_at_top | 30 s | 25 | auto_short_at_top_worker | orders (`sajangnim_top_short`, 350 trades +156.4, last 09-06) | real money; consumes `pump_top:alert:*` |
| auto_long_at_bottom | 30 s | 25 | auto_long_at_bottom_worker (1,999 L) | orders (`sajangnim_bottom_long`, 177 trades −1,064.8, last 09-06) | real money; consumes `sajangnim:bottom_long:*` |
| pump_top_detector | 5 min | 240 | pump_top_detector_worker | Redis `pump_top:alert:*`, `pump_top:scanned:*` → auto_short_at_top + v219 monitoring | producer |
| long_bottom_detector | 5 min (+offset) | 240 | long_bottom_detector_worker | Redis `sajangnim:bottom_long:*` → auto_long_at_bottom | producer |
| bb_upper_breakout_short | 300 s | 240 | bb_upper_breakout_short_worker | `pump_top:alert` (+`sajangnim:top_short`) | producer |
| macd_reversal_15m | 180 s | 150 | macd_reversal_15m_worker | `pump_top:alert` / `sajangnim:bottom_long` | producer |
| pump_dump_early_detector | 5 min | 240 | pump_dump_early_detector_worker | `pump_top:alert`, `sajangnim:top_short` | producer |
| unified_15m_entry | 30 s | 25 | unified_15m_entry_worker | orders + Redis `unified_15m:monitoring` | **OFF by DB** `unified_entry_enabled=0` (08-23) and `auto_bb_break_daily_limit=0`; runs every 30 s and returns at :164; monitoring key never written |
| resistance_reversal | 30 s | 25 | resistance_reversal_worker | orders | real money (memory 09-05: Traceback `ExecutionService(db)` #3900 — verify fixed) |
| surge_peak_ladder | 30 s | 25 | surge_peak_ladder_worker | Redis `surge_ladder:shadow:*` (0 readers) | **shadow** (`surge_ladder_mode=shadow`) — output invisible |
| peak_break_reversal | 30 s | 25 | peak_break_reversal_worker | orders, Redis `pbr:*` | real money (Fix 41) |
| ladder_restart | 300 s | 240 | ladder_restart_worker | orders (restart ladder ≤2×) | real money |
| pump_split | 900 s | 780 | pump_split_entry_worker (1,078 L) | orders (`split:pumpsplit` 65 trades −23.9, last 09-08) | real money; `pump_split_enabled=1`, `max_concurrent=1` (09-07) |
| bb_mid_line | 900 s | 780 | bb_mid_line_worker | orders (`split:bb_midline` 83 trades −21.3, 09-01..09-07), Redis `bb_mid_line:signal:*` (0 readers) | DB says `bb_mid_line_mode=off` updated 09-01 **but 83 BB_MIDLINE trades were created 09-01..09-07** → contradiction (value changed by a path that did not bump `updated_at`, or the dump is newer than the last trade); needs live check |
| scheduled_entry | 300 s | 240 | scheduled_entry_worker | orders | **OFF** (`scheduled_entry_enabled=0`) |
| reentry_alert | 2 min | 100 | reentry_alert_watcher | Redis `reentry_alerts:v1` → card | live |
| pump_bb_watcher | 10 min | 540 | pump_bb_middle_watcher | Redis `pump_bb_alerts:v1` → card | live, "관찰용" |
| realtime_watchlist | 15 min | 600 | realtime_watchlist_worker | Redis `v199:realtime_watchlist` → realtime-monitor.html, silent_bug_detector | live |
| suggestion_daily_predict | cron 06:30 (KST, comment says UTC) | 1800 | strategy_suggestion_team.team_lead | StrategySuggestion drafts | dump shows only EXECUTED rows → drafts unknown |
| suggestion_cleanup | 1 h | 300 | team_lead | deletes drafts >24 h | — |
| suggestion_auto_execute | cron 07:00 | 600 | team_lead | orders | **no-op**: `suggestion_auto_execute_enabled=false` |
| daily_briefing | cron 22:30 (comment "KST 07:30 = UTC 22:30" but tz is KST) | 300 | team_lead | Telegram | verify actual fire time |
| learning_sync | 5 min | 240 | learning_sync_worker | trade_learning_records | learning |
| prediction_outcome | 1 h | 900 | prediction_outcome_worker | suggestion_outcomes → prediction-stats card | learning |
| market_obs_snapshot / market_obs_update | 4 h / 1 h | 600/300 | market_observation_worker | market_observations → learning_team memory_agent, reentry_alert_watcher | learning |
| learning_team_cycle | 4 h | 600 | learning_team.team_lead | `learning_agent_insights` setting (updated 09-08) → card | live |
| pattern_learning | 1 h | 300 | pattern_learning_worker | `pattern_learning_insights_v187` (09-09) → learning-insights.html, orchestra status | live |
| failure_pattern_analyzer | 30 min | 1800 | failure_pattern_analyzer_worker | Redis `failure_analyzer:{stats,worst_symbols,danger_patterns}` | **0 consumers** — dead output |
| chart_pattern_scan | 6 h | 1800 | chart_pattern_learning_team.team_lead | chart_patterns table → API only (no UI) | check row count |
| chart_learning_snapshot / outcome | cron 00:05,12:05 / :20 | 1500/3000 | chart_learning_worker | chart_learning_days → `/chart-learning/*` reports | `chart_learning_enabled` (no DB row → code default) |
| paper_trading | cron :01/:16/:31/:46 | 800 | paper_trading_worker | paper_trades → `/paper-trading/*` | Fix 361; `paper_backfill_last_id=300` (09-09) |
| orchestra_health | 5 min | 240 | orchestra_health_worker | RiskEvent / auto-fix | monitoring |
| martingale_gate_validator | 5 min | 240 | martingale_gate_validator_worker | RiskEvent, Telegram | monitoring |
| self_check, stage_calc_audit, silent_bug_detector (1 min), user_intent_validator, edit_mode_validator, spec_audit (1 h), auto_fix_proposer, memory_consolidator (cron 18:00), mainnet_safety (1 h), settings_sync (1 h), setting_preservation (3 min), telegram_retry, tp_miss_detector (2 min), liquidation_risk (1 min) | — | — | 15 "Phase-3 self-audit" workers (v17–v58) | RiskEvent + Telegram → health page | monitoring; several write only dedup Redis keys (`liq_risk:*`, `tp_miss:*`, `spec_audit:*`, `mainnet_safety:*`, `edit_mode_validator:*`, `user_intent_validator:*`, `silent_bug_detector:*`, `stage_calc_audit:*`) with 0 readers |
| symbol_sync_daily (cron 03:00), binance_changelog_monitor (6 h), endpoint_health_monitor (30 min), daily_summary (cron 15:00 "=KST 00:00" comment), daily_report (cron 00:00) | — | — | ops | Telegram | ops |

**Cron timezone caveat**: scheduler tz has been `Asia/Seoul` since the initial commit (6f8689d); comments on `suggestion_daily_predict` ("06:30 UTC"), `daily_briefing` ("UTC 22:30 = KST 07:30"), `memory_consolidator` ("KST 03:00", hour=18), `daily_summary` ("KST 00:00", hour=15) and `chart_learning_snapshot` ("UTC 00:05·12:05") all assume UTC. Real fire times are the literal hours in **KST** unless a `timezone=` is passed (none is). Verify against scheduler logs before relying on "morning briefing".

**Unscheduled worker files** (67 files in `app/workers`): `auto_add_margin_worker` (376 L, 0 importers, `test_auto_add_margin_removed.py` asserts its removal), `pending_hc_fast_worker` (172 L, 0 importers), `realized_pnl_sync_worker` (133 L, 0 importers, never registered), `time_reverse_exit_worker` (170 L, 0 importers) → dead. `auto_bb_breakdown_worker` (2,297 L) is unscheduled but **imported by 11 modules** (slot counting, retry settings, reentry helpers) → library now, refactor-only. `mark_price_stream_consumer`, `run_user_stream`, `binance_user_stream_consumer` = separate compose services (`user-stream`, `mark-price-stream`) — keep.

**Orphan app modules** (imported nowhere, `orphan_modules.json`): `agents/coding_team/team_lead.py` (67 L), `agents/entry_team/stage_trigger_agent.py` (65 L), `agents/market_flow_team/daily_pump_dump_scanner.py` (56 L), `agents/planning_team/team_lead.py` (64 L), `agents/timezone_pattern_team/kst_pivot_recorder.py` (60 L), `core/exceptions.py` (2 L), `repositories/symbol_repository.py` (9 L), `services/current_price_action.py` (66 L, used only by `scripts/study_*`).

---

## (d) Settings (`system_settings`)

- Read paths: `SystemSettingsService.get/get_bool/get_decimal` (1 canonical class) **plus 14 local `_setting(...)` helpers** re-implemented in services/workers (`candle_battle, chart_events, chart_learning, chg24_entry_gate, momentum_phase, multiday_movers, stage_entry_timing, support_score, bb_mid_line_worker, paper_trading_worker, unified_15m_entry_worker ×2, reentry_alerts`) → consolidate.
- DB dump: **64 keys** (current values). Code references (context-filtered literals in files touching SystemSetting): **~150 keys** (`setting_keys_code.json`, heuristic — a few dict-field false positives such as `last_cycle`, `min_confidence`, `stage2_trigger`).

**DB keys that no code reads (dead rows, 2)**: `pending_hc_fast_enabled` (=0, 08-23), `post_liquidation_analysis_v212` (JSON blob, 08-21).

**DB keys read only by unscheduled / disabled code (13)**: `auto_add_margin_usdt` (auto_add_margin_worker only); `auto_bb_breakdown_enabled`, `auto_bb_break_reset_at`; `auto_obv_{enabled,capital_per_stage,daily_limit,leverage,min_confidence,stage2_trigger,stage3_trigger,tp1..tp4}` (11 keys shown by the OBV settings sub-panel; consumers = disabled auto_bb_breakdown entry + reentry_alert_watcher). `unified_15m_1h_pct`, `unified_15m_3h_pct`, `unified_v223_min_score`, `unified_entry_enabled` (worker OFF).

**Code keys with no DB row (defaults in force)** — 91 by heuristic; the ones that change money behaviour: `retry_after_liquidation_enabled` (default **False** in 7 files), `ladder_peak_stall_enabled` (True), `split_peak_stall_enabled` (DB=1), `surge_pullback_long_enabled` (True), `top_short_skip_if_1h_down` (True), `sajangnim_pyramid_enabled`, `pyramid_after_tp_enabled`, `pyramid_indicator_gate_enabled`, `pyramid_cap_loss_enabled`, `pyramid_sides`, `pyramid_min_move_pct`, `pyramid_4h_veto_enabled`, `sajangnim_max_concurrent_positions`, `sajangnim_stage_gap_pct`, `ladder_reserve_untriggered_enabled`, `bb_mid_line_{capital,max_concurrent,cooldown_hours,max_hold_hours,sl_price_pct,top_n}`, `pump_split_{depth_pct,long_min_chg24,long_trend_enabled,persist_bars_long/short,retrace_long/short}`, `stage_trim_*` (4), `stage_wait_for_turn_*` (3), `support_score_*` (3), `multiday_*` (7), `surge_start_*` (5), `entry_*` (6), `adaptive_tp_*` (3), `confluence/trend_4h/long_surge *_exempt` (6), `chart_learning_*` (5), `chart_events_enabled`, `paper_backfill_done`, `allow_duplicate_symbol_strategies`, `excluded_symbols`. Dead-feature keys: `reentry_auto_execute_{enabled,capital,leverage,force_sl_roi}` (settings modal removed from HTML).

Current operator throttles worth knowing (DB): `sajangnim_top_short_daily_limit=1` (09-07, it is the concurrent cap read by position_limit.py), `pump_split_max_concurrent=1` (09-07), `sajangnim_reentry_daily_limit=1`, `sajangnim_reentry_concurrent_slots=10`, `surge_ladder_max_concurrent=5` (shadow anyway), `concurrent_cap_scope=ladder` (09-06).

---

## (e) Cleanup plan

### Tier 1 — SAFE NOW (zero callers; delete + fix the 2 route-list tests)
Workers / modules:
- `backend/app/workers/auto_add_margin_worker.py` (376 L; Fix 340 removed the job; only `tests/test_auto_add_margin_removed.py`, `tests/unit/test_auto_add_margin_per_strategy.py`, `test_capital_authority.py` reference it — adjust tests) + DB key `auto_add_margin_usdt`
- `backend/app/workers/pending_hc_fast_worker.py` (172 L) + DB key `pending_hc_fast_enabled` + commented block scheduler_runner.py:397
- `backend/app/workers/time_reverse_exit_worker.py` (170 L) + commented block :722
- `backend/app/workers/realized_pnl_sync_worker.py` (133 L, never registered)
- orphan agents: `agents/coding_team/team_lead.py`, `agents/entry_team/stage_trigger_agent.py`, `agents/market_flow_team/daily_pump_dump_scanner.py`, `agents/planning_team/team_lead.py`, `agents/timezone_pattern_team/kst_pivot_recorder.py`, `core/exceptions.py`, `repositories/symbol_repository.py`
- scheduler_runner.py: the 6 commented `add_job` blocks (:336, :397, :412, :421, :495, :722)
Routes (16, §b-2): 4 `/admin/diagnostic/{reserved,today-trades,main-account-readonly,binance-load}`, `/admin/orphan/*` (2, verify zombie-guardian first), `/auth/login`, `/chart-patterns/recent`, `/events/by-strategy` (whole `events.py`), `/positions/by-strategy/{id}/latest`, `/reentry-alerts/settings` GET+PUT, `/pattern-learning/refresh`, `/suggestion-profiles/from-strategy/{id}`, `/trade-learning/prediction-outcome/recompute`, `/analysis/strategy/{id}`.
UI: reentry-alerts.js settings-modal code (3 refs, no HTML) + keys `reentry_auto_execute_*`; `failure_pattern_analyzer` job + worker (output has 0 readers) — or add a reader, but do not leave as is.
DB rows: `pending_hc_fast_enabled`, `post_liquidation_analysis_v212`.

### Tier 2 — NEEDS DATA CHECK (unused / stale for N days — confirm on VPS before removing)
- `unified_15m_entry` job + worker + card half + 4 `unified_*` keys — OFF for **17 days** (since 08-23); the 7-trade family +72.4 was the only day it ran. Decide: revive (it was the "single 15m entry" 사장님 asked for on 08-23) or remove. Keep `PumpTopDetector.check_v223_15m_primary` if others use it.
- `auto_bb_breakdown_worker.py` (2,297 L library) + 11 `auto_obv_*` keys + OBV settings sub-panel: entry path disabled since 08-23; the exported helpers (`_count_used_slots`, retry settings, `reentry_count:*`) are still used by orchestra_status/position_limit/realtime_reentry → extract the ~5 helpers, then drop the 2,000 lines.
- `scheduled_entry` job (OFF, `scheduled_entry_enabled=0` since 08-27) — Fix 182 feature never turned on.
- `surge_peak_ladder` (shadow since 09-01, 0 readers of shadow output) and `bb_mid_line` (DB `off` @09-01 vs 83 trades through 09-07 — resolve the contradiction first).
- `suggestion_daily_predict / suggestion_cleanup / suggestion_auto_execute / daily_briefing` (v132 draft-suggestion team): dump shows 0 non-EXECUTED suggestions; `suggestion_auto_execute_enabled=false` → verify whether any draft was created in the last 30 days; if none, the "🎯 자동 전략 제안" card is showing only auto-trade records.
- `auto_reentry` (legacy 60 s worker, 222 L) vs `realtime_reentry` — confirm which one actually fires today (memory 09-01 says realtime_reentry) and retire the other.
- `chart_pattern_scan` + `/chart-patterns/*` (no UI; table was 0 rows on 09-03) — check row count after Fix 337.
- Standalone pages `perp-terminal.html` (unlinked), `bb-middle-ranking.html` / `bb-reversal-ranking.html` / `bb-breakdown-ranking.html` / `multi-timeframe-ranking.html` (`bb_middle_scan.py` 1,186 L + `multi_timeframe_scan.py` 307 L are on-demand full-market scans) — check nginx access logs for hits in the last 14 days.
- `live-pump-dump` 60 s auto-scan and `tp-sl-advisor` 2 min scan (API weight) — check whether 사장님 uses the results.
- 15 Phase-3 self-audit workers: keep the ones whose RiskEvents appeared in the last 30 days (health page), retire the silent ones (RiskEvent counts per event_type are in `risk_events_per_strategy` of the dump; not aggregated here).
- Route-list tests + `CHANGELOG/DEVELOPMENT_SPEC` route tables must be regenerated after Tier 1.

### Tier 3 — DO NOT TOUCH (real-money paths)
`services/execution_service.py`, `services/risk_service.py`, `services/tp_sl_orchestrator.py`, `workers/stage_trigger_worker.py` (+ `stage_entry_signal/timing`, `stage_trim`, `capital_calculator`, `sajangnim_capital`, `position_limit`, gates `confluence_gate / trend_4h_gate / long_surge_gate / chg24_entry_gate / adaptive_tp`), `workers/run_workers.py` (tp_sl), `workers/reconcile_worker.py`, `services/stream_service.py`, `workers/binance_user_stream_consumer.py`, `workers/run_user_stream.py`, `workers/mark_price_stream_consumer.py`, `workers/keepalive_worker.py`, `workers/daily_loss_aggregator.py` + kill-switch routes (`admin/operations.py`), `system-banner.js`, `core/api_backoff.py`, `distributed_scheduler_guard.py`, `zombie_guardian.py`, the entry workers currently trading (`auto_short_at_top`, `auto_long_at_bottom`, `realtime_reentry`, `success_pyramiding`, `pump_split_entry`, `bb_mid_line`, `resistance_reversal`, `peak_break_reversal`, `ladder_restart`) and the create/edit strategy modal (`cm-*.js`, `strategies/*.py`).

---

## Side finding for the A-series (labeling)
`suggestion_type="bb4h_auto_entry"` is written by **realtime_reentry_worker.py:1733** and **success_pyramiding_worker.py:1002**, not only by the disabled `auto_bb_breakdown_worker.py:704`. The `auto:bb4h_auto_entry` family in `history_enriched.json` (179 trades, −1,237.5, 08-19 → 09-07) is therefore mostly martingale re-entries and pyramids after 08-23, not BB-4H breakdown entries.

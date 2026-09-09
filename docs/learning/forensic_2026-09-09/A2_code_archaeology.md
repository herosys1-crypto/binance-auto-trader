# A2 — Code archaeology: what ran during 2026-07-29..08-04 vs HEAD 0d174bf

Repo: `.claude/worktrees/infallible-euler-6dc297` (read-only git). THEN = `6618e46` (2026-07-29, "v129 CRITICAL: 시장 순위 top 50 → top 200"). NOW = `0d174bf` (2026-09-08, Fix 361/362).
Data: `scratchpad/history_enriched.json` (1,518 instances), `history_dump.json` → `settings_history` (64 rows), `git_timeline.txt` (636 commits).
Dumped THEN/NOW copies of the 15 key files are in `forensic/A2/then/` and `forensic/A2/now/`; compact timeline in `forensic/A2/timeline_compact.txt`.

## 0. Which commit was deployed 07-29..08-04

| | hash | date | subject |
|---|---|---|---|
| previous | f272fab | 07-26 | Merge PR #281 (fastapi pin) |
| **THEN (deployed 07-29 → 08-06)** | **6618e46** | **07-29** | v129 market ranking top 200 + up/down 100 union |
| next commit (docs only) | 3a46f2a | 08-06 | docs: OBV_REVERSE spec |
| first code change after | 56b7961 | 08-06 | v130 Phase 1 dashboard button (UI) |
| first *behaviour* change after | 390af4c | 08-07 | v130: SL/Force-SL only after ALL stages entered |
| | c5c0153 | 08-07 | v130 new defaults: leverage 5x + TP 25% + force-SL −10% |
| | ba8f113 / f45e0be | 08-08 | force-SL default −15%; trailing arms at peak ≥20% |
| | 7c63c7e | 08-09 | leverage default back to 2x |

There is **no commit between 07-29 and 08-06**, so (deploy ≈ commit) the whole window 07-29..08-05 ran `6618e46`.

### 0.1 What the data says about that window (manual = `_quick_` one-click entries, day_kst)

| day | n | wins | pnl | lev≥5 | tp1 override (mode) | had adds | FORCE_SL events | MANUAL_TP events | capital median |
|---|---|---|---|---|---|---|---|---|---|
| 07-29 | 9 | 6 | +1,007 | 0 | 50 | 6 | 0 | 28 | 267 |
| 07-30 | 8 | 7 | +1,401 | 0 | 50 | 7 | 0 | 25 | 23 |
| 07-31 | 4 | 3 | +172 | 0 | 25 | 4 | 0 | 2 | 2,109 |
| 08-01 | 15 | 11 | +372 | 0 | None | 11 | 0 | 16 | 0 |
| 08-02 | 4 | 2 | −1,026 | 0 | 30 | 4 | 0 | 15 | 1,055 |
| 08-03 | 9 | 3 | +91 | 0 | 30 | 8 | 0 | 20 | 1,000 |
| 08-04 | 15 | 7 | +1,103 | 0 | None | 12 | 0 | 11 | 1,282 |
| **08-05** | 39 | 8 | **−4,686** | 0 | 35 | 34 | 0 | 8 | **2,010** |
| **08-06** | 5 | 3 | **−4,112** | 0 | 35 | 3 | 0 | 6 | 544 |
| 08-07 | 48 | 13 | +1,958 | **36** | 50 | 14 | **31** | 0 | 1,394 |
| 08-08 | 53 | 27 | −1,992 | 53 | 25 | 14 | 10 | 3 | 1,300 |
| 08-09 | 54 | 19 | −2,690 | 48 | 25 | 20 | 6 | 1 | 1,310 |

- 07-29..08-04 on `6618e46`: 64 trades, 39 wins (61%), **+3,120**. Week 07-27 total: 63 trades / 44 wins / **+4,063**.
- Profile of the 21 trades 07-29..07-31 (+2,580, 16 wins): **all leverage 2**, all `_quick_` templates, `trigger_mode=PRICE_DOWN_PCT`, `current_stage=1` (no stage-2 ever fired — the operator added with 💉 add-position instead: 17/21 had ≥1 add; `ADD_POSITION_TP_RESET` 13, `ADD_POSITION_PRESERVE` 11), `tp1_pct_override` 50 (9) / 25 (5) / None (4) / 100 (3), `force_sl_roi_override` None for all 21 (= inherit global: LONG ON −10%, SHORT OFF), `MANUAL_TP` 15 events, `FORCE_STOP_LOSS_TRIGGERED` 0.
- **08-05 and 08-06 (−8,798) happened on the same code `6618e46`.** Nothing in git changed between the good days and the first big loss days; what changed is visible in the rows: capital median 23–1,282 → 2,010, 34/39 trades with adds on 08-05, TP1 raised to 35%.
- 08-07..08-09 is the v130 burst: leverage-5 default (`c5c0153`) shows up as lev≥5 in 137/223 trades of week 08-03, and `FORCE_STOP_LOSS_TRIGGERED` events appear for the first time (31 on 08-07) — the 5x + force-SL(−10/−15%) combination.
- Week 08-03 total in this dataset: 223 trades / 80 wins / **−10,327** (the brief's −19,170 / 189 trades uses a different cut; unverified here).
- First auto-worker instance: 2026-08-19 19:22 UTC. Auto total in dataset: 717 instances, **−2,118** realized, no positive week (08-17 −216 · 08-24 −890 · 08-31 −755 · 09-07 −257). Split families: −63.5 / +13.2 / +5.1 (≈ −45 in this dataset; brief said −543).

## 1. THEN inventory (6618e46) vs NOW (0d174bf)

### 1.1 Workers / scheduled jobs

| | THEN | NOW |
|---|---|---|
| worker files | 33 | 64 (+31) |
| `add_job(` in scheduler_runner | 27 | 70 |
| **auto-entry workers** | **none** — entry only by operator (`cm-submit.js:186` creates `_quick_` template → `POST /strategies` → `POST /strategies/{id}/start`) | auto_short_at_top, auto_long_at_bottom, long_bottom_detector, bb_upper_breakout_short, macd_reversal_15m, peak_break_reversal, resistance_reversal, pump_top_detector, pump_dump_early_detector, surge_peak_ladder, unified_15m_entry, pump_split_entry, bb_mid_line, scheduled_entry, realtime_reentry, reentry_alert_watcher, pump_bb_middle_watcher, success_pyramiding, ladder_restart, paper_trading, plus learning/observation jobs |
| stage progression | `stage_trigger` every 10 s, **price only** (`then/stage_trigger_worker.py:301` `should_fire = mark >= trigger` for SHORT) | every 15 s; price-only branch kept for `PRICE_DOWN_PCT/PRICE_UP_PCT` templates (`now/stage_trigger_worker.py:1153-1160`, Fix 232) but OBV_REVERSE / retry / split / ladder branches add indicator gates, peak-stall (Fix 260/342), trim-before-stage (Fix 304) |
| re-entry | `auto_reentry` (30 s) only for templates with `reentry_policy='auto'`; `_quick_` templates are `manual_ready` (`cm-submit.js:198`) → after TP/SL auto-close status becomes `REENTRY_READY` (`then/stream_service.py:181-183`) and the operator restarts by hand | `auto_reentry` (60 s) + `realtime_reentry` + `ladder_restart` + `reentry_alert`; capital ladder 10/300/600 (`sajangnim_capital_ladder`) |
| tp_sl loop | 10 s | 15 s |
| margin injection | per-stage `additional_margin_usdt` in `start_stage1` / `stage_trigger` (`then/execution_service.py:184-189`, `then/stage_trigger_worker.py:424-427`) | per-stage path still present (`now/stage_trigger_worker.py:1467-1472`); the separate `auto_add_margin_worker` (added 08-22) was retired by Fix 340 (`scheduler_runner.py:492-496` commented out) |
| guard/monitor jobs | self_check, trade_anomaly, stage_calc_audit, silent_bug_detector, user_intent_validator, edit_mode_validator, spec_audit, auto_fix_proposer, setting_preservation, tp_miss_detector, liquidation_risk, reconcile, daily_loss_check … | same set + orchestra_health, martingale_gate_validator, failure_pattern_analyzer, learning_sync, prediction_outcome, chart_learning_* |

### 1.2 Entry gates

| gate | THEN | NOW |
|---|---|---|
| kill-switch | yes (`then/execution_service.py:171`) | yes |
| ISOLATED margin forced + leverage applied | yes (`:176-177`) | yes |
| wallet 130 % reservation (stage 2+) | yes, `calc_reserved_for_account` (`then/stage_trigger_worker.py:323-357`) | yes (Fix 344 split reservation) |
| −2019 margin cooldown 30 min | yes (`:65`) | yes |
| whitelist | code yes, DB `whitelist_enabled=false` (only settings row that existed) | same |
| 24h-change ranking gate (Fix 310) | — | `execution_service.py:199-228`, key `entry_chg24_gate_enabled` (=1); **`_quick_` templates exempt** (`:205`) |
| support-score gate (Fix 327) | — | `support_score_gate_enabled` (OFF) |
| symbol exclusion BTC/ETH (Fix 303) | — | `_assert_symbol_allowed` (`execution_service.py:1155`), key `excluded_symbols` (`symbol_exclusion.py:52`) |
| indicator gates (OBV, 4H trend, confluence, peak confirm, chg24 direction, blocklist, position slots) | **none** | in auto workers / `stage_entry_signal` (`trend_4h_gate_enabled`, `confluence_gate_enabled`, `entry_window_short_enabled`, `long_surge_gate_enabled`, `top_short_skip_if_1h_down`, `concurrent_cap_scope`, `sajangnim_top_short_daily_limit` …) |
| stage 2+ indicator reversal (Fix 55) | — | `now/stage_trigger_worker.py:189`; skipped for price-mode, split, OBV (`:1160-1164`) |

### 1.3 Exit rules

| rule | THEN (6618e46) | NOW (0d174bf) |
|---|---|---|
| TP levels | template `tp1..tp3` required, UI defaults 10/15/20 % (`cm-collectors.js` `_defaults`), TP4..10 optional, auto-extend +5 % to TP20 (v126, `then/risk_service.py` L154-161 of excerpt) | same table + `TP1_PCT_DEFAULT=15` auto-written as `tp1_pct_override` on every new instance (`strategy_service.py:588`, `risk_constants.py:112`); adaptive TP1 15 %/3 % by |24h| (Fix 299, `adaptive_tp.py:80`, DB `adaptive_tp_enabled=1`) |
| TP qty ratio | 25 % each (`DEFAULT_TP_QTY_RATIO_PCT=25`, `risk_constants.py:79`), TP10 100 % constant unused (v117) | 25 %; Fix 187 full-close when residue < min notional |
| **TP1 override semantics** | v105: `max(override, val)` applied to **every** TP (`then/risk_service.py` excerpt L194-197) | v131 (08-10, `3497d25`): TP1 only (constitution C10) |
| TP1 override at creation | none (`then/strategy_service.py` has no `tp1_pct_override`); operator PATCHed after creation (`TP1_THRESHOLD_UPDATED` 17/21 trades) | 15 auto (`strategy_service.py:588`) |
| trailing | armed after `TP3_DONE_PARTIAL` (`TRAILING_MIN_TP_INDEX=3`), `stage>=1`, **peak ≥ 5 %** (`risk_constants.py:85`), retrace **10** default (`:91`, per-strategy `trailing_retrace_pct`), full close | peak ≥ **20 %** (`risk_constants.py:124`, v173 08-18), retrace **5** (`:132`), TP1-based arming (v131) with Fix 335 removing `peak>=TP1` requirement (`now/risk_service.py:805-829`) |
| force-SL global default | LONG ON −10 %, SHORT OFF (`risk_constants.py:66-69`); DB had **no** force_sl rows → code defaults ruled | code default ROI 5 (`:81`), DB rows since 08-22: `force_sl_long_roi=80`, `force_sl_short_enabled=true`, `force_sl_short_roi=80` |
| force-SL per-strategy | override only if operator PATCHed `/force-sl` (`FORCE_SL_OVERRIDE_UPDATED` 9/21) | every new instance gets `force_sl_enabled_override=True`, `force_sl_roi_override=25` (Fix 362, `strategy_service.py:589-590`; v166 08-17 had 5) |
| **force-SL stage gate** | **none — fires at any stage** (`then/risk_service.py:213-260`, docstring "단계 게이트 없음") | v130 gate (`390af4c`, 08-07): no force-SL while stages remain (`now/risk_service.py:434-511`, constitution C13) with exemptions `_stage_gate_exempt` (`:192-248`): retry-mode, split, stage_ladder, trim ON, or **any explicit `force_sl_roi_override`** (Fix 322) — so post-Fix 362 new instances are exempt again |
| force-SL execution | cancel open orders + **full** market close → `STOPPING`, no re-entry (`then/tp_sl_orchestrator.py:503-526`) | **partial stop** keeping ≈10 USDT margin when `stage_trim_before_next_enabled` (Fix 304/318/319/326, `now/tp_sl_orchestrator.py:623-720`, `stage_trim.py:65,112`; DB =1) and next stage exists; pyramid counter reset (Fix 338) |
| normal SL | `stop_loss_percent_of_capital` UI default 90 (`then/index.html:1771`), only after all stages | code default 50 (`risk_constants.py:59`), Fix 321 exemptions |
| crisis mode | disabled (sentinel −100 sent by UI) | same |
| time-based forced exit | none | `time_reverse_exit` worker exists but explicitly OFF (Fix 198, `scheduler_runner.py:718-726` commented) |

### 1.4 Add-position modes

| | THEN | NOW |
|---|---|---|
| `POST /strategies/{id}/add-position` | `mode=preserve|reset` (헌법 51), MARKET/LIMIT, amount USDT (`then/execution_service.py:1106-1131`, `lifecycle.py:108`) | same endpoint/modes (`lifecycle.py:108`, `execution_service.py:1387-1417`) + `cap_loss` param (Fix 269) used only by the pyramiding worker |
| automatic adds | **none** | `success_pyramiding_worker` adds 300 USDT at ROI ≥ `sajangnim_pyramid_trigger_roi` (DB 5, was 2) on any active strategy incl. manual `DYNAMIC_*` (DAY_02 §9: 47 manual adds in 7 days); switch `sajangnim_pyramid_enabled` default ON (`success_pyramiding_worker.py:484`); Fix 348 conditions (`pyramid_min_move_pct`, `pyramid_sides=SHORT`, hist accel) |
| `POST /manual-tp` | yes | yes |
| `/add-margin` | yes | yes |

### 1.5 Settings keys

- THEN DB: **1 row** (`whitelist_enabled=false`, 06-23). THEN code keys: `whitelist_enabled`, `force_sl_long_enabled/roi`, `force_sl_short_enabled/roi` (`then/system_settings_service.py:98-119`). Everything else was a constant or template column.
- NOW DB: 64 rows, all written ≥ 08-11. Key operational ones and their current values: `force_sl_long_roi=80`, `force_sl_short_enabled=true`, `force_sl_short_roi=80` (08-22); `auto_add_margin_usdt=300`; `sajangnim_capital_ladder=10,300,600`; `sajangnim_max_stage=3`; `sajangnim_pyramid_capital=300`; `sajangnim_pyramid_trigger_roi=5`; `pump_split_capitals=100,200,500`, `pump_split_steps=3,5,7`, `pump_split_sl_roi=10`, `pump_split_enabled=1`, `pump_split_max_concurrent=1`; `force_sl_unlock_unreachable_stage=true`; `confluence_gate_enabled=true`; `entry_window_short_enabled=true`; `trend_4h_gate_enabled=1`; `long_surge_gate_enabled=1`; `adaptive_tp_enabled=1`; `stage_trim_before_next_enabled=1`; `stage_wait_for_turn_enabled=1`; `entry_chg24_gate_enabled=1`; `sajangnim_ladder_stages_enabled=1`; `split_peak_stall_enabled=1`; `concurrent_cap_scope=ladder`; `surge_ladder_mode=shadow`; `bb_mid_line_mode=off`; `scheduled_entry_enabled=0`; `unified_entry_enabled=0`; `auto_bb_breakdown_enabled=0`; `auto_bb_break_daily_limit=0`; `sajangnim_top_short_daily_limit=1`; `sajangnim_reentry_daily_limit=1`; `auto_obv_enabled=1`.

### 1.6 Screens

- THEN: one page `index.html` + 35 JS modules (dashboard, strategies-list, strategy-detail, chart-detail, ranking, symbol-trading-modal, add-position-modal, templates-panel, health-page …).
- NOW: + 9 HTML pages (analysis, bb-breakdown/middle/reversal-ranking, learning-insights, multi-timeframe-ranking, perp-terminal, pump-ranking, realtime-monitor) + 12 JS modules (strategy-suggestions, reentry-alerts, pump-bb-alerts, live-pump-dump-alerts, learning-insights, prediction-stats, symbol-analyzer, tp-sl-advisor …) + 16 new API modules.

## 2. Dated table of major logic changes since 6618e46 (with later verdicts recorded in repo docs/memory)

| date | Fix / version | what changed | later verdict (source) |
|---|---|---|---|
| 08-06..08-09 | v130 | OBV_REVERSE strategy mode (alembic 0022), **force-SL only after all stages** (`390af4c`), new defaults lev 5x/TP 25 %/force-SL −10 % → −15 %, MARKET entry when no start price, trailing peak ≥20 % | leverage 5x reverted to 2x 08-09/08-11 (memory `defaults/leverage_2x.md`); stage gate later found to block the "−5 % then next stage" model → Fix 177 (08-27) / Fix 235 (08-31 deadlock) / Fix 321-322 (09-03) exemptions |
| 08-09..08-11 | v131/v132 | post-liquidation auto re-entry (alembic 0023/0024), TP1 override = TP1 only, martingale ×1.5, strategy-suggestion agents | re-entry found structurally impossible 3× → Fix 103-105 (08-26); daily counter frozen 8.7 days → Fix 262 (09-01, 9 days 0 re-entries) |
| 08-13..08-14 | v133..v147 | user-stream auto-recover, learning system, 7 strategy analyzers, 15m pump/dump popup, TP1 15 % confirmed | learning system had 3 bugs (0 records since v134) fixed in v147 |
| 08-16..08-21 | v149..v207 | first auto workers (4H top/bottom, BB reversal, MTA, insight-based entry), trailing peak 5→20 (v173), force-SL default −15→−5 (v166), blocklists, danger-hour filter (v197, removed 08-22), orchestra | v208–v216 rolled back 08-21 (`31697f1`) after duplicate function def killed auto-trading (memory v211 incident) |
| 08-21..08-23 | v218..v224, Fix 1-38 | OBV auto entry, martingale 300/600/1800 (v219), auto add-margin worker (Fix 18), MARKET forced for auto entries, unified 15m worker made the only auto entry (v224), old 4 workers disabled, SL forced −80 % for new auto (v225) | auto add-margin retired by Fix 340 (09-04); unified worker OFF in DB (`unified_entry_enabled=0`) |
| 08-24..08-25 | Fix 40-99 | smart martingale re-entry, bottom-LONG mirror system, 3 workers SL −5 %, success_pyramiding (max 3→2), OBV absolute gate, bidirectional blocklist, MACD 15m worker, UI CSS system | pyramiding later measured harmful (see 09-05/09-07) |
| 08-26 | Fix 103-105 | re-entry silent OFF / mark_price missing / SHORT mis-entry ×3 root causes | "deployed but never worked" (memory reentry_structural_failure) |
| 08-26 | Fix 107-112 | stop switch `0`→20 bug, UI 422 Content-Type, concurrent-cap 20, peak check on 15m | confirmed broken before fix (memory stop_switch_broken) |
| 08-26 | Fix 113-114 | stage gate order reversed; 24h absolute filter replaced by peak confirm | root causes of "stage entry never happens" |
| 08-26 | Fix 115-127 | IP-ban spiral, weight governor, klines cache | ban had been self-extended by the guard (memory ip_ban_spiral) |
| 08-26 | Fix 133-145 | capital ladder 10/300/600; six features found silently failing; Fix 136 "1단계 강제" killed martingale, Fix 137 chose "close then replace" | win-rate 3.7 % root cause = silent failures (memory capital_ladder_and_silent_failures) |
| 08-27 | Fix 173-187 | OBV stage entry via live logic, −5 % stop never firing (v130 gate) + ladder restart, BB split strategy (100/200/300 → −3/−5/−7 %, SL −10 %, TP1 15→5 %), **TP1 option completely dead** (Fix 183), TP10→TP20, pyramiding opened to all strategies | after fix: win-rate 3.7 %→50 %, +402 (memory pyramid_bbsplit_tp20) |
| 08-28 | Fix 188-201 | fail-OFF settings screen, `?v=` hashing, BB split stage-3 dead at −24 %, pyramiding entering empty strategies (Fix 196), learning record gaps, 4h forced exit explicit OFF (Fix 198), block-reason badge | Fix 188 itself created a shadow key and was withdrawn (Fix 191-193) |
| 08-29..08-30 | Fix 202-231 | BB split indicator gates removed (Fix 203) then re-added as "adjustment signal" (Fix 218), TP1 5 %, trigger re-anchored to fill price (Fix 209-211), **pyramiding pushed BB average the wrong way** (Fix 213, 4 trades −252), OBV sign bug (Fix 227) | BB split: COMPLETED 5/5 profitable +330 vs STOPPED 11/12 losing −369 (memory bbsplit_stage3_zero_root_cause) |
| 08-31 | Fix 232-252 | "기본방식 = price only" (Fix 232), last-stage trigger dual storage (Fix 234), force-SL deadlock unlock (Fix 235), capital hardcode removal, surge-pullback LONG first (Fix 244), **confluence gate** (Fix 247, effect size −2.06, 20 blocks in 6 h), SHORT entry window (Fix 248), LONG 100 % blocked regression (Fix 252) | doctrine-vs-code doc: 8 items running opposite to doctrine (`docs/spec/SAJANGNIM_DOCTRINE_VS_CODE_2026-08-31.md`) |
| 09-01 | Fix 253-274 | LONG force-SL 10→5, support-breakdown SHORT (OFF), peak-stall stage entry (Fix 260), re-entry daily counter fix (Fix 262/263), surge peak ladder (Fix 267, shadow), **4H trend gate** (Fix 270), pyramiding fixes (Fix 269/273), "LONG only while surging" (Fix 274) | **4H gate disproved 09-03** (blocked 58.8 % vs passed 52.1 %; pass rate 0 % in surge regime) → made "reference only" Fix 330; DAY_02: cuts 88 % of signals and what remains is worse |
| 09-02 | Fix 275-298 | BB entry "turn at extreme" (SHORT +0.673→+1.800/trade), mid-line as separate strategy, exit-fill price for re-entry (Fix 295-297), double-martingale prevented (Fix 298) | Fix 297 created a risk caught by Fix 298 |
| 09-03 | Fix 299-341 | volatility-linked TP1 15/3 (Fix 299, R=3.00 design vs 1.01 realized), pyramid trigger as setting (Fix 300), re-entry wait panel, BTC/ETH excluded, "10 USDT partial stop" (Fix 304/318/319/324/326/332), OBV auto 0 trades in 30 days (Fix 308 event-name mismatch), chg24 ranking gate (Fix 310/325), stage ladder (Fix 311-315), **stop-loss deferred to last stage** (Fix 315/317/321/322), 4H & confluence demoted to reference (Fix 330/331), auto margin injection abolished (Fix 340) | 09-04 RESET doc: operator "내가 언제 이렇게 로직을 만들었나" — 15 items where values were Claude's not the operator's |
| 09-04 | Fix 342-347 | ladder = peak-stall unified, TP1 restored, 130 % reservation split, indicator regime (15m base / 4H reference), surge-start LONG exemption | — |
| 09-05 | Fix 348-353 | pyramiding only ≥3 % move + hist accel + SHORT only; bottom-LONG alerts OFF; late SHORT skip; chart learning journal | 7-day forensics: manual −4,512 (67 %), **pyramiding 134 strategies −1,729 (no bucket positive)**, bottom LONG 9 %/0 % win (`docs/spec/TRADE_FAILURE_ANALYSIS_2026-09-05.md`) |
| 09-07 | Fix 354-360 | concurrent-cap scope, real-trade × journal join, force-SL event wording, pyramiding after TP (Fix 358), candle battle | DAY_02 §11: 188 pyramiding adds −634.87, win 22.9 %, parents +117.5 → adds ate the profit; 66 % ended in force-SL; re-entry 10 trades +4.92 |
| 09-08 | Fix 361/362 | **live auto entry switched off → paper trading**; new strategy force-SL default −25 % | current state |

## 3. THEN behaviours that are no longer active today, and how to restore each

| # | THEN behaviour (6618e46) | NOW state | restore by | evidence |
|---|---|---|---|---|
| 1 | **No automatic entries, adds, or re-entries** — only operator one-click `_quick_` entries | ~20 auto workers scheduled; since 09-08 mostly gated to 0/1 by settings (paper mode) | **setting**: `sajangnim_top_short_daily_limit=0`, `auto_bb_break_daily_limit=0` (already 0), `sajangnim_pyramid_enabled=0`, `sajangnim_reentry_daily_limit=0`, `pump_split_enabled=0`, `bb_mid_line_mode=off`, `surge_ladder_mode=off`, `unified_entry_enabled=0`, `scheduled_entry_enabled=0`, `auto_obv_enabled=0`, `bottom_long_dip_alerts_enabled=0`; alert producers keep running but only write Redis/DB | `auto_short_at_top_worker.py:73-94,129`, `auto_long_at_bottom_worker.py:216-228,1039-1057,1341`, `success_pyramiding_worker.py:484`, `position_limit.py:49-50,108`, settings_history |
| 2 | **No automatic adds on manual strategies** (adds were the operator's 💉 with preserve/reset) | `success_pyramiding_worker` adds 300 USDT to any active strategy incl. manual `DYNAMIC_*` (47 manual adds in 7 days, DAY_02 §9), measured −1,729 / −635 | **setting** `sajangnim_pyramid_enabled=0` (no restart) | `success_pyramiding_worker.py:47,308-318,484` |
| 3 | **Force-SL fires at any stage, full close, no re-entry** | v130 stage gate + Fix 322 exemption + partial stop (10 USDT) + `LIQUIDATED_WAITING_RETRY`/ladder restart | partial stop → **setting** `stage_trim_before_next_enabled=0` (DB currently 1). Stage gate: exempt automatically for instances with `force_sl_roi_override` (all new ones since Fix 362); for old instances without override the gate stays → **code** (`risk_service.py:434-511`) or set override per strategy via `PATCH /strategies/{id}/force-sl` (`control.py:1073`) | `tp_sl_orchestrator.py:623-720`, `stage_trim.py:65,112`, `risk_service.py:192-248` (exempt), `strategy_service.py:588-590` |
| 4 | Force-SL global defaults LONG ON −10 % / SHORT OFF, inherited by every new instance (no per-instance override at creation) | DB globals 80/80 both ON (08-22 rows) **and** every new instance gets override 25 (Fix 362) so globals are effectively unused for new strategies | globals → **setting** rows `force_sl_long_roi=10`, `force_sl_short_enabled=false` (or delete rows → code defaults LONG 5). Per-instance auto-override → **code**: `strategy_service.py:589-590` (`force_sl_roi_new_default=0` is refused by Fix 362c, `system_settings_service.py:110`) | `risk_constants.py:78-86`, `system_settings_service.py:98-131` |
| 5 | TP1 override at creation = none; template TP1 default 10 % (UI) and operator raised to 50/25 by PATCH | `tp1_pct_override=15` auto on every instance (`TP1_PCT_DEFAULT`) + adaptive TP1 15/3 when `adaptive_tp_enabled` | adaptive → **setting** `adaptive_tp_enabled=0`; auto 15 → **code** `strategy_service.py:588` / `risk_constants.py:112`; the operator's old habit (PATCH `/tp1-threshold`) still works (`control.py:963`) | `adaptive_tp.py:80-83`, `docs/spec/RESET_DOCTRINE_VS_CODE_2026-09-04.md` row 2/8 |
| 6 | TP1 override raised **all** TPs to ≥ override (v105) | TP1 only (v131, C10) | **code** `risk_service.py:669-…` — but v131 was an explicit operator correction (constitution `C10_tp1_override_tp1_only.md`); restoring v105 re-introduces the multi-TP-at-once close | `then/risk_service.py` excerpt L194-197 vs `now/risk_service.py:669` |
| 7 | Trailing: arms at peak ≥5 %, retrace 10 (per-strategy option 5/10/15/20) | peak ≥20 %, retrace 5, TP1-based arming (v131) with Fix 335 | **code** constants `risk_constants.py:124,132`; per-strategy retrace still settable via `PATCH /trailing-retrace` (`control.py:856`); memory (09-01) measured trailing 3 %p current as best — 10 not re-measured | `then/risk_constants.py:85,91` |
| 8 | Normal SL default 90 % of capital | 50 % | **code** `risk_constants.py:59` (template column `stop_loss_percent_of_capital` still per-template) | — |
| 9 | Stage 2+ purely by price for every template | still price-only for `PRICE_DOWN_PCT/PRICE_UP_PCT` (quick) templates; ladder/split/OBV use peak-stall/indicators; Fix 304 trim before stage when ON | already active for quick templates (`stage_trigger_worker.py:1153-1160`); trim → setting `stage_trim_before_next_enabled=0` | Fix 232 (`a288445`) |
| 10 | Any symbol enterable | Fix 303 excludes BTC/ETH family for all entries; Fix 310 chg24 ranking gate (manual `_quick_` exempt) | **setting** `excluded_symbols` (replace list) / `entry_chg24_gate_enabled=0` | `symbol_exclusion.py:52`, `execution_service.py:199-228,1155` |
| 11 | Per-stage additional margin (`additional_margin_usdt`) | still present (`stage_trigger_worker.py:1467-1472`); only the 08-22 auto_add_margin worker was retired (Fix 340) | nothing to restore | `scheduler_runner.py:492-496` |
| 12 | Leverage default 2 | still 2 (`index.html:2153 value="2"`); 5x existed only 08-07..08-11 | nothing to restore | memory `defaults/leverage_2x.md` |
| 13 | Loops: tp_sl 10 s, stage_trigger 10 s, auto_reentry 30 s | 15 s / 15 s / 60 s (API-ban mitigation v171/Fix 115-127) | **code** `scheduler_runner.py:612-617`; not recommended (ban spiral 08-17/08-26) | `then/scheduler_runner.py:157-162` |
| 14 | 4H forced time exit: none | worker exists, explicitly OFF | nothing to restore (`scheduler_runner.py:718-726`) | Fix 198 |

### 3.1 What "the logic of the good period" actually was (for the restore decision)

The good window ran **zero strategy logic beyond**: operator picks symbol/side/start price → LIMIT stage-1 at 2x → operator adds by hand (💉 preserve/reset) and takes profit by hand (`MANUAL_TP` 15 of 21 trades; `TP1_THRESHOLD_UPDATED` 17 of 21) → auto TP ladder 25 % per level with TP1 mostly 50 %/25 % → force-SL LONG −10 % (no stage gate, full close) / SHORT none → trailing at peak ≥5 % after TP3. The code that "stopped working" is not identifiable in git: the first two loss days (08-05/06, −8,798) ran the identical commit; the v130 burst (5x default, force-SL −10/−15 % at any stage, then stage gate) landed 08-07..08-09 and coincides with 137 lev-5 trades and the first `FORCE_STOP_LOSS_TRIGGERED` events.

Restoring the THEN *engine* today is mostly a settings exercise (rows 1, 2, 3-partial, 4-global, 5-adaptive, 10, plus leaving paper mode) with three code-level differences that cannot be undone by settings: per-instance auto override force-SL 25 / TP1 15 at creation (`strategy_service.py:588-590`), trailing 20/5 constants, and the TP1-all-levels v105 semantics (which was deliberately corrected).

# A5 — SETTINGS TIMELINE (system_settings × git × P&L) — 2026-09-09

Sources: `history_dump.json:settings_history` (64 rows = **current** value + last `updated_at` per key — a snapshot, not a change log),
`history_enriched.json` (1,518 instances; P&L keyed by **entry** time `created_at`), `git_timeline.txt` + `git show` on main `0d174bf`,
docs/spec/*.md, docs/learning/*.md, memory notes (repo `docs/handoff/memory-backup-2026-09-03` + user memory dir).
Scripts here: `pnl_windows.py` -> `pnl_windows.json`, `period_split.py`.

## 0. Three caveats about the timestamps (read first)

1. **`updated_at` is bumped only by ORM/API writes** (`SystemSetting.updated_at onupdate=func.now()`, `system_settings_service.py:73`). Raw `psql UPDATE`s do **not** bump it. Proven cases: `scheduled_entry_enabled` (row 08-27 04:30Z, description "2026-09-08 사장님: 가상만 운영 (옛 1)"), `bb_mid_line_mode` (row 09-01 22:24Z, desc "옛 on"), `sajangnim_reentry_daily_limit` (row 09-01 00:06Z, desc "실매매 일 최대 1건"), `sajangnim_pyramid_trigger_roi` (row 09-02 18:19Z = Fix 300's value 2, but DAY_02 §11.1 records a 2->5 UPDATE on 09-07 evening; value now 5). The table dates a row by `updated_at` only where that agrees with git/docs; otherwise the doc date is used and flagged.
2. `settings_history` cannot show intermediate values. Intermediate flips are reconstructed from commit bodies, audit docs and memory notes; each carries its source.
3. 3-day P&L windows are **by entry time** (`created_at`; house rule "진입일로 갈라라"), realized only; groups m=manual / a=auto / s=split. They are context, not causation: the manual account lost −6,913 on 08-26 (3 trades) and −2,372 on 08-28 (2 trades), which dominates every window touching those days.

## 1. Dated table — every operator/system setting change

Cells are n/wins/pnl (USDT) per group.

| # | UTC | KST | key = value | What it switched | 3d before | 3d after | Note / source |
|---|---|---|---|---|---|---|---|
| 1 | 06-23 22:45 | 06-24 07:45 | `whitelist_enabled=false` | symbol whitelist OFF | — (dump starts 07-25) | — | the only row that predates the good period |
| 2 | 08-11 07:04 | 08-11 16:04 | `suggestion_auto_execute_enabled=false`, `_confidence_threshold=0.85`, `_daily_auto_limit=3`, `_auto_dismiss_hours=24` | v132 suggestion system created, auto-exec **OFF** | m 160/83/−2,175 | m 71/30/−542 | 954de0e; never turned on |
| 3 | 08-12 05:08 | 08-12 14:08 | `suggestion_current_default_profile=safe` | default profile (lev 2, 300) | m 86/50/−227 | m 74/33/−79 | |
| 4 | 08-16 23:21 | 08-17 08:21 | `suggestion_default_profiles=[safe…]` | profile JSON | (not scored) | | data row |
| 5 | 08-21 17:14 | 08-22 02:14 | `auto_obv_min_confidence=0.95`, `auto_obv_daily_limit=3` | OBV auto-entry caution | a 17/4/−6 · m 54/18/−914 | a 114/31/−257 · m 32/10/+171 | 0ffcc2e |
| 6 | 08-21 18:41 | 08-22 03:41 | `auto_obv_tp1..4=15/25/35/45`, `auto_obv_capital_per_stage=400`, `auto_obv_leverage=2`, `auto_obv_stage2/3_trigger=−5` | OBV auto params | a 25/4/−6 · m 56/20/−736 | a 106/31/−257 · m 33/8/−47 | b0f89a1 |
| 7 | 08-22 14:24 | 08-22 23:24 | `force_sl_long_roi=80`, `force_sl_short_roi=80`, `force_sl_short_enabled=true`, `auto_add_margin_usdt=300` | global force-SL at **−80% ROI** (effectively off; workers put per-instance override 5), auto margin injection 300 | a 57/11/−224 · m 48/16/−654 | a 175/57/+178 · m 55/13/−21 | Fix 18 3b48415; auto margin **abolished** Fix 340 (09-04) |
| 8 | 08-23 04:31–04:53 | 13:31–13:53 | `unified_15m_3h_pct=7`, `unified_15m_1h_pct=2`, `unified_v223_min_score=1` | v224 "15m pump/dump = the only auto entry" live (`unified_entry_enabled` code default 1) | a 54/10/−163 · m 27/10/−538 | a 238/71/−50 · m 58/14/−6,934 | c633be4, eb5f1ad |
| 9 | 08-23 07:34 | 16:34 | `auto_bb_break_reset_at=…07:34` | daily-counter reset time | | | this stored time later froze "today" for 8.7 days -> reentry 0 for 5 days (Fix 262) |
| 10 | 08-23 08:57 / 09:04 | 17:57 / 18:04 | `unified_entry_enabled=0`, `pending_hc_fast_enabled=0`, `auto_bb_breakdown_enabled=0` (+ per commit: `auto_bb_break_daily_limit=5`, `success_pyramiding_enabled=0`, `sajangnim_max_stage=2`) | Fix 32/33 "v219 정점 SHORT only, stop everything else" | a 61/14/−90 · m 23/9/−607 | a 231/67/−122 · m 58/14/−6,934 | 0da4668. unified_15m lived **4h07m: 7 trades, 4W, +72.4** |
| 11 | 08-26 01:04 | 10:04 | `auto_bb_break_daily_limit=0` | operator's stop switch (Fix 108 body also lists `top_short_daily_limit=0`, `unified=0`, `reentry_daily_limit=0` at 10:04 KST) | a 226/69/−50 · m 56/13/−403 | a 132/29/+251 · m 9/2/−9,320 · s 8/3/0 | **0 was read as 20** -> 137 entries with limit 0 (Fix 108, 10:11 KST). Same key silently switched OFF success_pyramiding (Fix 138) |
| 12 | 08-26 09:21–10:21 | 18:21–19:21 | `sajangnim_capital_ladder=10,300,600`, `sajangnim_default_capital=50`, `sajangnim_max_stage=3` | capital ladder 10/300/600 | a 231/67/−122 · m 58/14/−6,934 | a 130/28/+32 · m 8/1/−3,132 · s 9/3/−30 | Fix 133–145 |
| 13 | 08-27 04:30 | 13:30 | `scheduled_entry_enabled` (row created; =1 then) | scheduled entry ON | a 254/74/+184 · m 39/10/−6,750 | a 123/17/−818 · m 13/1/−4,542 · s 21/11/−27 | Fix 182; **->0 on 09-08 (raw SQL, updated_at untouched)** |
| 14 | 08-29 09:47 | 18:47 | `sajangnim_pyramid_capital=300` | pyramiding lot | a 129/28/+50 · m 9/1/−3,435 · s 9/3/−30 | a 140/14/−1,202 · m 11/0/−1,619 · s 43/27/−50 | |
| 15 | 08-29 13:20 | 22:20 | `pump_split_capitals=100,200,500`, `pump_split_steps=3,5,7` | BB-split sizing | a 98/17/−546 · m 11/1/−4,029 · s 11/4/−32 | a 135/14/−750 · m 9/0/−1,025 · s 43/28/−35 | Fix 204–206 |
| 16 | 08-29 23:57 | 08-30 08:57 | `pump_split_sl_roi=10` | BB-split SL −10 | a 98/15/−480 · m 14/1/−4,542 · s 17/8/−37 | a 118/13/−677 · m 9/0/−578 · s 48/32/+4 | written 6.7h **after** Fix 218 (f6ba6c2, 02:15 KST) whose verbatim was "−15%되면 청산"; DB 10 overrides code fallback 15 |
| 17 | 08-30 22:46 | 08-31 07:46 | `force_sl_unlock_unreachable_stage=true` | Fix 235 deadlock release (code default OFF) | a 111/17/−1,148 · m 11/0/−4,493 · s 25/14/−107 | a 79/4/−268 · m 22/3/−589 · s 48/28/+40 | operator ON after one case (−735) |
| 18 | 08-31 08:53 / 09:11 | 17:53 / 18:11 | `confluence_gate_enabled=true`, `entry_window_short_enabled=true` | Fix 247/248 gates (code default OFF -> operator ON same day) | a 133/18/−1,413 · m 11/0/−2,567 · s 26/14/−98 | a 62/4/+30 · m 24/4/−197 · s 67/30/+70 | see §2 (harmful for peak SHORT) |
| 19 | 08-31 15:19 | 09-01 00:19 | `support_breakdown_short_enabled=0` | Fix 254 (default OFF) | a 146/18/−1,603 · m 11/0/−2,567 | a 68/10/+321 · m 24/4/−197 · s 65/29/+88 | Fix 256: had been wired into the **disabled** unified worker |
| 20 | 08-31 23:30 | 09-01 08:30 | `split_peak_stall_enabled=1` | Fix 260 peak-stall stage entry (default OFF -> ON) | a 151/16/−1,646 · m 13/0/−2,577 · s 39/23/−86 | a 61/12/+412 · m 22/4/−187 · s 58/23/+64 | |
| 21 | 09-01 00:06 | 09:06 | `sajangnim_reentry_daily_limit` (20 then), `sajangnim_reentry_concurrent_slots=10` | Fix 262/263 reentry revival | a 149/15/−1,680 · m 12/0/−2,237 | a 60/13/+413 · m 22/4/−187 · s 58/23/+64 | value **->10** (사장님 "일 10개") **->1 on 09-08** (raw SQL) |
| 22 | 09-01 02:35 | 11:35 | `surge_ladder_mode=shadow` | Fix 267 surge-peak ladder, **never set on** | a 144/15/−1,260 · m 13/0/−2,265 | a 58/13/+166 · m 21/4/−159 · s 58/23/+64 | 3STEP_LADDER doc row 3: "사상의 입구가 닫혀 있다" |
| 23 | 09-01 05:35 | 14:35 | `trend_4h_gate_enabled=1`, `surge_ladder_max_concurrent=5` | Fix 270 4H gate (default OFF -> ON) | a 142/14/−1,245 · m 13/0/−2,265 · s 39/23/−86 | a 65/16/+51 · m 25/4/−176 · s 60/24/+54 | see §2 |
| 24 | 09-01 14:55 | 23:55 | `long_surge_gate_enabled=1` | Fix 274 LONG only if 24h ≥ 15% | a 135/14/−750 · m 7/0/−513 · s 45/30/−13 | a 91/21/−261 · m 25/4/−176 · s 55/19/+66 | Fix 334: blocked LONG reentry 297/304; Fix 347 exempted surge patterns |
| 25 | 09-01 22:24 | 09-02 07:24 | `bb_mid_line_mode=on` | Fix 278 midline family (default shadow -> operator **on**) | a 118/13/−677 · m 9/0/−578 · s 45/30/+3 | a 94/22/−423 · m 25/4/−238 · s 51/15/+48 | family lifetime 83 trades, 28W (33.7%), **−21.3**; **->off 09-08** (raw SQL) |
| 26 | 09-02 17:47 | 09-03 02:47 | `adaptive_tp_enabled=1` | Fix 299 volatility TP1 (default OFF -> ON) | a 82/5/−241 · m 14/0/−868 · s 44/27/+58 | a 112/29/−524 · m 23/6/+41 · s 44/11/−42 | Fix 343 (09-04) removed it from ladders & pump_split ("TP1 복원") |
| 27 | 09-02 18:19 | 03:19 | `sajangnim_pyramid_trigger_roi=2` | Fix 300 (code 5 -> DB 2) | a 82/5/−241 · m 15/1/−588 · s 45/27/+44 | a 112/29/−524 · m 22/5/−239 · s 43/11/−28 | **->5 on 09-07** (DAY_02 §11.1; updated_at untouched) |
| 28 | 09-02 22:33 | 07:33 | `stage_trim_before_next_enabled=1` | Fix 304 partial-SL 10 USDT (default OFF; Claude INSERT) | a 79/4/−268 · m 22/3/−589 · s 48/28/+40 | a 116/31/−548 · m 15/3/−238 · s 42/11/−29 | after ON, stage-2+ entries **0** until Fix 316 (09-03 09:48 KST) |
| 29 | 09-02 23:32 / 23:39 | 08:32 / 08:39 | `auto_obv_enabled=1`, `entry_chg24_gate_enabled=1` | OBV auto ON; 24h-rank 50+50 gate (Fix 310 "당분간") | a 78/4/−283 · m 22/3/−589 | a 113/31/−499 · m 15/3/−238 · s 42/11/−29 | Fix 308 same morning: OBV auto had made **0 entries in 30 days** (event-name mismatch). Since the fix: 3 auto OBV_REVERSE instances −29.05 / +53.08 / −78.02 |
| 30 | 09-03 00:02 | 09:02 | `stage_wait_for_turn_enabled=1` | Fix 311/312 (default OFF -> ON) | a 73/3/−285 | a 114/32/−431 · m 15/3/−238 | |
| 31 | 09-03 07:22 | 16:22 | `sajangnim_ladder_stages_enabled=1` | Fix 316 ladder-mode switch | a 60/2/−188 · m 20/3/−143 · s 66/30/+76 | a 127/38/−408 · m 15/3/−238 · s 22/10/−29 | memory: briefly **0** as emergency block (force-SL lock), then 1 |
| 32 | 09-06 23:18 | 09-07 08:18 | `concurrent_cap_scope=ladder` | Fix 354: cap counts only v219 ladder | a 102/28/−804 · m 11/2/−185 · s 20/10/−34 | a 4/1/−179 · m 2/0/0 · s 24/9/+1 | cap was 10 and "17/10" blocked v219 |
| 33 | 09-07 19:14 | 09-08 04:14 | `sajangnim_top_short_daily_limit=0`, `pump_split_enabled=0` | **operator shutdown** ("실시간 자동은 종료") | a 60/18/−415 · m 7/2/−167 · s 36/14/−72 | | PAPER_TRADING doc L143; not visible in dump (overwritten 20 min later) |
| 34 | 09-07 19:34 | 09-08 04:34 | `sajangnim_top_short_daily_limit=1`, `pump_split_enabled=1`, `pump_split_max_concurrent=1` | re-opened at **1 slot each** (ORM write; author unknown) | | m 2/0/0 · s 1/1/+7 | 1 ≠ OFF: `position_limit.py:167` treats only ≤0 as OFF |
| 35 | 09-08 (time unknown) | 09-08 | `sajangnim_reentry_daily_limit 10->1`, `bb_mid_line_mode on->off`, `scheduled_entry_enabled 1->0` | "가상만 운영" | | | raw SQL (descriptions rewritten, updated_at untouched) |
| 36 | 09-08 22:48 / 09-09 01:48 / 02:19 | | `learning_agent_insights`, `pattern_learning_insights_v187`, `paper_backfill_last_id=300` | data rows | | | not switches |

Weekly context (entry week KST, n/wins/pnl): 07-27 m 63/44/**+4,063** · 08-03 m 223/80/−10,327 · 08-10 m 174/89/+420 · 08-17 a 70/16/−216, m 78/31/−590 · 08-24 a 428/104/−890, m 73/15/**−11,504**, s 31/17/−64 · 08-31 a 214/43/−755, m 37/6/−827, s 91/40/+13 · 09-07 a 5/1/−257, s 26/11/+5.

**The good period (07-27..07-31, manual +4,063 for the week) ran on code with exactly one commit inside the window (v129 6618e46, 07-29: market ranking top 200 + up/down-100 union) and a settings table holding one row (`whitelist_enabled=false`).** No auto-entry worker, gate, cap or ladder existed (first auto instance 08-19, first gate key 08-31). All 63 other switches in the dump were created on or after 08-11.

## 2. Oscillations (same setting flipped ≥2 times) and verdicts

| Setting | Sequence (value @ date, source) | Verdict from docs/memory/data |
|---|---|---|
| **`sajangnim_top_short_daily_limit`** (concurrent cap; 0 = OFF, ≥1 = live) | 20 (08-24 CURRENT_STATE) -> **0** (08-26 ~14:20 KST killswitch note / Fix 108 body) -> read as 20 by bug (Fix 108) -> 20 "동시 보유" (Fix 112) -> screen 20 / actual 40 (Fix 161, 08-26) -> 30 (08-28 complaint "30->10", Fix 188) -> 40 (08-31 선택 B) -> 50 (09-03/09-04 audits) -> 10 (09-06 22:19Z, position_limit.py:102) -> **0** (09-07 19:14Z) -> **1** (09-07 19:34Z) | 9 values in 14 days. Two flips were bugs (Fix 108 0->20; Fix 188's shadow key installed then withdrawn by Fix 191). The 09-07 0->1 re-opened the path the operator had closed 20 min earlier. |
| `unified_entry_enabled` | code default 1 (08-23 04:31Z, v224 "유일한 진입") -> **0** (08-23 08:57Z, Fix 32) -> still 0 | Ran 4h07m: 7 SHORTs, 4W, **+72.4** — best win-rate of any auto klass but n=7. TODAY_REQUESTS_AUDIT L400: "켜지 말 것을 권한다" (worker stale; Fix 254 was wired into it while off — Fix 256). **Inconclusive; not restorable as-is.** |
| Pyramiding (`success_pyramiding_enabled` -> `sajangnim_pyramid_enabled`; `auto_bb_break_daily_limit`) | `success_pyramiding_enabled=0` (08-23 Fix 32) -> accidentally OFF via `auto_bb_break_daily_limit=0` (08-26) -> own key, default ON (Fix 138, 08-26) -> opened to all strategies (Fix 185, 08-27) -> blocked for BB split (Fix 213, 08-30; 4 BB positions −252) -> SHORT only, ≥3% move, 3-bar accel (Fix 348, 09-05) -> after-TP ON (Fix 358, 09-07) -> dead row deleted (09-07) | Trades with adds: Fix185->213 window auto 33 -> **−500**, manual 7 -> −3,484; Fix213->348 auto 129 -> **−1,087**; after Fix 348 auto 16 -> +12 (50%W). TRADE_FAILURE: 134 strategies −1,729, "모든 구간 음수". **ON was harmful until Fix 348.** |
| `sajangnim_pyramid_trigger_roi` | 5 (code) -> **2** (09-03 Fix 300, 사장님 "+2%부터") -> **5** (09-07, DAY_02 §11.1) | 2–5% band = 64% of pyramid losses; Claude's "+182 CV 4/4" argument for 5 was itself corrected (V0 era). |
| `trend_4h_gate_enabled` | OFF (code) -> **1** (09-01 05:35Z Fix 270, measured +183 on 33 trades) -> reference-only for reversal (Fix 330, 09-03) + reentry exempt (Fix 334) -> row still 1 | Fix 330: pass rate 3.3% (1,546 blocked / 52 passed). CHART_EVENT top-reversal "정반대", resistance "반증"; Day-2 (Fix 354): passed −0.67 vs baseline −0.71. **ON was harmful for peak SHORT**: top_short per trade before gates +0.69 (n=268) -> gates ON **−1.63, 0/26 wins** -> demoted −3.97 (n=37) -> after Fix 348–350 +8.46 (n=19). |
| `confluence_gate_enabled` | OFF (code) -> **true** (08-31 08:53Z, operator; Fix 247 effect size −2.06) -> reference-only for reversal (Fix 331, 09-03) -> still true | Fix 331: v219 top SHORT 29.6% / +1.65 per trade before -> 2.9% / +0.62 after. "구조적으로 통과 불가" for peak reversal. |
| `long_surge_gate_enabled` | OFF -> **1** (09-01 14:55Z Fix 274) -> surge-pattern exempt (Fix 347, 09-04, 사장님 "차단 자체가 없어") -> reentry exempt (Fix 334) | Blocked LONG reentry 297/304 attempts in 24h (Fix 334). Bottom-long stayed negative in every period (−5.95 -> −8.42 -> −5.79 -> −4.39 per trade). |
| `bb_mid_line_mode` | shadow (code 09-02) -> **on** (09-02 07:24 KST, operator) -> **off** (09-08) | Backtest +785 / +656 (Fix 278) vs live 83 trades **−21.3** (33.7%W). Off agrees with live data. |
| `pump_split_enabled` | 1 (08-27) -> screen showed OFF while DB 1 (fail-OFF bug, Fix 192 08-28) -> **0** (09-07 19:14Z) -> **1** (09-07 19:34Z) with max_concurrent 1 | pumpsplit family 65 trades, 40W (61.5%), −23.9 total (+95.7 on adds 08-30..09-05). Still live at 1 slot (09-08 12:33Z SOPHUSDT LONG +6.92 entered after the "shutdown"). |
| `sajangnim_reentry_daily_limit` | 0 (08-26 Fix 108 body) -> 20 (frozen counter; 0 real entries for 5–9 days, Fix 262) -> 10 (09-01, 사장님) -> **1** (09-08) | Fix 262/263 revived it; Fix 334 then found 608 attempts / 0 successes in 24h (09-03) because of the 4H / 24h gates above. |
| `stage_trim_before_next_enabled` | OFF (code) -> **1** (09-03 07:33 KST) -> Fix 311 bug (15–30 USDT notional = exception -> stage-2 blocked) -> Fix 316, row still 1 | Self-inflicted ~2h outage of ladder stage 2 (TODAY_REQUESTS_AUDIT L463/798). |
| `sajangnim_ladder_stages_enabled` | ON (code, Fix 316) -> **0** (emergency, force-SL lock; memory 09-03) -> **1** (09-03 07:22Z) | |
| `adaptive_tp_enabled` | OFF -> **1** (09-03 02:47 KST, Fix 299) -> scope cut by Fix 343 (09-04): ladders back to TP1 15%, pump_split back to 5% | 사장님: "빠른 익절은 볼밴 분할전략에서 만든건데… 정말 너 맘대로구나". Kept ON only for single-stage auto_bb. |
| `scheduled_entry_enabled` | 1 (08-27) -> **0** (09-08) | no per-family P&L (scheduled entries are not a separate klass); verdict unknown. |
| `auto_bb_break_daily_limit` | 5 (08-23 Fix 32) -> 0 (08-24) -> 0 (08-26 01:04Z) | OFF for the old 1h BB worker; side effect switched pyramiding off (Fix 138). |
| `auto_add_margin_usdt` | 300 (08-22, Fix 18) -> worker **abolished** Fix 340 (09-04) | 사장님: "증거금 주입은 필요없는 기능". Row is dead. |
| Force SL | global 80/80 (08-22) = effectively off; per-instance override 5 (Fix 51, 08-24) -> new-strategy default **25** (Fix 362, 09-08) | |

### Turned OFF (or never ON) although later analyses found it helpful
- `surge_ladder_mode=shadow` (never on): SAJANGNIM_3STEP_LADDER (09-02) verified the 10/300/600 arithmetic exact, EV +27.98 even at 20% win; the doc's own row 3 says the doctrine's entrance is closed. Live evidence: none (shadow -> no orders). **Helpful on paper, unproven live.**
- `unified_15m_entry` (off after 4 h, +72.4 / 7 trades): inconclusive; audits say do not re-enable the stale worker.
- `bottom_long_dip_alerts_enabled` OFF (Fix 349, 09-05): **correct OFF** — bottom-long 177 trades 26W −1,064.8; per-trade improved after but still negative (−4.39).
- `bb_mid_line_mode=off` (09-08): consistent with live −21.3.

### Turned ON although later analyses found it harmful
- `confluence_gate_enabled=true` (08-31) and `trend_4h_gate_enabled=1` (09-01): both refuted for peak SHORT (Fix 330/331, CHART_EVENT docs, Day-2 −0.67 vs −0.71); top_short went 0/26 while both were hard gates. Both rows are **still 1/true** and still hard-gate the non-reversal auto_bb path.
- `long_surge_gate_enabled=1` (09-01): blocked LONG reentry 297/304 and surge-start LONGs; patched by exemptions rather than turned off.
- Pyramiding opened to all strategies (Fix 185, 08-27): auto adds −500 in 3 days; BB positions −252 (Fix 213).
- `stage_trim_before_next_enabled=1` (09-03) before Fix 316: 0 stage-2 entries for ~2 h.
- `auto_obv_enabled=1` (09-03): ON but inert for 30 days before Fix 308; since the fix 3 auto instances net −54.0.

## 3. Current values of entry-relevant switches (dump 2026-09-09 02:19Z) and live paths

| Switch | Value (DB unless noted) | Effect today |
|---|---|---|
| `sajangnim_top_short_daily_limit` | **1** | v219 ladder families (top SHORT + bottom LONG) may hold **1** concurrent position (0 would be OFF) |
| `concurrent_cap_scope` | ladder | that cap counts only v219 ladder instances |
| `pump_split_enabled` / `pump_split_max_concurrent` | 1 / **1** | BB-split family live, 1 slot |
| `bb_mid_line_mode` | off | midline family dead |
| `scheduled_entry_enabled` | 0 | dead |
| `sajangnim_reentry_daily_limit` / `sajangnim_reentry_concurrent_slots` | 1 / 10 | reentry worker live, max 1 new reentry per day |
| `unified_entry_enabled`, `pending_hc_fast_enabled`, `auto_bb_breakdown_enabled`, `auto_bb_break_daily_limit` | 0 / 0 / 0 / 0 | v224 unified, PENDING_HC, old 1h BB worker: dead (also commented out of scheduler) |
| `auto_obv_enabled` (limit 3, conf 0.95, 400/stage, lev 2, TP 15/25/35/45) | 1 | OBV auto live (3 instances since Fix 308) |
| `surge_ladder_mode` / `surge_ladder_max_concurrent` | shadow / 5 | no orders |
| `suggestion_auto_execute_enabled` | false | no orders; `reentry_auto_execute_enabled` absent -> code default "false" |
| `sajangnim_ladder_stages_enabled`, `ladder_peak_stall_enabled` (code ON), `stage_wait_for_turn_enabled`, `stage_trim_before_next_enabled`, `split_peak_stall_enabled` | 1 / ON / 1 / 1 / 1 | stages 2·3 of open ladders live (peak-stall judged); partial-SL 10 USDT live |
| `sajangnim_capital_ladder` / `sajangnim_default_capital` / `sajangnim_max_stage` | 10,300,600 / 50 / 3 | |
| `entry_chg24_gate_enabled` (`entry_chg24_gate_mode` absent -> rank) | 1 | new entries only from up-50 / down-50 |
| `trend_4h_gate_enabled` / `confluence_gate_enabled` / `entry_window_short_enabled` | 1 / true / true | hard gates on the non-reversal auto_bb path; reference-only for reversal & reentry (Fix 330/331/334) |
| `long_surge_gate_enabled` (`surge_pattern_exempt_enabled` code ON) | 1 | LONG needs 24h ≥ 15% unless SURGE_START/SURGE_PULLBACK |
| `bottom_long_dip_alerts_enabled` (absent) | code OFF | bottom-long LONG only via SURGE_START / SURGE_PULLBACK / MULTIDAY_PULLBACK (`multiday_pullback_long_enabled` code ON, `surge_pullback_long_enabled` code ON) |
| `support_breakdown_short_enabled`, `support_score_gate_enabled` (absent) | 0 / OFF | |
| Pyramiding: `sajangnim_pyramid_enabled` (absent -> ON), `sajangnim_pyramid_trigger_roi`=5, `sajangnim_pyramid_capital`=300, `pyramid_sides` (code SHORT), `pyramid_min_move_pct` (code 3), `pyramid_after_tp_enabled` (code ON), `pyramid_4h_veto_enabled` (code OFF), `pyramid_indicator_gate_enabled` / `pyramid_cap_loss_enabled` (code ON) | | adds on open SHORT positions live |
| Force SL: `force_sl_long_roi`/`force_sl_short_roi`=80, `force_sl_short_enabled`=true, `force_sl_roi_new_default` (absent -> code **25**), `force_sl_unlock_unreachable_stage`=true | | new instances default −25% ROI |
| `adaptive_tp_enabled` | 1 | only single-stage auto_bb (Fix 343) |
| `pump_split_capitals` / `pump_split_steps` / `pump_split_sl_roi` | 100,200,500 / 3,5,7 / 10 | |
| `paper_trading_enabled`, `chart_learning_enabled` (absent) | code ON | read-only, no orders |
| `auto_add_margin_usdt`=300, `whitelist_enabled`=false, `unified_15m_*`, `post_liquidation_analysis_v212`, `pending_hc_fast_enabled` | | dead or data rows (`pending_hc_fast_enabled`, `post_liquidation_analysis_v212` have 0 code readers) |
| Not in DB (env): `MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT`=100 (RESET doc), Kill-switch state | unknown from dump | |

**Entry paths live today (real orders possible):** (1) manual `_quick_` entries (no cap; new-strategy SL default −25%); (2) v219 top-SHORT / bottom-LONG ladder via `auto_short_at_top` / `pump_top_detector` / `auto_long_at_bottom` / `long_bottom_detector` — **1 concurrent position**, LONG only on surge patterns; (3) BB split `pump_split` — 1 slot (confirmed by the 09-08 12:33Z SOPHUSDT entry); (4) realtime reentry — 1 per day; (5) OBV auto (`auto_obv_enabled=1`, 3 per day); (6) stages 2·3 and pyramiding adds on already-open positions. **Dead:** unified_15m, PENDING_HC, old 1h BB breakdown, midline family, scheduled entry, surge ladder (shadow), suggestion auto-exec, auto margin injection, 4h time-exit. The 09-08 "실시간 자동 종료" is therefore **not a full stop**: three auto entry paths remain open at one slot each.

## 4. Restorability note for the parent task
The "good" logic of 07-27..07-31 was not a system logic: it was the operator's manual SHORTs on pumped alts with 1–7 adds, on a codebase with no auto entry, no gates, and one settings row. There is no earlier automated state to revive from the settings history. What can be restored is the *absence* of the gates added 08-31..09-01 (4H, confluence, 24h-rank, LONG-surge), which the project's own 09-03 / 09-05 / 09-07 measurements already found harmful or refuted for the peak-SHORT doctrine — yet two of them (`trend_4h_gate_enabled=1`, `confluence_gate_enabled=true`) are still ON in the DB.

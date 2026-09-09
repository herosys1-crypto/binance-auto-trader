# 매매 전략 한눈에 보기 (2026-09-09)

> 사장님: "우리 매매전략을 요약정리해서 알려줘 간략하게 한눈에 알수있게 해줘 너무 많아서 나도 모르겠어"

## 0. 열 줄 요약

1. 우리 전략은 **세 결정점**으로 돈다: ① 첫 진입 자리 → ② 이기면 추가(최대 2회) → ③ 지면 10 USDT 만 남기고 부분손절 후 재진입.
2. 첫 진입은 **정점 SHORT(v219)** 가 주력이고, 저점 LONG · 볼밴 분할 · 중단선 · 재진입 · 예약 진입이 곁가지다. 지금은 사장님 지시로 **하루 1건**만 살아 있다.
3. 자본은 **10 → 300 → 600 사다리**. 2·3단계는 지정 트리거가(가격 모드) 또는 OBV 신호(OBV 자동 모드)로 들어간다.
4. 정점 SHORT 신호 사슬: 정점 감지 → OBV → 국면 → **confirm_peak(15분 스윙 2회+지표 꺾임 2/3)** → 상승초입 거부 → 1h 늦은 진입 거부 → (캔들 꼬리봉, 기록만) → 동시 상한 → 4H 게이트 → 합의 게이트 → 24h 순위 게이트 → 시장가.
5. 청산: TP1 은 24h 변동 15% 이상이면 15%, 아니면 3% 에서 25% 부분익절 → 트레일링 5%p → 강제손절(옛 인스턴스 −5%, 새 인스턴스 **−25%**).
6. 추가(피라미딩): 수익 ROI 5% 이상 + 유리 이동 3% + 15분 MACD 가속 3봉, SHORT 만, 300 USDT 씩 최대 2회.
7. 학습: 매일 상승50·하락50 일지(3,298 심볼-일), 캔들 꼬리봉 shadow, **가상 매매(15분마다, 9/9 부터)** — 결과는 `/api/v1/chart-learning/report.md`, `/api/v1/paper-trading/report.md`.
8. 실측으로 확인된 것: 저점 반전 LONG 과 과매도 반등 LONG 은 양수, 정점 SHORT 는 이 국면에서 「덜 잃을」 뿐 양수가 아니다. 어떤 정의로도 SHORT 추가는 음수.
9. 켜져 있지만 실측이 반증한 게이트 둘(4H 게이트·합의 게이트)이 아직 ON 이다 — 정리 대상.
10. 상세 표는 아래(코드에서 키·기본값·실값을 전부 대조한 것).

---

# 매매 전략 한눈에 보기 (코드 기준, main 0d174bf · 2026-09-08)

기본값 = 코드(설정 행 없을 때) / **실값** = 운영 DB `system_settings` 덤프(마지막 갱신 2026-09-09). 설정 행이 덤프에 없으면 기본값이 살아 있다.

## 1. 세 결정점 — 어느 워커가 하나

| 결정점 | 구현 | 주기 | 파일 |
|---|---|---|---|
| ① 첫 진입 자리 | 알람 생산(정점/저점 감지) → 소비 워커가 게이트 통과 시 `_create_auto_bb_strategy` → `start_stage1` | 감지 5분 / 진입 30초 | `pump_top_detector_worker.py` → `auto_short_at_top_worker.py`, `long_bottom_detector_worker.py` → `auto_long_at_bottom_worker.py`, 공용 생성 `auto_bb_breakdown_worker.py:1405` |
| ② 이기면 추가 | 피라미딩(ROI +5% & 유리 이동 3% & 15m hist 가속 3봉) 300 USDT 시장가 추가 | 30초 | `success_pyramiding_worker.py`, 판정 `trend_4h_gate.check_pyramid_trend` |
| ③ 지면 부분손절 → 재진입 | 강제손절 도달 → 10 USDT 증거금만 남기고 청산(Fix 319/326) → 사다리 2·3단계(300/600)는 정점-주춤(Fix 260) 자리에 시장가 / 완전 종료 뒤엔 실시간 재진입 | 손절 15초 · 단계 15초 · 재진입 30초 | `tp_sl_orchestrator.py:633`, `stage_trim.py`, `stage_trigger_worker.py:900`, `realtime_reentry_worker.py` |

## 2. 진입 계열과 신호 사슬 (코드에 있는 순서)

**v219 정점 SHORT** (주력): `pump_top_detector`(15m 5지표 ≥3/5, 1h·4h 반대 <3, conf ≥0.85, 상위 50, TTL 30분) → `auto_short_at_top`: 동시 상한(`check_position_slot`) → 활성 심볼 제외 → OBV 게이트(`obv_gate`, SHORT 극값비 0.35) → 양방향 차단(`bidirectional_blocklist`, Fix 71 이후 **항상 빈 집합 = 무효**) → 국면(`pump_dump_regime`, 3일 +30% & 12h −5%) → `confirm_peak`(15m 반복상승 ≥2 + RSI/MACD/CCI 꺾임 ≥2/3) → Fix 346 상승초입 거부·LONG 인계 → Fix 350 1h hist 2봉 하락이면 늦은 진입 거부 → Fix 360 캔들 꼬리봉(shadow=기록만) → `_create_auto_bb_strategy`: 상한 재검사(Fix 168) → 4H 게이트(Fix 270) → 합의 게이트(Fix 247) → 사다리 구성(Fix 315) → 적응 TP(Fix 299) → 인스턴스 SL 덮어쓰기(Fix 362) → `ExecutionService.start_stage1`: **chg24 순위 게이트(Fix 310)** → 지지점수 게이트(Fix 327) → ISOLATED·레버 → 시장가. (chg24 게이트는 4H·합의 **뒤**, 발주 직전에 있다.)

| 계열 | 스위치(키) | 기본값 | **실값** | 비고 |
|---|---|---|---|---|
| 정점 SHORT 동시 상한 | `sajangnim_top_short_daily_limit` (0=OFF) / 범위 `concurrent_cap_scope` | 20 / all | **1 / ladder** (09-07 19:34) | 실질 「1건만」= 자동 거의 정지 |
| 4H 추세 게이트 | `trend_4h_gate_enabled` | OFF | **1** | 재진입·반전 계열 면제 키 `trend_4h_reentry_exempt`/`trend_4h_reversal_exempt` 기본 ON |
| 합의 게이트 | `confluence_gate_enabled` | OFF | **true** | LONG 은 Fix 251 되돌림 차단 동반 |
| chg24 순위 게이트 | `entry_chg24_gate_enabled` / `entry_rank_top_n` / `entry_chg24_gate_mode` | OFF / 50 / rank | **1** / 없음 / 없음 | 상승50·하락50 안만 진입 |
| 지지점수 게이트 | `support_score_gate_enabled` | OFF | 없음(OFF) | LONG ≥6 / SHORT ≤1 |
| Fix 346 / 350 | `surge_start_short_veto_enabled` / `top_short_skip_if_1h_down` | ON / ON | 없음(ON) | 346 은 `surge_start_long_handoff_enabled`(ON)로 LONG 알람 발행 |
| Fix 360 캔들 | `candle_battle_mode_short` | shadow | 없음(shadow) | gate 로 바꾸면 차단 |
| 진입창(Fix 248) | `entry_window_short_enabled` | OFF | **true** | `stage_entry_signal` 안 |
| **저점 LONG** | 알람 `sajangnim:bottom_long:*` 소비. 1순위 「급등중 조정」 `surge_pullback_long_enabled` | ON | 없음(ON) | 급락 알람(pattern B, 24h −15~−3%)은 `bottom_long_dip_alerts_enabled` 기본 OFF; LONG 급등 게이트 `long_surge_gate_enabled` 기본 OFF·**실값 1**(24h ≥+15% 만) |
| **볼밴 분할**(pump_split) | `pump_split_enabled` / `pump_split_max_concurrent` / `pump_split_capitals` / `pump_split_steps` / `pump_split_sl_roi` | 0 / 3 / 100,200,300 / 3,5,7 / 15 | **1 / 1 / 100,200,500 / 3,5,7 / 10** | 15분 주기, TP 5/10/15/20 각 25%, 트레일링 3, `split_peak_stall_enabled` 실값 1, 부분손절 항상 제외 |
| **중단선**(bb_mid_line) | `bb_mid_line_mode` (off/shadow/on) | shadow | **off** | 패턴 기본 ON = mid_resist·mid_break_down 만 |
| **재진입**(realtime_reentry) | `sajangnim_reentry_daily_limit` / `sajangnim_reentry_concurrent_slots` | 20 / 10 | **1 / 10** | 청산가 대비 반등 ≥1.0% + 지표 반전; 자본 = 사다리 2·3단(300/600), `sajangnim_max_stage` 실값 3 |
| **예약**(scheduled_entry) | `scheduled_entry_enabled` | OFF | **0** | 5분 주기, 만료 7일 |
| **급등 사다리 shadow**(surge_peak_ladder) | `surge_ladder_mode` (off/shadow/on) | off | **shadow** | 상위 10·+15%·500/1000/500, Redis `surge_ladder:shadow:*` 기록만 (Day 2: 7일 15승 24패 → 켜지 않음) |
| 통합 15m / OBV 자동 | `unified_entry_enabled` / `auto_obv_enabled` | 1 / 0 | **0 / 1** | OBV 자동 = 모달 OBV_REVERSE 전략의 단계 판정(`stage_entry_signal`), 단계당 400 |
| 4h 시간청산·저항반전 | `time_reverse_exit` 미등록(Fix 198) / `resistance_reversal` 30초 등록, 스위치 없음 | — | — | `scheduler_runner.py:722`, `:691` |

## 3. 자본 사다리와 단계 트리거

| 항목 | 키 | 기본값 | **실값** |
|---|---|---|---|
| 사다리 | `sajangnim_capital_ladder` | 10,300,600 | **10,300,600** |
| 사다리를 단계로 | `sajangnim_ladder_stages_enabled` / 간격 `sajangnim_stage_gap_pct` | ON / 1.5 | **1** / 없음(1.5) |
| 가격 모드 트리거 | N단계 트리거가 = (N−1)단계가 × (1 ± 1.5%) 불리 방향 (`stage_calculator.calculate_stages_new`) | — | — |
| 사다리 2·3단계 진입 판정 | `ladder_peak_stall_enabled` (Fix 260 정점-주춤: 트리거 도달 후 극값 갱신 → 주춤(2단계)/꺾임(3단계) 시 시장가) | ON | 없음(ON); 0 이면 옛 가격경로 + `stage_wait_for_turn_enabled`(기본 OFF, 실값 **1**, SHORT·v219 만, `execution_service.py:1821`) |
| OBV 모드 트리거 | template `trigger_mode=OBV_REVERSE` → `stage_entry_signal`(obv_gate + 15m 확인), `auto_obv_stage2/3_trigger` | −5 / −10 | **−5 / −5** |
| 레버리지 | 자동 진입 고정 2 (`DEFAULT_LEVERAGE`) | 2 | — |

## 4. 청산

| 항목 | 값 / 키 | 기본값 | **실값** |
|---|---|---|---|
| TP1 적응 | `adaptive_tp_enabled` / `adaptive_tp_calm_tp1` / `adaptive_tp_surge_tp1` / 급등 기준 `adaptive_tp_surge_chg24` | OFF / 3 / 15 / 15 | **1** / 3 / 15 / 15. 단, 사다리(2단계 이상) 템플릿은 제외 = TP1 15 (`TP1_PCT_DEFAULT`, Fix 343) |
| TP 사다리 | `TOTAL_TP_LEVELS`=20, 각 잔량 25% (`DEFAULT_TP_QTY_RATIO_PCT`), TP{n}=TP1×n | — | — |
| 트레일링 | 첫 TP 체결 뒤 피크 대비 −5%p (`TRAILING_RETRACE_PCT`, 전략별 `trailing_retrace_pct`) / TP 없이도 피크 ≥20% (`TRAILING_PEAK_THRESHOLD_PCT`) | 5 / 20 | `trailing_require_peak_ge_tp1` 없음(값 무관, Fix 335) |
| 강제손절 전역 | `force_sl_long_enabled`/`force_sl_long_roi`, `force_sl_short_enabled`/`force_sl_short_roi` | ON −5 / OFF −5 | long_roi **80**, short **true 80** (전역은 사실상 느슨) |
| 강제손절 인스턴스 | 자동 진입은 `force_sl_enabled_override=True` + `force_sl_roi_override = force_sl_roi_new_default` (Fix 362) | 25 (옛 Fix 49/52 = 5) | 없음(25). 기존 인스턴스는 저장값(대부분 5) 유지; `force_sl_unlock_unreachable_stage` 실값 true |
| 부분손절 (10 USDT 잔량) | `stage_trim_before_next_enabled` / `stage_keep_notional_usdt` / `stage_min_trim_ratio` | OFF / 10 / 2 | **1** / 없음(10) / 없음(2). 다음 단계 없으면 전량 청산(Fix 332); split_entry 항상 제외 |
| 4h 시간 강제청산 | `time_reverse_exit_worker` 스케줄 미등록 | OFF | OFF |
| 일반 SL | `DEFAULT_SL_PCT_OF_CAPITAL` 50 (템플릿 `stop_loss_percent_of_capital` 자동생성 90) | — | — |

## 5. 피라미딩 규칙 (`success_pyramiding_worker.py`)

| 규칙 | 키 | 기본값 | **실값** |
|---|---|---|---|
| 전체 스위치 / 트리거 ROI | `sajangnim_pyramid_enabled` / `sajangnim_pyramid_trigger_roi` | ON / 5.0 | 없음(ON) / **5** |
| 유리 가격 이동 / 방향 | `pyramid_min_move_pct` / `pyramid_sides` | 3.0 / SHORT | 없음 |
| 15m hist 가속 봉수 / 4H 역할 | `pyramid_hist_accel_bars` / `pyramid_4h_veto_enabled` | 3 / OFF(참고만) | 없음 |
| 횟수 / 자본 / 쿨다운 | `MAX_PYRAMID_COUNT`=2 / `sajangnim_pyramid_capital` / `COOLDOWN_SECONDS`=300 | 2 / 300 / 300s | — / **300** / — |
| 익절 후 추가 / 트레일링 여유 | `pyramid_after_tp_enabled` / `pyramid_after_tp_min_trail_room_pct` | ON / 2.0 | 없음 |
| 손실 캡 / 지표 게이트 / 몸통 성장 | `pyramid_cap_loss_enabled` / `pyramid_indicator_gate_enabled` / `pyramid_body_growth_mode` | ON / ON / shadow | 없음 |

## 6. 학습 루프 — 어디서 읽나

| 루프 | 스위치 | 주기 | 결과 위치 |
|---|---|---|---|
| 차트 학습 일지(Fix 353) | `chart_learning_enabled`(기본 ON), `chart_learning_snapshot_hours`("0"), `chart_learning_top_n`(50) | 스냅샷 UTC 00:05·12:05 / 라벨 매시 :20 | `GET /api/v1/chart-learning/status·report(.md)·trades(.md)`, `docs/learning/DAY_0x_*.md`, `docs/learning/CHART_LEARNING_CURRICULUM.md` |
| Fix 360 캔들 shadow | `candle_battle_mode_short`=shadow | 진입마다 | `strategy_config.entry_snapshot.candle_battle` (API 없음 → chart-learning/trades 와 대조) |
| 급등 사다리 shadow | `surge_ladder_mode`=shadow | 30초 | Redis `surge_ladder:shadow:{sym}:{ts}` (14일) |
| 가상 매매(Fix 361) | `paper_trading_enabled`(ON), `paper_base_usdt` 10, `paper_add_lot_usdt` 300, SL 25/TP1 3·15/트레일 5/48h | 매 15분 :01/:16/:31/:46 | `GET /api/v1/paper-trading/status·report(?days=)·report.md·trades`, `docs/spec/PAPER_TRADING_LEARNING_2026-09-08.md` |
| 패턴 학습 요약 | `pattern_learning_insights_v187`(system_settings) | 1시간 | 09-09 값: `sajangnim_top_short:SHORT` 14/381 성공(3.7%), `sajangnim_bottom_long:LONG` 2/199 |

# 기획서 v2.20 「캔들 세력 공방 분석」 통합 — 분석·측정·적용 (Fix 360, 2026-09-07)

> 사장님: "우리 자동매매에 적용할수 있게 분석해서 같이 사용할수 있게 만들어줘" (`binance_master_trading_spec_v220.md`)

## 0. 한 줄 결론

기획서 Part 2 의 운영 구조(10% 변동 심볼·15m+4H·10/300/600 사다리·99% 부분손절 10 USDT 잔량·기본/OBV 전략·피라미딩 2회)는 **이미 전부 코드에 있다**(§1 표).
새 내용은 Part 1 「캔들 몸통·꼬리 수치화」와 Part 2 ④ 「몸통 성장 중에만 추가, 꼬리 노이즈에 조기 청산 금지」 셋이다. 이 셋을 **같은 잣대로 측정**한 뒤 코드에 넣었다:

| 기획서 항목 | 측정 결과 (일지 2,992 심볼-일 + 실매매 추가 188건) | 적용 |
|---|---|---|
| SHORT: 긴 윗꼬리 → 음봉 몸통 | UP 첫 발동 n=637 **+0.44** (기준선 −0.65) CV 4/4 — 이 일지에서 **처음** 채택 문턱을 넘은 기계적 SHORT 규칙. 실매매 `confirm_peak` 위 필터로: 꼬리봉 있음 **+0.10**(n=437) / 없음 **−0.59**(n=611) | 일지 규칙 `wick_rev_short_v220` + SHORT 워커 필터 **shadow**(기록만). 켜기 = `candle_battle_mode_short=gate` |
| LONG: 긴 아래꼬리 → 양봉 몸통 | 두 봉 형태는 약함. 단일봉 해머 DOWN n=814 +0.68 Δ+0.42 CV 4/4 — 그러나 **꼬리 없이 「구역+양봉 종가」만으로 같거나 낫고**(Δ+0.71), 기존 `bottom_331`(Δ+0.89) 을 못 넘음 | 일지 규칙 `wick_rev_long_v220` 만 (실매매 배선 없음) |
| 피라미딩 「몸통이 커질 때만 추가」 | 어떤 정의도 채택 실패. 「봉마다 커짐」이 **가장 나쁨**. 덜 나쁜 정의(G3A)도 배포된 15m hist 가속(Fix 348)보다 못 가름 | 추가 스냅샷에 **shadow 표식**만. `pyramid_body_growth_mode=gate` 옵션 |
| 「꼬리 노이즈에 조기 청산 금지」 | 종가 기준 트레일링은 틱 기준을 못 이김 (LONG 동률, **SHORT 더 나쁨**). 결과를 가르는 축은 되돌림 폭(3 > 5 > 8) | **변경 없음** |

실매매 판정은 하나도 바뀌지 않았다(전부 shadow). 되돌리기 = 설정 두 줄(§4).

## 1. 기획서 → 코드 대응 (Part 2, 이미 있는 것)

| # | v2.20 | 상태 | 어디 |
|---|---|---|---|
| 1 | 당일 10%↑ 변동 심볼 모니터링 | ✅ | `market_movers.top_movers`(상승50/하락50) + 진입 게이트 `chg24_entry_gate.passes`(Fix 310, `entry_min_abs_chg24=10`) |
| 2 | 15m 진입 타이밍 + 4H 추세 필터 | ✅ (4H 는 기본 참고) | `peak_confirmation.confirm_peak`(15m 스윙 ≥2 + 지표 꺾임 ≥2/3) / `trend_4h_gate.check_trend_4h`(9/3 반증으로 기본 OFF) / Fix 350 1h 늦은 진입 거부 |
| 3 | 1단계 소액 진입 | ✅ | `sajangnim_capital.DEFAULT_CAPITAL_LADDER=[10,300,600]`, `execution_service.start_stage1` |
| 4 | 99% 청산 + 10 USDT 잔량, 2단계 감시 유지 | ✅ (Fix 319/326/332) | `stage_trim.compute_trim`(keep = 10×레버리지 명목) ← `tp_sl_orchestrator._execute_force_stop_loss`, 잔량은 `STAGE_N_OPEN` 유지 → `stage_trigger_worker` 계속 감시 |
| 5 | 2단계 지정 트리거 단가 (잔량 + 추가 자금) | ✅ | `stage_trigger_worker`(`trigger_mode=PRICE_DOWN_PCT`), `trigger_percents`, `execution_service.trigger_next_stage` |
| 6 | 3단계 최종 트리거 | ✅ | `MAX_REENTRY_STAGE=3`, 마지막 단계 이중 저장 Fix 234 로 해소 |
| 7 | 기본전략 vs OBV 자동전략 | ✅ | `StrategyTemplate.trigger_mode ∈ {PRICE_DOWN_PCT, OBV_REVERSE}` → `stage_entry_signal.check_stage_entry_signal` |
| 8 | 피라미딩 최대 2회 + 「몸통 성장」 | 🟡 부분 | 횟수·ROI·유리이동·지표 게이트 있음(`success_pyramiding_worker`, Fix 348 15m hist 3봉 가속). **몸통 조건 = 없었음 → Fix 360 shadow** |
| 9 | 꼬리 노이즈 조기 청산 금지 | ❌ 없음 → 측정 결과 **넣지 않음** | 트레일링·강제손절은 15초 마크가격 샘플러(`risk_service:575~945`, `scheduler_runner:599`) = 틱 민감. 종가 기준이 더 낫지 않았다(§2.4) |
| 10 | 전략 인스턴스 파라미터 동기화 | ✅ | `StrategyTemplate` JSON + `system_settings` 행을 워커가 매 사이클 읽음 |

기존 캔들 코드: `chart_events._body_ratio/_lwick_ratio`(범위 대비, 저점 규칙 `m15_smallbody<0.45`) · `bb_top_analyzer.WICK_RATIO=0.5`(화면·학습 전용, 진입에 안 씀) · `resistance_reversal/peak_break_reversal` 의 꼬리≥몸통×1.5(알람 생산자). 상세: [c1_spec_to_code_map.md](../learning/v220/c1_spec_to_code_map.md).

## 2. 측정 (잣대 = 9/3 이후 모든 규칙과 동일: 레버 2 · SL −5% / TP +15% ROI · 12h · 완성봉 · 미래참조 없음 · CV = 심볼 홀짝 × 날짜 반쪽)

표본: 학습 일지 `chart_learning_days` 2,992 심볼-일 (2026-08-16~09-05, UP 1,050 / DOWN 1,050, 알트 상승 표류 국면 — LONG 기준선 +0.26~+0.34, SHORT −0.55~−0.65). 격자는 사전 선언(W∈{0.4,0.5,0.6} 꼬리/범위 · K∈{1,2} 꼬리≥K×몸통 · R∈{0.8,1.2} 범위≥R×ATR14 · 확인봉 몸통 B∈{0.3,0.5} · 구역 Z1 24h 극값 3% / Z2 %B / Z3 없음).

### 2.1 SHORT 「긴 윗꼬리 + 매도 폭탄 뒤 음봉」 — [wick_short_grid.md](../learning/v220/wick_short_grid.md)
- 채택 셀: **W0.5 · K1 · R0.8 · Z2(%B≥0.85) · 확인봉 음봉 몸통≥0.3 · 종가<꼬리봉 중간** → UP 첫 발동 n=637 **+0.44**, 승 44%, TP 10%/SL 50%/TIME 40%, CV +0.12/+0.10/+0.77/+0.67, 기준선 −0.65 (Δ+1.09). 3주 각각 양수(+0.36/+0.60/+0.37), 상위 5심볼 제외 +0.17. 코드 재현: n=638 +0.43 CV 4/4 ([code_rules_firstfire_check.json](../learning/v220/code_rules_firstfire_check.json)).
- 🚨 **180셀 중 2셀만 통과**, 약한 CV 셀 +0.10/+0.12, 전체 발동 +0.23(1셀 음수), **중앙값 −3.1**(평균은 10% TP 가 만든다), DOWN −0.52 / UP35_DOWN24 −0.81 / ALL −0.08 = **UP 전용**. 부품 하나만 빼도 기준선 이하(구역+확인 −0.42, 꼬리+구역 −0.42, 꼬리+확인 −0.64) = 3중 상호작용, 표본 밖에서 깨지기 쉽다.
- 발동의 67% 가 `confirm_peak` 발동 봉과 같은 봉(±2봉 82%) = 새 발견이 아니라 **기존 신호의 필터**. `confirm_peak` 첫 발동 UP −0.31(n=1,048) 을 「발동 봉 포함 5봉(직전 4봉 + 발동 봉) 안에 **loose 꼬리봉(꼬리 ≥ 0.4·≥몸통·≥0.8×ATR14) + %B≥0.85**」로 가르면 **+0.10(n=437) vs −0.59(n=611)**, 전체 발동 +0.07 vs −0.32. (반박 검증이 잡음: 처음 배선은 꼬리 0.5·4봉이었고 그 정의는 +0.05(n=302) vs −0.45(n=746), CV 2/4 — 인용 숫자와 다른 정의였다. 측정 셀대로 0.4·5봉으로 고침.)
- 「꼬리봉 저가 아래로 마감」(기획서의 「길게 떨어지는」)은 「중간 아래」보다 낫지 않았다(+0.38, CV 1셀 음수).

### 2.2 LONG 「긴 아래꼬리 뒤 양봉」 — [wick_long_grid.md](../learning/v220/wick_long_grid.md)
- 기획서의 두 봉 형태는 약하다(확인봉을 기다리면 반등을 돌려준다): 최선 DOWN 2B n=789 +0.84 Δ+0.57 이지만 전체 발동 Δ+0.07.
- 단일봉 해머(**아래꼬리≥0.5 · 범위≥0.8×ATR14 · 양봉 · 저가 ≤ 24h 최저×1.03**) DOWN n=814 **+0.68** Δ+0.42 CV 4/4, ALL n=2,163 +0.73 Δ+0.39 4/4. 코드 재현 n=814 +0.68 CV 4/4. 발동 중앙 6.5h(0~1h 9.5%) = 「언제」 고르기가 아님.
- 🚨 대조군이 결정적: **꼬리 조건 없이 「24h 최저 3% 안 + 양봉 종가」만** = DOWN n=1,008 +0.97 Δ+0.71 CV 4/4. 꼬리는 「구역+양봉」 위에 아무것도 더하지 않는다. 기존 `bottom_331`(DOWN Δ+0.89 CV 4/4)을 못 넘고, 합집합 +0.04, AND 로 쓰면 건당은 오르나(+1.46) 발동의 18~25% 만 남는다.
- R=1.2(큰 봉)는 일관되게 더 나쁘다(큰 캔들이 2.5% 손절을 친다).

### 2.3 피라미딩 「몸통이 추세 방향으로 계속 성장할 때만 추가」 — [body_growth_summary.md](../learning/v220/body_growth_summary.md) · [실매매 172건](../learning/v220/body_growth_real_adds.md)
- 실매매 추가 172/188건(16건은 봉 결손) 재채점: 모든 몸통 정의가 평균을 **낮춘다**(전체 −3.57 → 엄격 성장 G1_2 −5.31, G3A −4.54). SHORT 에선 배포된 15m hist 가속(ACCEL3 +0.45 vs 차단 −4.48)이 몸통보다 잘 가르고, 「몸통만 참·가속 거짓」 셀은 음수(−2.19), 「가속만 참」은 −0.53.
- 일지(SHORT confirm_peak 1,028 진입 / LONG bottom_331 920 진입, ROI 6 도달 뒤 300 추가, 각 lot SL −5%·트레일 5%p): SHORT 추가는 어떤 조건에도 음수(NONE −0.69 … G3A −0.24, CV 3/4 음수), LONG 저점 추가는 **조건 없음이 최선**(+0.24 vs G3A +0.17). 
- → 채택 불가. 기획서 문장은 코드에 **표식**으로만 남긴다(§3).

### 2.4 「꼬리 노이즈에 조기 청산하지 않고」 — [wick_exit_engines.md](../learning/v220/wick_exit_engines.md)
- 실코드: 트레일링·강제손절은 **15초 마크가격 샘플**로 판정(틱 민감). 일지 재생(LONG bottom_331 2,603 진입 / SHORT confirm_peak 600행): 꼬리만으로 나간 청산이 17~22%(트레일)·24~29%(손절) 있지만 **제거해도 낫지 않다** — LONG ALL 틱 +0.78 / 종가확인 +0.77 / 종가만 +0.86(CV 2/4), SHORT 는 반대로 **더 나쁨**(틱 −0.13 / 종가확인 −0.30 / 종가만 −0.52, 3/4 셀). 
- 결과를 가르는 축은 되돌림 폭: 3%p > 5 > 8 (LONG +0.87/+0.78/+0.74, SHORT +0.29/−0.13/−0.31) — 9/1 실매매 측정(5 가 최선)과 반대라 **shadow 로만 기록**, 변경 없음. LONG 은 트레일링 없이 하드 TP +15 가 최선(+0.94, 4/4) = 현행 「TP 부분체결 뒤에만 트레일링 무장」(Fix 335)이 맞는 쪽.

## 3. 적용 (Fix 360) — 실매매 판정 변경 0

| 부품 | 내용 |
|---|---|
| `app/services/candle_battle.py` | 순수 함수: `metrics`(몸통·꼬리·비율) · `atr_range`(직전 14봉 범위 평균) · `zone_ok`(24h 극값 / %B / 없음) · `reversal_signal`(LONG 기본 **hammer**, SHORT 기본 **two_bar**) · `recent_wick_bar`(confirm_peak 필터, 직전 4봉) · `body_growth`(기본 G3A, `growth_strict` 로 기획서 원문) · 설정 읽기 `cfg_from_db`/`mode` · `completed_15m`(진행중 봉 제거) |
| 일지 규칙 | `chart_learning.RULES` 에 `wick_rev_short_v220`(SHORT, candidate) · `wick_rev_long_v220`(LONG, candidate). `LABEL_VERSION 2→3`. 🚨 반박 검증이 잡음: 버전을 올려도 매시 잡은 PENDING 행만 봐서 **옛 행이 저절로 재라벨되지 않았다** → 매시 :20 잡 끝에 옛 버전 행을 최대 500건씩 재라벨(API 호출 없음, 약 6시간이면 2,992행 완료, `relabel` 의 limit 은 SQL 에서 옛 버전만 세도록 고침). 보고서는 **그 규칙이 평가된 행만 분모**로 세고 버전 혼재를 표시한다 → `/api/v1/chart-learning/report.md` 에 두 규칙의 그룹별·CV 성적이 매일 쌓인다 |
| SHORT 워커 | `auto_short_at_top_worker`: `confirm_peak` → Fix 346(LONG 인계) → Fix 350 → **Fix 360 필터** → 진입 순(인계를 가로채지 않게 뒤에 둠). shadow 면 로그 `[Fix360] 🕯 … ✅/✗` + `strategy_config.entry_snapshot.candle_battle` 에 판정 저장(반박 검증: 처음엔 저장되지 않는 cfg dict 에 넣었었다). gate 면 꼬리봉 없는 신호를 `skipped` 로 보류하되 봉이 모자라 판정을 못 하면 통과(fail-open) |
| 피라미딩 워커 | Fix 273 지표 게이트 통과 뒤 `body_growth`(판정 봉 포함 TR14 = 측정 G3A 정의) 를 추가 스냅샷 `body_growth` 에 기록. gate 면 `body_not_growing` 사유로 보류하되 봉 조회 실패·부족은 통과 |
| 테스트 | `tests/test_fix360_candle_battle.py` 17건(정의·측정 창·설정·배선 순서·fail-open·재라벨 연결) + Fix 353 테스트 갱신(규칙 12종·버전) |

## 4. 설정키 (전부 Claude 가 정함 — 기본값 = §2 측정값. 행 없음 = 기본)

| 키 | 기본 | 뜻 |
|---|---|---|
| `candle_battle_mode_short` | **shadow** | off / shadow(기록) / **gate**(꼬리봉 없는 confirm_peak 신호 보류) |
| `pyramid_body_growth_mode` | **shadow** | off / shadow / gate(마지막 완성봉 몸통 조건 없이는 추가 안 함) |
| `candle_battle_mode_long` | shadow | 예약(LONG 실매매 배선 없음 — 일지 규칙만) |
| `candle_battle_wick_ratio_min` / `_wick_body_mult_min` / `_range_atr_mult_min` | 0.5 / 1.0 / 0.8 | 꼬리봉: 꼬리/범위 · 꼬리≥k×몸통 · 범위≥R×ATR14 (1.2 는 일관되게 더 나쁨) |
| `candle_battle_zone_long` / `_zone_short` / `_zone_pct` / `_zone_pctb_long` / `_zone_pctb_short` | extreme24h / bb / 3.0 / 0.15 / 0.85 | 구역 |
| `candle_battle_form_long` / `_form_short` | hammer / two_bar | 형태 |
| `candle_battle_confirm_body_ratio_min` / `_confirm_mode` | 0.3 / mid | 확인봉 (extreme = 꼬리봉 저가 아래, 더 낫지 않았음) |
| `candle_battle_short_addon_lookback` / `_short_addon_wick_ratio_min` | 5 / 0.4 | confirm_peak 필터: 발동 봉 포함 5봉 안에 꼬리 ≥ 0.4 꼬리봉 (= 측정 셀 「loose W0.4 incl_fire_bar」) |
| `candle_battle_growth_bars` / `_growth_strict` / `_growth_body_ratio_min` / `_growth_body_atr_mult_min` / `_growth_opp_wick_max` | 1 / 0 / 0.5 / 0.5 / 0.3 | 몸통 성장(G3A). `growth_strict=1` 이 기획서 원문(측정 최악) |

**되돌리기**: `candle_battle_mode_short=off` · `pyramid_body_growth_mode=off` (재시작 불필요, 워커가 매 사이클 읽음). 일지 규칙은 기록이라 되돌릴 것이 없다.

## 5. 사장님 결정 사항

1. **SHORT 꼬리봉 필터를 gate 로 켤지** — 근거: confirm_peak 신호를 꼬리봉 유무로 가르면 +0.10 vs −0.59(일지, UP). 반대 근거: 180셀 중 2셀·3중 상호작용·중앙값 음수·상승 표류 국면 한정. 권고: **shadow 7일**(실 스냅샷에서 `wick_rev_short_v220` 이 CV 4/4 를 유지하고, 실매매 진입의 `candle_battle.ok` 별 손익이 갈리면) 뒤 gate. 켜는 명령은 §6.
2. LONG 해머는 일지에서만 본다(저점 자리는 `bottom_331` 이 더 낫고, 그것도 아직 미배선 — 9/5 Day 1 결정 그대로).
3. 「몸통 성장」과 「꼬리 노이즈 청산」은 측정이 반대라 넣지 않았다. 기획서 문장을 그대로 원하시면 `pyramid_body_growth_mode=gate` + `candle_battle_growth_strict=1` 로 켤 수는 있으나 실측은 −5.31/건(가장 나쁨)이다.

## 6. 배포·확인

```bash
cd ~/binance-auto-trader/backend && git pull origin main && docker compose restart api scheduler
```
- 1분 뒤 `docker compose logs --since 2m scheduler | grep Fix360` 에 `🕯` 판정 줄(confirm_peak 통과 신호가 있을 때) / 피라미딩 `몸통` 줄.
- 라벨링 진행: `docker compose exec -T scheduler python -m app.workers.chart_learning_worker status` 에서 version 3 행 수 증가(시간당 200).
- 보고서: `/api/v1/chart-learning/report.md` 에 `wick_rev_short_v220`·`wick_rev_long_v220` 행.
- gate 켜기(사장님 결정 1): `system_settings` 에 `candle_battle_mode_short='gate'` 한 행.

## 7. 구현 반박 검증(3 렌즈)이 잡아 고친 것
1. **애드온 필터 정의 불일치** — 인용한 +0.10/−0.59 는 「꼬리 ≥ 0.4 · 발동 봉 포함 5봉」 셀인데 코드는 0.5·4봉이었다(그 정의는 +0.05/−0.45, CV 2/4, 사전 격자에 없던 셀). → 애드온 전용 키 2개로 측정 셀과 일치시키고 회귀 테스트로 창 의미(발동 봉 포함 N 봉)를 고정.
2. **버전 재라벨이 없었다** — `LABEL_VERSION` 만 올리면 옛 행은 영원히 v2 이고, `_prune` 이 45일 뒤 봉을 지우면 다시는 v3 가 될 수 없었다(500행만 재라벨된 상태에서 새 규칙 발동율이 46% → 7.7% 로 보임). → 매시 잡 끝 재라벨 + 보고서 분모 = 평가된 행.
3. **SHORT shadow 판정이 저장되지 않았다** — `cfg["candle_battle"]` 는 `_create_auto_bb_strategy` 가 읽기만 하고 버린다. → `entry_snapshot` 에 저장.
4. gate 모드의 fail-closed 두 곳(피라미딩 봉 조회 실패·SHORT 신규 상장 봉 부족) → fail-open. Fix 346 LONG 인계보다 뒤로 이동.
5. 몸통 성장 ATR 이 측정(판정 봉 포함 TR14)과 달랐음(0.3% 봉 불일치) → 측정 정의로. 퇴화 입력(24h 봉 부족·ATR 0·전부 평탄) 가드.
6. 두 일지 규칙은 코드 재현에서 측정 스크립트와 **발동 봉 0건 불일치**(SHORT 982/982, LONG 2,663/2,663).

## 8. 함정·주의
- 국면: 표본 3주가 알트 상승 표류 — SHORT +0.44 는 국면 특수일 수 있다. 실 스냅샷 일지가 매일 재판정한다.
- 격자 낙관: 채택 셀은 180셀의 최선. 진짜 기대값은 Z2·R0.8 블록 평균(+0.1~+0.3)에 가깝다.
- CV 4/4 는 시대(era) 혼입을 못 잡는다 — 9/7 피라미딩 트리거 검증에서 배운 것. 그래서 3주 각각·상위 심볼 제외·대조군까지 봤다.
- 「꼬리」는 대조군(구역+방향 종가)과 반드시 같이 봐야 한다 — LONG 에선 꼬리가 아무것도 더하지 않았다.

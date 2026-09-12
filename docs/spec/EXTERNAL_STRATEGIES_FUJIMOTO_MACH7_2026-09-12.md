# Fix 368 — 외부 전략 2종 반영: 후지모토 「3역 호전」 · 마하세븐 「속임수 돌파」 (2026-09-12)

사장님: "이 내용을 우리 시스템 로직에 반영해서 운영할 수 있게 만들어줘" (`rufu_trading_strategy.md`, `mach7_ma_strategy.md`).

## 0. 한 줄 요약

- 두 전략은 **가상매매 규칙 8개**로 먼저 등록돼 자리별 Δ·CV 가 매일 쌓이고, **워커는 shadow 모드**(신호만 기록, 주문 없음)로 돈다.
- 실주문은 사장님이 설정 `fujimoto_mode=on` / `mach7_mode=on` 으로 켠다. 주문 경로는 이미 검증된 `create_surge_position`(1단계 템플릿·MARKET·
  손절/TP·킬스위치·ban·잔액·중복·전용 슬롯) 과 `add_position_now(mode="preserve")` 만 쓴다.
- 판정 코드: `app/services/external_strategies.py` (순수 함수). 워커: `app/workers/external_strategies_worker.py` (60초, 15분 완성봉당 1회).

## 1. 출처 → 우리 시스템 대응

| 출처 | 우리 구현 | 비고 |
|---|---|---|
| RSI14 30/70, MACD 12/26/9, 일목 9/26/52 | 그대로 (상수, verbatim) | 봉 = 15분 (`ext_interval`, 사장님 사상: 15분 = 타이밍) |
| 후지모토 1차 10%: RSI 30 아래→위 복귀 | `fujimoto_stages()[1]` | `rsi[j-1] < 30 ≤ rsi[j]` |
| 2차 20%: 상승 다이버전스 + 영선 아래 골든크로스 | `[2]` | 다이버전스 = 창(`fujimoto_div_lookback`=30)을 반으로 갈라 두 저점 비교 |
| 3차 70%: 전환선↑기준선 + 구름 위 + 후행스팬 | `[3]` | 구름 = 26봉 전 선행스팬 A/B, 후행스팬 = 종가 > 26봉 전 종가 |
| SHORT 거울 | `side="SHORT"` | 2차에 RSI<50, 3차는 구름 하단 이탈 + 전환선↓ |
| 1:2:7 분할 | `fujimoto_stage_ratios`=10,20,70 × `fujimoto_total_alloc_usdt`(100) | 2·3차는 **같은 인스턴스에 preserve 추가** (우리 단계 워커·피라미딩은 손대지 않음) |
| 2% 룰: 최대 진입 = 총자산×2% ÷ 손절폭 | `risk_capped_margin()` | 총자산 = `totalWalletBalance`, 손절폭 = 진입가 대비 손절가 % |
| 손절 = 최근 지지/저항 | 1차 = `fujimoto_swing_lookback`(20봉) 스윙 저점/고점 → `force_sl_roi_override` 환산; 2·3차 뒤 평단 기준으로 다시 환산 | 가격 % 는 `ext_stop_pct_min/max`(0.3~15) 로 클램프 |
| 마하 30일선/200일선 | 15분봉 SMA30/SMA200 | 「일」은 못 옮긴다 — 봉 수만 유지 (Claude가 정함) |
| 200선 우상향/우하향 | `sma_l[j] > sma_l[j-5]` | 슈도코드 그대로 |
| 30선 이탈 뒤 2봉 연속 복귀 | `c[j-2] < s[j-2]` 그리고 `c[j-1], c[j] > s` | SHORT 거울 |
| 30선 각도 ≥ 30도 | `mach7_min_slope_pct`(0.5 = 30선 5봉 기울기 %) | 각도는 차트 배율 종속 → 기울기 % 로 대체, **가상매매로 보정** (LONG 만, 출처대로) |
| 손절 = 함정 최저/최고점 | 최근 3봉 저가 min / 고가 max | 슈도코드 `min(low[-3:])` |
| 마하 진입 크기 | `mach7_capital_usdt`(50) + 2% 룰 상한 | 출처에 크기 규칙 없음 → 같은 2% 룰 (Claude가 정함) |

## 2. 설정 키 (전부 `system_settings`, 재시작 불필요)

`external_strategies.SETTINGS` 가 단일 진실이다 — 검사기 ⑥절이 실효값과 출처(verbatim / Claude가 정함)를 함께 찍는다.
핵심: `fujimoto_mode`·`mach7_mode`(off|shadow|on, 기본 shadow), `*_sides`, `*_max_concurrent`(2), `*_cooldown_hours`(4),
`ext_universe_top_n`(60, 거래대금 상위), `ext_min_quote_volume`(5,000,000), `ext_leverage`(2).

## 3. 워커 동작

1. 거래대금 상위 N 심볼(DB 심볼 테이블에 있는 것만) × 15분봉 300개 → 진행 중 봉 제외 → 마지막 완성봉 `ts` 가 Redis `ext:last:{sym}` 와 같으면 건너뜀.
2. 후지모토: 살아 있는 FUJIMOTO 인스턴스가 있으면 저장된 단계(`ext:fujimoto:stage:{sid}`)의 **다음** 단계 조건만 본다 → shadow 기록 / on 이면 추가.
   없으면 1차 조건 + 쿨다운 없음 → shadow 기록 / on 이면 진입.
3. 마하세븐: 살아 있는 MACH7 인스턴스가 없고 함정 조건 + 쿨다운 없음 → shadow 기록 / on 이면 진입.
4. 사이클 요약: 로그 `[Fix368] 완료: …` + Redis `ext:last_cycle`. 그림자 신호: `ext:shadow:{family}:{sym}:{ts}` (7일).

## 4. 가상매매 등록

`chart_learning.RULES` 에 `fujimoto_l1_rsi · l2_div_gc · l3_ichimoku · s1_rsi · s2_div_dc · s3_ichimoku · mach7_trap_long · mach7_trap_short`
(origin=candidate). `LABEL_VERSION` 3→4 라 옛 일지 행이 자동 재라벨된다(Fix 356). 지표는 시리즈(같은 배열 객체)당 한 번만 계산해 캐시하므로
백필 사이클 부담이 작다. 보고서 `/api/v1/paper-trading/report.md` 의 규칙 표에 자리별 Δ·CV 가 쌓인다 — **채택 잣대(CV 4/4 · n≥100 · Δ>0)를
넘기 전에는 on 으로 켜지 않는 것을 권한다.**

## 5. 켜는 법 / 끄는 법 (사장님, VPS)

```
fujimoto_mode = on       (또는 off)
mach7_mode    = on       (또는 off)
```
켜기 전 확인: 가상 보고서에서 해당 규칙의 Δ 가 양수·CV 4/4 인지, 검사기 ⑥절의 그림자 신호 수가 하루 몇 건인지(너무 많으면 `ext_universe_top_n` 을 줄인다).

## 6. 검증

- `tests/test_fix368_external_strategies.py` 11건: 지표(SMA/MACD/RSI/일목 26봉 시프트) · 다이버전스 · 후지모토 1/2/3차 LONG·SHORT 각 조건 ·
  마하세븐 함정/추세/기울기/손절 · 2% 룰 산식 · 설정 가드(NaN·오타 모드) · 가상 규칙 등록·캐시 · 배선 핀(스케줄러·단일진입·검사기).
- 배포 후 검사기 ⑥절: 규칙 8/8 · LABEL_VERSION 4 · 스케줄러 잡 · 기본 shadow · 마지막 사이클 · 그림자 신호 수.

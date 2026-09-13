# 📉 손실 원인 학습 자료 (Fix 371b, 2026-09-14)

## 사장님 지시 (verbatim)

> 새전략 기본방식과 새전략 obv 자동만 가능하게 수동으로 전략을 만들수 있게 남기고 모든 자동매매 중단하고 가상으로만 매매하고 학습하고 손실이 발행하는 원일을 학습해서 수정할수 있게 기록해서 우리 자동매매에 적용할수 있게 자료를 만들어줘

## 한눈에

| 무엇 | 어디 | 상태 |
|---|---|---|
| 자동 실주문 | Fix 371 게이트 (`docs/spec/AUTO_TRADING_HALT_2026-09-14.md`) | ⛔ 중단 — 사람이 모달로 만든 전략만 |
| 가상매매 (규칙 12종 + 기준선, 엔진·청산 변형) | `paper_trading_worker` · 보고서 v3 (Fix 366/370) | ✅ 계속 — 주문 없음 |
| 그림자 워커 (외부 전략·규칙 가족·다일 반등) | Redis `ext:shadow:*` · `rf:shadow:*` · `multiday:shadow:*` | ✅ 계속 |
| **손실 원인 기록 (신규)** | `trade_learning_records.insights["loss_causes"]` | 매시간 태깅 (과거분 소급, 사이클당 200건) |
| **손실 원인 보고서 (신규)** | `GET /api/v1/trade-learning/loss-causes?days=30&format=md` · `system_settings.loss_cause_report_last` | 매시간 갱신 |

## 1. 손실 한 건을 어떻게 기록하나

청산된 실거래 중 손실 1 USDT 이상마다 **DB 에 이미 있는 사실만** 모아(`loss_cause.gather_facts`) 원인 태그를 붙인다(`loss_cause.classify`, 순수 함수).

### 추가분 손실 금액 = 체결 재생

`trade_learning_records.exit_price` 는 운영에서 항상 비어 있고(Fix 197), 부분 익절(TP1 25%)·10 USDT 잔량 손절(Fix 326)이 있어
「수량 × (청산가 − 추가가)」 로는 추가분 손실을 최대 3배까지 틀리게 잰다 (반박 검증 C). 그래서:

1. 체결된 진입 주문(`orders` purpose=ENTRY)을 lot 으로 쌓는다. 단계 번호가 있으면 계획 단계, 없으면 계획 밖 추가.
2. 체결된 청산 주문(purpose=EXIT)마다 열린 lot 을 **보유 비중대로** 줄이고 그 청산 손익을 lot 에 나눠 준다
   (선물 평균원가 — 부분 청산해도 평단 불변).
3. lot 별 손익을 합쳐 「자동 추가분」「수동 추가분」「계획 단계분」 금액을 낸다. 수수료 제외.
   청산 체결이 모자라면(`closed_ratio` < 1) `approx=true`, 청산 체결이 아예 없으면 금액을 만들지 않는다(`ADD_UNATTRIBUTED`).

예: 1단계 100 @1.0 · 자동 추가 100 @1.2 · TP1 60 @1.25 · 나머지 140 @0.9 → 자동 추가분 **−19.5** (옛 근사 −30 아님).

### 계획 밖 추가의 출처

| 순서 | 판정 |
|---|---|
| 1 | 주문 id 접미사 `_ADHOC_AM_`/`_ADHOC_AL_` = **자동** (Fix 371 이후 자동 추가 주문에 붙음) |
| 2 | 옛 접미사(`ADHOC_M` — 자동·수동 공용) **시장가**는 자동 수익 추가 기록(`strategy_suggestions` pyramid=true) 시각과 1대1 최근접 매칭 (±600초) |
| 3 | 남은 추가: 사람이 모달로 만든 전략이면 **수동**, 아니면 **출처 미상** (외부 전략·급등 사다리 추가는 추천 기록을 남기지 않는다) |

체결 시각은 주문 `updated_at`(스트림이 체결을 반영한 시각). 지정가는 `created_at` 이 주문 시각이라 쓰지 않는다.

### 그 밖의 입력

| 사실 | 출처 |
|---|---|
| 최고·최저 ROI (레버리지 반영, 평단 기준) | `trade_learning_records.max_profit_pct / max_loss_pct` |
| 청산 사유 | RiskEvent 유도 (`resolve_close_reason`, Fix 197) |
| 진입 당시 급등락 | `entry_context.pump_dump.change_pct` |
| 가족 · 강제손절 실효값(전략 설정 없으면 전역) · 누가 만들었나 | `family_of` · `force_sl_enabled_override`/`get_force_sl` · `entry_origin` |

기록 예 (`insights.loss_causes`, KOMA 가 손절로 끝났다고 가정):

```json
{"v": 1, "pnl_usdt": -107.98, "primary": "AUTO_ADD_LOSS", "add_loss_usdt": -91.04, "closed_ratio": 1.0, "family": "legacy_manual",
 "tags": [{"code": "AUTO_ADD_LOSS", "usdt": -91.04, "detail": "추가 @ 0.0188303(+7.9%) → 청산 체결 재생 배분 -91.04 USDT"},
          {"code": "GAVE_BACK_PROFIT", "usdt": null, "detail": "최고 ROI +15.8% 뒤 손실"},
          {"code": "STOP_LOSS_HIT", "usdt": null, "detail": "청산 사유 SL"}], "approx": false}
```

## 2. 원인 태그 → 자동매매에 적용할 때 먼저 검증할 것

| 코드 | 뜻 | 먼저 검증할 것 |
|---|---|---|
| `AUTO_ADD_LOSS` | 자동 수익 추가분이 손실로 뒤집힘 | 자동 추가 재개 전 가상 추가 lot 결과 · 재개 시 `pyramid_after_add_sl_scope=all` |
| `UNKNOWN_ADD_LOSS` | 계획 밖 추가분 손실 (출처 미상 — 자동 워커 추정) | 외부 전략·급등 사다리 추가 경로 |
| `MANUAL_ADD_PROFIT_ZONE_LOSS` | 수동 💉 이익 구간 추가분이 손실 | `manual_add_after_sl_enabled=1` (대기열 2①) |
| `MANUAL_AVG_DOWN_LOSS` | 수동 💉 물타기분이 손실 | 손실 구간 추가 금액·횟수 한도 (사람 규율) |
| `ADD_UNATTRIBUTED` | 추가는 있었는데 청산 체결이 없어 금액 미계산 | 체결 누락(user-stream) 확인 |
| `LADDER_AVERAGING_LOSS` | 계획 단계 2개 이상 체결 뒤 손실 | `stage_trim_before_next_enabled` · 단계 간격 |
| `GAVE_BACK_PROFIT` | 최고 ROI +10 이상 갔다가 손실 | 가상 청산 변형(이익 보호, Fix 370) |
| `NEVER_IN_PROFIT` | 최고 ROI +2 미만 = 진입 자리 문제 (추가가 있던 거래엔 붙이지 않음 — 추가가 최고 ROI 를 지운다) | 가상 보고서 규칙별 Δ·CV 4조각 |
| `DEEP_DRAWDOWN_NO_STOP` | 손절 없이 ROI −50 이하 | `legacy_ladder_force_sl_enabled` |
| `STOP_LOSS_HIT` | 손절 발동 | 가상 손절 깊이 변형 |
| `EXTERNAL_CLOSE` | 시스템 밖에서 닫힘 (거래소 강제청산·앱 청산 가능) | 거래소 거래 내역 대조 · 증거금·레버리지 |
| `SURGE_CHASE_ENTRY` | 급등락 같은 방향 추격 진입 | chg24 진입 게이트(Fix 310) · 정점 판정 |
| `ROI_RECORD_MISSING` · `CLOSE_REASON_UNKNOWN` | 기록 결손 표시 (주원인으로 쓰지 않음) | 평가·체결 누락 확인 |
| `UNCLASSIFIED` | 주원인으로 쓸 사실이 없음 | 기록 결손 확인 |

주원인(`primary`): 추가분 손실(체결 재생)이 전체 손실의 50% 이상이면 가장 큰 추가 태그 → 금액 미계산 추가 → 손절 없는 역행 → 이익 반납 → 사다리 → 추격 → 이익 구간 없음 → 손절 → 시스템 밖 청산.
문턱값은 모두 「Claude가 정함」 — 설정 `loss_cause_thresholds` (JSON, 예 `{"gave_back_roi": 15, "min_loss_usdt": 3}`) 로 덮는다.

## 3. 적용 루프 (자동매매를 다시 켜기 전까지)

1. **기록** — 매시간 손실 거래에 태그.
2. **집계** — 보고서 「주원인별 손실」 상위 원인을 고른다.
3. **가상 검증** — 대응 변형을 가상매매로 먼저 잰다(실주문 없음). 채택 조건은 가상 보고서 v3 그대로(사전등록 표본 · 클러스터 t · CV 4조각 · 7일+).
4. **사장님 결정** — 통과한 변형만 설정 키로 켠다(가족별 적용).
5. **재측정** — 켠 뒤 같은 원인 태그 손실이 줄었는지 보고서로 확인. 줄지 않으면 되돌린다.

## 4. 첫 사례 — 9/13 자동 수익 추가 (9/14 실측, 로그·공개 시세)

| | KOMAUSDT #4500 LONG | 哈基米USDT #4483 LONG |
|---|---|---|
| 가족 | 기존 방식 (TP1 +25 · 손절 없음) | 기존 방식 |
| 1단계 | 100 → 11,442 @ 0.0174535 (9/13 04:58 KST) | 100 → 4,864 @ 0.04111 (9/11 14:03) |
| 자동 수익 추가 | 07:15:03 300 → 31,872 @ 0.0188303 (ROI +15.8, 15m·4H 상승 통과) | 9/12 15:15 300 → 13,945 @ 0.0429636 (ROI +8.96) |
| 추가 뒤 | 1시간 뒤 고점 0.01968, 11시 급락 | 그 시간봉 고가 0.04344 부근, 이후 0.0333 |
| 미실현 (9/14 06시) | **−108** (추가 없었다면 약 −17) | **−172** (추가 없었다면 약 −38) |
| 예상 태그 (청산 시) | `AUTO_ADD_LOSS`(주) · `GAVE_BACK_PROFIT` | `AUTO_ADD_LOSS`(주) |
| 수동 지정가 (미체결) | – | 💉 100 @ 0.0327 · 300 @ 0.0304 → 체결 뒤 손실이면 `MANUAL_AVG_DOWN_LOSS` |

배운 것:
- **자동 추가의 지표 조건(15m MACD 가속 · 4H 상승)은 「오르는 중」은 가리지만 「끝물」은 못 가린다.** 두 건 모두 시간봉 고가 근처에서 샀다.
- **추가 금액(300)이 1단계(100)의 3배라 평단이 추가가 쪽으로 끌려가** TP1 +25 가 멀어졌다 (KOMA 추가 전 TP1 0.019635 는 08시 고가와 0.2% 차이).
- 추가 뒤 손절 −5(Fix 364)는 OBV 자동 가족에만 걸려 기존 방식엔 멈출 장치가 없었다.
- 자동 추가도 수동 💉 와 같은 「헌법 51 preserve」 알림을 보내 사람 조작처럼 보였다 → Fix 371 이후 자동 추가 주문 id 는 `ADHOC_AM`.

## 5. 한계

- 수수료 제외 · 청산 체결 누락 시 근사(`approx`). 과거(Fix 371 이전) 옛 접미사 추가의 자동/수동 구분은 시각 매칭이라 드물게 틀릴 수 있다.
- 최고 ROI 는 평단 기준이라 preserve 추가 뒤엔 새 평단 기준으로 이어지고, reset 추가는 지운다.
- 강제손절 on/off 는 **태깅 시점** 실효값이다 (거래 당시 값 기록이 없다).
- `entry_context` 가 빈 옛 기록(12%만 채워짐, Fix 240)은 `SURGE_CHASE_ENTRY` 판정이 안 된다.
- Fix 156 이전 피라미딩(별도 자식 인스턴스)은 자동 추가로 잡히지 않는다.
- 열린 포지션(KOMA·哈基米)은 청산 뒤에 태깅된다.

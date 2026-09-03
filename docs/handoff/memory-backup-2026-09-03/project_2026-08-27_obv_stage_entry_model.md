---
name: project_2026-08-27_obv_stage_entry_model
description: "OBV 단계 진입 = 운영 로직 사용 + -5% 청산이 애초에 발동 안 하던 원인(#1488 메커니즘) + 사장님 결정 4건"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9810b26c-b7e1-4349-8e91-83e3a14b072a
  modified: 2026-08-26T23:23:32.384Z
---

# 🎯 2026-08-27 OBV 단계 진입 모델 확정 (Fix 173~177)

브랜치 `claude/infallible-euler-6dc297` — `359eaeb`(Fix 173) + `01d329f`(Fix 174~177).
**미머지 = 운영 미반영.**

## 🚨 #1488 이 -90% 까지 간 진짜 메커니즘 (Fix 177)

`risk_service.py:276` (v130, 2026-08-06):
```python
if _current_stage < _total_stages:
    return False   # 다음 단계 미진입 시 = force SL 발동 X
```
= **물타기 모델** 전제. 단계가 남으면 손절을 미룬다.
→ #1488 은 `2/3 단계` 라 `2 < 3` → **force SL 이 영원히 발동 못 함** → ROI -52% 방치 → 사장님 수동 관리.

⚠️ **내 Fix 133(사다리 3칸 정상화)이 이 잠복 게이트를 깨웠다.**
그 전엔 1단계짜리 template 이라 `1 >= 1` 로 통과했다. 제대로 고치니 `1 < 3` 이 성립.

**해법**: `retry_after_liquidation_enabled` 켠 전략은 단계 게이트 건너뜀 (= 청산 후 대체 모델 선언).
새 설정을 만들지 않고 **기존 토글을 모델 선택 신호로 재사용**했다 (헌법 102/127).
+ OBV 모달이 그 토글을 **기본 ON** (기본값 False 라 매번 켜야 하는 구조가 함정).

**나머지 고리는 이미 다 맞게 되어 있었다**: `STAGES_WITH_NEXT` 에 `LIQUIDATED_WAITING_RETRY` 포함 ✅,
`stage_trigger:336` 에 "retry ON 이면 LIQUIDATED_WAITING_RETRY 에서만 진입" (= 1+2 동시보유 방지) ✅.
**청산 한 고리만 막혀서 그 코드에 도달할 수가 없었다.**

## Fix 173/174 — 단계 진입을 「운영 로직」으로

신설 `services/stage_entry_signal.py` = 자동 진입 워커와 **같은 함수를 같은 순서로**:
① `check_obv_gate` (**4H** OBV) ② `is_bidirectional_blocked` ③ `is_regime_blocked_for_short`(SHORT만) ④ `confirm_peak` (**15m**).

옛 `check_obv_reverse_signal` 이 신뢰 못 받은 이유 = **SHORT 하드코딩** / **3중 AND** /
**운영 로직과 다른 기준** / **차단 사유 미기록**. 이제 사유를 Redis 에 남긴다.

**Fix 174** = `LIQUIDATED_WAITING_RETRY` 분기가 OBV 분기보다 **먼저** 실행돼
("trigger_mode / OBV 무관" 주석까지 있었음) Fix 173 이 청산 후 경로에 안 닿았다 → OBV 모드면 운영 로직으로.

## Fix 175 — 사다리 전 소진 → 처음부터 재시작 (최대 2회, 사장님 선택)

신설 `workers/ladder_restart_worker.py` (5분). 기존 REENTRY_QUEUE 로는 안 됐다:
`_reentry_stage = count+2` (**2·3단계 금액**) + `strategy_type LIKE 'auto_bb_break%'` (**자동 생성만**)
→ 사장님 모달 전략은 대상 밖이었다.
카운터는 `ladder_restart_count:` 로 **분리** (auto_bb 의 `reentry_count:` 와 자본 프로필이 완전히 다름).

## Fix 176 — 피라미딩 = 사다리와 독립 고정값

사장님: "10 +5% 마틴게일 300 진입 이건 **초기 1단계 상관없이 300으로 고정**하고 300도 차후에 선택옵션으로"
옛 `ladder[1]` → 사다리 100/**500**/900 이면 500 을 따라갔다. 신 `sajangnim_pyramid_capital` (기본 300) + 세팅 UI.

## 🔑 사장님 결정 (이 날짜 기준)

1. **피라미딩 1회 = 300 고정** (사다리 무관, +5% 마다 최대 2회)
2. **재시작 = 2회** (총 3사이클)
3. **3단계 OBV STRICT = 그대로 둔다** ← 2026-08-27 선택
   → 3단계(6000)는 15m OBV 가 꺾여야만 진입 = 대부분 1·2단계에서 종료.
   → 2000/4000/6000 이면 주 경로 2000→4000, 3단계 미진입 시 사이클 최대 손실 **-300**.
4. **BTRUSDT 재진입은 2000/4000/6000** 희망 → ⚠️ **사다리 설정(전역) 말고 모달에 직접 입력**할 것.
   사다리는 자동 진입 워커 전용이라 바꾸면 **모든 종목**이 2000 으로 시작한다 (상한 40 → 최대 80,000 노출).

## ⚠️ 15분 게이트가 두 겹이다 (미해결, 사장님이 「그대로」 선택)

| 게이트 | 지표 | RSI 기준 |
|---|---|---|
| `confirm_peak` (Fix 111/173) | RSI·MACD·**CCI** | **≥65 에서 꺾임**, 2/3 |
| `_check_stage_indicator_reversal` (Fix 55, `stage_trigger:180`) | RSI·MACD·**OBV** | **1.0 이상 하락**, 2/3 · **3단계 3/3 STRICT** |

같은 15분 RSI 를 서로 다른 방식으로 두 번 본다 = 헌법 106 이 경고한 패턴.
Fix 55 는 `if next_stage_no >= 2` 하나로만 걸려 **모드 무관 공통 적용**된다.
`obv_slope = obv[-1] - obv[-5]` (75분). **3단계는 OBV 포함 3/3 필수.**

## ⚠️ #1488 관련 운영 주의

`create_strategy_instance` 에 **같은 계정/심볼/방향 활성 전략 중복 거부** 가드가 있다.
→ **#1488 을 닫기 전에는 BTRUSDT SHORT 새 전략을 만들 수 없다.**

**헌법 125** = 모델을 바꾸면 **옛 모델 전제의 게이트**가 어디 남아있는지 반드시 찾을 것.
**헌법 126** = 어떤 fix 가 **잠복 게이트를 깨울 수 있다** (사다리 정상화가 v130 게이트를 활성화).
**헌법 127** = 모델 선택은 **이미 있는 토글**로 표현할 것 — 새 설정은 모순 쌍을 늘린다.

관련: [[project_2026-08-26_killswitch_gaps]] [[project_2026-08-26_capital_ladder_and_silent_failures]]

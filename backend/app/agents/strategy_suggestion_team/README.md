# 🎯 Strategy Suggestion Team

## 미션
매일 학습 → 예측 → 신 전략 자동 생성 → 사장님 수동/자동 매매!

## 사장님 사고
- 매일 학습 = 급등/급락 예상!
- 급락 후 지속 하락 = 신 전략 제안!
- **기본 = 수동! (사장님이 결정!)**
- 옵션 = 자동 (차후!)
- 유지/삭제 관리!
- **만들어진 시간 표기!**

## 5개 에이전트

### 1. `pump_dump_predictor` (매일 06:30 UTC!)
- Market Flow + Timezone 팀 결과 참조!
- 4H OBV/RSI/BB 분석!
- 상위 20 예상 심볼 (pump/dump!)

### 2. `descent_pattern_detector`
- 급락 후 = OBV 매도세 유지?
- RSI 30 이하 지속?
- BB 하단 하방 이탈?
- → 지속 하락 예상 심볼!

### 3. `strategy_suggestion_generator` ⭐ 핵심!
- 예측 심볼 = 전략 draft!
- 사장님 신 default 자동 세팅!
- confidence_score 계산!
- DB 저장!

### 4. `suggestion_manager`
- 사장님 「❌ 삭제」 클릭 = 즉시 제거!
- 24h 미실행 = 자동 삭제 (선택!)
- 실행 완료 = archived!

### 5. `auto_manual_executor`
- **기본 = 수동!** (사장님 「▶」 클릭!)
- 사장님 옵션 = 「🤖 자동」!
- 자동 = 안전장치 필수!

## 대시보드 UI

```
🎯 자동 생성 전략 제안 [3건]    [⚙ 세팅]
━━━━━━━━━━━━━━━━━━━━━━━━━
📉 BTCUSDT SHORT | 신뢰도 87%
  ⏰ 생성: 2시간 전!
  📊 500 USDT × 2x, 강제 SL -15%
  💡 이유: OBV 매도세 + RSI 28
  [▶ 실행] [⚙ 자동] [❌ 삭제]
━━━━━━━━━━━━━━━━━━━━━━━━━
```

## 관련 spec
- `docs/STRATEGY_SUGGESTION_SPEC_v132.html`
- alembic 0027 (strategy_suggestions - 다음 세션!)

## 사장님 자율 100%!
- 기본 = 수동!
- 자동 = 선택 옵션!
- 헌법 C02 준수!

# C09. retry ON = 순차 진입! (동시 보유 X!)

## 원칙
retry_after_liquidation_enabled = True 전략:
- 각 단계 = 순차 진입!
- 절대 = 동시 보유 X!
- = 청산 후에만 = 다음 단계!

## 사장님 사고
"1단계 진입한것은 청산하고 0인 상태에서 2단계 200usdt가 진입하는건데"
= 사장님 = 순차 = 반드시!

## 동작
```
Case A (retry ON):
1단계 진입 → 손실 → 강제 SL 청산!
    ↓ (status = LIQUIDATED_WAITING_RETRY!)
청산가 기준 트리거 대기!
    ↓ (도달!)
2단계 진입! (신 로직!)

Case B (retry OFF):
1단계 진입 → +10% 도달!
    → 2단계 진입! (옛 stage_trigger 로직!)
    → 동시 보유 O!
```

## 에이전트 적용
- stage_trigger_worker = retry ON 전략 = 옛 로직 skip!
- 오직 LIQUIDATED_WAITING_RETRY 상태만 = 신 로직!

## 관련 fix
- v131 commit 4bb9054 (retry ON = 옛 stage skip!)
- #828 TSTUSDT 사례 fix!

## 관련
- C02 (사장님 사상)
- spec: retry_after_liquidation_v131.md

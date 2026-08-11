# C13. 다음 단계 남으면 SL 발동 X!

## 원칙
아직 진입 안 한 단계 (미체결!) = 존재 시:
- 강제 SL 발동 = 대기!
- 사장님 = 손실 회복 기회!

## 사장님 사고
- 4단계 세팅한 전략:
  - 1단계 진입!
  - 손실 -15% 도달!
  - **하지만 = 2/3/4단계 미체결!**
  - = 강제 SL 발동 X!
  - = 사장님 = 다음 단계 진입해 = 평단 개선!
  - = 손실 회복 기회!

## 로직 (risk_service.py)
```python
if force_sl_condition_met:
    if next_stage_exists (2/3/4단계 미진입!):
        logger.info("발동 조건 도달 but 다음 단계 남음 = 발동 X!")
        return  # 발동 X!
    else:
        # 마지막 단계 = 진짜 청산!
```

## 예외
- retry_after_liquidation_enabled = True 전략!
- = 청산 후 = 재진입 대기 = 신 로직!
- = 다음 단계 = LIQUIDATED_WAITING_RETRY!
- = 옛 SL 발동 X 로직 = 여전 유효!

## 관련
- C09 (retry 순차)
- v130 fix

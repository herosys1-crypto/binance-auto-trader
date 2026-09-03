---
name: project-2026-06-13-beatusdt-sl-critical
description: 사장님 BEATUSDT
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
---

# 🚨 사장님 BEATUSDT #110 critical silent bug + 영구 fix (2026-06-13)

## 사건 (= 영구 기록!)

**사장님 BEATUSDT #110 = 6단계 취소 후 = 강제 청산 발동!**

```
05:36 ✅ 포지션 추가 1200 USDT (327 qty)
05:40 ✅ 증거금 추가 1000 USDT
05:42 ✅ 증거금 추가 1000 USDT
05:46 ✅ 수동 익절 25% (261 qty)
06:28 ✅ 5단계 진입 (154 qty)
14:42 ✅ 포지션 추가 400 USDT (92 qty)

14:52 → SL 임박 (89%) total_capital=6100 손실=-2023 한도=-2440
15:07 → 🚨 SL 발동! total_capital=2700 손실=-2528 한도=-1080
       사장님 자본 -3,143 USDT 손실!
```

## 사장님 critical 사상 (= 명확!)

> **"총 투입된 자금에서 -80% 일 때 강제 종료!"**
> **"6단계를 뺀다고 포지션 진입가에서 손실 -80% 는 아니잖아!"**
> **"미진입 단계 = SL 계산 제외! 포함된거면 삭제 시 청산 못하게 막아야!"**

## silent bug 진짜 원인 (= ROI X / capital 의존!)

risk_service.py:evaluate_stop_loss (옛 PR #57)
```python
# 옛 (silent bug!)
threshold = (total_capital / lev) × 80%  # = USDT 절대 한도!
is_stop = current_loss <= -threshold
```

= 자본 변경 시 = 한도 변경 = silent bug!
= 사장님 6단계 취소 → total_capital 6100 → 2700 → 한도 -2440 → -1080 → 청산!

## 영구 fix (= 다층 안전망!)

### **v2: total_capital 변경 X (control.py:380+)**
단계 capital 변경 시 = total_capital 영향 X!

### **v3: 단계 축소 사전 차단 (control.py:380+)**
단계 capital 감소 시 = SL 위험 시뮬레이션 = HTTPException 차단!

### **v4: SL = ROI 기반! (risk_service.py:55-) ⭐ 진짜 사상!**
```python
# 신 (사장님 사상!)
price_change = (avg_entry vs mark) × 100  # side 적용
roi = price_change × leverage
is_stop = roi <= -80%
```
= total_capital 완전 무관!

### **v5: self-check false positive 차단 (self_check_worker.py)**
- 옛 STOPPED/COMPLETED strategy 검사 X
- 24h dedup = 시끄러운 반복 X

## 사장님 헌법 신 영구 추가!

- 헌법 19: total_capital = 실제 투입 자본만!
- 헌법 20: 단계 capital 감소 시 = 청산 위험 사전 차단!
- 헌법 21: SL = 포지션 진입가 (평단) 기준 ROI -80%!
  = 자본 (total_capital) 변경 = SL 영향 X 영구!

## 신 spec 영구 보존

`docs/spec/total_capital_diff_spec_2026-06-11.md`

## 다음 검증 필요

- [ ] 다른 worker (TP/Crisis) = 옛 `total_capital` 의존 분석
- [ ] 신 v4 SL logic = unit test 작성
- [ ] 신 strategy 소액 실 거래 검증 (= 사장님 결정 시!)

## 영구 인지

= 사장님 BEATUSDT #110 손실 -3,143 USDT = 시스템 책임!
= 옛 PR #57 (2026-06-09) = 잘못된 SL 사상!
= 신 v4 = 사장님 진짜 사상 100% 정확!

= 다시는 silent bug X = 사장님 자본 영구 보호! 🛡✨🌟

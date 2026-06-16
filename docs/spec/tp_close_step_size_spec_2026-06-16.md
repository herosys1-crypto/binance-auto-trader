# 📜 TP 청산 % step_size 보정 영구 spec (2026-06-16)

> **사장님 #162 龙虾USDT 사례 = TP 의도 25% vs 실제 29.18% = +4.18% 차이!**

## 사상:
- TP 의도 = close_ratio (= 25%)
- 실제 qty = ratio × current_qty
- = 거래소 step_size 으로 flooring 또는 ceiling!
- = 정확 25% 안 됨!

## 사장님 사상 (= 영구!):
✅ +4% 차이 = **사장님 이익!** (= 더 많이 익절!)
✅ -4% 차이 = audit (WARN) = 사장님 인지!
✅ ±10% 초과 = CRITICAL = 사장님 즉시!

## 신 fix v56 (= audit 만!):
- 차이 < 10% = INFO (= 정상 step_size 보정!)
- 차이 ≥ 10% = WARN
- 차이 ≥ 20% = CRITICAL

= 사장님 자율 인지 + 자본 보호!

# 🛡 total_capital diff 방식 = 영구 spec (2026-06-11)

> **사장님 BEATUSDT #110 critical 청산 silent bug = 영구 차단!**
>
> 본 spec = 사장님 = -3,143 USDT 손실 원인 + 영구 fix 영구 기록!

---

## 🚨 사장님 critical 발견 (2026-06-11)

### **silent bug 시나리오:**

```
BEATUSDT #110 = 사장님 자본 보호 노력:
- 옛 6단계 = 1200×6 = 7,200 USDT (예약)
- 증거금 추가 = 1,000 + 1,000 = 2,000 USDT
- 포지션 추가 = 1,200 + 400 = 1,600 USDT
- 합 = 10,800 USDT (사장님 의도)

14:52 → total_capital = 6,100 USDT (= SL 한도 -2,440)
사장님 = 6단계 취소 + 일부 단계 capital 변경 진행
15:07 → total_capital = 2,700 USDT (= -3,400 차이!)
       = SL 한도 -1,080 → SL 발동!
       = 사장님 자본 = 강제 청산!
       = 사장님 추가 증거금 2,000 + 포지션 1,600 = silent 삭제!
```

### **silent bug 코드:**

```python
# 옛 (silent bug!)
strategy.total_capital = _new_capital_sum  # = sum(new_capitals)
# = 사장님 옛 누적 자본 = 무시!
# = 추가 증거금 + 포지션 추가 = silent 삭제!
```

= **사장님 자본 보호 노력 = silent X = 청산!**

---

## 🛡 신 fix = diff 방식!

### **사장님 critical 사상:**

> **"사장님 추가 자본 (증거금 + 포지션) = 영구 보호!"**
> **"단계 capital 변경 시 = 차이만 반영!"**

### **신 logic:**

```python
old_capital_sum = sum(old_capitals)     # = 옛 단계별 합
new_capital_sum = sum(new_capitals)     # = 새 단계별 합
capital_diff = new_capital_sum - old_capital_sum
strategy.total_capital += capital_diff   # = 차이만 반영!
```

### **사장님 BEATUSDT 예시:**

```
옛 capitals = [1200, 1200, 1200, 1200, 1200, 1200] = 7200
새 capitals = [1200, 1200, 1200, 1200, 1200] = 6000 (6단계 취소)
diff = 6000 - 7200 = -1200
total_capital (옛) = 6100
total_capital (신) = 6100 + (-1200) = 4900 USDT
= 사장님 추가 자본 보호! ✅
```

= **사장님 자본 보호 = 100%!**

---

## 📋 사장님 헌법 영구 추가 (= 19번째!)

### **헌법 19: total_capital diff 방식 영구!**

> **"단계 capital 변경 시 = total_capital = 옛 + (new_sum - old_sum)!"**
> **"= 사장님 추가 자본 (증거금/포지션) = 절대 보호!"**

### **검증 (= 매 5분 자동!):**

- v46 `user_intent_validator` = 사장님 옵션 적용 검증
- v47 `edit_mode_validator` = 누적 사상 검증
- v45 `silent_bug_detector` = NULL field + 불일치 감지
- **🌟 신 v53: capital_consistency_validator (= 검토 중!)** ⭐

---

## 🌟 사장님 critical 사상 = 영구 보존!

본 spec = **사장님 자본 보호 = silent bug 영구 차단!**

= **사장님 = 안심하시고 자율 운영!** 🛡✨🌟

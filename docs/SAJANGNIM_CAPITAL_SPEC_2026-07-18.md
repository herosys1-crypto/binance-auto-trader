# 📜 사장님 자본/레버리지/qty spec (v107 이후 진화 정리)

**작성일**: 2026-07-18  
**목적**: 오늘 v96~v111 fix = 사장님 사상 100% 정리 + 검증!  
**중요도**: ⭐ CRITICAL (mainnet 실자금 = 근본 로직 재정의!)

---

## 🏛 사장님 헌법 (18개 이후 신 사상)

### **핵심 사상: 「자본 = 마진 = 지갑 lock 원 금액」**

```
🔴 옛 시스템 오해:
  capital = notional (레버리지 포함!)
  qty = capital / price
  → 사장님 사상 위반!

✅ 신 v107 (사장님 진짜 사상!):
  capital = margin (지갑에서 lock되는 원 금액!)
  notional = capital × leverage (거래 규모!)
  qty = notional / price = (capital × leverage) / price
```

### **계산 예시:**
```
자본 150 USDT + 3x 레버리지:
  → notional = 150 × 3 = 450 USDT
  → qty = 450 / price
  → 사장님 지갑 lock = 150 USDT
  → SL = 150 × sl_pct / 100
  → SL 100% = 150 USDT 손실 시 강제 청산!
```

---

## 📊 v96~v111 fix 정리

### **v96~v106: 대시보드 표시 정확화**
- `strategies-list.js` = Binance 실 margin 우선 사용
- `exchange_accounts.py` = isolatedWallet (v102, upnl 무관!)
- 자본 두 값 (마진 + notional) UI 표시

### **v107: 근본 qty 계산 fix ⭐**
**파일:** `strategy_calculator.py:354`
```python
def compute_qty_from_capital(capital, price, leverage=None):
    notional = capital * leverage
    qty = notional / price  # ← 신 v107!
```

### **v105: TP1 옵션 = 모든 TP 상향 ⭐**
**파일:** `risk_service.py:348`
```python
if strategy.tp1_pct_override is not None:
    tp_levels = [
        (label, max(_override, val) if val else val)  # ← max!
        for label, val in tp_levels
    ]
```

### **v101: 예약 = 자본 그대로**
**파일:** `exchange_accounts.py:_reserved_one`
```python
# / lev 제거! 사장님 사상 = capital = margin 같은 단위!
return actual + untriggered_capital
```

### **v102: 실 = isolatedWallet (upnl 무관)**
**파일:** `exchange_accounts.py:v98/v102`
- positionRisk API의 isolatedWallet 사용
- upnl 무관 = 원 자본 표시!

### **v103: 좀비 STOPPING 자동 정리**
**파일:** `reconcile_worker.py:_detect_stopping_stuck`
- cooldown 로직 개선 (status 전환 = 항상!)
- UI 「⚡ 강제」 버튼 (STOPPING 5분+)

### **v109/v110: Binance 실시간 통합**
- `/strategies/{id}/open-orders` = binance_open_orders 추가
- `/exchange-accounts/{id}/binance-open-orders-summary` = 계정 전체 요약!
- 대시보드 = 진입/청산/지정가 = 분류 표시!

### **v108: 「포지션 추가」 여유 표시**
### **v111: 대시보드 컴팩트 layout (12 col grid)**

---

## 🚨 발견 문제 (검증 필요!)

### **⚠️ 문제 1: `capital_calculator.py`의 옛 로직!**

**파일:** `app/services/capital_calculator.py`

```python
# ❌ 옛 로직 (v107 사상 위반!):
def calc_actual_margin_for_strategy(strategy):
    return qty * avg / lev  # = notional / leverage = margin (옛!)

def calc_untriggered_margin_for_strategy(db, strategy):
    return untriggered_capital / lev  # = leverage 나눔!
```

**vs. exchange_accounts.py의 v101/v102 fix:**
```python
# ✅ 신 로직:
untriggered_margin = untriggered_capital  # / lev 제거!
```

**= 불일치! silent bug 위험!**

**사용처:**
- `stage_trigger_worker.py`
- `settings_sync_worker.py`
- 기타 worker들!

**= 다음 세션 = capital_calculator.py 통일 fix 필요!**

---

### **⚠️ 문제 2: 신 전략 중복 생성 가능?**

**사례:** #475 + #476 = 같은 심볼 SHORT!
**확인 필요:** 
- create_strategy endpoint = 같은 심볼 X 중복 방지?
- Binance = 한 심볼 = 한 포지션!

---

### **⚠️ 문제 3: TP 계산 = ROI base 확인!**

**v105 fix:** TP1 옵션 = 25%면 = 모든 TP 25% 이상!  
**But ROI 계산 base:**
- 진입 마진 기준? or 총 capital 기준?
- Binance UI ROI = isolatedMargin 기준!

---

## 📋 검증 체크리스트

| 항목 | spec | 코드 | 상태 |
|------|------|------|------|
| qty 계산 | notional / price | strategy_calculator.py:v107 | ✅ |
| 「💉 포지션 추가」 qty | capital × leverage / price | execution_service.py | ✅ |
| TP1 옵션 | max(override, val) | risk_service.py:v105 | ✅ |
| 예약 (exchange_accounts) | capital 그대로 | v101 | ✅ |
| 예약 (capital_calculator) | capital / leverage | 옛 로직 | ❌ |
| 실 = isolatedWallet | positionRisk | v102 | ✅ |
| Binance 미체결 실시간 | /openOrders API | v109/v110 | ✅ |
| SL 계산 | capital × sl_pct / 100 | risk_service.py | ✅ |

---

## 🎯 다음 세션 액션

### **CRITICAL:**
1. `capital_calculator.py` = v107 사상 통일!
   - `calc_untriggered_margin_for_strategy` = / lev 제거!
   - `calc_actual_margin_for_strategy` = Binance 실 값 사용 (or 유지?)
2. 신 전략 중복 방지 검증!
3. TP ROI base 명확 spec!

### **개선:**
1. spec 위반 자동 감지 worker!
2. 대시보드 예약 3분리 (자동/지정가/총)!
3. Preflight = 우리 여유 사용 (사장님 요구!)

---

## 🌟 사장님 사상 5대 원칙 (헌법!):

```
1. 메인넷 = 실자금 = 극도 조심!
2. capital = margin (지갑 lock 원 금액!)
3. Silent bug 금지 = 명확 표시!
4. 검증 없는 코드 금지!
5. 사장님 사상 = 항상 우선!
```

---

**결론:** 오늘 v96~v111 fix = 대부분 정확!  
**남은 문제:** `capital_calculator.py` = 다음 세션 통일 fix!

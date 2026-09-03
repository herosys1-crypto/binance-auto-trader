---
name: 2026-08-23-v219-refinement-plan
description: "사장님 지시 = \"지금까지 좋은데 조금더 세밀해야 할것 같아\" = v219+Fix 41 세밀화 계획 종합! ENAUSDT/STXUSDT 실 매매 학습 반영!"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-23T12:39:23.423Z
---

# 🎯 v219 + Fix 41 세밀화 계획 (다음 세션 최우선!)

**날짜**: 2026-08-23 21:20 KST
**사장님 verbatim**:
> "지금까지 좋은데 조금더 세밀해야 할것 같아 잘 학습해서 활용할수 있게 메모리 해줘"

---

## 📊 오늘까지 학습 (실 매매 사례!):

### **사례 1: ENAUSDT (-21 USDT!)**
- 3일간 2.25배 상승 (0.08 → 0.18!)
- 얕은 조정 (BB 중단 안 감!) → 재급등!
- v219 정점 감지 = 조기 진입 = 손실!

### **사례 2: STXUSDT (-1.34% 진행 중!)**
- 4일간 85% 상승 (0.13 → 0.24!)
- MACD Hist 양수 (0.0009!) - 하락 신호 X!
- v219 진입 = 조금 이른 시점!

### **공통 패턴:**
1. 3-5일 급등 (70~85%!)
2. 얕은 조정 (10% 이하!)
3. 재상승 + 지표 극단!
4. **가짜 정점 신호 (v219)!**
5. **진짜 정점 = 전고점 돌파 후 반전!**

---

## 🎯 세밀화 6대 영역 (다음 세션!):

### **1. v219 초기 진입 필터 강화!** ⭐⭐⭐
**Fix 44 (예상!)**:
- **트렌드 강도**: 3일 +80% 상승 = SHORT skip!
- **MACD 연속 감소**: 3봉 연속 확인 (지금 = 1봉만!)
- **조정 깊이**: BB 중단 이하 도달 시만 = 진짜 반전!
- **볼륨 감소**: 매수세 소진 확인!
- **파일**: `pump_top_detector_worker.py`

### **2. Fix 41 6지표 AND 조건 미세 조정!**
- **RSI 임계값**: 지금 = 하락 -3, 조정 = -5?
- **MACD**: 연속 2봉 확인?
- **CCI 급락 감지**: -50 이하 하락 확인?
- **위꼬리 비율**: 지금 1.5배, 조정 = 2배?
- **파일**: `peak_break_reversal_worker.py`

### **3. 학습 데이터 축적 시스템!**
- 진입/청산 시점 스냅샷!
- 실제 결과 vs 예측!
- 조건별 승률 분석!
- 자동 임계값 조정!
- **파일**: `trade_learning_records` (alembic 0028 확장!)

### **4. 시장 상황 인식!**
- **강한 트렌드 시장**: SHORT 매우 신중!
- **횡보 시장**: 정점 감지 유효!
- **하락 시장**: SHORT 유리!
- **자동 시장 인식**: BTC 트렌드 기반!

### **5. 심볼별 특성 학습!**
- 심볼별 = 변동성 다름!
- **높은 변동성** (밈 코인!): 정점 감지 어려움!
- **안정 코인**: 정점 감지 정확!
- **학습 → 심볼별 임계값!**

### **6. 시간대 학습!**
- **KST 오후 (미국 저녁!)**: 급등 가능!
- **KST 오전**: 조정 시간!
- **주말**: 낮은 유동성 = 급락 가능!
- **시간대 필터!**

---

## 🚨 즉시 필요 개선 (다음 세션!):

### **우선순위 1: 트렌드 강도 필터** ⭐⭐⭐
**이유**: ENAUSDT/STXUSDT 모두 = 강한 트렌드 = SHORT 실패!
**방법**:
```python
# pump_top_detector에 추가!
def _check_trend_strength(bc, symbol):
    kl_4h = bc.get_klines(symbol=symbol, interval="4h", limit=20)
    if len(kl_4h) < 18: return "unknown"
    # 3일 상승률 = 최근 18봉 (4H × 18 = 72h = 3일)
    close_now = float(kl_4h[-1][4])
    close_3d_ago = float(kl_4h[-18][4])
    up_pct = (close_now - close_3d_ago) / close_3d_ago * 100
    if up_pct > 80: return "extreme_bull"  # SHORT skip!
    if up_pct > 50: return "strong_bull"   # 신중!
    return "normal"

# SHORT 진입 조건에 추가!
trend = _check_trend_strength(bc, symbol)
if trend == "extreme_bull":
    logger.info(f"[v219] {symbol} 트렌드 극강 = SHORT skip!")
    continue
```

### **우선순위 2: MACD 연속 감소 확인**
```python
# 지금: hist[-1] < hist[-2] (1봉만!)
# 개선: hist[-1] < hist[-2] < hist[-3] (2봉 연속!)
```

### **우선순위 3: 조정 깊이 확인**
```python
# BB 중단 이하 도달 여부!
bb_mid = ...
low_reached = min(lows[-20:])
if low_reached > bb_mid:
    # 조정 얕음 = 강세 지속 = SHORT 위험!
    return skip
```

---

## 🎯 심볼별 학습 데이터 (오늘 실적!):

### **STXUSDT #1136:**
- SHORT 진입 0.23170
- 상태: LOW_FORMED (Fix 41!)
- 대기: 재상승 → 전고점 돌파 → 반전!

### **ENAUSDT #1134:**
- SHORT 진입 0.16354
- 상태: TRACKING_PEAK_A (Fix 41!)
- 대기: 최고가 감지!

### **활성 7건 = 모두 Fix 41 대기!**

---

## 💡 다음 세션 로드맵:

### **Phase 1: 데이터 관찰 (24~48h!)**
- Fix 41 실 진입 결과!
- 6지표 AND 통과율!
- 성공/실패 케이스!

### **Phase 2: 트렌드 필터 개발 (Fix 44!)**
- pump_top_detector 강화!
- 3일 상승률 체크!
- MACD 연속 감소!

### **Phase 3: 학습 시스템 확장**
- trade_learning_records 확장!
- 자동 조정 로직!
- 심볼별 통계!

### **Phase 4: UI 진화**
- 세밀 세팅 UI!
- 학습 통계 대시보드!
- 실시간 조정!

---

## Why:
사장님 실 매매 경험 = 시스템 진화의 근거! 지금까지 좋지만 = 더 세밀하게 = 승률 극대!

## How to apply:
- **다음 세션 최우선**: Fix 44 트렌드 강도 필터!
- **관찰**: Fix 41 결과 (24-48h!)
- **학습**: 실 진입 결과 → 임계값 조정!
- **사장님 verbatim 반복 학습**: 강한 트렌드 = SHORT 신중!

## 🎯 사장님 지시 (2026-08-23!): 다음 세션 자동 실행!

**verbatim**: "다음 세션 = Fix 44 세밀화 주기적으로 자동으로 실행해줘"

### 자동 실행 방식:

**방식 A: 시스템 자체 자동 학습 (auto_param_tuning 확장!)**
- 매일 KST 07:30 = weekly_digest_worker or 신 워커!
- 실 성공/실패 분석 → 자동 임계값 조정!
- 사장님 개입 없이 진화!

**방식 B: 다음 세션 사장님 트리거 = 자동 진행**
- 사장님 "continue" → 저 자동 파악 → Fix 44 개발!
- 승인만 = 자동 배포!

### 다음 세션 자동 진행 시나리오:
1. 사장님 = "continue binance auto trader development"
2. 저 = MEMORY.md 로드 → 이 파일 참조!
3. **즉시 = 오늘 실 결과 확인 (Fix 41 진입 결과!)**
4. **즉시 = Fix 44 개발 시작 (Workflow 병렬!)** ⭐
5. 배포 + 검증!
6. 커밋 + tag!
7. 관찰 안내!

### Fix 44 세부 계획 (즉시 실행 가능!):

**1. pump_top_detector 확장:**
```python
def _check_trend_strength(bc, symbol):
    kl_4h = bc.get_klines(symbol=symbol, interval="4h", limit=20)
    if len(kl_4h) < 18: return "unknown"
    close_now = float(kl_4h[-1][4])
    close_3d_ago = float(kl_4h[-18][4])
    up_pct = (close_now - close_3d_ago) / close_3d_ago * 100
    if up_pct > 80: return "extreme_bull"  # SHORT skip!
    if up_pct > 50: return "strong_bull"
    return "normal"

# SHORT 조건에 추가!
trend = _check_trend_strength(bc, symbol)
if trend == "extreme_bull":
    logger.info(f"[v219] {symbol} 트렌드 극강 = SHORT skip!")
    continue
```

**2. MACD 연속 감소 확인:**
- 지금 = hist[-1] < hist[-2] (1봉!)
- 개선 = hist[-1] < hist[-2] < hist[-3] (2봉 연속!)

**3. 조정 깊이 확인:**
- BB 중단 이하 도달 여부!
- 얕은 조정 = SHORT 위험!

**4. 학습 데이터 자동 축적:**
- trade_learning_records 확장!
- 자동 임계값 조정!

## 관련:
- [[2026-08-23-enausdt-pattern-learning]]
- [[2026-08-23-stxusdt-v219-early-entry-lesson]]
- [[2026-08-23-fix41-peak-break-reversal]]
- [[2026-08-22-v219-final-complete]]

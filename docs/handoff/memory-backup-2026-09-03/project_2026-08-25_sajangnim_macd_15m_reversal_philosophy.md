---
name: 2026-08-25-sajangnim-macd-15m-reversal-philosophy
description: "🌟 사장님 신 매매 사상 (2026-08-25!): MACD 15분 하락→반등 시작점 + 반등→하락 시작점 = 진입 시그널! 15m + 4H 통합 방향 판단!"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-25T04:52:30.017Z
---

# 🌟 사장님 신 매매 사상 v3 (2026-08-25!) = MACD 15m 변곡점!

## 사장님 verbatim:

> **"macd 15분 하락 후 반등 시작점과 반등후 하락 위치를 참고해줘 15분과 4시간의 움직임을"**

**분석 사례**: AEROUSDT (24h +17.38%!)
- **4H**: BB 상단 근접, RSI 85.46 (과매수!), MACD Hist 상승!
- **1H**: RSI 70, MACD Hist 상승!
- **15m**: MACD Hist 하락→반등→하락 사이클!

---

## 🎯 사장님 핵심 사상:

### **15m MACD 변곡점 = 신 진입 시그널!**

1. **바닥 반전 (하락 → 반등 시작!)** = **LONG 진입!**
   - MACD Hist 음수 지속 → 첫 양전환 봉!
   - OR MACD Line이 Signal Line을 상향 돌파!
   - + 볼륨 증가 확인!

2. **정점 반전 (반등 → 하락 시작!)** = **SHORT 진입!**
   - MACD Hist 양수 지속 → 첫 음전환 봉!
   - OR MACD Line이 Signal Line을 하향 돌파!
   - + 볼륨 증가 확인!

### **4H 방향 필터 (필수!)**
- **15m LONG 진입** → **4H MACD Hist 양수 OR 상승 중!**
- **15m SHORT 진입** → **4H MACD Hist 음수 OR 하락 중!**
- **4H와 반대 방향 = skip!** (사장님 verbatim = "참고!")

---

## 📊 AEROUSDT 실 분석 (2026-08-25 UTC 13:00):

### **4H 상태 (큰 방향!):**
- **가격**: 0.5598 (BB 상단 0.5610 근접!)
- **RSI(6)**: **85.46** (과매수 극단!)
- **RSI(12)**: 76.99 / **RSI(24)**: 71.33
- **MACD Hist**: **+0.0078** (양수 지속!) = **LONG 지속!**
- **MACD Line**: 0.0170 > Signal 0.0249 → 하지만 최근 약화!
- **CCI(9)**: 103.35 (과매수!)
- **OBV**: 135.765M (상승 지속!)
- **볼륨**: 최근 급증!

### **1H 상태:**
- **RSI(6)**: 70.27 (과매수!)
- **MACD Hist**: +0.0015 (양수, 약화!)
- **볼륨**: 최근 급증!

### **15m 상태 (신호 확인 시점!):**
- **RSI(6)**: 58.72 (**중립 하락!**) ⚠️
- **MACD Hist**: **+0.0003** (매우 약화!) ⚠️
- **MACD Line**: 0.0055 < Signal 0.0058 → **하락 시작!** ⚠️
- **CCI(9)**: **-63.50** (음수!) ⚠️

---

## 🎯 AEROUSDT 판정 (사장님 사상 v3 적용!):

### **15m 신호 = SHORT 후보!** (반등 후 하락 시작!)
- ⚠️ **MACD 상승 중 → 최근 약화 → Signal 하회!**
- ⚠️ **CCI 음수 = 하락 신호!**
- ⚠️ **RSI 중립 = 상승 힘 X!**

### **4H 필터 = SHORT 지원!**
- ✅ **RSI 85.46 (극단 과매수!)** = 되돌림 확실!
- ✅ **BB 상단 근접!** = 저항!
- ⚠️ **but MACD Hist 여전히 양수!** = 조심!

### **결론:**
- **주의 SHORT 후보!** = 15m 하락 시작 + 4H 극단 과매수!
- **but 아직 4H MACD 양수** = 확실치 X!
- **더 명확한 신호 = 15m MACD 완전 음전환!** = 확실 SHORT!

---

## 🌟 신 워커 개발 방향 (사장님 승인 대기!):

### **`macd_reversal_15m_worker.py`** (신설!)
- **주기**: 매 3분 (15m 봉 완성 감지!)
- **감지**:
  * 15m MACD Hist 변곡점 (양전환/음전환!)
  * 15m MACD Line/Signal 크로스오버!
- **필터**:
  * 4H MACD 방향 일치!
  * 볼륨 증가 확인!
  * OBV 방향 일치!
- **자본**: 300 USDT 1단계!
- **SL**: -5%!
- **재진입**: realtime_reentry 마틴게일 활용!

---

## 🚨 헌법 77 (신설!):

> **"15m MACD 변곡점 = 진입 신호! 4H 방향 = 필터!"**
> - MACD Hist 양전환 + 4H 상승 = LONG!
> - MACD Hist 음전환 + 4H 하락 = SHORT!
> - 4H 반대 방향 = skip!

---

## Why:
사장님이 AEROUSDT 차트 (4H/1H/15m) 3장 제시!
= MACD 사이클 인식 사상!
= 기존 지표 조합 + 시간대 통합!

## How to apply:
- 다음 개발 우선순위 1!
- macd_reversal_15m_worker.py 신설!
- 4H 방향 필터 필수!
- 볼륨 + OBV 확인!

## 관련:
- [[2026-08-25-sajangnim-long-short-philosophy-v2]] (사장님 사상 v2!)
- [[2026-08-25-orchestra-2day-final]] (오늘 최종!)
- Fix 67 (BB 상단 돌파!) 와 상호 보완!

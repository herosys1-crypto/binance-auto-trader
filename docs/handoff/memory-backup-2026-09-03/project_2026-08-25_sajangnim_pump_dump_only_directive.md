---
name: 2026-08-25-sajangnim-pump-dump-only-directive
description: "🌟 사장님 CRITICAL 사상 (2026-08-25!): '전략에 들어가는건 당일 급등락한 심볼만 거래' = LONG=급락만 / SHORT=급등만! 헌법 78!"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-25T07:58:24.110Z
---

# 🌟 사장님 CRITICAL 사상 = 급등락 심볼만!

## 사장님 verbatim (2026-08-25!):

> **"전략에 들어가는건 당일 급등락한 심볼만 거래하는거야"**

## 의미:

- **SHORT 진입** = **당일 급등 심볼만!** (예: 24h ≥ +10%!)
- **LONG 진입** = **당일 급락 심볼만!** (예: 24h ≤ -10%!)
- **일반 심볼 (변동 미미!) = 절대 진입 X!**

## Why:
- 사장님 실 매매 경험 = **급등락 심볼 = 되돌림 확실!**
- 일반 심볼 = 방향 예측 어려움!
- **급등후 SHORT = 확실한 되돌림!**
- **급락후 LONG = 확실한 반등!**

## 🚨 헌법 78 (신설!):

### **"전략 진입 = 당일 급등락 심볼만!"**

**필터 기준:**
- **SHORT**: 24h ≥ **+10%** (급등!)
- **LONG**: 24h ≤ **-10%** (급락!)
- **중간 (-10% ~ +10%) = 진입 절대 금지!**

**예외 심볼도 X:**
- 예외적 상황 (BB 상단 돌파 등!)도 = 24h 급등락 필수!
- 실 성공 조건 = **극단 변동!**

## How to apply:

### **즉시 수정 필요 워커 (7개!):**

1. **auto_short_at_top_worker.py** ✅ 이미 24h +15%+ (헌법 64 = SHORT skip 아님!)
   - **but 필터 완화 검토** (+15% → +10%!)

2. **auto_long_at_bottom_worker.py**:
   - **현재 = 24h -15% ~ +10%** = 너무 관대!
   - **신 = 24h ≤ -10% 필수!**
   - **또는 이미 하락 지속 심볼!**

3. **long_bottom_detector_worker.py** (Fix 50 v2):
   - Pattern A (상승 지속!) = **삭제!** (당일 급등 X = 진입 X!)
   - Pattern B (조정 반등!) = **-10% 이하만!**

4. **macd_reversal_15m_worker.py** (Fix 74):
   - 현재 = **±15% 극단 skip** (헌법 64!)
   - **정정**: LONG = ≤ -10%만! SHORT = ≥ +10%만!
   - 중간 = skip!

5. **pump_dump_early_detector_worker.py** (Fix 62):
   - 이미 +15% 급등 조건 = OK!

6. **bb_upper_breakout_short_worker.py** (Fix 67):
   - 이미 +15%+ = OK!

7. **pump_top_detector_worker.py** (v219):
   - 이미 급등 = OK!

## 🎯 우선순위:

**우선 1**: `auto_long_at_bottom_worker.py` = 급락 필터 강화!
**우선 2**: `long_bottom_detector_worker.py` = Pattern A 삭제!
**우선 3**: `macd_reversal_15m_worker.py` = LONG 급락 필수!

## 관련:
- [[2026-08-25-sajangnim-long-short-philosophy-v2]] (사장님 사상 v2!)
- [[2026-08-25-sajangnim-macd-15m-reversal-philosophy]] (Fix 74 사상!)
- [[2026-08-25-sajangnim-no-blocklist-directive]] (blocklist 해제!)
- 헌법 64 (급등 반대매매 금지!) - **관련!**
- 헌법 76 (심볼 blocklist 금지!) - **관련!**

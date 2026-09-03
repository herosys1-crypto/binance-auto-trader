---
name: 2026-08-25-pump-dump-failure-pattern-learning
description: "PENGUUSDT + XPLUSDT 실패 학습! 4H OBV 극단 음수 + 급등 완성 후 하락 국면 = LONG/SHORT 모두 위험! 양방향 실패 심볼 = 7일 blocklist 필요!"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-24T19:04:59.357Z
---

# 🎓 실패 패턴 학습 (PENGUUSDT + XPLUSDT!)

**날짜**: 2026-08-25

## 공통 실패 패턴:

### PENGUUSDT LONG 2회 = -55.42 USDT!:
- 4H OBV = **-1.684B** (극단!)
- 급등 완성 후 하락 국면!
- LONG 진입 = 대실패!

### XPLUSDT 양방향 4회 = -51.88 USDT!:
- 4H OBV = **-3.328B** (매우 극단!)
- 8/19~8/22 급등 (+56%!) → 8/23~ 하락
- LONG 2회 (하락 국면 진입!) + SHORT 2회 (이미 늦은 진입!) = 모두 실패!

## 공통점 = 4가지!:
1. **4H OBV = 매우 큰 음수** (세력 이탈 확실!)
2. **급등 완성 후 하락 국면!**
3. **RSI < 50 + MACD Hist 음수 + CCI < -100!**
4. **양방향 = 예측 불가!**

## 이미 배포 (Fix 65!):
- ✅ OBV 극단 감지 = LONG/SHORT 자동 skip!
- ✅ obv_gate.py 공통 서비스!

## 추가 필요 (Fix 66!):
1. **양방향 실패 심볼 = 7일 blocklist!**
   - XPLUSDT / TAOUSDT / UNIUSDT / NEARUSDT!
   - Redis 저장 → 모든 진입 워커 참조!

2. **"급등 완성 후 하락 국면" 감지!**
   - 최근 3일 급등 (+30%+) → 하락 시작!
   - LONG 절대 금지!
   - SHORT도 = 하락 중반 이후 = skip!

## 진입 규칙 (사장님 사상 정리!):

### LONG:
- 4H OBV 양수/상승 (>+500M!)
- 상승 초기 (BB MB 위, MA 정배열!)
- RSI 30~55
- MACD Hist 양수/반전!

### SHORT:
- 4H OBV 음수/하락 (-500M ~ 정상)
- 정점 형성 초기 (BB 상단 근접 후 밀림!)
- RSI 60~75
- MACD Hist 음수/반전!

### 절대 금지:
- 4H OBV 극단 (±20 ratio) = Fix 65 자동!
- 반복 실패 (양방향) = Fix 66 필요!
- 급등 완성 후 하락 국면 = Fix 66 필요!

## 차트 조합 규칙:
- **BB + OBV**: BB 상단 도달 + OBV 이탈 = 정점!
- **RSI + MACD**: 두 지표 방향 일치 필수!
- **CCI + OBV**: 방향 확정!
- **볼륨 + MACD Hist**: 볼륨 감소 + Hist 음전환 = 매도 세력!

## Why:
사장님 실 매매 사고 학습 = 시스템 진화!
Fix 65 (OBV 극단!) 이미 완성 = LONG 방지 확실!
Fix 66 (양방향 blocklist + 급등 국면!) = 다음 개발!

## 관련:
- [[2026-08-24-obv-absolute-priority]] (OBV 원칙!)
- [[2026-08-24-fix48-obv-hierarchy-trading]] (OBV 계층!)
- [[2026-08-24-fix45-seryeok-pattern-recognition]] (세력 그림!)

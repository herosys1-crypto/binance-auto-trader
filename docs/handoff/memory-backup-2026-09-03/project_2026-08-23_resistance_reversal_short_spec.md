---
name: 2026-08-23-resistance-reversal-short-spec
description: 사장님 신 사상 「저항 반전 SHORT 2단계 진입」 = COTIUSDT 사례 = 저항선 접근 시 반전 감지 후 마틴게일 2단계 자동 SHORT! (2가지 시나리오 A/B!)
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-23T07:13:46.136Z
---

# 🎯 사장님 신 사상 = 「저항 반전 = 2단계 SHORT!」

**날짜**: 2026-08-23  
**사례**: COTIUSDT SHORT 포지션 관리 중!  
**저항**: 0.013354 (전고점!)

---

## 📊 사장님 verbatim:

> "전고점 13354가 최대 저항인데 이것을 돌파했다가 하락시점에 2단계 진입을 해야 할것 같아"

> "0.013354 아니면 돌파전에 하락하는 시점에 2단계 진입으로 봐도 될것 같아"

---

## 🎯 2가지 시나리오 (사장님 명시!):

### **㉠ 시나리오 A = 저항 도달 실패 후 하락!**
- 심볼이 저항 근접 (±0.5~1%)
- 저항 못 뚫음 = 위꼬리 음봉!
- 반전 신호 = 2단계 SHORT!

### **㉡ 시나리오 B = 저항 돌파 후 Fake Breakdown!**
- 심볼이 저항 순간 돌파 (스파이크!)
- 1-2봉 내 다시 아래!
- Fake breakout = 2단계 SHORT!

**= 둘 다 = 저항 근처 = 매도 심리 극대화!**

---

## 🔍 자동 감지 조건:

```
IF 심볼_현재가 접근 (저항 ±1%)
AND (시나리오 A: 저항 <-접근-> RSI 6 >= 78 -> 하락 반전
     OR 시나리오 B: 저항 <-순간 돌파-> 1-2봉 내 아래로)
AND 확인 지표:
   ✅ 15m 위꼬리 음봉 (윗꼬리 >= 실체 1.5배)
   ✅ RSI 6 = 최고점 (전 봉 대비 하락!)
   ✅ MACD Hist 감소 시작!
   ✅ CCI(9) >= 180 → 하락!
   ✅ 볼륨 감소 (매수세 소진!)
THEN → 자동 2단계 SHORT (마틴게일 600 USDT!)
```

---

## 💡 구현 방안:

**A. 신 워커 = `resistance_reversal_worker`** ⭐ (추천!)
- 매 30초 실행
- 활성 SHORT 전략의 저항선 감시
- 반전 감지 시 = 자동 2단계 진입!

**B. 기존 확장 = `pump_top_detector`에 추가**
- v219 로직에 「전고점 반전」 추가

**C. 수동 관리 = 사장님이 직접!**

---

## 🎼 시스템 연계:

- **마틴게일 사장님 사상 (v219)**: 
  - 1단계 = 300 USDT
  - **2단계 = 이전×2 = 600 USDT!** ← 여기 적용!
  - 3단계 = 투자금 전체×2 = 1800 USDT (매우 신중!)
  - 4단계+ = 금지!

- **강제 SL v219 = -80%!** (이미 v225 반영!)

- **트리거 방향**: SHORT 전용!

---

## Why:
사장님 = 실전 매매에서 검증! 「저항선 반전」 = 매도 심리 극대화 = 승률 높은 진입! COTIUSDT SHORT 관리 중 = 사장님 우려 = 상승 지속 시 마틴게일 자동화 필요!

## 완성 상태 (2026-08-23 16:12 KST):
- ✅ **DB 필드 4개** (alembic 0032!) = resistance_price + source + detected_at + triggered_at
- ✅ **worker.py 신설** = backend/app/workers/resistance_reversal_worker.py (매 30초!)
- ✅ **scheduler 등록** = IntervalTrigger(seconds=30)
- ✅ **COTIUSDT #1128 저항 지정** = 0.013354 (user)
- ✅ **자동 실행 검증** = scanned=3, errors=0 (신 SHORT도 자동 감지!)
- ✅ **커밋 2건** = a6cefe6 + e1db2a8 (fix branch = feat/fix29-resistance-reversal-short)
- ⏳ **push** = 사장님 GitHub 웹 UI 정책 = 서버에서 X, 나중에!

## How to apply (이제 자동!):
- **신 SHORT 진입** = 자동 감지 (7일 15m 최고가!)
- **COTIUSDT** = user 지정 우선 (0.013354!)
- **저항 접근 (±1%)** = 5지표 반전 검사!
- **반전 = 즉시 자동 2단계 SHORT (600 USDT!)!**
- **텔레그램 알림 필수!**
- **PR 필요**: 사장님이 GitHub 웹에서 = feat/fix29-... → main 병합!

관련: [[2026-08-22-v219-final-complete]] (v219 완성!) / [[feedback_no_unrequested_features]] (사장님 명시 요구까지만!) / [[feedback_orchestra_agent_validation]] (Agent 검증 필수!)

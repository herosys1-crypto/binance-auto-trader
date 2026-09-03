---
name: project-gemini-session-summary
description: 「Gemini 채팅 인터페이스」 세션 요약 = 사장님 매매 사상 30개 흐름 (2026-08-14 이전!)
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-14T01:16:36.156Z
---

# 📊 「Gemini 채팅 인터페이스」 세션 = 사장님 매매 사상 30개

## 세션 파일:
`C:\Users\user\.claude\projects\C--Users-user------binance-auto-trader\c83fb51f-c7ba-48ff-9868-b11fa5654bff.jsonl` (8.9MB, 30 user + 208 asst)

## 🎯 사장님 매매 사상 (15개 핵심!):

### 1. 매매 학습 시스템 (성공/실패 → 로직 반영!) [#3]
### 2. 15분봉 천장 + 볼밴중단 (주 매매!) [#4]
- 15분봉 = 주 매매! 1h/4h = 보조!
- **볼밴 중단 = 매매 기준!**
### 3. MACD + OBV + RSI + Volume (4대 지표!) [#5]
### 4. 15분 20% 전후 급등락 = 실시간 진입! [#6~9]
- 15분봉 **20% 전후만** = 실시간 진입!
- 급락 후 상승 패턴 분석!
### 5. 4시간 볼밴 중단 이탈 = 하단까지! [#10]
- 4시간 볼밴 중단 깨면 → 하단까지 추가 하락!
- 볼밴 하단 = 잘 깨지 X!
### 6. 급등락 실시간 vs 자동 전략 = 분리! [#11]
- **급등락 실시간 = 15분 20%!**
- **자동 전략 = 4시간 볼밴 중단/하단!**
### 7. 20% 이상 = **반대 매매 유리!** [#12]
- 알트코인 = 급등락 반복 = 반대매매!
### 8. 20% 이상 = 분할 매수 = 안정 수익! [#13]
- 평균가 진입!
- 안정 하락/상승 → 추가 진입!
### 9. 20% 급등 후 100% 급등 케이스! [#14]
- 지속 상승 패턴 로직!
- 1분/5분 = 진입 결정!
- **최대 3단계 = 고점!**
### 10. 롱/숏 동시! [#15]
- 급등 후 하락 = SHORT / 지속 상승 = LONG 짧게!
### 11. **17.5~27.5% 급등만 LONG!** [#30]
- **급락 = 진입 X!** (사장님이 결정!)
- 「이건 아니야 결제는 내가 해!」
### 12. 15분 급등/급락 팝업창 각각! [#17, #26, #27]
- 급등 팝업 / 하락 팝업 = 별도!
### 13. PnL/ROI 액션 = **-5% 기본!** [#17, #18, #19]
- 50%로 변경!
### 14. TP1 = **15%로!** [#28]
- 트레일링 회귀 = **-5%!**
### 15. 학습 = 2주일이면 충분! [#16]

## ✅ 이번 세션 (v133~v136!) = **이미 반영된 것!**

| 사상 # | 내용 | 반영 |
|---|---|---|
| #3 | 매매 학습 시스템 | ✅ v134 TradeLearningRecord |
| #3 | 예측 후 분석 | ✅ v135 prediction_outcome_worker |
| #5 | MACD/OBV/RSI/Volume | ✅ v134d analysis.py |
| #4 | 15m/1h/4h 다중 시간대 | ✅ analysis.py changes |
| #6~9 | 급등락 실시간 진입 카드 | ✅ v133d live-pump-dump (일반형!) |
| #6~11 | 자동 전략 제안 카드 | ✅ v132 (일반형!) |
| #3 | 심볼별 성공률 반영 | ✅ v135 |
| #3 | Learning Team | ✅ v136 |
| #3 | 시장 관찰 | ✅ v136 market_observations |

## 🎉 UPDATE (2026-08-14 확인!): **모두 반영 완료!**

사장님 = 「Gemini 채팅 인터페이스」 세션에서 = **v137~v147h 진화 완료!**
- 브랜치: `feat/v137-v147-strategy-analyzers-learning-fix` (9 commits!)
- main보다 = 앞섬 = **PR 필요!**
- URL: https://github.com/herosys1-crypto/binance-auto-trader/compare/main...feat/v137-v147-strategy-analyzers-learning-fix

### ✅ 모두 반영!

| # | 요구 | 완료 커밋 |
|---|---|---|
| 1 | 급등락 = 15분 17.5~27.5% + LONG만 | v147d/e/f/h |
| 2 | 자동 전략 = 4시간 볼밴 특화 | v137 (bb_4h_band_analyzer.py) |
| 3 | 1분/5분봉 = 진입 결정 로직 | v141 (PumpDumpLiveAnalyzer) |
| 4 | PnL/ROI 액션 = -5% | v147 (ACTION_PNL_PCT_DEFAULT) |
| 5 | TP1 = 15% | v147 (TP1_PCT_DEFAULT) |
| 6 | 트레일링 회귀 = -5% | v147 (TRAILING_RETRACE_PCT) |
| 7 | 15분 급등/급락 팝업창 각각 | v147f (실측 분포!) |
| 8 | 분할 매수 (안정 수익) | 기존 다단계 시스템 |

### 📊 신 서비스 (v137~v147):
- `bb_4h_band_analyzer.py` - 4시간 볼밴!
- `bb_top_analyzer.py` - 15분 천장!
- `ema_vcp_analyzer.py` - EMA/VCP!
- `sar_ichimoku_analyzer.py` - SAR/일목!
- `pump_continuation_analyzer.py` - 급등 지속!
- `pump_dump_live_analyzer.py` - 실시간 급등락!
- `strategy_confluence.py` - 합의 판정!

= 아래 「미반영」 섹션 = 이제 = **역사 기록!**

---

## ⚠️ ~~미반영 = 다음 세션 우선!~~ (v147h까지 다 반영!)

### 특화 필요!
1. **live-pump-dump 로직 = 15분 17.5~27.5% (LONG만!)** [#30]
   - 현재: 5분 1.5%+ or 1h 3%+
   - 신: **15분 17.5~27.5% + LONG 전용!**
   - 급락 = 진입 X (사장님이 결정!)

2. **자동 전략 제안 = 4시간 볼밴 특화!** [#10, #11]
   - 현재: 24h ticker 기반 pump_end/dump_continuation!
   - 신: **4시간 볼밴 중단/하단 이탈 특화!**

3. **1분봉/5분봉 = 진입 결정 로직!** [#14]
   - 20% 급등 후 지속 상승 = 진입 시점!
   - 최대 3단계 로직!

### 세팅 기본값 변경!
4. **PnL/ROI 액션 = -5% 기본** (현재 -20%!) [#17]
5. **TP1 = 15% 기본** (현재 25%!) [#28]
6. **트레일링 회귀 = -5%** [#28]

### 신 UI!
7. **15분 급등/급락 팝업창** = 각각 별도! [#17, #26]
   - 급등 팝업창
   - 하락 팝업창
   - 15분 기준 순위!

### 사장님 사상!
8. **분할 매수 안정 수익 전략** [#13]
   - 20%+ = 평균가 진입 → 추가 → 물량!
   - (기존 다단계 진입 시스템 = 이 사상 반영 중!)

## 다음 세션 = **v137 진화 준비!**
= 위 8건 = **사장님 요구 순위대로 반영!**
= 특히 = **#1 (15분 17.5~27.5% LONG만!)** = 최우선!

## 관련:
- [[project-2026-08-13-v134-v135a-learning-system]] = v134~v135 완성
- [[project-2026-08-13-v133-critical-recovery]] = v133 fix
- 세션 dump: `scratchpad/gemini_session_dump.md`

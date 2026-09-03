---
name: 2026-08-23-fix31-4-major-requests
description: Fix 31 = 사장님 4대 요구! (TP1 -5% 회귀 청산 / 4h + 반대신뢰도 청산 후 모니터링 + 재진입 / 마틴게일 3→2단계 조정 가능 / 1주일 재진입 모니터링)
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-23T08:49:54.844Z
---

# 🎯 Fix 31: 사장님 4대 요구! (2026-08-23)

## 📝 사장님 verbatim:

> "tp1 실행후 -5% 회기하면 청산하게 해줘"
> "포지션 진입 후 4시간 또는 행보 또는 포지션 진입 반대로 움직일 신뢰도 높으면 청산하고 모니터링으로 전환하고 다시 포지션 진입이 가능하면 다시 포지션에 진입해둬"
> "마틴게일도 지금 3단계인데 이것도 조정가능하게 한고 지금은 2단계로 세팅을 해줘"
> "익절이든 손절이든 청산후 1주일은 모니터링해서 추가 진입를 위한 모니터링을 계속해줘"

---

## 🎯 4대 요구 정리:

### **1. TP1 후 -5% 회귀 청산!**
- TP1 도달 → 트레일링 활성!
- peak PnL - 5% 도달 시 = 전량 청산!
- **현재 상태**: 조사 중! (TRAILING_RETRACE_PCT 기본 5%?)

### **2. 4시간 or 반대 신뢰도 청산 + 모니터링 + 재진입!**
- **A. 진입 후 4시간 경과** → 청산!
- **B. 반대 방향 신뢰도 높음** → 청산!
- **후속**: 모니터링 전환!
- **모니터링 중 재진입 조건 만족 시** → 다시 진입!
- **현재 상태**: 신 기능 = 개발 필요!

### **3. 마틴게일 단계 = 3 → 2로! (조정 가능!)**
- 현재: 최대 3단계 (300/600/1800!)
- 요구: **지금 = 2단계로 세팅!** (300/600!)
- **UI 조정 가능**: 1, 2, 3 선택!
- **SystemSetting**: `martingale_max_stage` (신설!) = default 2

### **4. 청산 (익절/손절) 후 = 1주일 모니터링!**
- SUCCESS or FAIL = 청산 후 7일!
- 신 진입 조건 만족 시 = 재진입!
- **현재 상태**: 부분 있음! (REENTRY_COUNT_TTL_DAYS = 7!)

---

## 💡 구현 계획 (Workflow 조사 후 확정!):

### **① TP1 -5% 회귀** (기존 확장?):
- `trailing_retrace_pct` 필드 = 이미 있음! (default 5%!)
- 확인만: 사장님 요구 = 이미 되어 있는가?

### **② 4h + 반대 신뢰도 청산** (신 워커!):
- 신 워커: `time_reverse_exit_worker.py`
- 매 5분:
  - 활성 전략 조회!
  - IF started_at + 4h < now → 청산!
  - ELIF ChartAnalyzer.compute_reversal_score(반대 방향) >= 4 → 청산!
  - 청산 후: retry_after_liquidation_enabled=True 세팅!

### **③ 마틴게일 최대 단계 조정**:
- SystemSetting: `martingale_max_stage` (신!) = default 2
- 하드코딩된 곳들 = get_martingale_max_stage(db) 참조!
- UI: 세팅 모달에 「최대 단계」 select (1/2/3!)

### **④ 청산 후 7일 모니터링**:
- 이미 있음! (REENTRY_COUNT_TTL_DAYS = 7)
- 확인만: 익절 후도 모니터링? 손절 후도 모니터링?
- 부족 시 = 신 로직 추가!

---

## 🚨 헌법 준수:
- 헌법 65/66: Workflow 병렬 Agent 검증 (진행 중!)
- 헌법 68 (사장님 사상 100%): 4대 요구 = 사장님 verbatim!
- 헌법 69: 사장님 요구 = 즉시 메모리 저장 (지금!)
- 헌법 70/71: 완료 = 실 검증 후!

## Why:
사장님 실 매매 경험 축적 = 시스템 진화 필수! v219 마틴게일 = 3단계 위험! 2단계로 낮춤! + 시간 청산 = 물타기 폭발 방지! + 재진입 모니터링 = 기회 놓치지 않음!

## 완성 상태 (2026-08-23 17:50 KST):

### Phase 1 완성:
- ✅ **① TP1 -5% 회귀 = 값 무관 활성!** (v148 gap-fix!) risk_service.py _tp1_active
- ✅ **③ 4h + 반대 신뢰도 청산 = 신 워커!** time_reverse_exit_worker.py (매 5분!)
- ✅ **scheduler 등록!** IntervalTrigger(minutes=5)
- ✅ **auto_add_margin ImportError = fix!** (중복 등록, run_auto_add_margin_once 이름 오타!)
- ✅ **SystemSetting sajangnim_max_stage=2!** (default 저장!)
- ✅ **sajangnim_capital.py 통합 함수 3개!** (get_max_stage/get_stage_capital/get_martingale_multipliers)
- ✅ **커밋!** a9e4f26
- ✅ **git tag 백업!** v-2026-08-23-fix31-phase1-deployed

### Phase 2 미완 (다음 세션!):
- ⏳ ② 마틴게일 5 파일 완전 통합 (sajangnim_capital MAX_REENTRY_STAGE, auto_bb_breakdown MAX_REENTRY_COUNT, success_pyramiding MAX_PYRAMID_COUNT+MARTINGALE_MULT, resistance_reversal MARTINGALE_STAGE2_USDT, realtime_reentry)
- ⏳ ④ 7일 재진입 확장 (익절 후 포함!)
- ⏳ UI + API max_stage 옵션!

## How to apply:
- **다음 세션**: Phase 2 진행 = 5 파일 마틴게일 통합!
- **현재 상태 = 실 작동!** = time_reverse_exit 5분마다 감시!
- **위험**: 마틴게일 아직 3단계 하드 (300/600/1800)!
- **SystemSetting=2 저장했지만 = 워커 참조 X = 다음 세션 완전 통합!

## 관련:
- [[2026-08-22-v219-final-complete]] (v219 마틴게일 원형!)
- [[2026-08-23-resistance-reversal-short-spec]] (Fix 29 = MARTINGALE_STAGE2_USDT!)
- [[feedback_verify_before_complete]] (헌법 69/70/71!)

---

## 🎯 Fix 32/33 = v219 7중 정점만 유지! 나머지 자동매매 OFF!
(2026-08-26 MEMORY.md 인덱스 압축 시 통합 — 같은 파일을 가리키던 별도 인덱스 항목)

**사장님 verbatim**: "자동매매는 v219 로직만 운영하고 다른 모든 자동매매는 중단해줘"

- **OFF된 워커**: `auto_bb_breakdown` (Fix 33 DISABLE flag) / `unified_15m_entry` (v224) / `pending_hc_fast` (Fix 32) / `success_pyramiding` (Fix 32)
- **유지**: v219 `auto_short_at_top` + `pump_top_detector` + `auto_add_margin` + `resistance_reversal` (Fix 29) + `time_reverse_exit` (Fix 31)
- **SystemSetting**: `auto_bb_break_daily_limit=5` (v219 공유) / `auto_bb_breakdown_enabled=0` / `unified_entry_enabled=0` / `pending_hc_fast_enabled=0` / `success_pyramiding_enabled=0`
- **commit** `0da4668` / **tag** `v-2026-08-23-fix32-33-v219-only`
- 당시 활성 SHORT 6건 흑자 +50 USDT

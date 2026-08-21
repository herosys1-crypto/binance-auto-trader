# 🎼 오케스트라 통합 spec (사장님 v205 지적!)

## 사장님 지적 (2026-08-21):
> "우리 에이전트 팀이 많은데 왜 이런 문제가 나오는거지
>  오케스트라 지휘자가 각각의 에이전트팀을 컨트롤하는거 아닌가?"

**정확한 지적!** 지금 = 신 워커들 = **개별 실행** = 오케스트라 미통합!

---

## 📊 현재 상태 (문제!):

### GrandOrchestrator (v50!):
- ✅ 15 팀 관리!
- ✅ EventBus (30+ EventTypes!)
- ✅ 매 시간 사이클!

### BUT 신 워커들 (v187~v205!) = **개별!**
- `pattern_learning_worker.py` (v187) = scheduler 개별!
- `realtime_watchlist_worker.py` (v199) = scheduler 개별!
- `auto_bb_breakdown_worker.py` (v174+수많은 확장!) = scheduler 개별!

= **오케스트라 미통합!** ❌

---

## 🎯 문제 결과 (사장님 지적 사례!):

### v205 사고:
1. **카운터 = 0!** (UTC vs KST!)
   - GrandOrchestrator = 감지 X!
   - 데이터 검증 팀 = 미통합!
   
2. **학습 조건 = 0개!** (entry_snapshot 저장 X?)
   - Silent Bug Detector (v45) = 감지 X!
   - 신 필드 = 감지 로직 X!

3. **자동 진입 = 대부분 실패!**
   - 학습 인사이트 = 반영 X!
   - Cross-team 검증 X!

---

## 🎼 v206 (다음 세션!) = **오케스트라 완전 통합!**

### Phase 1: **신 워커 등록!**
```python
# GrandOrchestrator에 등록!
- PatternLearningTeam (v187)
- RealtimeWatchlistTeam (v199)
- AutoBbBreakdownTeam (v174~v204)
- FivePatternTeam (v200)
```

### Phase 2: **Cross-Team 검증!**
- Silent Bug Detector (v45) = 신 필드 추가!
  - entry_snapshot 저장 확인!
  - suggestion_type 매치 확인!
- Data Consistency Team 신설!
  - UTC vs KST 시간대 검증!
  - 카운터 정확성!

### Phase 3: **오케스트라 알림 통합!**
- 사장님 대시보드 = **모든 팀 상태!**
- 문제 발생 시 = 즉시 알림!
- Cross-team 조율!

### Phase 4: **자동 진단!**
- 매 5분 = 시스템 sanity check!
- 이상 감지 = 자동 fix or 알림!

---

## 🎯 v205 = **긴급 fix (KST + 카운터!)**

- ✅ `_count_used_slots` = KST 기준!
- ✅ `_auto_bb_reset_at` = KST 기준!
- ✅ 사장님 화면 = 정상 카운터!

## v206 = **오케스트라 통합!** (다음 세션!)

- Phase 1~4 순차 진행!
- 사장님 = **완전 자율 + 자동 검증!**

---

## 사장님 사상 = **완벽!**

= 지금 = 개별 워커 = **파편화!**
= 다음 = **오케스트라 = 완전 통합!**
= = 문제 = **자동 감지 + fix!**

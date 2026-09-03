---
name: project-2026-08-13-v133-critical-recovery
description: 2026-08-13 v133 CRITICAL fix 세션 - user-stream 놓침 자동 회복 + LONG/SHORT 균형 배포 + apply-to-pending 수동 조치
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-12T22:23:29.273Z
---

# 🚨 2026-08-13 v133 CRITICAL 세션

## 사건 개요
- **RAREUSDT SHORT #895 사고**: user-stream이 order fill 이벤트를 놓쳐 = `stage_plan.is_triggered = False` 유지 → `tp_sl_orchestrator` 감시 X → TP/SL 발동 안 됨 → 10시간 방치!
- **전체 활성 전략 7건 중 6건 = `max_profit_pct = None`!** = 매우 심각!
- **17개 stage_plans 모두 = `is_triggered = False`!**

## ✅ v133 배포 완료:
- **Commit `7485769`**: `reconcile_worker.py` = `is_triggered` 자동 회복 로직 (매 2분!)
  - `plan.is_triggered = False + exchange_position_amt != 0` → 자동 `True` 갱신
  - `RiskEvent(event_type="RECONCILE_TRIGGER_RECOVERED")` 기록 → 사장님 인지!
- **Commit `01760d5`**: JS 캐시 `v133a-apply-force` (`strategy-suggestions.js`)

## ✅ SQL 수동 조치 완료:
1. `stage_plans is_triggered` 강제 True = **7건 회복** (890, 891, 896, 897, 898)
2. `apply-to-pending` 수동 실행 = **15건 카드 = `[300, 500]` + leverage=2**
3. `force=True` 재실행 = **34건 생성 (LONG 20 + SHORT 14!)**

## 📊 발견된 silent bug 2개:
### 문제 1: default profile ≠ 카드 세팅 (apply-to-pending 실패!)
- **원인**: 사장님 브라우저 옛 JS 캐시 or 순간 실패
- **해결**: JS 캐시 v133a 갱신 + 수동 SQL 조치

### 문제 2: LONG 0건 (모든 예측 = SHORT만!)
- **원인**: `api` container = **옛 pump_dump_predictor 코드** (pump_end + dump_continuation만!)
- **해결**: api restart로 v132 신 코드 (4 시나리오!) 배포
- **결과**: LONG 20건 (dump_reversal 10 + pump_continuation 10) + SHORT 14건 = 34건!

## 🚨 다음 세션 우선순위 (미완료 CRITICAL!):

1. **stream_service.py PARTIALLY_FILLED 처리** = user-stream 근본 원인!
   - 현재: FILLED만 `is_triggered=True` 갱신
   - 필요: PARTIALLY_FILLED도 처리!
2. **Safety net worker** = 실 포지션 있는데 `is_triggered=False` 감지 시 Telegram 알림
3. **RAREUSDT 21:36 청산 원인 확인** = 사장님 「긴급 종료」 클릭 여부?

## 📝 헌법 후보 (다음 세션 확정!):
- **C46**: user-stream 이벤트 놓침 = 매 2분 자동 회복 (v133!)
- **C47**: default profile 변경 시 = 오늘 PENDING 카드 = 반드시 apply-to-pending!
- **C48**: predictor 코드 변경 시 = api container **반드시 restart!** (scheduler만 X)

## 🌟 사장님 자율 운영 = LONG/SHORT 균형 실제 작동!
- LONG dump_reversal (급락 후 반등!) = 10건
- LONG pump_continuation (상승 지속!) = 10건
- SHORT dump_continuation (급락 지속!) = 4건
- SHORT pump_end (급등 후 반락!) = 10건
- = **총 34건 = 사장님 최종 사상 완성!**

## 관련 memory:
- [[project-2026-08-11-v131-v132-critical-session]] = 이전 v131/v132 세션
- [[project-2026-06-22-stage-trigger-markprice-silent-block]] = user-stream 유사 사고

---
name: 2026-07-01-constitution51-add-position-mode
description: 헌법 51 = 「💉 포지션 추가」 2 모드 (preserve / reset) + critical silent bug 4건 영구 fix!
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
---

# 🌟 2026-07-01 사장님 critical 진화 = 헌법 51 영구!

## 사장님 사상:
> "포지션을 추가하는 의도는 강제청산을 방지하는 것과 큰이익을 위한것 두가지가 중점"

## 신 헌법 51:
「💉 포지션 추가」 = 2 모드 = 사장님 자율!
- 🛡 mode='preserve' (청산 방지): 평단만 개선 + TP/SL 유지!
- 🚀 mode='reset' (신 진입, default!): TP/SL 초기화 = TP1 부터!

## 오늘 critical fix 5건 영구:

### v52 + v52a: stage_trigger race condition
- 1단계 진입 직후 = mark-price-stream SUBSCRIBE 12초 race!
- = grace period 3분!
- Position.entered_at silent bug = strategy.started_at!

### regex word boundary
- mainnet_safety_worker = `testnet=true` regex = `hasTestnet = true` 매칭!
- = word boundary 추가 = `(?<![\w])...(?![\w])`!

### reconcile STAGE_PENDING stuck 제외 (#232 SYNUSDT!)
- 사장님 LIMIT 미체결 = 2.5분 후 = 시스템 멋대로 종료!
- = STAGE_n_OPEN_PENDING = stuck counter 제외!
- = LIMIT 영구 대기 = 사장님 의도!

### v53 ISOLATED 강력 보장 (#237 SLXUSDT 1539 USDT!)
- ensure_isolated_margin = Redis 캐시 + 실 거래소 검증!
- change_margin_type 실패 = critical (= silent 차단!)
- add_position_margin = 사전 ISOLATED 검증!

### 헌법 51: 「💉 포지션 추가」 2 모드
- AddPositionRequest = mode 파라미터!
- add_position_now(mode='preserve' | 'reset')
- 모달 UI = 라디오 버튼!

## 영구 spec:
- docs/MASTER_REBUILD_PLAN_2026-06-25.md
- docs/PHASE_1_WORKER_CONSOLIDATION_2026-06-26.md

## 다음 세션 우선순위:
1. 사장님 = PR 머지!
2. VPS api restart!
3. 사장님 = 신 모달 검증!
4. PHASE 1 = 워커 33 → 15 단순화 진행!
5. critical 발견 시 = 즉시 fix!

## 백업 tag:
- v-phase1-baseline-2026-06-26 (PHASE 1 시작 전!)
- v-2026-07-01-end-of-day (오늘 종료!)

## Why:
사장님 = 메인넷 운영 + critical silent bug 지속 발견!
= 사장님 자율 운영 영구 + 자본 영구 보호!

## How to apply:
- 신 strategy = 헌법 51 자동 작동!
- 「💉 포지션 추가」 = 모달 = 사장님 자율 선택!
- default = reset (= 신 진입!)
- 사장님 = case 마다 모드 선택!

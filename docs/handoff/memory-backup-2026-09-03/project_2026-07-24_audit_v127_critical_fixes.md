---
name: 2026-07-24-audit-v127-critical
description: 사장님 요청으로 전체 시스템 감사 = 60건 발견 (CRITICAL 17건 fix + 배포 완료)
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-07-24T03:42:36.193Z
---

# 2026-07-24 전체 시스템 감사 = v127 CRITICAL 대규모 fix!

## 배경
사장님 #505 DEXEUSDT TP10 조기 청산 사고 (원한 TP20까지 X) →
사장님 요청 = "다시 모든 로직을 점검하고 싶어 지금 실투자 메인넷이야 이런 문제가 다시 일어나면 안되"

## 감사 방법
- 6개 병렬 Agent (일반 목적)
- 사장님 헌법 51+ 대비 코드 검증
- 시나리오 시뮬레이션 per Agent

## 발견 = **60건!**
- CRITICAL 17, HIGH 21, MEDIUM 18, LOW 4

## Phase 1 완료 (2026-07-24) — CRITICAL 17건 모두 fix + 배포!

### commits
- Batch 1 (9건): `829fc8d`
- Batch 2 (8건): `9b49a1b`
- **VPS 배포 완료**: git pull + docker restart

### CRITICAL 17건 요약
1. **strategy_calculator.py:300** — 중간 stage qty leverage 누락 → 3x 6-stage에서 1/3 qty!
2. **risk_service.py:155** — evaluate_stop_loss Redis mark_price 우선
3. **risk_service.py:294** — evaluate_take_profit_level Redis 우선
4. **liquidation_risk_worker** — Redis 우선 (SYNUSDT -585 재발 방지)
5. **exchange_accounts._reserved_one** — 미체결 ad-hoc LIMIT 마진 포함 (130% 검증)
6. **execution_service.py:1173** — Redis peak 리셋 (「💉 포지션 추가 reset」 완성)
7. **execution_service emergency_close** — cancel_all_orders (좀비 방지)
8. **execution_service trigger_next_stage** — STOPPING race 방지
9. **tp_sl_orchestrator** — 옛 template tp10_qty_ratio=100 잔재 safety net
10. **reconcile_worker flat 좀비** — cancel_all_orders
11. **admin/monitoring.py** — tp_breakdown TP1~20
12. **dashboard-refresh.js** — stats-tp TP1~20 순회
13. **mainnet_safety_worker whitelist** — word boundary만
14. **execution_service add_position_now LIMIT** — preflight 검증
15. **add-position-modal.js** — 계정별 여유 (Sub-Account -2019 재발 방지)
16. **distributed_scheduler_guard bytes/str** — leader 전면 정지 방지!
17. **tp_miss_detector Redis mark_price**

## 헌법 v127 신규 12개 원칙
1. 모든 mark_price = Redis 우선
2. 모든 leverage 계산 = capital × lev / price
3. 「💉 포지션 추가 (reset)」 = Redis peak도 리셋
4. 긴급 종료 = LIMIT도 취소
5. STOPPING/TERMINAL = 신 진입 차단
6. template 옛 100% qty_ratio 잔재 = safety net
7. 미체결 ad-hoc LIMIT 마진 = 예약 계산 포함
8. LIMIT 도 preflight 검증
9. UI 표시 vs backend 실제 = 일치
10. Sub-Account 여유 = 계정별 정확
11. whitelist = word boundary만
12. Redis get() = bytes 변환

## 남은 Phase (다음 세션 우선순위!)
- **Phase 2**: HIGH 21건 (1주 내)
- **Phase 3**: MEDIUM 18건 (2주 내)

### HIGH 주요 후보
- strategy_service = capital_calculator 통합
- tp_sl_orchestrator:253 = capital_based inflation
- risk_service:409 = TP1_override=0 (「끔」) → TRAILING 여전히 발동
- run_workers.py:71 = TPSL 예외 spam (10초마다!)
- heartbeat_worker = severity 검색 오류

## Spec 문서
- docs/AUDIT_2026-07-24_CRITICAL_60ISSUES.md = 전체 감사 결과 + 헌법 v127

## 검증 방법 (신 세션에서 사용!)
1. **재발 방지**: 이 헌법 v127 준수 = silent bug 근본 차단
2. **정기 감사**: 분기별 6-Agent 병렬 감사 권장
3. **관련 파일 수정 시**: 이 문서 참고 → 헌법 위반 여부 확인

## 관련 메모리
- [[project_2026-07-01_constitution51_add_position_mode]] = 헌법 51 (「💉 포지션 추가」 2 모드)
- [[project_2026-07-18_v96_v116_sajangnim_spec_evolution]] = v96~v116 21개 fix (v107 capital=margin!)
- [[project_2026-06-24_force_sl_loss_limit_spec]] = ROI 기준 강제 SL

---
name: 2026-08-06-v130-obv-reentry-complete
description: v130 신 OBV 자동 재진입 완성 + 사장님 신 default (5x/25%/-15%) + 대량 fix (30+ commits)
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-08T20:19:01.850Z
---

# 2026-08-06 ~ 08 = v130 완성 = OBV 자동 재진입 + 사장님 신 default!

## 배경
사장님 요청 = 「기존 로직에 추가할려고해 4H OBV 하락 시 재진입 신 로직!」
→ 3일 세션 = 대규모 신 시스템 + 사장님 신 default!

## Git tag
- **v-2026-08-08-v130-obv-reentry-complete** ← 최종 백업!
- branch: fix/pin-fastapi-prometheus-incompat-2026-06-24

## Phase별 완료

### Phase 1: 신 OBV 자동 재진입 시스템
- **spec**: `docs/CHART_REENTRY_STRATEGY_SPEC.md`
- **대시보드 2개 버튼**:
  - ➕ 새 전략 (기존 방식)
  - 📊 새 전략 (OBV 자동)
- **alembic 0022**: `strategy_templates.trigger_mode` 신 컬럼
- **chart_analyzer.py** (신!): OBV 계산 + 4H 첫 하락봉 + 15m/1h 확인 + 10% 이동
- **stage_trigger_worker**: OBV_REVERSE 분기 = ChartAnalyzer 호출
- **openCreateChartObvModal**: 신 모달 = mode='direct' 강제
- **「📊 OBV」 배지**: 심볼 옆 보라 발광!
- **cm-submit.js**: trigger_mode 전달

### Phase 2: 재진입 알람 시스템
- **reentry_alert_watcher.py** (신 worker!): 5분마다
  - 24h 강제 종료 심볼 스캔
  - 4H OBV+RSI+10% 이동 = 3조건 AND
  - Redis 저장 + Telegram (6h dedup)
- **API endpoints**: GET/DELETE /reentry-alerts
- **reentry-alerts.js**: 대시보드 알람 카드 (보라 그라디언트!)
- **알람 클릭** = 신 OBV 모달 자동 (심볼/side/계정 auto-fill!)

### Phase 3: 사장님 신 default (모든 전략!)
- **레버리지 5x** default (cm-collectors.js)
- **TP qty 10/15/20/25** default (사장님 사상: 점진적!)
- **tp1_pct_override=25** 자동 저장 (모든 신 전략!)
- **force_sl_enabled_override=True + roi=15** 자동 (강제 -15%!)
- **시작가 없으면 = MARKET 진입!** (execution_service.py)
- **트레일링 activation** = peak >= 20% (기존 5% → 20%!)

### Phase 4: CRITICAL fix (진입 안됨 해결!)
- **wallet 검증 fail-open 복원** (v127 default deny → 사장님 사고 원인!)
- **v107 자본 검증 완화** (OBV 모드 = 1단계 자본만!)
- **다음 단계 남으면 SL 발동 X!** (사장님 사상 = 손실 회복 기회!)
- **▶ 강제 진입** (미체결 시 마지막 자본 재사용!)
- **미세팅 단계 = plan 자동 생성** (control.py)

### Phase 5: UI/UX fix
- **버튼 라벨 명확화**: "신 전략" → "새 전략" (혼란 방지!)
- **「⬆ 심볼로」 버튼 제거** (모바일 방해!)
- **「📊 OBV」 배지 심볼 옆** (구/신 즉시 구분!)
- **cm-submit 성공 alert = 방식 표시** ([📊 OBV 자동 재진입])

## 헌법 v130 (13개 신 원칙!)

1. **신 시스템 = 2개 페이지** (기존/OBV) = 사장님 자율!
2. **OBV_REVERSE trigger_mode** = 4H OBV 첫 하락봉 + 15m/1h + 10% 이동
3. **재진입 알람** = 24h 강제 종료 + OBV/RSI/10% 자동 감지
4. **알람 클릭 = 신 전략 즉시** (심볼/side/계정 auto-fill!)
5. **레버리지 default = 5x** (신 default!)
6. **TP qty ratios = 10/15/20/25** (점진적 청산!)
7. **TP1_override = 25** 자동 저장 (모든 신 전략!)
8. **강제 SL = -15%** 자동 (모든 신 전략!)
9. **시작가 없으면 = MARKET** (신 default!)
10. **트레일링 = peak >= 20%** (기존 TP3 조건 완화 = 사장님 25% 사상!)
11. **다음 단계 남으면 SL 발동 X** (사장님 사상 = 손실 회복 기회!)
12. **자본 검증 완화** (OBV 모드 = 1단계만! 나머지는 preflight!)
13. **wallet 검증 fail-open** (v127 default deny → 진입 사고 해결!)

## 사장님 사용 흐름 (완성!)

### 「➕ 새 전략 (기존 방식)」:
- 기존 로직! 사장님 옛 습관!
- 가격 도달 시 자동 진입
- 신 default 적용 (5x, TP qty, TP1 25%, 강제 -15%)

### 「📊 새 전략 (OBV 자동)」:
- 신 로직!
- 1단계 진입 → 손절 → OBV 신호 대기 → 자동 재진입!
- 모든 신 default 적용!
- 카드에 「📊 OBV」 배지!

### 재진입 알람:
- 강제 종료된 심볼 = 자동 감시
- OBV+RSI+10% 신호 = 대시보드 알람 카드!
- 클릭 = 신 전략 즉시!

## 관련 memory
- [[project_2026-07-24_audit_v127_critical_fixes]] = v127 대감사 (60건!)
- [[project_2026-07-01_constitution51_add_position_mode]] = 헌법 51
- [[project_2026-07-18_v96_v116_sajangnim_spec_evolution]] = v96~v116

## 다음 세션 우선순위
1. **실 테스트** = 사장님 소액 신 OBV 전략 진행!
2. **재진입 알람 확인** = 실제 발동 시 알림 OK?
3. **트레일링 실제 발동 확인** = peak >= 20% 도달 시 정확?
4. **주말/휴일** = 시장 관찰!

## 다음 배포 명령
```bash
cd ~/binance-auto-trader/backend
git pull origin fix/pin-fastapi-prometheus-incompat-2026-06-24
docker compose exec api alembic upgrade head
docker compose restart api scheduler
```

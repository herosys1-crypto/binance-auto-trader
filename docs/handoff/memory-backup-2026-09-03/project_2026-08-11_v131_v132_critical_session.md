---
name: 2026-08-11-v131-v132-critical-session
description: "v131 청산후 재진입 시스템 완성 + v132 CRITICAL fix (레버리지 2x, TP1 override, retry 순차) + 급등BB알람"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-10T23:55:00.544Z
---

# 2026-08-11 = v131~v132 세션 = 사장님 CRITICAL 완전 fix!

## Git tag
- **v-2026-08-11-v132-critical-fixes** ← 백업!
- branch: **main** (fix branch에서 병합 완료!)
- 앞으로 사장님 = 항상 main 사용!

## 신 기능 완성!

### 1. 청산 후 자동 재진입 시스템 (v131 완성!)
- retry_after_liquidation_enabled 옵션 (UI/DB/Backend!)
- 단계별 개별 트리거 (하이브리드 = 기본값 + 개별 override!)
- 「🔄 재진입 대기중」 상태 배지 (LIQUIDATED_WAITING_RETRY!)
- 상단 + 하단 두 곳 동기화!
- 130% 자본 실시간 계산 + 경고 (사장님 자율!)
- 수정 모드에도 반영!
- **retry ON = 옛 stage_trigger 완전 skip!** (순차 진입!)

### 2. 급등+BB중단 알람 시스템 (v131 신!)
- Binance 선물 24h 상승률 top 50 조회
- 4H 최고점 vs BB중단 (20MA) ±5% 근접 감지!
- 10분마다 실행
- Telegram + 대시보드 알람 (30초 polling!)
- 알람 클릭 = 신 전략 즉시 (심볼 auto-fill!)

## CRITICAL fix (5건!)

### 1. TP1_override = TP1만 override! (v131)
- 문제: #838 BMTUSDT TP4 audit "의도 25% vs 실제 30.96% (초과!)"
- 원인: v105 로직 = tp_levels = max(override, val) = TP1-4 모두 25% = 동시 발동!
- Fix: TP1만 override, TP2-10은 template 그대로!

### 2. Self-Check false positive fix! (v131)
- 문제: #836 CYSUSDT = 진입 정상, 알림 정상, but silent bug 알림!
- 원인: title.like("%포지션 진입 체결%") = 매칭 X = 항상 false positive!
- Fix: title.like("%단계 진입]%") = 실제 title 매칭!

### 3. retry ON = 옛 stage_trigger skip! (v131)
- 문제: #828 TSTUSDT = retry ON인데도 +10% 도달 = 2단계 자동 진입 (동시 보유!)
- 사장님 사고: "1단계 청산하고 0인 상태에서 2단계 진입하는건데"
- Fix: retry ON = STAGE_OPEN 상태 = 옛 stage_trigger skip! 오직 LIQUIDATED_WAITING_RETRY만 신 로직!

### 4. 강제 SL JS 검증 확장! (v131)
- 문제: 대시보드 강제 SL -30% 선택 = "옵션 오류: on:30" alert!
- 원인: JS 검증 = [5, 10, 15, 20]만 허용!
- Fix: [0, 5, 10, 15, 20, 25, 30, ..., 100] 확장!

### 5. 레버리지 5x → 2x (v132 최종!)
- 문제: 배포 후에도 = 여전히 5x 표시!
- 원인: main branch에 옛 5 남아있음! (fix branch만 fix!)
- Fix: main branch 3 파일 모두 2로!
  - index.html value="2"
  - cm-open-modal.js _lvInit.value = 2
  - cm-collectors.js return 2

## 배포 흐름 (사장님 앞으로!)
```bash
cd ~/binance-auto-trader/backend
git pull   # main branch (기본!)
docker compose restart api scheduler
```

## 헌법 신 원칙 (v131~v132!)
1. **branch 확인 = 필수!** (main vs fix branch 헷갈림 사고!)
2. **override는 명확히!** (TP1_override = TP1만!)
3. **retry ON = 순차 = 절대 동시 보유 X!**
4. **UI 검증 = Backend와 100% 동기화!**
5. **레버리지 = 사장님 자율 = 언제든 변경 가능!**

## 사장님 사고 정확 반영
- 「청산 후 재진입」 = 각 단계 순차 = 절대 동시 X!
- 「130% 경고」 = 사장님 자율 진행 가능!
- 「단계별 개별 트리거」 = 시장 분석 반영!
- 「기본값 = 항상 유효!」 = 개별세팅이 우선!

## 관련 memory
- [[project_2026-08-06_v130_obv_reentry_complete]] = v130 OBV 재진입 (base!)
- [[project_2026-07-24_audit_v127_critical_fixes]] = v127 대감사 (기반!)

## 다음 세션 우선
1. **사장님 실 mainnet 관찰!** (신 시스템 검증)
2. **재진입 알람 실 발동 확인!**
3. **급등 BB 알람 실 발동 확인!**
4. **표기 「LONG 진입 체결」 정확 위치 파악!** (남은 조사!)

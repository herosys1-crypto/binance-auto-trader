---
name: project-2026-07-18-v96-v116-sajangnim-spec-evolution
description: 2026-07-18~21 대량 진화 = v96~v116 (21개 fix!) = 사장님 사상 근본 spec 정착 (capital=margin, qty=capital×leverage, TP1 옵션 13개 + 끔). tag=v-2026-07-21-tp-extended-v116
metadata:
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-07-20T23:43:00.557Z
---

# 2026-07-18~21 대량 진화 (v96~v116 = 21개 fix!)

## 🌟 핵심 = 사장님 사상 근본 spec 정착!

### **v107 CRITICAL (진짜 근본!):**
```
capital = margin (지갑 lock 원 금액!)
notional = capital × leverage
qty = notional / price = (capital × leverage) / price
SL = capital × sl_pct / 100
```

옛 시스템 (silent bug!): capital = notional 오해!
= 사장님 자본 150 → qty 81,000 (1/3만!)
= 사장님 사상 위반!

v107 fix (strategy_calculator.py):
= capital 150 × 3x = qty 245,000 ✅

## 진행 순서:

### **v96~v106: 대시보드 표시 정확화**
- v96: Binance 실 margin 우선
- v97~v99: positionRisk API + REPLACE (max 아니라!)
- v100: total_position_initial_margin override
- v101: 예약 = 자본 그대로 (/lev 제거!)
- v102: 실 = isolatedWallet (upnl 무관!)
- v103: 좀비 STOPPING 자동 정리 + 「⚡ 강제」 버튼
- v104/v106: 자본 두 값 표시 (마진 + notional)
- v105 ⭐: TP1 옵션 = 모든 TP 상향 (max!)

### **v107 ⭐ CRITICAL: 근본 spec 변경!**
- strategy_calculator.py:compute_qty_from_capital
- leverage 파라미터 추가 = 정확 계산!

### **v108~v110: 편의 + Binance 통합**
- v108: 「포지션 추가」 여유 자금 표시
- v109: 미체결 = Binance 실시간 (silent bug 재발!)
- v110: 대시보드 = 진입/청산/지정가 실시간 표시

### **v111: UI 개선**
- 12 col grid 컴팩트!

### **v112: spec 통일 + 문서화**
- capital_calculator.py = 사장님 사상 통일!
- docs/SAJANGNIM_CAPITAL_SPEC_2026-07-18.md!

### **v113/v114: v109 silent bug 2연발 fix!**
- v113: import path 잘못 (app.services.binance_client → app.integrations.binance.client)
- v114: method 이름 잘못 (get_open_orders → list_open_orders)
- = v168 (decrypt_text) case 재발!

### **v115: TP1 옵션 대폭 확장 + 끔!**
- 옛: 4 옵션 (10/15/20/25)
- 신: 13 옵션! (0=끔, 10~300%)
- 「🚫 TP 끔」 = 사장님 100% 수동 관리!
- backend + frontend 3-layer!

### **v116: v115 silent bug fix!**
- frontend validation 옛 리스트!
- if (![10, 15, 20, 25].includes(pct)) → 신 값 reject!
- v116: 13 값 모두 허용!
- 4-layer 완성!

## 📜 spec 문서:
- `docs/SAJANGNIM_CAPITAL_SPEC_2026-07-18.md`
- 사장님 헌법 5대 원칙!
- 검증 체크리스트 8/8 완료!

## 🚨 발견 문제 (v112에서 통일 fix):
- capital_calculator.py = 옛 로직 (/ lev)
- exchange_accounts.py v101과 불일치!
- v112 fix로 통일!

## 미배포:
- PR #278 (v115) = 머지 대기
- v116 = 신 PR 필요!
- 브랜치: fix/pin-fastapi-prometheus-incompat-2026-06-24

## 🏷 Git Tags:
- `v-2026-07-21-tp-extended-v116` ⭐ 최종!
- `v-2026-07-16-v95-root-cause-fix` (전 백업)

## 다음 세션 우선순위:
1. **PR 머지 (v115 + v116) + 배포!**
2. 브라우저 Ctrl+Shift+R!
3. 신 전략 = v107 실 검증 (qty 3배!)
4. 「TP 끔」 시장 = v115 수동 관리 검증!
5. 남은 spec:
   - 중복 전략 (#475/#476) 원인 (create_strategy 검증?)
   - 대시보드 예약 3분리 (자동/지정가/총)
   - Preflight = 우리 여유 사용

## 🌟 사장님 사상 5대 원칙 (헌법!):
1. 메인넷 = 실자금 = 극도 조심!
2. capital = margin (지갑 lock!)
3. Silent bug 금지 = 명확 표시!
4. 검증 없는 코드 금지!
5. 사장님 사상 = 항상 우선!

## 관련 메모리:
- [[project-2026-07-16-ui-symbol-scroll-v95-backup]] - 옛 UI fix
- [[project-2026-07-01-constitution51-add-position-mode]] - 헌법 51
- [[reference-vps]] - VPS 배포

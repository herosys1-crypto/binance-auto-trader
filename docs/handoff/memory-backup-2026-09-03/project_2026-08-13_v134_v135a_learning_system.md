---
name: project-2026-08-13-v134-v135a-learning-system
description: 2026-08-13 v134~v135a 완전한 학습 시스템 + 상세 분석 + 급등락 카드 + 이유 확인 모달 (16 commits!)
metadata: 
  node_type: memory
  type: project
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
  modified: 2026-08-13T03:57:47.189Z
---

# 🎓 2026-08-13 v134~v135a 학습 시스템 세션 (v133 다음!)

## 배포 완료 (14 commits!):

### Phase 1: v133 시리즈 (급등락 + 분석):
- `7485769` v133: reconcile_worker = is_triggered 자동 회복 (RAREUSDT 사고 fix!)
- `01760d5` v133a: JS 캐시 갱신
- `40b9dc4` v133b: 신뢰도 순 정렬 + 순위/신뢰도 배지 (🥇🔥⭐✨💧)
- `bdae747` v133c: 상세 분석 새 창 (analysis.html) + 실시간 감지 (pump_live/dump_live)
- `b2e69fc` v133d: 급등락 실시간 진입 = 별도 카드 (`/live-pump-dump/scan`)

### Phase 2: v134 시리즈 (학습 + 심볼 분석기):
- `c3c47f9` v134: **trade_learning_records + TP/SL 조정 제안 + 심볼별 통계!** (alembic 0028!)
  - 신 모델 TradeLearningRecord (JSONB: entry_config, entry_context, progression, insights)
  - 신 service TradeLearningService (on_entry/snapshot/on_exit + auto insights!)
  - 신 worker learning_sync_worker (매 5분!)
  - 신 API /trade-learning/records + /summary + /tp-sl-advisor/scan
  - 신 카드 「🎯 TP/SL 조정 제안」 (2분마다 자동!)
- `88d2952` v134a: 심볼 분석기 카드 (수동 + 활성 quick!)
- `dcd8890` v134b: 401 fix (`accessToken` → `access_token` 오타!)
- `0e8e613` v134c: 신 전략 modal에 「📊 이 심볼 분석」 버튼!
- `59aadc1` v134d: **OBV + MACD + Volume 지표** + 「세팅 후 진입」 = 실제 modal 자동 열기!
- `78da772` v134e: 창 컴팩트 (800x900 → 550x700, 46% 감소!)
- `d63e1e3` v134f: **3중 안전장치** (직접 호출 → postMessage → localStorage) - "오류 없는 개발"!

### Phase 3: v135 시리즈 (예측 학습 사이클!):
- `a79f93a` v135: **예측 학습 사이클 완성!** (alembic 0029!)
  - strategy_suggestions에 outcome_status/change_1h/4h/24h/price_at_prediction/checked_at/symbol_prior_success_rate 추가
  - 신 worker prediction_outcome_worker (매 1시간!)
  - predictor 개선 = `adjusted_conf = raw * (0.5 + sr * 0.5)` = 심볼 성공률 반영!
  - 신 API /trade-learning/prediction-stats + /prediction-outcome/run-now
  - 신 카드 「🎓 예측 학습 통계 [%]」 = 배지 색상 + TOP/BOTTOM 심볼!
- `49d4f64` v135a: **「즉시 진입」 = 이유 확인 모달!** = 사장님 판단 개입!

## 자동 학습 사이클 (전부 자동!):

| 주기 | 워커 | 역할 |
|---|---|---|
| 매 06:30 UTC | 예측 | 34건 카드 생성! |
| **매 1시간** | prediction_outcome_worker | 예측 후 실제 변동 확인! (4h 후 판정!) |
| **매 5분** | learning_sync_worker | 활성 전략 진입/스냅샷/종료 저장! |
| 매 2분 | reconcile_worker | is_triggered 자동 회복! (v133!) |
| 매 07:30 KST | daily_briefing | 텔레그램 발송! |

## 사장님 대시보드 신 카드 순서:
1. 🎓 예측 학습 통계 [%] ← v135!
2. 🔎 심볼 분석기 ← v134a!
3. 🎯 TP/SL 조정 제안 ← v134!
4. 🚀 급등락 실시간 진입 ← v133d!
5. 🎯 자동 전략 제안 ← v132!
6. 🚨 급등+BB중단 알람 ← v131!
7. 🎯 재진입 알람 ← v130!

## 헌법 후보 (다음 세션 확정!):
- **C46**: 「즉시 진입」 = 반드시 이유 확인 modal! (사장님 판단 개입!)
- **C47**: UI 신 기능 = 3중 안전장치 (직접 → postMessage → localStorage) 원칙!
- **C48**: 예측 시 = 심볼 과거 성공률 반영 = `sr * 0.5 + 0.5` 배율!
- **C49**: predictor 코드 변경 시 = api container 반드시 restart!
- **C50**: 모든 거래 = 5분 내 자동 학습 저장 (learning_sync_worker!)
- **C51**: 예측 = 4h 후 자동 판정 = 심볼 성공률 누적!
- **C52**: JS/HTML 신 파일 = localStorage 키 = api.js와 동일 (access_token!)

## 배포 사항 (사장님!):
```bash
cd ~/binance-auto-trader/backend && git pull
docker compose exec api alembic upgrade head  # 0028, 0029!
docker compose restart api scheduler
```

## 다음 세션 우선순위:

### 즉시:
1. **stream_service PARTIALLY_FILLED 처리** - user-stream 근본 원인!
2. **Safety net worker** - 실 포지션 vs is_triggered=False 감지 → Telegram 알림!

### 개선:
3. **자동 조정 옵션** = 시스템 안정 후 = 사장님 선택 = 자동 실행!
4. **학습 데이터 → predictor ML** = confidence 향상!
5. **거래 학습 + 예측 학습 통합 뷰** = 하나의 「학습 대시보드」!
6. **활성 전략 카드 = 클릭 = 상세 분석** (기존 strategies-list.js 통합!)

### 관찰:
7. 예측 성공률 데이터 축적 (7일 후!)
8. 심볼별 TOP/BOTTOM 관찰
9. LONG vs SHORT 성공률 비교

## 관련:
- [[project-2026-08-13-v133-critical-recovery]] = v133 세션 (RAREUSDT 사고!)
- [[project-2026-08-11-v131-v132-critical-session]] = 이전 v131/v132 세션

## 사장님 자율 운영 = 완전 자동 학습 시스템!
- 예측 → 실행 → 결과 → 학습 → 다음 예측 반영!
- 사장님 = 대시보드 확인 + 이유 확인 후 진입 결정!
- 시스템 = 24/7 자율 학습 지속!

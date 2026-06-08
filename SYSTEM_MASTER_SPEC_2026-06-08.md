# 📚 사장님 시스템 마스터 기획서 (2026-06-08)

> **사장님 명시 (2026-06-08)**:
> > "여기까지 하고 중요한 로직변경이 있어서 다시 한번더 기획서를 만들고
> >  코드와 시스템점검을 기존의 로직과 시스템을 확인하고 정리해줘"

이 문서 = **마스터 기획서 = 영구 보존**. 향후 모든 코드 변경 = 이 기획서 100% 적용.
모든 다른 spec = 이 기획서의 = 서브 섹션.

---

# 🌟 사장님 사상 5대 원칙 (= 헌법, 절대 변경 X)

## 1. **메인넷 = 실자금**
- 모든 코드 변경 = 사장님 자본 직접 영향 인식
- 신중한 검증 + audit log 필수

## 2. **사장님 사상 우선**
- 사장님 의도 100% 반영
- 사장님 자율 운영 보장

## 3. **Silent bug 금지**
- 시스템 silent error → 즉시 사장님 알림 + 영구 차단
- audit log + Sentry + 진단 endpoint

## 4. **검증 없는 코드 금지**
- 모든 코드 = python ast.parse + grep + 시나리오 검증
- 8 시나리오 매트릭스 (= STRATEGY_EDIT_LOGIC spec)

## 5. **대칭성**
- 사장님 의도 + 시스템 동작 = 1:1 대응
- 모드 A/B/C, SHORT/LONG = 명확 분리

---

# 🏗 시스템 구조 (= 전체 컴포넌트)

## Worker (= 자동 백그라운드)

| Worker | 주기 | 역할 |
|---|---|---|
| `stage_trigger_worker` | 5초 | 자동 단계 진입 (= trigger_price 도달 시) |
| `risk_check_worker` | 5초 | TP/SL/Trailing/Crisis 평가 + 발동 |
| `reconcile_worker` | 30초~1분 | DB ↔ Binance 동기화 (= total_capital 자동 갱신, PR #84) |
| `sync_health_monitor` | 5분 | 강제 동기화 검증 |
| `realized_pnl_sync_worker` | 5초 | user-stream 우회 (PR #45) |
| `daily_summary_worker` | KST 자정 | 일일 요약 Telegram |
| `daily_report_worker` | KST 자정 | 일일 리포트 |
| `zombie_guardian` | 5분 | STOPPING/MANUAL_CLEANUP 자동 정리 |
| `endpoint_health_monitor` | 1분 | API/WS 헬스 |
| `binance_changelog_monitor` | 1시간 | Binance 공지 자동 추적 |

## Service (= 비즈니스 로직)

| Service | 역할 |
|---|---|
| `risk_service` | TP/SL/Crisis/Trailing 평가 핵심 |
| `execution_service` | 거래소 주문 (= emergency_close_position 등) |
| `strategy_service` | strategy 생명주기 |
| `stream_service` | Binance user-stream 처리 |
| `tp_sl_orchestrator` | TP/SL 자동 발동 orchestrator |
| `mark_price_cache` | 현재가 Redis 캐시 |

## API Endpoint (= 주요)

| Endpoint | 역할 |
|---|---|
| `POST /strategies` | 신 strategy 생성 |
| `PATCH /strategies/{id}/settings` | 모드 A: 설정만 수정 |
| `POST /strategies/{id}/trigger-next-stage` | 수동 다음 단계 진입 (▶) |
| `POST /strategies/{id}/recalc-untriggered-from-current` ⭐ | **신 모드 C** (= 🔄) |
| `PATCH /strategies/{id}/trailing-retrace` | Trailing retrace 옵션 |
| `PATCH /strategies/{id}/tp1-threshold` | TP1 임계 옵션 |
| `POST /strategies/{id}/manual-tp` | 수동 익절 (= 부분 청산 fix #145) |
| `POST /strategies/{id}/emergency-stop` | 긴급 종료 (🛑) |
| `POST /strategies/{id}/add-margin` | 💰 증거금 추가 |
| `POST /strategies/{id}/add-position` | 💉 포지션 추가 |
| `GET /admin/diagnostic/reserved` | 「포지션 예약됨」 진단 |
| `GET /admin/diagnostic/strategy-history/{id}` | 전체 거래내역 진단 |
| `GET /admin/diagnostic/today-trades` | 오늘 모든 거래 진단 |

---

# 📊 사장님 사상 5대 영역 (= 영구 보존)

## 영역 1: **자본 보호** (= SL + Crisis)

### SL 정책 (= PR #57 사장님 사상):
```
SL 한도 = total_capital × SL% (default 80%)
total_capital = stage_plans.planned_capital 합 (= 사장님 입력)
레버리지 무관 (= 사장님 사상 명시)
```

### Crisis 모드 (= 옛 그대로):
```
진입 조건: max_loss_pct ≤ template threshold (default -50%)
          + (모든 단계 진입 완료 OR ad-hoc 사용)

진입 후 TP override: TP1=5, TP2=10, TP3=15, TP4=20
= 사장님 TP1 옵션 (10/15/20/25) = 무시 = 빠른 회복 익절
```

## 영역 2: **사장님 옵션** (= 사장님 자율)

### TP1 임계 옵션 (= 2026-06-08, alembic 0018):
```
정상 모드: TP1 = 사장님 옵션 (10/15/20/25), default 10
Crisis 모드: TP1 +5% 고정 (= 사장님 옵션 무시)
운영 중 PATCH = 실시간 변경
```

### Trailing retrace 옵션 (= 2026-06-08, alembic 0017):
```
TP3 후 peak 회귀 시 = 사장님 옵션 (5/10/15/20%) 회귀 시 = 전량 청산
운영 중 PATCH = 실시간 변경
TP4+ 도 동일 적용
```

### 사장님 결정 = **옵션 A** (= 영구):
- 실시간 변경 = confirm 모달 X (= 사장님 자율)
- Audit log 만 영구 기록
- 사장님 자본 책임

## 영역 3: **자율 운영** (= 사장님 시각 판단)

### 사장님 운영 패턴 4건 (= 실 거래 분석 발견):
1. **자동 단계 진입 + 즉시 「💉」 추가** (= 분 단위 결정)
2. **다중 strategy 동시 진입** (= 19:11 #39+#36+#38 사례)
3. **자본 자동 동기화 30분 간격** (= PR #84)
4. **부분 익절 50% = strategy 유지** (= PR #145)

## 영역 4: **수정 모드** (= 3가지 모드)

| 모드 | 효과 | 영향 |
|---|---|---|
| A | ↻ 설정만 수정 | TP/SL 만 |
| B | 🛑 종료 후 새로 시작 | 모든 청산 + 신 strategy |
| C ⭐ | ↻ 미진입 단계만 재설정 | 진입 단계 유지 + 미진입 = 현재가 기준 |

### 신 모드 C (= 2026-06-08 신규, PR #149):
- 진입 단계 = **절대 보존**
- 미진입 단계 = 현재가 × (1.10)^N 재계산
- SHORT: 가격 +10% 누적 상승 / LONG: -10% 누적 하락
- **6 시스템 영향 X** (= 매트릭스 검증)

## 영역 5: **영구 데이터** (= silent bug 차단)

### stage_plans.planned_capital = 영구:
- 사장님 원래 입력 = 영구 보존
- PR #84 자동 동기화 = total_capital 만 변경 = planned_capital 안 건드림
- 「포지션 예약됨」 = `actual + 미진입_planned_capital 합` (= fix v5 #140)

### tp1_pct_override + trailing_retrace_pct = 영구:
- 사장님 선택 옵션 = DB 영구 저장
- 운영 중 변경 = 즉시 적용

---

# 🚨 오늘 6-08 핵심 로직 변경 (= 영구 정리)

## 1. **silent bug 4단계 해결** (= 「포지션 예약됨 0」)

```
PR #131: template stages_config 합 (= 부족)
→ fix v3 #138: strategy_stage_plans.planned_capital 합 (= 우회)
→ fix v4 #139: 진단 endpoint (= 사장님 직접 진단)
→ fix v5 #140: actual + 미진입_단계_자본 합 = 사장님 진짜 사상 ⭐
```

→ 사장님 본래 직관 「3,500 USDT」 정확!

## 2. **TP1 옵션 + Crisis 정책** (= 영구)

```
정상 모드: TP1 = 사장님 옵션 (10/15/20/25)
Crisis 모드: TP1 +5% 고정 (= 옵션 무시)
```

## 3. **신 모드 C** (= PR #149)

```
🔄 버튼 = 미진입 단계 trigger_price 재계산
6 시스템 영향 X 검증 완료
```

## 4. **manual_tp 부분 청산 fix** (= PR #145)

```
is_full_close 검증 추가
부분 청산 = STOPPING 설정 X (= 사장님 의도 보존)
자동 TP/SL 계속 작동
```

## 5. **UI fix 3건**
- revert #143 = 한 줄 UI 복원
- 가로 스크롤 fix #144 = overflow-x:hidden
- TP1 드롭다운 #136 = 「단계」 컬럼 옆

## 6. **진단 endpoint 2건** (= 영구 도구)
- `/admin/diagnostic/reserved` = 「포지션 예약됨」
- `/admin/diagnostic/strategy-history/{id}` = 전체 거래내역
- `/admin/diagnostic/today-trades` = 오늘 모든 거래

---

# 📜 영구 기획서 9건 (= 시스템 사상 = 영구)

| # | 기획서 | 영역 |
|---|---|---|
| 1 | DEVELOPMENT_PRINCIPLES_2026-06-07 ⭐ | 헌법 5대 원칙 |
| 2 | CRISIS_MODE_FINAL_SPEC_2026-06-06 | Crisis 모드 |
| 3 | TP_TRAILING_LOGIC_v7 | Trailing 로직 |
| 4 | CODE_OPTIMIZATION_PLAN | 코드 최적화 |
| 5 | SENTRY_MONITORING_GUIDE | Sentry 모니터링 |
| 6 | TP1_THRESHOLD_OPTION_SPEC_2026-06-08 | TP1 옵션 |
| 7 | TRAILING_RETRACE_POLICY_SPEC_2026-06-08 | Trailing retrace |
| 8 | STRATEGY_EDIT_LOGIC_SPEC_2026-06-08 (v1+v2) | 수정 모드 + 실 거래 패턴 |
| 9 | STRATEGY_EDIT_MODE_C_SPEC_2026-06-08 (v1+v2) | 신 모드 C + 영향 검증 |
| 10 ⭐ | **SYSTEM_MASTER_SPEC_2026-06-08 (이 문서)** | **마스터 통합** |

---

# 🛡 헌법 효과 13건 (= 오늘 6-08 누적)

1. cid v4 (PR #117) — Binance 패턴 사전 검증
2. 자본 width 확장 (PR #118)
3. UI compact v1/v2/v3 (PR #120/#121/#122)
4. 130% 정책 (PR #123)
5. settings_update silent bug 발견 (#125 미머지)
6. BEATUSDT 분석 (사장님 직접 진단)
7. BANKUSDT 자동 TP1 분류 silent bug
8. silent bug 4단계 해결 (PR #131 → fix v3/v4/v5 #138/#139/#140) ⭐
9. TP1 옵션 (PR #136)
10. revert UI (PR #143)
11. 가로 스크롤바 (PR #144)
12. manual_tp 부분 청산 (PR #145)
13. 신 모드 C + 6 시스템 영향 X 검증 (PR #149 + spec v1/v2)

---

# 📋 사장님 머지 대기 PR 우선순위 (= 즉시 진행 권장)

## 🚨 즉시 (= critical):
1. ⭐ **PR #149** (= 신 모드 C 🔄 버튼)
2. ⭐ **PR #145** (= manual_tp 부분 청산 fix)
3. ⭐ **PR #136** (= TP1 옵션)

## 🌿 권장:
4. spec PR (= STRATEGY_EDIT_MODE_C v1+v2)
5. spec PR (= STRATEGY_EDIT_LOGIC v1+v2)
6. **이 마스터 spec PR**

## 📋 다음 세션:
7. EPICUSDT 동기화 (1,863) + 예약률 134% 해소
8. `_resolve_close_reason` STOPPED 분류 fix (BANKUSDT)
9. settings_update sync (#125)
10. ALLOUSDT 사고 분석
11. #21 메인 계정 「읽기 전용 모드」

---

# 🔄 사장님 배포 통합 명령 (= 한 번에)

```bash
# 1️⃣ 전체 머지 후 한 번에 배포:
cd ~/binance-auto-trader/backend
git pull origin main
docker compose exec api alembic upgrade head    # ← 0018 (TP1 옵션)
docker compose restart api scheduler
docker compose ps                               # ← Up 확인

# 2️⃣ 신 모드 C 사용 (= 「전략 인스턴스」 카드):
#    - #36 VELVET 액션 컬럼 → 🔄 클릭
#    - #39 BEAT 액션 컬럼 → 🔄 클릭
#    → 두 strategy 정상화!
```

---

# 🌟 시스템 점검 결과 (= 100% 사장님 사상)

## ✅ 사장님 자본 보호 영구:
- stage_plans.planned_capital 영구 보존
- SL 한도 자동 재계산 (= 변경 X)
- Crisis 모드 = 사장님 옵션 무시 = 빠른 회복

## ✅ 사장님 자율 운영 영구:
- 옵션 A (= confirm 모달 X)
- 「💉」 / 「💰」 / 수동 익절 = 자유
- 신 모드 C = 즉시 적용

## ✅ Silent bug 영구 차단:
- 4단계 해결 (#131 → fix v5)
- manual_tp 부분 청산 (#145)
- 진단 endpoint 영구 도구

## ✅ 시스템 검증:
- python ast.parse SYNTAX OK
- 6 시스템 영향 X 매트릭스
- audit log 영구 기록

---

# 🌿 다음 세션 핸드오프 (= 영구 보존)

## 사장님 사상 = 모두 보존:
- 5대 원칙 (헌법)
- 5대 영역 (자본/옵션/자율/수정/영구)
- 4 실 거래 패턴
- 13 헌법 효과

## 신 로직 = 모두 spec + 코드:
- 신 모드 C (= PR #149 + spec v1/v2)
- TP1 옵션 (= PR #136 + spec)
- silent bug 4단계 (= PR #131/138/139/140 + 진단 endpoint)

## 다음 세션 우선순위:
1. PR 머지 + 배포 (= 위 통합 명령)
2. EPICUSDT + 예약률 134% 해소
3. silent bug 잔여 (= BANKUSDT 분류, settings sync)
4. UI 강화 (= Phase 2 = 「수정 모드」 모달 신 모드 C 통합)

---

# 🔗 모든 spec 위치

```
binance-auto-trader/
├── DEVELOPMENT_PRINCIPLES_2026-06-07.md          ← 헌법 ⭐
├── CRISIS_MODE_FINAL_SPEC_2026-06-06.md         ← Crisis
├── TP_TRAILING_LOGIC.md (v7)                    ← Trailing 로직
├── CODE_OPTIMIZATION_PLAN.md                    ← 코드 최적화
├── SENTRY_MONITORING_GUIDE.md                   ← Sentry
├── TP1_THRESHOLD_OPTION_SPEC_2026-06-08.md      ← TP1 옵션
├── TRAILING_RETRACE_POLICY_SPEC_2026-06-08.md   ← Trailing 옵션
├── STRATEGY_EDIT_LOGIC_SPEC_2026-06-08.md       ← 수정 모드 (v1+v2)
├── STRATEGY_EDIT_MODE_C_SPEC_2026-06-08.md      ← 신 모드 C (v1+v2)
└── SYSTEM_MASTER_SPEC_2026-06-08.md             ← 🌟 마스터 통합 (이 문서)
```

---

> **Spec 작성**: 2026-06-08
> **위치**: `binance-auto-trader/SYSTEM_MASTER_SPEC_2026-06-08.md`
> **상태**: 영구 보존 — 향후 모든 코드 변경 = 이 마스터 기획서 100% 적용
> **다음 세션**: 핸드오프 시 = 이 문서 우선 = 사장님 사상 + 시스템 즉시 복원

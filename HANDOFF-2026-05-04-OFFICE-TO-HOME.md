# HANDOFF — 2026-05-04 (사무실 → 집)

5-04 사무실에서 PR #1 + PR #2 머지 후 Phase 3a 검증 중 인계.

---

## 📌 한 줄 요약

집 PR #1 (26 commits) + 사무실 신규 PR #2 (1 commit, 86bd347) 둘 다 main 으로 머지 완료. **수동 진입 기능 (Phase 1 + 2 + 3a) 가 production main 에 적용됨.** 추가 검증 + 누적 LIMIT 정리 + Phase 3b/c (capital 변경 + stage 추가) backend 확장이 보류.

---

## ✅ 사무실 세션 완료 작업

### A. 환경 검증 (Section A)
- [x] `git status` clean, 27 commits ahead of origin/main 확인
- [x] pytest 292 passed (100.23s)
- [x] 신규 파일 5-04 작업물 모두 존재 (sentry.py, strategy_status.py, account_daily_loss_limiter.py 등)
- [x] 활성 전략 4개 (#93/#96/#98/#99) DB ↔ Binance 동기화 확인

### B. 코드 작업 — 수동 진입 기능 (PR #2, commit `86bd347`)

**Phase 1 — 「▶ 다음 단계」 시장가 즉시 진입**
- `execution_service.enter_stage_at_market()` 신규 메서드
- planned_capital × leverage / current_price 로 qty 재계산 → MARKET 주문
- 자동 워커 (stage_trigger_worker) 는 LIMIT @ trigger_price 그대로 (의도)
- API endpoint 동일 (`POST /strategies/{id}/trigger-next-stage`), 내부만 변경

**Phase 2 — 「💉 포지션 추가」 ad-hoc 진입**
- 신규 endpoint: `POST /strategies/{id}/add-position`
- `execution_service.add_position_now()` — 자유 USDT 금액 + MARKET/LIMIT
- 신규 모달 (심볼/방향/현재가/레버리지/미리보기 표시)
- 신규 ticker endpoint: `GET /market/ticker?symbol=...`
- ad-hoc 주문 (stage_no=NULL)

**Phase 3a — 「↻ 설정만 수정」 trigger% 갱신**
- 사용자 보고 #99: 「↻ 설정만 수정」 가 trigger% 변경 적용 안 됨 → fix
- `submitInPlaceSettings` 가 이전엔 TP/SL 만 보냄 → 이제 trigger_percents 도 보냄
- 발동된 stage (current_stage 이하) 는 frontend 가 null 마스킹 (backend 거부 회피)
- backend 의 PATCH /settings 는 이미 trigger_percents 받을 준비됨 (commit `3d96d89`)

### C. PR 머지 + main 동기

```
da8d2d5  Merge pull request #2 from herosys1-crypto/feat/manual-position-entry
86bd347  feat: 「▶」 시장가 즉시 진입 + 「💉 포지션 추가」 모달 + 「↻ 설정만 수정」 trigger% 갱신 연결
9d91dd7  Merge pull request #1 from herosys1-crypto/claude/loving-rhodes-52788c
b820a3e  docs: 2026-05-04 HOME→OFFICE 핸드오프 + ...
... (PR #1 의 26 commits)
```

local main = origin/main = `da8d2d5` ✓

---

## 🟡 보류 / 미해결 — 집에서 이어갈 작업

### 1. 「↻ 설정만 수정」 backend 확장 — Phase 3b + 3c (CRITICAL)

**현재 한계:**
- ❌ Capital (자본) 변경 in-place 미지원
- ❌ 신규 stage 추가 (예: 6단계 → 7단계) 미지원

**필요한 backend 변경:**
```python
# backend/app/api/v1/strategies.py StrategySettingsUpdate
class StrategySettingsUpdate(BaseModel):
    # 기존 TP/SL, trigger_percents...
    capitals: list[Decimal | None] | None = Field(...)  # NEW
    # 길이 변경 허용 (stages 추가/제거): current_stage 이하는 보존
```

`update_strategy_settings_in_place` 로직 확장:
- capitals 길이 변경 시: 신규 stage_plan 생성 또는 미발동 stage_plan 삭제
- capital 변경 시: 미발동 stage 의 planned_capital + planned_qty 재계산
- current_stage 이하 단계 변경 시도는 거부

**Frontend 변경:**
- `submitInPlaceSettings` 에서 `body.capitals = inp.capitals` 추가
- confirm 다이얼로그에서 capital 변경 표시

**예상 작업량**: 1~2시간 (backend + frontend + tests)

---

### 2. 「↻ 설정만 수정」 Phase 3a 검증 미완료

사용자가 #99 BIOUSDT 에서 testing 중에 발견:
- #99 의 current_stage = 4 (예상 1)
- stages 1-4 모두 LIMIT 미체결 (is_triggered=false)
- 사용자가 ▶ 다음 단계 3번 빠르게 클릭한 결과 (06:04, 06:07, 06:08)

→ Phase 3a 검증을 stage 5 또는 6 trigger 변경으로만 가능 (집에서 진행):

```
1. ✏️ 수정 → stage 5 trigger 10 → 15, stage 6 trigger 20 → 25
2. 「↻ 설정만 수정」 → 토스트 성공 확인
3. DB 검증:
   docker exec binance-auto-trader-db psql "..." -c "SELECT stage_no, trigger_percent, trigger_price FROM strategy_stage_plans WHERE strategy_instance_id = 99 AND stage_no IN (5, 6);"
   → trigger_percent 가 15 / 25 로 갱신됐는지
```

---

### 3. #99 BIOUSDT 누적 LIMIT 정리 (운영 측면)

**현재 상태:**
- current_stage = 4
- Stage 1: PARTIALLY_FILLED (2,441/3,298 lots @ 0.06063)
- Stage 2: NEW LIMIT (4,498 @ 0.06669) — 미체결
- Stage 3: NEW LIMIT (6,816 @ 0.07335) — 미체결
- Stage 4: NEW LIMIT (8,676 @ 0.08068) — 미체결

**위험성:**
- 현재가 0.01915 → 평균가 0.06063 대비 -68% (SHORT 수익 중)
- 가격이 4배 (~ 0.08) 까지 오를 가능성은 낮지만, bull run 시 LIMIT 들 차례로 체결 → 평단 끌어올림 + 청산 위험

**옵션:**
- A. 그대로 둠 (가격 낮은 한 안전)
- B. 「⏸ 미체결 주문 취소」 → stages 2/3/4 LIMIT 만 취소 (current_stage 는 4 유지 — DB 정합성 이슈 잠재)
- C. DB 의 current_stage 를 1 로 되돌리기 + LIMIT 취소 (정합성 회복, 수동 작업 필요)
- D. 「종료 후 새로 시작」 — 깨끗하게 재시작 (포지션 청산 + 새 전략)

---

### 4. #96 TSTUSDT 도 비슷한 상태

- current_stage = 4 또는 5 (이전에 ▶ 여러 번 + 5단계 LIMIT 발송됨)
- Stages 5, 6 도 LIMIT 발송됐을 가능성
- 손실 -56 USDT (-13%)
- 처리 방향: #99 와 동일 (관망 / 정리)

---

### 5. Section B 운영 검증 미완료 (Task #14)

핸드오프 인계 사항 4가지 시나리오:
1. 「▶ 다음 단계」 중복 가드 (이제 시장가라 의미 변경됨 — 같은 stage MARKET 주문 발송 시도?)
2. 「↻ 설정만 수정」 in-place — Phase 3a 부분 검증, capital/stage 추가는 미지원
3. 「💰 증거금 추가」 — 미시연
4. -50% ROI 손실 임계 알림 — 시뮬레이션 어려움 (인위 -50% 만들기)

---

## 🚀 집 컴퓨터 setup 절차

### 1. 코드 sync
```powershell
cd C:\Users\user\바이낸스\binance-auto-trader
git pull origin main
git log --oneline -5
```

기대 HEAD: `da8d2d5 Merge pull request #2 from ...`

### 2. 컨테이너 재시작 (Docker Desktop 켜진 상태)
```powershell
cd backend
docker compose restart api scheduler user-stream
```

### 3. user-stream 다중 실행 확인
```powershell
docker ps --filter "name=user-stream"
```
→ 1개만 보이는 게 정상

### 4. 브라우저 하드 리프레시
- `localhost:8000/admin-ui` → **Ctrl + Shift + R**
- 활성 전략 행에 「💰 증거금 추가」 + **「💉 포지션 추가」** 버튼 둘 다 보이는지 확인

### 5. pytest 검증 (선택)
```powershell
cd backend
.venv\Scripts\activate
pytest -q
```
→ 292 passed 그대로 나와야 정상

---

## 🎯 집에서 이어갈 작업 우선순위

### 우선순위 1: Phase 3a 검증 마무리 (10분)
- #99 BIOUSDT stage 5 trigger 10 → 15 변경 → DB 반영 확인
- 성공 시 Phase 3a 완전 종결

### 우선순위 2: Phase 3b + 3c backend 확장 (1~2시간)
- StrategySettingsUpdate 에 capitals 필드 추가
- update_strategy_settings_in_place 에 capitals 처리 로직
- stages_config 길이 변경 허용 (신규 stage_plan 생성/제거)
- frontend submitInPlaceSettings 에서 capitals 도 전송
- pytest 회귀 + 신규 통합 테스트 (test_inplace_capitals_and_stage_addition.py 등)
- commit + push + PR + merge

### 우선순위 3: #96/#99 누적 LIMIT 정리
- 옵션 B (LIMIT 취소만) 또는 D (종료 후 새로 시작) 선택
- testnet 검증 시나리오 (200/300/500/700/900/1200 6단계 +20%) 시작

### 우선순위 4: Section B 미완료 시나리오
- 「💉 포지션 추가」 모달 시연 (#93 AKTUSDT 같은 작은 전략)
- 「💰 증거금 추가」 시연 (ISOLATED 모드 한정)

### 우선순위 5: 보안 로테이션 (4-30 핸드오프부터 보류)
- `.env` Neon DB password
- SECRET_KEY / ENCRYPTION_KEY (단, 기존 데이터 영향 신중히)
- Telegram BOT_TOKEN

---

## 🔧 환경 정보 (변경 없음)

- DB: Neon Cloud (`ep-sparkling-forest-ao116t81.c-2.ap-southeast-1.aws.neon.tech/neondb`)
- 로컬 docker postgres: 옛날 BTCUSDT 테스트 데이터 (#10-21) 만 있음 — 무시
- main HEAD: `da8d2d5` (origin/main 동기)
- 활성 전략: 4개 (#93 AKTUSDT, #96 TSTUSDT, #98 LABUSDT, #99 BIOUSDT)

---

## 📚 권위 있는 문서 (변경 없음)

| 문서 | 역할 |
|---|---|
| `SYSTEM-SPEC.md` | 시스템 정밀 기획서 — 새 작업 전 반드시 참조 |
| `AUDIT-FINDINGS.md` | A01~A17 audit 결과 |
| `RUNBOOK.md` (backend/) | 운영 매뉴얼 |
| `MAINNET-CHECKLIST.md` | mainnet 전환 체크리스트 |
| `CHANGELOG.md` | 세션 단위 변경 이력 — **5-04 사무실 세션 추가 필요** |

---

## 📂 untracked 파일 (정리 보류)

```
HANDOFF-2026-04-30-OFFICE-EVENING.md (이전 세션 인계서)
HANDOFF-2026-05-04-OFFICE-TO-HOME.md (이 파일)
option_c_diff.txt (4-30 진단용 임시)
sync-from-office.ps1 (4-30 동기화 스크립트)
이어서-진행하기.md (메모)
```

→ `.gitignore` 에 추가 또는 삭제 — 다음 세션 결정.

---

## 🔖 sumar — 5-04 사무실 세션 commits (모두 main 에 반영됨)

```
da8d2d5  Merge pull request #2 — feat/manual-position-entry
86bd347  feat: 「▶」 시장가 즉시 진입 + 「💉 포지션 추가」 모달 + 「↻ 설정만 수정」 trigger% 갱신
9d91dd7  Merge pull request #1 — claude/loving-rhodes-52788c (PR #1 의 26 commits)
b820a3e  docs: HOME→OFFICE 핸드오프 + SPEC + CHANGELOG
... (PR #1 contents)
```

---

**작성: 2026-05-04 사무실. 다음 작업: 집 PC pull → Phase 3a 마무리 → Phase 3b/3c backend 확장 → testnet 검증.**

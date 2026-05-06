# HANDOFF — 2026-05-06 (집 → 사무실) [FINAL]

5-06 종일 작업 — **8개 PR + 5개 docs/deploy commit = 총 13 main commits**. 사무실에서
이어받기 위한 최종 인계서. **branch: `main` (모든 작업 머지 완료, 추가 작업 branch 없음).**

> **본 핸드오프는 2회차 갱신 (2266225 1차 → cbd1968 최종)**: VPS 배포 패키지 + 시장 순위 별도 페이지 + production .env 갱신 + SPEC cross-check + C-full archive UI 추가됨.

---

## 📌 한 줄 요약

**5-06 세션 13개 commits 모두 main 머지 완료.** 운영 통계 정확화 + UX 개선 + #96/#103
critical 사례 영구 방어 + **TP1~10 익절 10단계 확장 (사용자 요청 #1)** + **24h/주/월 변동률
순위 검색 + 별도 페이지 (사용자 요청 #2)** + **VPS 배포 패키지 (사용자 결정 — Neon 유지 +
DigitalOcean Singapore + ngrok 폐지)** + **C-full soft delete 완성 (active filter +
restore endpoint + UI 토글)**. **alembic 0010 → 0012 production 적용**. 회귀 가드
329 → **383 passed** (+54). 시스템 안정. **mainnet 직전 모든 핵심 기능 + 안전망 완성**.

---

## 🛠️ 5-06 세션 origin/main 에 들어간 13개 commit (최신 → 과거)

```
cbd1968 feat(archive): C-full — active filter + restore + UI toggle (#12)
3ea79c6 feat(ui): 시장 순위 별도 페이지 + nav + hash routing
55276e1 chore(env): production .env template + gitignore exception
0aa85c7 feat(deploy): VPS bootstrap.sh + secrets.sh + CHECKLIST.md
8f3436c docs(spec): 5-06 cross-check + TP10/peak/soft delete/ranking
2266225 docs: 2026-05-06 HOME→OFFICE 핸드오프 (1차)
fe00fda feat(market): symbols ranking endpoint + new-strategy modal integration (#11)
fa199ca feat(tp): TP1-10 take-profit stages (#10)
0620805 fix(risk): trailing TP fallback when Redis peak key volatile (#9)
aaaada2 feat(stats): clickable stats cells -> breakdown modal + autotranslate block (#8)
559ef95 feat(soft-delete): DELETE strategies -> archive (#7)
98f5dbb fix(ui): tiny-price start-price autofill + realized label autotranslate workaround (#6)
5adb538 fix(stats): strategy-based win rate + UI label clarity (#5)
```

PR 머지: #5/#6/#7/#8/#9/#10/#11/#12 — 8건. 그 외 docs/deploy 5건 main 직접 commit.

---

## 🐛 이 세션에 fix 한 핵심 사례

### 🔴 CRITICAL — 사용자 #103 FHEUSDT (트레일링 미발동)
- 증상: TP3 까지 발동 (피크 +20.24%) 후 -13% 회귀했는데 trailing 100% 청산 안 됨.
- 원인: `_update_peak_pnl` 가 Redis 만 보고, key 휘발 시 (TTL/evict) 현재 PnL 을 새 peak 로 reset → trailing 무력화.
- Fix ([PR #9](https://github.com/herosys1-crypto/binance-auto-trader/pull/9)): `db_max_profit_pct` fallback 인자 추가. `true_peak = max(current, redis, db)`. Redis 자가 회복.
- 결과: #103 자가 회복 → COMPLETED + 잔량 5,229 청산 + realized +20.25 USDT.

### 🔴 CRITICAL — 사용자 #96 TSTUSDT (cascade delete 데이터 손실)
- 증상: hard delete 로 +867 USDT realized_pnl 이 통계 합계에서 영구 누락.
- Fix ([PR #7](https://github.com/herosys1-crypto/binance-auto-trader/pull/7)): DELETE → soft delete (archive). row + cascade orders 모두 보존. 통계 합계 거래소 history 일치 유지.

### 🟡 사용자 보고 — 운영 통계 정확화
- 「승률 100%」 가 실제 수익 23 / 손실 3 → **88.46%** 잘못 표시.
- 라벨 「확정 손익」 이 Chrome 자동번역에서 「안녕 손익」 / 「원숭이 손익」 으로 오역.
- Fix ([PR #5](https://github.com/herosys1-crypto/binance-auto-trader/pull/5) + [#6](https://github.com/herosys1-crypto/binance-auto-trader/pull/6) + [#8](https://github.com/herosys1-crypto/binance-auto-trader/pull/8)):
  - 승률 = strategy.realized_pnl 부호 기반 (수익 strategy / decided strategy × 100)
  - sublabel "수익 X / 손실 Y" 추가
  - `<html translate="no">` + meta google notranslate (자동번역 차단)
  - 6개 통계 셀 모두 클릭 가능 → 「📊 운영 통계 상세」 모달 (12 컬럼 strategy 별 detail)

### ✨ 신규 기능 (사용자 요청)
- **익절 5단계 → 10단계 확장** ([PR #10](https://github.com/herosys1-crypto/binance-auto-trader/pull/10))
  - default: TP1=10/TP2=15/.../TP10=55 (5% 간격), 각 잔량 25%, TP10=100%
  - alembic 0012: `tp6~tp10_percent` + `tp6~tp10_qty_ratio` 컬럼 추가
  - 마지막 활성 TP 자동 100% 청산 로직 활용 (기존)
  - 트레일링 -5% 회귀 그대로 (사용자 명시)
  - backward-compat: 기존 5단계 strategy (tp6~10 NULL) 동작 그대로
- **24h/주/월 변동률 순위 검색** ([PR #11](https://github.com/herosys1-crypto/binance-auto-trader/pull/11))
  - `GET /api/v1/symbols/ranking?period=&direction=&limit=`
  - period 13종: 1d/2d~7d/1w/2w/1m/3m/6m/1y
  - direction: gainers / losers
  - 1d 는 모든 USDT/USDC perp, 그 외는 24h 거래대금 top 50 만 정확 계산 (호출 수 제한)
  - Redis 캐시 (1d=60s, 1w=5m, 1m=30m, 1y=4h)
  - 빠른 작업 「📈 시장 순위」 + 새 전략 모달 「📉/📈 top」 통합 (선택 → 심볼/시작가 자동 채움)

---

## 🗂️ 새로 생성된 파일

### Backend (마이그레이션)
- `backend/alembic/versions/0011_strategy_instances_archived.py` — soft delete (PR #7)
- `backend/alembic/versions/0012_strategy_templates_tp6_to_tp10.py` — TP6~10 컬럼 (PR #10)

### Backend (신규 endpoint, 5건)
- `POST /strategies/{id}/add-margin` (5-04 PR #1, spec 갱신 누락이었음)
- `GET /admin/stats/breakdown?view=` (PR #8)
- `GET /symbols/ranking?period=&direction=&limit=` (PR #11)
- `POST /strategies/{id}/restore` (PR #12)
- frontend `#ranking` page route (3ea79c6)

### VPS 배포 패키지 (mainnet 직전)
- `deploy/vps-bootstrap.sh` — Phase 1 자동화 (Ubuntu 24.04 root 1회 실행)
- `deploy/generate-secrets.sh` — SECRET_KEY/ENCRYPTION_KEY 자동 생성 + 외부 자격증명 가이드
- `VPS-DEPLOY-CHECKLIST.md` — 단계별 진행 (사전 결정 30분 + 셋업 2~3시간)
- `backend/.env.production.template` — DAILY_LOSS_LIMIT_USDT 등 5-04 신규 변수 추가
- `.gitignore` — `!backend/.env.production.template` 예외

### Docs
- `SYSTEM-SPEC.md` — 본문 fix (TP1~10, peak fallback, status 표 + ARCHIVED) + 「🔍 5-06
  cross-check 결과」 섹션 + 「📜 리비전 노트」 5-06 절 추가

### Tests (329 → 383, +54 신규)
- `test_admin_stats_winrate.py` (6) — 승률 strategy 단위
- `test_admin_stats_breakdown.py` (6) — 운영 통계 상세 endpoint
- `test_strategy_soft_delete.py` (7) — archive 동작
- `test_peak_pnl_redis_fallback.py` (7) — peak DB fallback
- `test_tp10_stages.py` (18) — TP1~10 확장
- `test_symbol_ranking_route_order.py` (4) — ranking endpoint route order
- `test_archive_active_filter_and_restore.py` (6) — C-full filter + restore

---

## ✨ 추가 작업 (1차 핸드오프 후 — 6 commits)

### PR #12 — C-full archive UI (사용자 데이터 영구 방어 강화)
PR #7 (soft delete) 의 자연스러운 후속:
- 모든 active query 7곳에 `WHERE NOT is_archived` filter (repository / 5 worker / strategy_service / zombie_guardian)
- 신규 `POST /strategies/{id}/restore` endpoint — archive 해제, idempotent
- UI 「📦 보관 보기」 체크박스 (localStorage 저장) + archived row 의 「↻ 복원」 버튼
- StrategyDetailResponse 에 `is_archived` + `archived_at` 필드 노출
- 진입 종료 strategy 도 「🗑」 (archive) 가능 (이전엔 「🔄 다시 시작」 만 가능했음)

### 시장 순위 별도 페이지 (사용자 요청 #2 의 미완성 부분)
PR #11 의 모달 외에 페이지 신설 (사용자가 "별도로 다른 페이지에서도" 명시):
- 헤더 nav: 「📊 운영」 / 「📈 시장 순위」
- URL hash routing: `#dashboard` (default) / `#ranking`
- 페이지 = 상단 방향 toggle + 13 period tab + 표시 개수 select + 30 row 테이블
- 「↑ 새 전략」 버튼 → dashboard 이동 + 새 전략 모달 자동 열림 + 심볼/시작가 자동 채움
- 모달 + 페이지 양쪽 모두 활용 가능 (workflow 끊김 없음)

### VPS 배포 패키지 (사용자 결정 — Neon 유지 + DigitalOcean Singapore + ngrok 폐지)
사용자 응답: 「Neon Cloud 이미 유료 전환」 → 마이그레이션 X, region 동일 Singapore 유지.
- Phase 1 (OS hardening + Docker) 완전 자동화 — `vps-bootstrap.sh` 1회 실행
- 자격증명 helper — `generate-secrets.sh` (SECRET_KEY/ENCRYPTION_KEY/POSTGRES_PASSWORD/REDIS_PASSWORD)
- 단계별 체크리스트 — Phase 0~5 (droplet 생성 → testnet 검증 → mainnet 전환)
- 월 비용 예상: VPS $48 + Backups $10 + Neon $19 + 도메인 $1 = ~$78/월. ngrok $0 (폐지).
- 첫 60일 DigitalOcean $200 promo 적용 시 검증 무료.

### SYSTEM-SPEC 5-06 cross-check 보강
사용자 요청 #2 「전체 로직 정확하게 정리해서 적용되는지 검증」:
- 9 영역 (익절/트레일링/손절/크라이시스/단계/재진입/좀비/일일손실/Kill Switch + 운영통계)
- 각 영역 SPEC ↔ 코드 cross-check 결과 + 회귀 테스트 inventory
- 본문 fix: 2.2 (TP1~10), 2.3 (peak fallback), 2.9 (status 표 STAGE1~10/TP1~10/ARCHIVED/REENTRY_FAILED/CRISIS_TP1)
- 신규 14절 체크리스트 항목 (5-06 신규 5건 추가)

---

## 📊 운영 데이터 현재 상태 (2026-05-06)

### 활성 strategies
- #102 LABUSDT STAGE1_OPEN
- #104, #105 STAGE1_OPEN
- (#103 FHEUSDT COMPLETED — trailing 자가 회복)
- (#96 TSTUSDT 재진입 했으면 별개 — 어제 archive 완료)

### 누적 통계 (/admin/stats 응답)
- 전체 strategies: 39
- profit / loss: 24 / 3
- 승률 (strategy 기준): 88.89%
- 실현 손익 (확정): +621 USDT 수준 (수시 변동)

### alembic head: `0012_template_tp6_to_tp10`

---

## 🚀 사무실 컴퓨터 setup 절차

### 1. 코드 sync
```powershell
cd C:\Users\user\바이낸스\binance-auto-trader
git pull origin main
git log --oneline -8
```
기대 HEAD: `fe00fda feat(market): symbols ranking endpoint + new-strategy modal integration (#11)`

### 2. Alembic 동기화 (production DB 가 자동으로 적용된 상태이므로 no-op)
```powershell
docker exec binance-auto-trader-api alembic current
# 기대: 0012_template_tp6_to_tp10 (head)
```

### 3. 컨테이너 재시작 (안전망)
```powershell
docker restart binance-auto-trader-api binance-auto-trader-scheduler binance-auto-trader-user-stream
```

### 4. 브라우저 하드 리프레시
- `localhost:8000/admin-ui` → **Ctrl + Shift + R**
- 확인 항목:
  - 빠른 작업 패널에 **「📈 시장 순위」** 버튼
  - 운영 통계 패널 6 셀 모두 **「🔍」** 클릭 가능, 「확정 손익 (Realized)」 라벨
  - 새 전략 모달 「⚙️ 익절/손절 설정 (TP1~10)」 — TP6~10 입력 칸
  - 새 전략 모달 시작가 영역에 「📉 하락 top」 / 「📈 상승 top」 버튼
  - 「🗑」 클릭 시 archive 다이얼로그 (강화된 confirm)

### 5. pytest 검증 (선택)
```powershell
cd backend
.venv\Scripts\activate
pytest -q
```
기대: **383 passed** (1차 핸드오프 후 +6 — `test_archive_active_filter_and_restore.py`)

---

## 🎯 사무실에서 이어갈 작업 (우선순위 순)

### 우선순위 1: 신규 기능 운영 검증 (15분)
- 「📈 시장 순위」 클릭 → page 전환 (#ranking) — 13 period tab + 방향 toggle 모두 정상
- 새 전략 모달 안에서 ranking → 「↑ 선택」 → 심볼/시작가 자동 채움
- ranking page 의 「↑ 새 전략」 → dashboard 이동 + 모달 자동 + 심볼 채움
- TP1~10 default 채워진 새 strategy 시작 → TP10 까지 정상 progression
- 「🗑」 클릭 → archive 후 「📦 보관 보기」 체크 → 「↻ 복원」 동작 확인

### 우선순위 2: VPS 배포 진행 (사용자 직접 작업, 사전 결정 30분 + 셋업 2~3시간)
**사전 결정 4건** (`VPS-DEPLOY-CHECKLIST.md` 의 0-A~0-D):
- [ ] DigitalOcean 가입 + 결제 + 2FA + (첫 가입 시 $200 promo)
- [ ] SSH 키 생성 (Windows PowerShell `ssh-keygen`)
- [ ] 도메인 결정 (옵션 — Cloudflare/Namecheap ~$10/년)
- [ ] 외부 자격증명 사전 발급 (Neon password reset / Binance Mainnet API / Telegram BotFather / Sentry DSN)

**Phase 0~5 진행 후 ngrok 폐지 + mainnet 운영 시작**.

### 우선순위 3: mainnet 보안 로테이션 (mainnet 가기 전 필수)
`generate-secrets.sh` 자동 + 외부 자격증명 수동:
- `.env` Neon DB password (Neon console reset)
- SECRET_KEY / ENCRYPTION_KEY (자동 생성 — ENCRYPTION_KEY 손실 시 DB 복호화 불가, 백업 필수)
- Telegram BOT_TOKEN (BotFather 새 봇)
- Binance Mainnet API key (Futures only, Withdrawals OFF, IP whitelist)
- Sentry DSN (선택, 권장)

### 우선순위 4: scheduler 자동 사이클 verification (선택)
세션 중 일시적으로 #103 trailing 자동 발동 안 보이는 현상 발견. 결국 자가 회복했지만
lock TTL 20s + Interval 10s 의 ½ 빈도 + 일시적 mark price 변동이 원인일 가능성. 별도
확인 안 했으니 디버그 가치 (운영 영향 작음).

---

## 📚 권위 있는 문서 (변경 없음, 그대로 유효)

| 문서 | 역할 |
|---|---|
| `SYSTEM-SPEC.md` | 시스템 정밀 기획서 — 14절 |
| `AUDIT-FINDINGS.md` | A01~A17 audit |
| `RUNBOOK.md` (backend/) | 운영 매뉴얼 |
| `MAINNET-CHECKLIST.md` | mainnet 전환 체크리스트 |
| `DEPLOYMENT-DIGITALOCEAN.md` | VPS 배포 가이드 |
| `CHANGELOG.md` | 세션 단위 변경 이력 — **5-06 세션 추가 필요** (다음 작업) |

---

## ⚠️ 알려진 별개 이슈 (다음 세션 결정)

1. **scheduler tp_sl 자동 사이클 일시 미발동** — false alarm 으로 판명됐으나 lock TTL 20s + Interval 10s 의 ½ 빈도 영향. 운영 영향 작지만 향상 가능.
2. **#100 4USDT STOPPING 좀비** — zombie_guardian 5/5 escalation 돼야 함. 확인 필요.
3. **C-full** (PR #7 의 후속) — `WHERE NOT is_archived` filter + restore endpoint + UI 「복원」 버튼. mainnet 안정화 후 검토.
4. **시장 순위 (PR #11) 의 별도 페이지** — 모달만 구현. 「URL `#ranking` 별도 페이지」 는 미구현 (사용자 요청에 명시됐으나 모달이 충분 가시성 제공). 필요 시 추가.

---

## ✅ 이번 세션 commit 메시지 컨벤션

- `feat(<scope>):` 신규 기능 (사용자 가시)
- `fix(<scope>):` 버그 수정. scope = ui/risk/api/stats/workers/...
- `docs:` 문서만 변경
- 본문에 사용자 사례 번호 (#96, #103) 명시

---

**1차 작성: 2026-05-06 새벽 집 PC (commit 2266225).**
**최종 갱신: 2026-05-06 (commit cbd1968 후 — VPS 패키지 + 시장순위 page + .env template + SPEC + C-full 추가).**

**다음 작업 흐름**:
1. 사무실에서 `git pull origin main` (HEAD = `cbd1968`)
2. 우선순위 1 (신규 기능 운영 검증, 15분)
3. 우선순위 2 (VPS 배포 — 사용자 직접 작업 시작)
4. 우선순위 3 (mainnet 보안 로테이션 + 첫 거래)

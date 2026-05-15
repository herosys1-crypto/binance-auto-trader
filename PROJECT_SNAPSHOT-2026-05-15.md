# 프로젝트 종합 스냅샷 — 2026-05-15

| 항목 | 내용 |
|---|---|
| 작성일 | 2026-05-15 (저녁 — leverage UX fix 머지 직후) |
| main HEAD | `575c10a` |
| 운영 상태 | testnet on VPS 24/7, 코드 측면 mainnet 준비 100% 완성 |
| 5월 누적 변화 | 151 commits (4-28 ~ 5-15) |
| pytest | 684 passed |
| 정책 버전 | TP qty v6 (균일 25%) + trailing v5 (TP3+, stage>=3) + 단축 익절 v7 + crisis 비활성 (사용자 결정) |

---

## 1. 한 문장 요약

**1인 운영자가 Binance Futures USDⓢ-M Perpetual 에서 「분할 진입 1~10 + TP1~10 + 트레일링 + 크라이시스 + 자동 좀비 청소」 전략을 24시간 자동 실행하는 트레이딩 시스템. 2026-05-15 시점 testnet on VPS 운영 중, mainnet 전환은 사용자 testnet 검증 충족 시 즉시 가능.**

---

## 2. 운영 환경 (2026-05-15 검증)

### VPS — DigitalOcean SGP1
- **IP**: `159.65.137.250` (옛 `152.42.232.195` 는 5-08 이후 stale)
- **Plan**: General Purpose 8GB
- **OS**: Ubuntu 24.04 LTS
- **Hostname**: `binance-trader-prod`
- **SSH**: `ssh -i ~/.ssh/id_ed25519 root@159.65.137.250`
- **Repo 위치**: `/root/binance-auto-trader/`
- **컨테이너**: api / scheduler / user-stream / redis (smoke 13/13 통과)
- **운영 URL**: http://159.65.137.250/ (nginx → api 8000)

### Database — Neon Cloud (Singapore)
- PostgreSQL 16
- 5-15 시점 strategy 59건 보존 (testnet 운영 누적)
- alembic head: `0016_hot_path_indexes`

### 외부 자격증명
- Binance Testnet API (DB 의 ExchangeAccount #1, websocket 활성)
- Telegram Bot (heartbeat + RiskEvent 알림)
- Sentry DSN: 미설정 (옵션, mainnet 권장)

---

## 3. 5월 진화 타임라인

| 날짜 | 핵심 이벤트 |
|---|---|
| 4-28 | 옵션 C (1~10 단계) + TP1~5 기반 옵션 가격 자동매매 시스템 시작 |
| 4-29~30 | UI #17~28 (TradingView 차트, 액션 버튼, 단계바) + Bug #11 step_size flooring |
| 5-02 | trailing TP 도입 (v1: TP3+ 잔량 이후 -5% 하락 시 청산) |
| 5-04 | 옵션 C 검증 + AUDIT-FINDINGS A01~A17 처리 + zombie_guardian 회귀 테스트 |
| 5-06 | TP1~10 확장 (#10), 시장 순위 페이지 (#11), C-full archive (#12), trailing fallback (#9) |
| 5-07 | mainnet 안전망 7건 머지 (#13~#19): KS 알림, 일일 손실 한도, 자본/동시성/화이트리스트, leverage cap, liq 거리, heartbeat, KS 수동 해제 UI, 키 회전 |
| 5-08 | trailing TP3+ + crisis 전 단계 -50% (#20) |
| 5-09 | 화이트리스트 운영자 런타임 토글 (#22) |
| 5-10~12 | trailing v3~v5, TP qty v6 (균일 25%), crisis 임계 사용자 정의, ensure_isolated_margin 자동 |
| 5-13~14 | 다중 심볼 chip + 사용자 정의 템플릿 + Phase 3 UI 모듈화 시작 (cm-* 9개) |
| 5-15 (오전~오후) | Phase 3 마무리 (32 모듈), 사용자 보고 #33/#41/#57/#VICUSDT, ensure_isolated, archive nonzero CRITICAL |
| **5-15 (저녁)** | **PR #23 머지 (89 commits)** + VPS 배포 (smoke 13/13) + leverage UX 3건 |

---

## 4. 코드 아키텍처 (2026-05-15 현재)

### 4.1 Backend 디렉토리

```
backend/
├── app/
│   ├── api/v1/           — REST endpoints (53건, admin 19 + strategies 17 + ...)
│   │   ├── admin/        — 5 모듈 분리 (templates/export/monitoring/operations/system)
│   │   └── strategies/   — 5 모듈 분리 (helpers/calculate/crud/control/lifecycle)
│   ├── services/         — 비즈니스 로직 (10+ services, 큰 것: execution 718줄, zombie_guardian 578줄)
│   ├── workers/          — APScheduler 작업 (reconcile/stage_trigger/auto_reentry/daily_loss/heartbeat/user_stream)
│   ├── models/           — 13 SQLAlchemy 모델
│   ├── repositories/     — DB 접근 layer
│   ├── integrations/binance/  — Binance Futures API client + WebSocket
│   ├── core/             — config / database / dependency / encryption
│   └── static/
│       ├── index.html    — 1,178줄 (이전 5,875줄 → -79.9%)
│       └── js/           — 32 모듈
├── tests/                — 684 pytest passed
├── alembic/versions/     — 0001~0016 migrations
├── scripts/              — rotate_encryption_key, check_binance_key, db_backup
└── docker-compose.yml + Dockerfile
```

### 4.2 32 JS 모듈 (Phase 3 완료, 2026-05-14~15)

| 카테고리 | 모듈 | 역할 |
|---|---|---|
| 코어 | constants / api / helpers | 상수 / 인증 / UI 헬퍼 |
| 새 전략 모달 (cm-*) | collectors / loaders / market-info / capitals-grid / preview / submit / state-helpers / open-modal / prev-blueprint | 「+ 새 전략」 모달 9개 |
| 대시보드 패널 | dashboard-refresh / templates-panel / strategies-list / indicators | 패널 갱신 + 보조지표 |
| 전략 상세 | strategy-detail / chart-detail / strategy-actions | 상세 패널 + TradingView 차트 + 액션 |
| 모달 | accounts-modal / add-position-modal / stats-modals / ranking-modal / trade-history-modal | 5개 모달 |
| 페이지 | page-router / health-page / ranking-page | hash routing + 별도 페이지 2개 |
| 액션 | admin-shortcuts / multi-symbol / template-save | 헤더 액션 + 다중심볼 + 템플릿 저장 |
| 부트스트랩 | auth-bootstrap / system-banner | 로그인 + init + 시스템 배너 |

### 4.3 13 SQLAlchemy 모델

`exchange_account` / `strategy_template` / `strategy_instance` / `strategy_stage_plan` / `order` / `position` / `risk_event` / `notification` / `account_kill_switch` / `account_daily_risk_limit` / `stream_session` / `symbol` / `system_setting` / `user`

### 4.4 16 Alembic Migrations

`0001` baseline → `0002~0007` reentry/templates → `0008` risk_event nullable → `0009` crisis_qty_ratios → `0010` daily_loss_limit → `0011` archived → `0012` tp6~10 → `0013` system_settings → `0014` stage_addmargin → `0015` template_crisis_threshold → **`0016` hot_path_indexes (5-13)**

---

## 5. 핵심 정책 최종 버전

### 5.1 단계 진입 (1~10)
- 1단계: `IMMEDIATE` (start_price LIMIT)
- 2~N-1: `PRICE_UP_PCT` (SHORT) / `PRICE_DOWN_PCT` (LONG), default 2~4=10%, 5~10=20%
- N (마지막): `PRICE_UP_PCT` default, 사용자 last_stage_trigger_percent 입력 (default 20%)
- **단계별 추가 증거금** (alembic 0014, 5-11): LIMIT fill 후 자동 add_position_margin

### 5.2 익절 v6 — TP qty 균일 25% (5-12 밤)
- TP1~9: 25% (잔량 비율) — 사용자 입력 우선, NULL 이면 default
- TP10: 100% (절대 마지막 안전망)
- last_active_tp shortcut **폐지** (잔량 보유 → trailing 가능)
- 한 cycle 1단계만 발동 (TP skip 방지, #98 LABUSDT)
- step_size floor + 최소 1 step 보장 (#40 BUSDT)

### 5.3 트레일링 청산 v5 — TP3+ AND stage>=3 (5-12)
- 진입 조건: TP3 이상 발동 + 진입 단계 ≥ 3
- 청산 조건: 피크 PnL 대비 -5% 회귀 시 잔량 100% 청산
- Redis peak key fallback (#103 사례 영구 방어)

### 5.4 단축 익절 v7 — stage<3 + TP3+ (5-14)
- 진입 단계 1~2 + TP3 이상 도달 → 잔량 100% 즉시 청산 (trailing 기다림 불필요)
- 사용자 기획: "낮은 단계인데 큰 익절 났으면 그냥 정리"

### 5.5 손절 (SL)
- `template.stop_loss_percent_of_capital` 기준
- 도달 시 잔량 100% 시장가 청산 + status=STOPPED + last_close_reason=SL

### 5.6 크라이시스 복구 모드 (사용자 결정 — 비활성)
- 5-14 사용자 결정: 「손절만 사용」 → dropdown 제거 + 새 strategy 자동 -100 (비활성 sentinel)
- 코드는 보존 (template 별 임계 사용자 정의 가능, alembic 0015)

### 5.7 ISOLATED 마진 (5-15)
- `ensure_isolated_margin` 모든 신규 거래 자동 호출 — CROSS 모드 방지
- -4046 / -4096 친절 에러 매핑 (#102)

---

## 6. 안전망 (Mainnet 준비도 100%)

| 안전망 | 코드 | 발동 조건 | 알림 |
|---|---|---|---|
| **Kill-Switch** | `account_kill_switch_service` | 자동 발동 또는 수동 | 텔레그램 + UI 「🔓 해제」 |
| **일일 손실 한도** | `account_daily_loss_limiter` | 80% 경고 → 100% KS | 텔레그램 (#15) |
| **자본 상한** | `risk_service` | 단일 strategy ≤ 잔액 5% | ValueError |
| **동시성 한도** | `strategy_service` | 계정당 ≤ 3 strategy | ValueError |
| **심볼 화이트리스트** | DB `system_settings` (#22) | testnet 「BTC/ETH」 default, 운영자 토글 | 진입 차단 |
| **레버리지 상한** | `risk_service` | ≤ 5x | ValueError |
| **청산가 거리** | `risk_service` | ≥ 5% | ValueError |
| **Heartbeat** | `heartbeat_worker` | 6h 주기 | 텔레그램 |
| **Zombie Guardian** | `zombie_guardian` | 1) DB-거래소 dedup 2) orphan position 3) **orphan open order (5-15)** | RiskEvent CRITICAL/WARN |

---

## 7. 사용자 보고 누적 + Fix (5월 핵심 사례)

| 보고 | 증상 | 원인 | Fix |
|---|---|---|---|
| #21 SAGAUSDT | 수동 진입 시 마진 안 들어감 | additional_margin_usdt 자동 투입 누락 | 명령 발송 시 자동 add_margin 호출 |
| #26 JELLYJELLY (4차) | -4015 clientOrderId 에러 | Binance 32자 cap | clientOrderId v3: 하이픈→언더스코어 + 28자 cap + cid 빼고 재시도 |
| #33 AVAAIUSDT | archive 후 거래소에 잔량 좀비 | TP6~10_DONE_PARTIAL active 분류 누락 + position snapshot 미체크 | active 분류 보강 + archive nonzero position CRITICAL 알림 |
| #40 BUSDT | TP3 발동했는데 2 exits 만 표시 | step_size floor 가 0 으로 떨어짐 | 최소 1 step 보장 + INFO RiskEvent |
| #41 ESPORTSUSDT | #33 와 같은 패턴 | 동일 | #33 fix 가 함께 처리 |
| #57 MLNUSDT | 「청산 중」 stuck → 새 전략 차단 | STOPPING 5분+ stuck 시 안내 부재 | force-stop endpoint URL 명시 |
| #96 archive | DELETE 시 realized_pnl 합계 깨짐 | hard delete cascade | soft delete (archive) — DB row 보존 |
| #98 LABUSDT | TP2 skip | TP 정렬 안 됨 | ascending sort + cur_done_idx 보다 큰 첫 TP |
| #102 add_margin | -4046 「Add margin only support for isolated」 | endpoint path 잘못 + 친절 에러 X | path 수정 + 에러 매핑 |
| #103 trailing | Redis peak key 휘발 | restart 시 peak loss | DB fallback (#9) |
| #VICUSDT | 거래소 open order 좀비 (LIMIT 잔재) | Zombie Guardian 가 position 만 봄 | orphan_exchange_open_orders 신설 (3차 가드) |
| 5-15 leverage | 롱 default 1 + 불러오기 시 leverage 안 따라옴 + 인스턴스에 leverage 안 보임 | 3건 동시 보고 | 3개 모두 fix (`575c10a`) |

---

## 8. 검증된 배포 절차 (2회 성공, 5-15)

### 로컬 (PowerShell)
```powershell
cd C:\Users\user\바이낸스\binance-auto-trader
git checkout main && git pull

# Archive 만들기 (Git Bash 권장 — /tmp 경로)
# 또는 PowerShell 의 경우: $env:TEMP\repo.tar.gz

scp -i $env:USERPROFILE\.ssh\id_ed25519 $env:TEMP\repo.tar.gz root@159.65.137.250:/tmp/
ssh -i $env:USERPROFILE\.ssh\id_ed25519 root@159.65.137.250
```

### VPS 안에서
```bash
# .env 백업 + repo 갱신 + .env 복구
cp /root/binance-auto-trader/backend/.env /tmp/env-backup
tar -xzf /tmp/repo.tar.gz -C /root/binance-auto-trader --overwrite
cp /tmp/env-backup /root/binance-auto-trader/backend/.env

# CRLF 제거 (Windows tar 호환 — dos2unix 미설치)
find /root/binance-auto-trader -name '*.sh' -exec sed -i 's/\r$//' {} \;

# api 만 rebuild — 캐시 무시
cd /root/binance-auto-trader/backend
docker compose -f docker-compose.yml -f ../docker-compose.production.yml build --no-cache api
docker compose -f docker-compose.yml -f ../docker-compose.production.yml up -d --force-recreate api

# 검증
sleep 10
bash /root/binance-auto-trader/deploy/smoke-test.sh
```

### 주의사항 (5-15 hard-learned)
- ⚠️ **CRLF 제거 필수** — Windows tar 의 .sh 파일은 bash 가 거부
- ⚠️ **--no-cache** — 안 쓰면 `COPY . /app` 캐시 layer 재사용 → 옛 코드 그대로
- ⚠️ **sleep 10** — api startup 시간 (smoke /health 응답 위해)

---

## 9. VPS 운영 환경변수 (testnet 기준)

```bash
DAILY_LOSS_LIMIT_USDT=2000           # mainnet 시 자본 10% 권장
MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT=3
MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE=5.0
ALLOWED_SYMBOLS_CSV=BTCUSDT,ETHUSDT  # whitelist 토글로 운영자 변경 가능
MAX_LEVERAGE=5
MIN_LIQUIDATION_DISTANCE_PCT=5
HEARTBEAT_INTERVAL_HOURS=6
```

---

## 10. 다음 단계 — Mainnet 전환 잔여 (사용자 결정)

### 코드 측면 (완료)
- ✅ Kill-Switch + UI 해제 버튼
- ✅ 일일 손실 한도 + 80% 경고
- ✅ 자본 상한 / 동시성 / 화이트리스트
- ✅ 레버리지 상한 (≤5x) / 청산가 거리 (≥5%)
- ✅ 모든 텔레그램 알림 wired
- ✅ 24/7 heartbeat
- ✅ ENCRYPTION_KEY 회전 도구
- ✅ API 키 회전 + testnet ↔ mainnet 전환 endpoint
- ✅ Zombie Guardian 3차 (dedup + orphan position + orphan open order)

### 운영 측면 (사용자 직접)
1. testnet 종단간 검증 24h+ (`MAINNET-CHECKLIST.md` Phase 4)
2. Binance mainnet API 발급 + IP whitelist `159.65.137.250`
3. (옵션) 도메인 + Let's Encrypt HTTPS
4. ENCRYPTION_KEY 회전 (`scripts/rotate_encryption_key.py`)
5. 「💼 계정」 → 「🔑 키 변경」 → 환경 "mainnet" 선택
6. 운영 시작 후 모니터링 (Telegram heartbeat + Grafana)

---

## 11. 참조 문서 색인

| 문서 | 용도 |
|---|---|
| **이 파일** | 종합 스냅샷 (한 번 읽고 전체 그림) |
| `DEVELOPMENT_SPEC.md` v1.2 | 시스템 정의 + 비즈니스 룰 상세 |
| `SYSTEM-SPEC.md` | 시스템 아키텍처 (5-06 기준) |
| `AUDIT-FINDINGS.md` | A01~A24 (모두 완료) |
| `CONSISTENCY_CHECKLIST.md` | 코드 vs 기획서 정합성 (❌ 0건) |
| `TP_TRAILING_LOGIC_FINAL.md` | 익절/트레일/크라이시스 정책 최종 확정 |
| `MAINNET-CHECKLIST.md` | mainnet 전환 단계별 체크리스트 |
| `VPS-DEPLOY-CHECKLIST.md` | VPS 배포 단계별 (5-07 기준, 절차는 5-15 검증) |
| `OPERATIONS.md` | 일상 운영 (트러블슈팅 / 모니터링) |
| `CHANGELOG.md` | 날짜별 변경 이력 (5-06까지) |
| `HANDOFF-2026-05-15-PR23-MERGED.md` | 5-15 세션 핸드오프 + 검증된 배포 절차 |

---

## 12. 5-15 시점 commits 트리 (최근 10개)

```
575c10a Merge: leverage UX 3건 (롱 2x default + 불러오기 leverage 적용 + 인스턴스 컬럼 표시)
2c53d1e fix(ui): leverage UX 3건 — 롱 기본 2x + 불러오기 leverage 적용 + 인스턴스 컬럼 표시
279a5f4 docs(handoff): 5-15 VPS 배포 완료 반영 (smoke 13/13)
34e4b02 docs(handoff): 5-15 PR #23 머지 + VPS 배포 보류 기록
e824b0f Fix/pnl display Phase 3 UI 모듈화 + 사용자 보고 대응 + 정책 진화 (89 commits, 5-08~5-15)and loss alert clarity (#23)
d89a22c feat(settings): 화이트리스트 운영자 런타임 토글 (#22)
c02c05d feat(policy): trailing TP3+ + crisis 전 단계 -50% + 화이트리스트 UI (#20)
59e8ca4 feat(safety): KS 수동 해제 UI + leverage cap + liq 거리 + heartbeat (#19)
8b71dd0 feat(deploy): VPS 배포 자동화 강화 (#18)
2027624 feat(security): API 키 회전 + testnet ↔ mainnet 전환 (#17)
```

---

## 결론

**시스템은 mainnet 가능 상태. 코드 측면 모든 안전망 + 정책 + UX 완성. 사용자께서 testnet 검증 충족 시 즉시 mainnet 전환 가능.**

남은 단계는 모두 사용자 결정/직접 진행 항목 (testnet 검증, mainnet 키 발급, 환경 전환). 코드 변경은 운영 중 발견되는 버그/UX 개선에 한정.

VPS 배포 절차 검증 완료 (5-15 2회 성공) — 향후 기능 추가 시 같은 패턴으로 1~2분 내 배포 가능.

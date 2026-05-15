# Handoff — 2026-05-15 PR #23 머지 + VPS 배포 완료

이 세션은 **5-08~5-15 누적 89 commits 를 PR #23 으로 통합 머지** 하고, **VPS 배포까지 완료** (smoke test 13/13 통과) 한 것으로 마무리됨.

---

## 🎯 한 문장 요약

**main = `34e4b02` (PR #23 머지 + handoff). 코드 + 테스트 + 배포 모두 완료. 운영 환경 정상.**

---

## 🚀 5-15 VPS 배포 결과

| 검증 항목 | 결과 |
|---|---|
| api `/health` | ✅ `{"status":"ok"}` |
| 4 컨테이너 (api/scheduler/user-stream/redis) | ✅ 모두 running |
| alembic head | ✅ `0016_hot_path_indexes` |
| DB | ✅ Neon, 59 strategies 보존 |
| Redis ping | ✅ PONG |
| scheduler 활동 | ✅ 30 lines/min |
| user-stream websocket | ✅ connected |
| 정적 자산 | ✅ index.html 1180줄 + JS 모듈 32개 |
| Smoke test | ✅ **13/13 통과** |

⚠️ Smoke test 의 두 WARN 은 무시 (testnet 운영 — mainnet 시 채워야 함):
- `DAILY_LOSS_LIMIT_USDT` 미설정
- `SENTRY_DSN` 미설정

---

## ✅ 이번 세션 완료 작업

### 1. Phase 3 UI 모듈 분리 — 마무리 (Phase 3 단계 3m~3t)

`backend/app/static/index.html` 5,875 → 1,178줄 (-79.9%). 32 JS 모듈로 완전 분리.

이번 세션에서 새로 추출한 8개 모듈:
- `strategy-detail.js` — selectStrategy + stopStrategy
- `chart-detail.js` — 9개 차트 함수 + _detailChartState
- `accounts-modal.js` — 계좌 관리 + 화이트리스트
- `add-position-modal.js` — 「💉 포지션 추가」
- `strategy-actions.js` — emergencyStop + deleteStrategy + triggerNextStage + addMargin
- `admin-shortcuts.js` — testTelegram + exportCsv
- `page-router.js` — showDashboard + hash routing + scrollToSection
- `auth-bootstrap.js` — login submit + 자동 로그인 + 5초 폴링 init

`index.html` 의 inline `<script>` 는 이제 모두 포인터 코멘트만 남고 실제 로직은 모듈에. `<form id="login-form">` 등 DOM 만 inline.

### 2. PR #23 통합 머지

- 제목: `Fix/pnl display Phase 3 UI 모듈화 + 사용자 보고 대응 + 정책 진화 (89 commits, 5-08~5-15)`
- 89 commits / 115 files / +17,815 / −7,992
- Merge commit: `e824b0f`
- 브랜치 `fix/pnl-display-and-loss-alert-clarity` 머지됐지만 **삭제 안 함** (배포 후 정리 권장)

### 3. 테스트

- pytest **684 passed** (2분 51초)
- 정적 자산 린트 77개 — anchor 갱신 (showDashboard / login-form inline → auth-bootstrap.js script tag)

---

## ⏸ 다음 세션이 이어받을 작업 (선택)

### A. 머지된 브랜치 정리

배포 검증 완료 → 안전하게 삭제 가능:
```bash
# 로컬
git branch -d fix/pnl-display-and-loss-alert-clarity

# 원격: GitHub 웹 PR #23 페이지 하단 「Delete branch」 버튼
```

### B. mainnet 전환 (사용자 결정)

testnet 충분히 검증됐으면 진행:
1. Binance mainnet API 발급 + IP whitelist `159.65.137.250`
2. (옵션) 도메인 + Let's Encrypt HTTPS
3. ENCRYPTION_KEY 회전 (`scripts/rotate_encryption_key.py`)
4. 「💼 계정」 → 「🔑 키 변경」 → 환경 "mainnet" 선택

---

## 📦 5-15 검증된 배포 절차 (재사용용)

**현재 운영 환경**:
- VPS IP: `159.65.137.250` (root@, repo at `/root/binance-auto-trader/`)
- 운영 URL: `http://159.65.137.250/` (nginx port 80)

**핵심 주의사항** (5-15 hard-learned):
- ⚠️ **Windows 에서 만든 tar 의 .sh 파일은 CRLF 줄바꿈** → bash 가 거부. `find ... -exec sed -i 's/\r$//' {} \;` 필수
- ⚠️ docker `--no-cache` 안 쓰면 `COPY . /app` 캐시 layer 재사용 → 옛 코드 그대로
- ⚠️ smoke test 전 `sleep 10` — api startup time

**배포 명령** (PowerShell + SSH):

```powershell
# 1) 로컬에서 archive 만들기 (Git Bash 권장 — /tmp 경로 동작)
cd "C:\Users\user\바이낸스\binance-auto-trader"
git checkout main
git pull
git archive --format=tar.gz HEAD -o /tmp/repo.tar.gz
# 또는 PowerShell 의 경우: archive 위치는 $env:TEMP\repo.tar.gz

# 2) SCP — PowerShell 에서
scp -i $env:USERPROFILE\.ssh\id_ed25519 $env:TEMP\repo.tar.gz trader@159.65.137.250:/tmp/

# 3) SSH 접속
ssh -i $env:USERPROFILE\.ssh\id_ed25519 trader@159.65.137.250
```

VPS 안에서:

```bash
# 4) repo 추출 (.env 백업/복구 포함)
cp ~/binance-auto-trader/backend/.env /tmp/env-backup
tar -xzf /tmp/repo.tar.gz -C ~/binance-auto-trader --overwrite
cp /tmp/env-backup ~/binance-auto-trader/backend/.env

# 5) 신규 32 모듈 확인 (8 줄, 32 카운트)
ls ~/binance-auto-trader/backend/app/static/js/ | grep -E "strategy-detail|chart-detail|accounts-modal|add-position-modal|strategy-actions|admin-shortcuts|page-router|auth-bootstrap"
ls ~/binance-auto-trader/backend/app/static/js/ | wc -l   # 32

# 6) api 컨테이너 rebuild — 캐시 무시 (없으면 옛 layer 재사용)
cd ~/binance-auto-trader/backend
docker compose -f docker-compose.yml -f ../docker-compose.production.yml build --no-cache api
docker compose -f docker-compose.yml -f ../docker-compose.production.yml up -d --force-recreate api

# 7) 10초 대기 후 smoke test (api startup time 고려)
sleep 10
bash ~/binance-auto-trader/deploy/smoke-test.sh

# 8) 브라우저로 http://159.65.137.250/ 접속 → 차트/모달/액션 모두 정상 동작 확인
```

⚠️ 주의: scheduler / user-stream 컨테이너는 rebuild 안 함 (백엔드 코드 변경 없이 UI 만 변경됨, 워커 재시작 시 reconcile 부담)

### B. 운영 상태 점검 (배포 직후)

```bash
# kill-switch 발동 여부
docker compose exec api python -c "
from app.core.database import SessionLocal
from app.services.account_kill_switch_service import AccountKillSwitchService
db = SessionLocal()
ks = AccountKillSwitchService(db)
print('KS active:', ks.is_active(1))
db.close()
"

# 최근 RiskEvent (CRITICAL/WARN)
docker compose exec api python -c "
from app.core.database import SessionLocal
from app.models.risk_event import RiskEvent
from sqlalchemy import select
db = SessionLocal()
events = db.execute(
    select(RiskEvent).where(RiskEvent.severity.in_(['CRITICAL', 'WARN']))
    .order_by(RiskEvent.id.desc()).limit(20)
).scalars().all()
for e in events:
    print(f'#{e.id} {e.severity:8} {e.event_type:30} {e.title[:60]}')
db.close()
"

# active strategy + position 확인
docker compose exec api python -c "
from app.core.database import SessionLocal
from app.models.strategy_instance import StrategyInstance
from sqlalchemy import select
db = SessionLocal()
strats = db.execute(
    select(StrategyInstance).where(~StrategyInstance.is_archived)
    .where(StrategyInstance.status.notin_(['STOPPED', 'COMPLETED', 'REENTRY_READY']))
).scalars().all()
print(f'Active: {len(strats)}')
for s in strats:
    print(f'  #{s.id} {s.symbol} {s.side} {s.status} qty={s.current_position_qty}')
db.close()
"
```

### C. 머지된 브랜치 정리 (배포 후)

배포 + smoke test 통과 확인 후:

```bash
# 로컬
git branch -d fix/pnl-display-and-loss-alert-clarity

# 원격 — GitHub 웹 UI 의 PR #23 페이지 하단 「Delete branch」 버튼
```

---

## 🆘 트러블슈팅

| 증상 | 원인 / 조치 |
|---|---|
| `Test-NetConnection :22 → False` | 현재 네트워크 outbound 22 차단 — 핫스팟/다른 망 |
| `tar: /tmp/repo.tar.gz: No such file` | scp 단계 빠뜨림 — 로컬에서 SCP 먼저 |
| docker build CACHED 만 나옴 | `--no-cache` 플래그 추가 |
| smoke test `/health 응답 없음` | api startup 5~10초 기다리고 재실행 (`sleep 10`) |
| dashboard 가 옛 UI 로 보임 | 브라우저 강력 새로고침 (Ctrl+Shift+R) — JS 모듈 캐시 무시 |

---

## 📂 핵심 파일 위치 (5-15 갱신)

### 신규 추가 (PR #23)

- `backend/app/static/js/` — 32 JS 모듈 (이번 PR 에서 8개 추가)
- `backend/tests/integration/test_orphan_open_orders.py` — Zombie Guardian 3차
- `backend/tests/integration/test_archive_active_filter_and_restore.py` — C-full
- `backend/tests/integration/test_create_strategy_duplicate_prevention.py` — STOPPING stuck 안내
- `backend/tests/integration/test_add_margin_and_loss_alert.py` — 증거금 추가 + 알림
- `backend/tests/integration/test_ensure_isolated_margin.py` — ISOLATED 자동 진입
- `backend/alembic/versions/0014~0016` — soft-delete + ranking + hot-path indexes

### Repo 운영 docs (5-15 시점 진실 기준)

- `DEVELOPMENT_SPEC.md` — 시스템 + VPS IP 명시
- `TP_TRAILING_LOGIC_FINAL.md` — 익절/트레일 정책 최종 확정
- `CONSISTENCY_CHECKLIST.md` — 코드 vs 기획서 정합성
- `SYSTEM-SPEC.md` — 시스템 정의 (5-06 기준)
- `MAINNET-CHECKLIST.md` — mainnet 전환 체크리스트
- `VPS-DEPLOY-CHECKLIST.md` — VPS 배포 단계별

---

## 📊 현재 코드 상태 (참고)

```
main HEAD: e824b0f
pytest: 684 passed
index.html: 1,178 lines (5,875 → 1,178, -79.9%)
JS modules: 32
alembic: 0016_hot_path_indexes
```

---

## 🔮 mainnet 전환 잔여 (5-07 이후 미진행)

다음 세션이 사용자와 함께 진행:
1. testnet 24시간+ 검증 (현재 testnet 운영 중)
2. Binance mainnet API 발급 + IP whitelist `159.65.137.250` (옛 IP `152.42.232.195` 아님 주의)
3. (옵션) 도메인 + Let's Encrypt HTTPS
4. ENCRYPTION_KEY 회전 (`scripts/rotate_encryption_key.py`)
5. 「💼 계정」 → 「🔑 키 변경」 → 환경 "mainnet" → mainnet 운영

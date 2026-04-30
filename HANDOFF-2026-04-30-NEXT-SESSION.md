# HANDOFF — 2026-04-30 (집 저녁 마무리, 다음 세션용)

집 PC 에서 사무실 work 받아와 정리 + 좀비 STOPPING 만성 이슈 fix 진행한 세션.

---

## 📌 한 줄 요약

사무실 fix (`0d30201`/`0da0f55`) 무사히 origin 에 있음 확인 + unit test 5개 추가 + `.dockerignore` 추가 + **STOPPING 좀비 자동 정리 fix** + `.gitignore` 인코딩 정리. 활성 전략 0개. SECRET_KEY 만 .env 갱신 (Neon/Telegram 보류).

---

## 🔄 이전 핸드오프 (`HANDOFF-2026-04-30-OFFICE-EVENING.md`) 검증 결과

| 클레임 | 실제 |
|---|---|
| `0d30201` push 됨 | ✅ origin 에 존재 |
| `0da0f55` push 됨 | ✅ origin 에 존재 |
| `e1bdfd7` (.gitignore session-local) push 됨 | ✅ origin 에 존재 |
| `a97504f` 옵션 C [버그 있음, 0d30201 에서 복구] | ✅ 정확 |

**전부 사실이었음.** 다만 집 PC 의 stale `origin/main` 정보 (`a97504f`) 때문에 sandbox 에서 잠시 false claim 으로 오인했었음 (push 시도 후 `non-fast-forward` 거부로 정정됨).

→ **다음 세션 주의: handoff 의 commit hash 검증은 `git fetch origin` 후 `git log origin/main --oneline` 으로 확인할 것.**

---

## 🛠️ 오늘 origin 에 들어간 commit (5개)

```
03f9d90 chore(.gitignore): 인코딩 깨진 라인 정리 + pytest-cache-files-* 패턴 추가
2677aff fix(stream/reconcile): STOPPING 좀비 자동 정리 — 매번 SQL 보정 불필요
d62a6d5 chore(docker): add .dockerignore — db_backups symlink build error 회피
6f3de28 test: stream_service partial close 회귀 방지 unit test 5개 추가
e1bdfd7 chore: ignore session-local artifacts (← 사무실에서 push 됐던 것)
```

`origin/main = 03f9d90` (집 PC 시점).

---

## 🐛 좀비 STOPPING 자동 정리 fix (코어 fix)

### 문제

「수동 정지/청산」 클릭 시 status=STOPPING → 거래소 청산 → EXIT FILLED 받음 → status 가 자동으로 STOPPED 안 가고 STOPPING 으로 stuck. 매번 SQL 보정 필요했음 (이전 핸드오프 7개, 오늘 또 3개).

### 원인

1. `stream_service.handle_order_trade_update` 의 EXIT FILLED 분기:
   ```python
   if strategy.status != "COMPLETED":
       strategy.status = "REENTRY_READY"
   ```
   → STOPPING 상태에서도 REENTRY_READY 로 가야 정상이지만, ACCOUNT_UPDATE/race 로 실제로는 STOPPING 으로 stuck 되는 케이스 발생.

2. `reconcile_worker` 의 status filter 에 STOPPING 미포함:
   ```python
   .where(StrategyInstance.status.in_(["STAGE1_OPEN", ..., "TP1_DONE_PARTIAL", "TP2_DONE_PARTIAL"]))
   ```
   → STOPPING 좀비를 자동 회복할 안전망 없음.

### Fix (commit `2677aff`)

#### 1) `stream_service.py` — STOPPING 분기 추가
```python
if is_full_close:
    strategy.current_position_qty = Decimal("0")
    strategy.unrealized_pnl = Decimal("0")
    if strategy.status == "COMPLETED":
        pass  # _execute_take_profit 가 마킹한 것 보존
    elif strategy.status == "STOPPING":
        # 사용자 「수동 정지」 의도 보존 → STOPPED (재진입 안 함)
        strategy.status = "STOPPED"
        strategy.stopped_at = datetime.now(timezone.utc)
    else:
        strategy.status = "REENTRY_READY"
        strategy.reentry_ready = True
```

#### 2) `reconcile_worker.py` — STOPPING 좀비 안전망
- status filter 에 STOPPING 추가
- `matched=None` (거래소 포지션 없음) + status=STOPPING → STOPPED 자동 승격 + RiskEvent (`RECONCILE_STOPPING_ZOMBIE_CLEANUP`)

### 회귀 방지 unit test (6/6 통과 — Windows Python 3.14 + Linux Python 3.10 양쪽)

`tests/unit/test_stream_service_partial_close.py`:
1. `test_short_partial_close_preserves_remaining_qty_and_status` — #58 NAORISUSDT TP1 시나리오
2. `test_short_full_close_sets_reentry_ready_and_zero_qty`
3. `test_long_partial_close_preserves_positive_qty`
4. `test_completed_status_is_preserved_on_full_close`
5. `test_over_execution_clamps_to_zero` — ACCOUNT_UPDATE race 안전망
6. `test_stopping_status_transitions_to_stopped_on_full_close` — ⭐ NEW (좀비 fix)

### 검증 안내

다음 청산 (testnet 또는 mainnet) 시 자동 STOPPED 까지 가는지 확인. 만약 또 STOPPING 좀비 발생하면:
1. `docker compose logs user-stream --tail=200` — EXIT FILLED 처리 로그 확인
2. `docker compose logs scheduler` — reconcile_worker 30초 사이클 동작 확인
3. RiskEvent 테이블에 `RECONCILE_STOPPING_ZOMBIE_CLEANUP` 들어왔나 query

---

## 💰 시스템 현재 상태 (집 PC, 2026-04-30 12:30 UTC 기준)

### 활성 전략

**0개** ✅ — 모두 정리됨.

### 정리 결과

| ID | Symbol | Status | Realized | 비고 |
|---|---|---|---|---|
| 78 | BIOUSDT | STOPPED | **+17.30** | 핸드오프 후 자동 TP1 발동 |
| 77 | INTCUSDT | STOPPED | **+2.56** | 사용자 수동 청산 |
| 68 | ALGOUSDT | STOPPED | **−4.72** | 사용자 수동 청산 (약관 동의 후) |

### 누적 통계 (좀비 통계 보정 후)

| 항목 | 값 |
|---|---|
| Finished | 15 |
| Profit count (realized > 0) | **10** ← 이전 핸드오프의 "익절 10건" 과 정확히 일치 |
| Loss count (realized < 0) | 2 (#68 −4.72, #59 −22.78 — manual stop) |
| Zero | 3 |
| **Total realized** | **+196.58 USDT** |

진행 흐름:
1. 이전 핸드오프 통계 +117.75 — 그 시점은 #54/#55/#63 의 realized_pnl 이 누락 (코드 버그) 상태에서 카운팅됨. 익절 알림은 정상 발송됐지만 DB 누적 안 됨.
2. 오늘 청산 추가 +15.14 (#78 +17.30 / #77 +2.56 / #68 −4.72)
3. **좀비 통계 보정** +63.69:
   - #63 SKYAIUSDT (SHORT, raw): **+31.08** (entry 0.25155 → exit 0.21260, qty 798)
   - #54 AIOTUSDT (SHORT, raw): **+20.81** (entry 0.12010 → exit 0.10760, qty 1665)
   - #55 SKYAIUSDT (SHORT, raw): **+11.80** (entry 0.24992 → exit 0.23517, qty 800)

→ 117.75 + 15.14 + 63.69 = **+196.58 USDT** ✅

> 보정값은 fee/funding 미반영 raw PnL. Binance Trade History 와 1~2 USDT 차이 가능.

### 통계 누락 원인

#54/#55/#63 모두 **2026-04-29 기간** 청산. 이 시점의 코드는 `7bc188a` ("realized_pnl accumulator") fix 가 들어가기 전 (4월 30일 08:16 UTC commit). 즉 EXIT FILLED 처리는 됐지만 strategy.realized_pnl 갱신 로직 자체가 없어서 DB 0 으로 남음. 거래 자체는 정상.

### 추가 발견 — `max_profit_pct == max_loss_pct`

#54 (10.71/10.71), #55 (12.26/12.26) — 두 컬럼이 정확히 같음. 보통 다른 값일 텐데. 코드의 다른 버그 의심 (peak 추적 로직). **부수적 — 다음 세션 안건**.

---

## 🔐 보안 로테이션 — 진행 상황

### 완료
- ✅ `SECRET_KEY` `.env` 갱신 (집 PC 만, sandbox 가 secrets.token_urlsafe(48) 로 생성)
  ```
  SECRET_KEY=do9G-jZvkhw-Ug6qGyqR3ywfOmVLoP6qEZAWaPaD5LYIjHTk3_0nvs-yMLBfD_hr
  ```
  > backend 재시작 시점에 적용 → 모든 사용자 JWT 무효화 → 재로그인 필요

### 사용자 외부 콘솔 작업 보류 중
- ⏳ **Neon DB password** — https://console.neon.tech → Roles → `neondb_owner` → Reset password
- ⏳ **Telegram BOT_TOKEN** — @BotFather → /mybots → API Token → Revoke
- ⛔ **ENCRYPTION_KEY** — 보류 권장 (DB 의 `exchange_account.api_key/secret_enc` 마이그레이션 필요)

### 사무실 PC 동기화 시 주의
1. `git pull origin main` (오늘 5개 commit 받음)
2. `.env` 의 SECRET_KEY 같은 값으로 갱신:
   ```
   SECRET_KEY=do9G-jZvkhw-Ug6qGyqR3ywfOmVLoP6qEZAWaPaD5LYIjHTk3_0nvs-yMLBfD_hr
   ```
3. Neon password 또는 Telegram token 재발급했으면 사무실 .env 에도 동일 값 적용
4. `docker compose up -d --build` (이미지 rebuild — `.dockerignore` 가 db_backups symlink 회피)

---

## 🧪 검증 — 운영에서 확인할 것 (다음 세션 추천)

### 1. 옵션 C 종단간 testnet 검증 (#75 시나리오)
이전 핸드오프 우선순위 1번. 직접 입력 6단계 (200/300/500/700/900/1200, 6단계 trigger=20).

**검증 체크리스트:**
- 미리보기 6단계 trigger 컬럼 = "+20% 도달 시" ☐
- 1단계 진입 텔레그램 알림 정확히 1회 (dedup gate 검증) ☐
- 가격 변동에 따라 2~6단계 자동 진입 ☐
- TP1 부분 청산 시 잔량 75% 보존 + STAGE_X_OPEN 유지 (origin 0da0f55 검증) ☐
- 검증 종료 「수동 청산」 시 자동 STOPPED 전환 (오늘 fix 2677aff 검증) ⭐ ☐

### 2. Neon / Telegram 자격증명 재발급 + .env 갱신

위 보안 섹션 참고.

### 3. (완료) 좀비 통계 보정 — #63, #54, #55

이번 세션에서 raw 계산값으로 보정 완료 (위 누적 통계 섹션 참고). **이전 핸드오프 4번 항목 closed.**

후속:
- (선택) Binance Trade History 로 fee/funding 포함 정확값 재보정
- (다음 세션 안건) `max_profit_pct == max_loss_pct` 의심 — peak 추적 로직 버그?

### 4. (장기) ENCRYPTION_KEY 마이그레이션

마이그레이션 스크립트 작성 필요. 옛 키로 `exchange_accounts.api_key_enc / secret_enc` 복호화 → 새 키로 재암호화 → 새 키로 .env 교체. 별도 안건.

---

## 📂 working tree 임시 파일 (정리 결정 보류)

```
HANDOFF-2026-04-30-OFFICE-EVENING.md   # 사무실 → 집 핸드오프 (.gitignore 적용됨, untracked 유지)
HANDOFF-2026-04-30-HOME-EVENING.md     # 이전 세션 작성한 것 (commit 여부 결정)
HANDOFF-2026-04-30-NEXT-SESSION.md     # 이 파일 (commit 가치 있음 — 추후 add 결정)
이어서-진행하기.md                      # (.gitignore 적용됨)
option_c_diff.txt                      # (.gitignore 적용됨)
sync-from-office.ps1                   # (.gitignore 적용됨)
```

---

## 🔖 인프라 메모

- **Docker 환경**: 모든 컨테이너 정상 (api / scheduler / user-stream / db / redis / prometheus / grafana / db-backup)
- **Neon Cloud DB**: `ep-sparkling-forest-ao116t81.c-2.ap-southeast-1.aws.neon.tech/neondb`
  - sandbox 에서는 외부 인터넷 막혀 있어 직접 query 불가. PowerShell + psycopg2 로 처리.
  - PowerShell 에서 `.env` 읽을 때 **`encoding='utf-8'` 명시 필수** (cp949 default 가 한국어 주석 못 읽음)
- **로컬 docker postgres**: 옛날 BTCUSDT 테스트 데이터 (#10–21) 만 있음 — 무시
- **Git**: HEAD = origin/main = `03f9d90`
- **`.gitignore`**: git 이 binary 로 인식 (cosmetic 이슈, 내용 정상 적용됨). 다음 commit 부턴 정상 diff 가능 예상

---

## ⚙️ Sandbox 에서 PowerShell 로 자주 쓴 명령 (재사용용)

### Neon DB query 헬퍼

```powershell
cd C:\Users\user\바이낸스\binance-auto-trader\backend

python -c @"
import psycopg2
from psycopg2.extras import RealDictCursor
db_url = [l.split('=',1)[1].strip() for l in open('.env', encoding='utf-8').read().splitlines() if l.startswith('DATABASE_URL=')][0].replace('postgresql+psycopg2://','postgresql://')
with psycopg2.connect(db_url) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
    cur.execute(\"SELECT id, symbol, status, current_position_qty, realized_pnl FROM strategy_instances WHERE status NOT IN ('STOPPED','COMPLETED','REENTRY_READY','CLOSED') ORDER BY id DESC\")
    for r in cur.fetchall(): print(r)
"@
```

### 좀비 STOPPING 정리 (fix 후엔 불필요할 것)

```powershell
python -c @"
import psycopg2
db_url = [l.split('=',1)[1].strip() for l in open('.env', encoding='utf-8').read().splitlines() if l.startswith('DATABASE_URL=')][0].replace('postgresql+psycopg2://','postgresql://')
with psycopg2.connect(db_url) as conn, conn.cursor() as cur:
    cur.execute(\"UPDATE strategy_instances SET status='STOPPED', stopped_at=NOW() WHERE status='STOPPING' AND current_position_qty=0\")
    print(f'updated rows: {cur.rowcount}')
    conn.commit()
"@
```

### Backend 재시작

```powershell
cd C:\Users\user\바이낸스\binance-auto-trader\backend
docker compose up -d --build              # 이미지 rebuild
docker compose up -d --force-recreate api scheduler user-stream  # .env 만 다시 읽음 (코드 변경 없을 때)
docker compose logs api --tail=20
```

---

## 🎯 다음 세션 첫 작업 추천

1. **사무실 PC 인 경우** → `git pull origin main` + `.env` SECRET_KEY 동기화 + `docker compose up -d --build`
2. **집 PC 또는 mainnet 인 경우** → 옵션 C testnet 검증 (#75 시나리오)
3. **Neon/Telegram 재발급** 시간 잡기

이번 세션 가장 큰 수확: **STOPPING 좀비 만성 이슈가 fix** 됐고, 다음 청산부터 SQL 보정 없이 자동 STOPPED 됨 (운영 부담 ↓).

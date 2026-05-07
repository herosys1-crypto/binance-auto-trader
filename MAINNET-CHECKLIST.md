# Mainnet 전환 체크리스트

testnet → mainnet 전환 전에 반드시 완료해야 할 작업 정리.

> ⚠️ = MUST (안 하면 자금 손실 가능)
> 🟡 = 권장
> ⚪ = 선택

---

## 1. 보안 (자격증명) ⚠️

### 1-1. 채팅에 노출된 자격증명 전면 갱신 ⚠️
이번 세션에 `.env` 가 한 번 노출됐음. mainnet 자금이 걸리기 전에 반드시 모두 새 값으로 갱신.

| 자격증명 | 작업 | 상태 |
|---|---|---|
| `SECRET_KEY` | 갱신 완료 (집 PC) | ✅ |
| `DATABASE_URL` (Neon password) | https://console.neon.tech → Roles → Reset password | ☐ |
| `TELEGRAM_BOT_TOKEN` | @BotFather → /mybots → Revoke current token | ☐ |
| `ENCRYPTION_KEY` | DB 마이그레이션 후 갱신 (별도 안건) | ☐ |
| 사무실 PC `.env` 동일 갱신 | 다음 출근 시 | ☐ |

### 1-2. Binance Mainnet API 키 발급 ⚠️
- [ ] Binance 계정의 API Management 에서 새 API 키 생성
- [ ] **권한 최소화**:
  - ✅ Enable Futures
  - ❌ Enable Spot Trading (선물 only 면 끄기)
  - ❌ Enable Withdrawals (절대 끄기 — 출금 권한 주면 안 됨)
- [ ] **IP whitelist 설정** (운영 서버 IP 만 허용)
- [ ] **2FA 필수** (Binance 계정 자체)
- [ ] 발급받은 API key/secret 을 시스템 UI 에서 「거래소 계정 등록」 으로 추가 (is_testnet=false)

### 1-3. ENCRYPTION_KEY 마이그레이션 ⚠️
DB 의 `exchange_account.{api_key_enc, api_secret_enc, passphrase_enc}` 가 ENCRYPTION_KEY 로 암호화됨. 이 키가 노출됐으니 마이그레이션 필요.

#### 옵션 A — 자동 회전 (권장, 2026-05-07 도구 추가)
스크립트: [backend/scripts/rotate_encryption_key.py](backend/scripts/rotate_encryption_key.py)
단위 테스트: [backend/tests/integration/test_rotate_encryption_key.py](backend/tests/integration/test_rotate_encryption_key.py) (7 cases passed)

```powershell
cd backend

# 1) 새 Fernet 키 생성
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2) Dry-run (DB 변경 없이 검증)
$env:NEW_ENCRYPTION_KEY="<위에서 생성한 키>"
python scripts/rotate_encryption_key.py --dry-run

# 3) 실 실행 (백업 JSON 자동 생성)
python scripts/rotate_encryption_key.py

# 4) .env 의 ENCRYPTION_KEY 를 새 값으로 교체

# 5) 백엔드 재시작
docker-compose restart api  # 또는 uvicorn 재실행

# 6) 검증 — 새 키로 거래소 호출
python scripts/check_binance_key.py

# 7) 백업 JSON 안전한 곳으로 이동 + 검증 후 폐기
```

**Roll-back**: `python scripts/rotate_encryption_key.py --restore-from <backup.json>` 으로 옛 cipher 복원 가능.

#### 옵션 B — 더 안전 (자격증명 새로 등록)
거래소 계정 row 전부 삭제 → 새 mainnet API 키로 다시 등록 (옛 testnet 자격증명도 같이 정리됨).

### 1-4. 인프라 보안 🟡
- [ ] Neon DB IP whitelist (운영 서버만 접근)
- [ ] Redis 비밀번호 설정 (현재 password 없음 — `redis://redis:6379/0`)
- [ ] HTTPS 적용 (현재 `http://localhost:8000` 평문)
- [ ] 관리자 계정 비밀번호 강력하게 (8자 이상 + 특수문자)
- [ ] Grafana admin 비밀번호 변경 (`Admin1234!` 디폴트)

---

## 2. 운영 검증 (코드 정확성) ⚠️

### 2-1. testnet 종단간 검증 ⚠️
**최소한 한 번은 testnet 에서 모든 시나리오 통과 후 mainnet 전환.**

- [ ] **옵션 C #75 시나리오** — 직접 입력 6단계 (200/300/500/700/900/1200, 6단계 trigger=20)
  - 미리보기 6단계 = "+20% 도달 시" 표시
  - 1단계 진입 텔레그램 알림 정확히 1회 (dedup gate)
  - 2~6단계 자동 트리거 (가격 변동 따라)
  - TP1 부분 청산 시 잔량 보존 + STAGE_X_OPEN 유지 (origin `0da0f55` 검증)
  - 검증 종료 「수동 청산」 시 자동 STOPPED 전환 (오늘 fix `2677aff` 검증)
- [ ] **트레일링 익절** — TP1 발동 후 피크 대비 −5% 회귀 시 전량 청산
- [ ] **−50% 손절** — 모든 단계 진입 후 손실 −50% 도달 시
- [ ] **REENTRY_READY 자동 재진입** — 청산 후 재진입 시나리오
- [ ] **크라이시스 모드** (max_loss < −30% 도달 후 양수 전환 시 발동)
- [ ] **listenKey 갱신** — 24시간 이상 운영 후에도 user-stream 살아있나
- [ ] **API key 만료/회전 시나리오** — 만료된 키로 거래 시도 시 에러 핸들링

#### 2-1-A. 5-04 신규 검증 (PR #1, 26 commits)
- [ ] 「▶ 다음 단계」 manual MARKET 진입 — 단계 trigger_price 무시 + 즉시 시장가
- [ ] 「▶」 빠른 더블 클릭 → atomic UPDATE race guard 차단 (5-04 fix `f9bbe16`)
- [ ] 「💉 포지션 추가」 ad-hoc — stage_no=NULL 자유 금액 진입
- [ ] 「↻ 설정만 수정」 — 포지션/단계 보존 + TP/SL/trigger_percents/capitals 갱신
- [ ] 「💰 증거금 추가」 — ISOLATED margin 만 추가 (포지션 변경 X)
- [ ] -50% ROI 알림 1회 (one-time crossing — `_maybe_send_loss_threshold_alert`)
- [ ] 일일 손실 한도 — 계정별 override (`exchange_accounts.daily_loss_limit_usdt`) 가
  global setting 보다 우선 발동
- [ ] Kill Switch 사각지대 — stage 2+ 진입 시도 + 새 strategy create 양쪽 차단
- [ ] 옵션 C 5+단계 status 매핑 — STAGE5~10_OPEN, TP3/4/5_DONE_PARTIAL 모두 평가됨

#### 2-1-B. 5-06 신규 검증 (PR #5~#12, 13 commits)
- [ ] **TP10 익절 10단계** — TP1=10/.../TP10=55% (5% 간격) 신규 strategy 생성 →
  TP3/5/8/10 까지 progression 가능 (잔량 25% 청산, TP10=100%)
- [ ] **트레일링 peak DB fallback** — Redis `strategy:{id}:peak_pnl_pct` 강제 삭제
  후도 trailing 발동 (DB max_profit_pct fallback, #103 회귀 영구 방어)
- [ ] **승률 정확도** — 운영 통계 패널 「승률 (전략)」 = realized_pnl 부호 기준
  (수익 strategy / decided × 100). 알림 기반 (이전) 과 다름
- [ ] **운영 통계 셀 클릭 → modal** — 6 셀 모두 「🔍」 + 클릭 시 strategy 별 detail
- [ ] **자동번역 차단** — Chrome 한국어 페이지에서 「확정 손익」 그대로 표시
  (「안녕 손익」 X)
- [ ] **「📈 시장 순위」 페이지** — `#ranking` URL 직접 접근 + 13 period × 2 direction
  + 「↑ 새 전략」 → 모달 자동 + 심볼 자동 채움
- [ ] **새 전략 모달 안 「📉/📈 top」** — modal 통합 (workflow 끊김 X)
- [ ] **soft delete 「🗑」 → archive** — DB row + cascade orders 보존, realized
  통계 합계 변화 X (#96 cascade 영구 방어)
- [ ] **「📦 보관 보기」 토글 + 「↻ 복원」** — archived strategy 목록 + 복원 가능
- [ ] **Background workers 가 archived 제외** — reconcile / tp_sl / stage_trigger /
  auto_reentry / daily_loss / zombie 모두 active filter 적용

### 2-2. 단위 + 통합 테스트 모두 통과
```powershell
cd C:\Users\user\바이낸스\binance-auto-trader\backend
python -m pytest -q
```
현재 (5-06 cbd1968 / e8afec7 기준): **383 passed** in ~135s.

- [ ] 모든 unit 테스트 통과 (115+)
- [ ] 모든 integration 테스트 통과 (260+)
- [ ] alembic head 적용 (`docker compose exec api alembic current` → `0012_template_tp6_to_tp10`)

### 2-3. mainnet 전환 직전 testnet 회귀 테스트 ⚠️
mainnet 전환 직전 코드 변경이 있다면 testnet 에서 한 번 더 검증.

---

## 3. 리스크 관리 (자금 보호) ⚠️

### 3-1. Kill Switch 검증 ⚠️
- [ ] `account_kill_switch_service` 의 동작 확인
- [ ] UI 또는 API 로 즉시 모든 거래 중단 가능
- [ ] kill switch 발동 시 텔레그램 알림 도착
- [ ] 발동 후 새 진입 차단 + 기존 포지션 대응 절차 명확

### 3-2. 일일 손실 한도 ⚠️
- [ ] `.env` 의 `DAILY_LOSS_LIMIT_USDT` 또는 계정별 `exchange_accounts.daily_loss_limit_usdt`
  설정 (5-04 신규)
- [ ] 권장값: mainnet 첫 거래 자본의 10~20% (예: $1,000 자본 → 한도 $100~200)
- [ ] 계정별 override 가 global 보다 우선 발동 검증
- [ ] `daily_loss_aggregator` worker 1분 주기 — active strategy 의 unrealized + 일일
  누적 realized 합 → 한도 초과 시 자동 STOPPING + Kill Switch 발동
- [ ] 한도 초과 시 텔레그램 알림 도착 (발동 + 차단 알림)

### 3-3. 자본 상한 🟡
**구현 완료** (2026-05-07, 13 통합 테스트). 운영자가 `.env` 에서 활성화:
```
MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT=3       # mainnet 초기 권장 3~5 (default 10)
MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE=5.0       # 단일 전략 자본 ≤ 잔액 5% (default 비활성)
ALLOWED_SYMBOLS_CSV=BTCUSDT,ETHUSDT           # high-liquidity 만 (default 모든 심볼)
```
가드 동작:
- [ ] 단일 전략 자본 한도 초과 시 거부 (`available × max_pct/100` 와 비교)
- [ ] 동시 활성 전략 수 한도 도달 시 거부 (status not in TERMINAL 카운트)
- [ ] 화이트리스트에 없는 심볼 거부 (case-insensitive)
- [ ] CSV 빈/None 이면 모든 심볼 허용 (testnet/dev default)

검증 ([test_strategy_capital_limits.py](backend/tests/integration/test_strategy_capital_limits.py)):
13 케이스 — symbol whitelist (4), max_concurrent (3), capital_pct (4), CSV 파싱 (2).

### 3-4. 레버리지 정책
**구현 완료** (2026-05-07, 5 통합 테스트). `.env` 에서:
```
MAX_LEVERAGE=5    # mainnet 권장. 비워두면 비활성 (Binance API 한도)
```
- [x] template.leverage 또는 leverage_override 가 한도 초과 시 거부
- [x] 0/None/음수는 비활성 (deploy-safe)

검증: [test_strategy_leverage_cap.py](backend/tests/integration/test_strategy_leverage_cap.py)

### 3-5. 청산 가격 안전 거리 🟡
**구현 완료** (2026-05-07, 4 통합 테스트). `.env` 에서:
```
MIN_LIQUIDATION_DISTANCE_PCT=5    # mainnet 권장. leverage=10 일 때 거리 ≈ 9.95%
```
추정 공식: distance% ≈ (1 - mmr) / leverage × 100, mmr=0.5% (Isolated 보수적).
- [x] 진입 직후 추정 청산가까지의 거리가 한도 미만이면 진입 거부
- [x] LONG/SHORT 동일 공식 적용

검증: [test_strategy_liquidation_distance.py](backend/tests/integration/test_strategy_liquidation_distance.py)

---

## 4. 모니터링 + 알림 ⚠️

### 4-1. 텔레그램 알림 ⚠️
- [ ] BOT_TOKEN 새로 발급 후 적용
- [ ] 다음 알림 모두 도달 확인:
  - 단계 진입
  - TP1/2/3 부분/전체 청산
  - 손절 (−50%)
  - 크라이시스 모드 진입
  - kill switch 발동
  - listenKey 만료
  - 거래소 에러 (API rate limit, balance 부족 등)
- [ ] dedup gate (60초 윈도우) 정상 동작 — 같은 알림 1회만

### 4-2. Prometheus / Grafana 🟡
- [ ] `http://localhost:9090` 접속, 메트릭 정상 수집
- [ ] `http://localhost:3000` Grafana 대시보드 정상
- [ ] 다음 메트릭 모니터링:
  - `user_stream_events_total` (event 수신율)
  - `position_reconcile_total` (좀비 정리 카운트)
  - `position_qty_mismatch_total` (DB/거래소 불일치)
  - `strategy_stop_loss_total`
- [ ] 알림 룰 (`prometheus/alerts-binance-auto-trader.yml`) 검증

### 4-3. Sentry (에러 트래킹) 🟡
- [ ] `.env` 의 `SENTRY_DSN` 비어있음 → mainnet 가기 전 설정 권장
- [ ] sentry.io 에 프로젝트 만들고 DSN 발급
- [ ] 에러 발생 시 알림 도착 확인

### 4-4. 로그 보존 🟡
- [ ] `docker compose logs` 만으로 충분? 또는 로그 수집 시스템 (예: Loki)
- [ ] 로그 회전 (rotation) 설정

---

## 5. 데이터 안전 ⚠️

### 5-1. DB 백업 ⚠️
- [ ] `db-backup` 컨테이너 작동 확인 (매일 03:00 UTC)
- [ ] `./db_backups/` 폴더에 .sql.gz 파일 정상 생성
- [ ] **복원 시뮬레이션**: 한 번 testnet DB 복원해보기
- [ ] 백업 보관 정책: 일 7개 / 주 4개 / 월 6개 — mainnet 은 더 길게?
- [ ] **오프사이트 백업** 🟡 — 현재 로컬 폴더만. AWS S3 / Backblaze 등 권장

### 5-2. DB 마이그레이션 ⚠️
- [ ] alembic upgrade head 한 번 실행 (mainnet 환경에서)
- [ ] 모든 alembic version 적용 확인 — 5-06 기준 head = `0012_template_tp6_to_tp10`
  - `0011_strategy_archived` (PR #7) — soft delete
  - `0012_template_tp6_to_tp10` (PR #10) — TP6~10 컬럼
- [ ] 마이그레이션 실패 시 롤백 절차 명확 (각 마이그레이션 파일에 `downgrade()` 정의됨)

### 5-3. 데이터 레코드 정확성 🟡
- [ ] `realized_pnl` 누적 정상 (오늘 fix 들어감)
- [ ] `max_loss/profit_pct` 정상 (오늘 fix 들어감)
- [ ] DB cleanup 한 번 실행 (이전 잘못된 row):
  ```sql
  UPDATE strategy_instances SET max_loss_pct = NULL WHERE max_loss_pct > 0;
  UPDATE strategy_instances SET max_profit_pct = NULL WHERE max_profit_pct < 0;
  ```

---

## 6. 운영 인프라 ⚠️

### 6-1. 24/7 운영 환경 ⚠️
**자기 PC 에서 docker 띄워놓고 운영하면 PC 재시작/잠자기/네트워크 끊김 시 거래 중단됨.**

**5-06 결정 — DigitalOcean Singapore VPS** (`VPS-DEPLOY-CHECKLIST.md` 참조):
- [ ] DigitalOcean Singapore (sgp1) droplet 생성 — Basic AMD 2 vCPU 8GB ($48/월)
- [ ] `deploy/vps-bootstrap.sh` 실행 (Phase 1 자동화 30분)
- [ ] `deploy/generate-secrets.sh` + `.env.production.template` (자격증명 발급)
- [ ] Neon Cloud DB 그대로 (마이그레이션 X, region 동일 Singapore)
- [ ] nginx + Let's Encrypt HTTPS (도메인 필요)
- [ ] **ngrok 폐지** (VPS 가 공인 IP + 24/7 가동)
- [ ] **모니터링 외부 가용성 체크** — UptimeRobot 무료 (`/health` endpoint, 5분 주기)
- [ ] 첫 60일 DigitalOcean $200 promo 적용 (검증 무료)

### 6-2. listenKey 자동 갱신 ⚠️
- [ ] `keepalive_worker` 정상 작동 확인 (30분 간격 ping)
- [ ] 24시간 이상 끊김 없이 user-stream 유지
- [ ] 거래소 disconnect 발생 시 자동 재연결

### 6-3. Reconcile 안전망 ⚠️
- [ ] `reconcile_worker` 정상 작동 (DB 와 거래소 상태 동기화)
- [ ] 좀비 STOPPING 자동 정리 (오늘 fix `2677aff` 운영 검증)
- [ ] 거래소 outage 시나리오 대응 (Binance API 다운 시)

### 6-4. 시스템 자원 🟡
- [ ] 메모리/CPU 사용량 검증 (특히 user-stream 의 websocket 처리)
- [ ] 디스크 공간 (DB 백업 누적)

---

## 7. 점진적 전환 (Soft Launch) 🟡

mainnet 전환을 한 번에 하지 말고 단계적으로:

### Phase 1 — 최소 자본 검증 (1주)
- [ ] 매우 작은 자본 (10~50 USDT) 으로 새 전략 1개
- [ ] 1단계만 사용 (멀티 단계 나중)
- [ ] BTC/ETH 같은 high-liquidity 심볼만
- [ ] 수동으로 close 한 번 해보고 알림 + DB 정상 확인

### Phase 2 — 단일 전략 정상 사이클 (1~2주)
- [ ] 정상 자본 (예: 100~500 USDT) 으로 멀티 단계 전략
- [ ] TP/SL 자동 발동 한 사이클 완성
- [ ] 통계 정확성 확인

### Phase 3 — 동시 다중 전략 (1주+)
- [ ] 동시 활성 전략 2~3개
- [ ] dedup / 좀비 fix / reconcile 모두 정상 동작 확인

### Phase 4 — 정상 운영
- [ ] 모든 자본 / 모든 심볼 운영 시작

---

## 8. 비상 대응 절차 🟡

### 8-1. 운영 매뉴얼 정비
- [ ] `RUNBOOK.md` 정확성 확인 (현재 매우 간단)
- [ ] 다음 시나리오 명확히:
  - kill switch 발동 시
  - DB 손상 시 (백업 복원 절차)
  - 거래소 API 키 노출 의심 시 (즉시 회전)
  - listenKey 영구 끊김 시
  - 우리 서버 다운 시 (Binance 에 포지션 살아있는데 우리는 모르는 케이스)

### 8-2. 텔레그램 비상 채널 🟡
- [ ] 평소 알림 채널 외 별도 비상 채널 (kill switch 발동, DB 다운 등 critical 만)

### 8-3. 회복 시뮬레이션 🟡
- [ ] DB 복원 시뮬레이션
- [ ] 시스템 다운 후 재시작 시 거래 정상 회복 확인 (reconcile_worker 가 동기화)

---

## 9. 법규 / 세무 ⚪

- [ ] 본인 거주 국가의 가상자산 거래 법규 확인
- [ ] 손익 기록 보존 (DB 의 realized_pnl + Binance Trade History)
- [ ] 세금 신고용 데이터 export 가능

---

## 10. 다음 세션에 제일 먼저 해야 할 것 (우선순위)

```
1. ⚠️ Neon DB password / Telegram BOT_TOKEN 재발급
2. ⚠️ ENCRYPTION_KEY 마이그레이션 (또는 거래소 계정 row 삭제 후 재등록)
3. ⚠️ testnet 옵션 C #75 종단간 검증 (오늘 fix 모두 한 번에)
4. ⚠️ Binance Mainnet API 키 발급 (권한 최소화 + IP whitelist)
5. 🟡 Kill switch / 일일 손실 한도 검증
6. 🟡 24/7 운영 환경 결정 (VPS or 데스크톱)
7. 🟡 Sentry DSN 설정
8. 🟡 백업 복원 시뮬레이션
9. 🟡 운영 매뉴얼 (RUNBOOK) 보강
10. 🟡 Phase 1 — 최소 자본 (10 USDT) 으로 mainnet 첫 거래
```

---

## 11. 점검 — 오늘까지 적용된 fix 요약

mainnet 가기 전 다음 fix 들이 origin 에 들어가 있는지 한 번 더 확인:

| Fix | Commit | 설명 |
|---|---|---|
| 부분 청산 잔량 보존 | `0da0f55` | TP1 25% 후 잔량 75% stuck 방지 |
| 옵션 C UI | `0d30201` | 마지막 단계 사용자 입력값 진입 + 미리보기 |
| dedup gate | `a97504f` 일부 | 60초 SENT/PENDING 윈도우 |
| 회귀 방지 test 1차 | `6f3de28` | partial close 5개 |
| .dockerignore | `d62a6d5` | symlink build error 회피 |
| **STOPPING 좀비 자동 정리** | `2677aff` | stream + reconcile 양쪽 |
| .gitignore 정리 | `03f9d90` | 인코딩 + pytest cache |
| **max_loss/profit peak 추적 fix** | `69692d4` | 음수만 max_loss, 양수만 max_profit |

---

이 체크리스트를 한 항목씩 처리하면서 ☐ → ☑ 로 갱신하면 다음 세션이 진행 상황 한 번에 파악 가능.

# RUNBOOK — Binance Futures Auto Trading Platform

운영 매뉴얼. 시스템 운영 / 비상 대응 / 트러블슈팅 절차.

---

## 1. 기본 기동

### 1.1 로컬 개발/testnet
```bash
cd backend
cp .env.example .env             # 첫 실행 시
# .env 편집 (자격증명, DATABASE_URL, TELEGRAM_BOT_TOKEN, ENCRYPTION_KEY 등)
chmod 600 .env

docker compose up -d --build     # 모든 서비스 빌드 + 기동
docker compose ps                # 11개 컨테이너 Running 확인
docker compose logs api --tail=20
```

### 1.2 Production (DigitalOcean VPS)
`DEPLOYMENT-DIGITALOCEAN.md` 의 Phase 0~8 따라:
1. Droplet 생성 (Singapore, 8GB AMD)
2. OS hardening + Docker 설치
3. 코드 clone + `.env` (mainnet 자격증명, ENCRYPTION_KEY 마이그레이션 후)
4. `docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build`
5. Nginx + Let's Encrypt HTTPS

### 1.3 첫 사용자 + 거래소 계정
- UI 회원가입 또는 admin 직접 user 생성
- 「거래소 계정 추가」 → API key/secret + `is_testnet` 선택

---

## 2. 일상 운영

### 2.1 시스템 상태 확인 — 운영 점검 스크립트 (권장)

**한 줄로 「오늘 문제 있었나?」 점검** (2026-05-09 추가):
```bash
# 최근 24시간 — 거래 활동 + 위험 이벤트 + 권장 조치
docker compose exec api python scripts/health_check.py --hours 24

# 최근 1시간 — 짧은 점검 (자주)
docker compose exec api python scripts/health_check.py --hours 1

# 즉시 진단 — DB ↔ 거래소 1:1 일치 + 5분 내 CRITICAL 확인
docker compose exec api python scripts/health_check.py --now
```

출력 예시 — 모두 정상이면:
```
🚨 검토 필요   ✅ 0건 — 운영 정상
💡 권장 조치   없음 — 그대로 운영
```

문제 있으면 「검토 필요」 + 「권장 조치」 항목에 구체적 안내 표시.

### 2.1b 컨테이너/로그 직접 확인 (필요 시)
```bash
# 컨테이너 상태
docker compose ps

# api 로그
docker compose logs api --tail=50 -f

# user-stream (체결 이벤트 수신)
docker compose logs user-stream --tail=50 -f

# scheduler (TP/SL/reconcile 30초 사이클)
docker compose logs scheduler --tail=50 -f

# 시스템 헬스
curl http://localhost:8000/health
curl http://localhost:8000/api/v1/admin/system-health
```

### 2.2 활성 전략 monitoring
```bash
# DB 쿼리 (PowerShell or bash)
python -c "
import psycopg2
from psycopg2.extras import RealDictCursor
db_url = [l.split('=',1)[1].strip() for l in open('.env', encoding='utf-8').read().splitlines() if l.startswith('DATABASE_URL=')][0].replace('postgresql+psycopg2://','postgresql://')
with psycopg2.connect(db_url) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
    cur.execute(\"SELECT id, symbol, side, status, current_position_qty, realized_pnl, unrealized_pnl FROM strategy_instances WHERE status NOT IN ('STOPPED','COMPLETED','REENTRY_READY','CLOSED','CLOSED_BY_TP','CLOSED_BY_SL') ORDER BY id DESC\")
    for r in cur.fetchall(): print(r)
"
```

---

## 3. 긴급 대응 절차

### 3.1 모든 거래 즉시 중단 (Kill Switch)
```bash
# UI: 관리자 페이지의 Kill Switch 활성화
# API:
curl -X POST -H "Authorization: Bearer <JWT>" \
  http://localhost:8000/api/v1/admin/kill-switch/{exchange_account_id}/enable
```
**효과**: 새 진입 차단 + 활성 전략 모두 STOPPING

### 3.2 단일 전략 정지
- UI: 「수동 정지/청산」 버튼 (mode = `close_position_market`)
- 또는:
```bash
curl -X POST -H "Authorization: Bearer <JWT>" \
  http://localhost:8000/api/v1/strategies/{id}/stop \
  -d '{"mode":"close_position_market","reason":"manual"}'
```

### 3.3 좀비 STOPPING 정리
**자동**: `reconcile_worker` 30초 사이클에 자동 정리 (commit `2677aff`).

**수동** (자동 안 될 때):
```sql
UPDATE strategy_instances
SET status='STOPPED', stopped_at=NOW()
WHERE status='STOPPING' AND current_position_qty=0;
```

### 3.4 거래소 API 키 노출 의심
1. Binance UI 즉시 API key 비활성화
2. 새 key 발급 (권한 최소화 + IP whitelist)
3. 시스템 UI 의 거래소 계정 row 키 갱신
4. backend 재시작:
   ```bash
   docker compose restart api scheduler user-stream
   ```

### 3.5 DB 손상 / 의심
```bash
# 백업 복원 (db-backup 컨테이너의 일별 백업)
ls backend/db_backups/daily/   # 최신 .sql.gz 확인
gunzip -c backend/db_backups/daily/binance_auto_trader-latest.sql.gz | \
  docker compose exec -T db psql -U postgres binance_auto_trader

# Neon 사용 시: Neon UI 의 "Restore" 사용
```

### 3.6 listenKey 영구 끊김
- 증상: user-stream 로그에 reconnect 무한 반복 + RiskEvent CRITICAL
- 조치:
  1. Binance API 자체 가용성 확인 (https://www.binance.com/api/status)
  2. 거래소 계정 API key 권한 (futures + read user data) 확인
  3. user-stream 컨테이너 재시작:
     ```bash
     docker compose restart user-stream
     ```
  4. 재시작 후에도 끊김 → keepalive_worker 로그 확인

### 3.7 우리 서버 다운 + 거래소엔 포지션 살아있는 케이스
1. 즉시 서버 복구 (docker compose up)
2. `reconcile_worker` 가 자동 동기화 (30초 안)
3. 그래도 좀비 발견되면 수동 SQL (3.3 참고)

---

## 4. 정기 점검

### 4.1 일일 (매일 권장 — 1분)
**한 줄로 끝**:
```bash
docker compose exec api python scripts/health_check.py --hours 24
```

이 스크립트가 다음을 자동 점검:
- [x] 거래 활동 (진입/청산/신규)
- [x] 텔레그램 발송 실패 여부
- [x] CRITICAL/ERROR 검토 필요 항목
- [x] 빈도 높은 이벤트 패턴 (rate limit / orphan / mismatch)
- [x] 권장 조치 자동 도출

추가로 (필요 시):
- [ ] DB 백업 파일 (오늘 03:00 UTC 의 .sql.gz 생성됐나)
- [ ] `docker compose ps` — 컨테이너 모두 Running

### 4.2 주간
- [ ] 누적 통계 (`SELECT ... FROM strategy_instances WHERE status IN ('STOPPED','COMPLETED','REENTRY_READY')`)
- [ ] DigitalOcean Snapshot (Droplet → Backups)
- [ ] Disk 공간 (`docker system df`)
- [ ] Prometheus 메트릭 검토 (Grafana 대시보드)
- [ ] Sentry 에러 검토

### 4.3 월간
- [ ] DB 백업 복원 시뮬레이션 (별도 환경)
- [ ] `pip` / Docker image 보안 업데이트
- [ ] `apt update && apt upgrade -y` (VPS)
- [ ] Binance API 키 권한 재확인 (변경 없는지)

---

## 5. 트러블슈팅

### 5.1 "전략 생성 실패: 같은 거래소/심볼/방향 으로 활성 전략이 있습니다"
**의도된 안전장치** — Binance hedge mode 통합 포지션 충돌 방지.
- 기존 전략을 종료하거나
- 다른 심볼/측면 선택

### 5.2 "Unmatched stream event"
- RiskEvent 의 WARN 로그
- 거래소가 우리 시스템 외에서 만든 주문 (수동 거래 등) 의 이벤트
- **거래 로직엔 영향 없음** — 단순 monitoring 노이즈
- 자주 발생하면 stream_service 의 매칭 로직 + Binance 자체 sub-event 검토

### 5.3 텔레그램 알림 안 옴
1. `.env` 의 `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` 정확?
2. 봇이 채팅에 추가됐나? (사용자가 `/start` 한 번 입력)
3. 60초 dedup gate 에 걸린 건 아닌가? (같은 title 1분 내 중복)
4. NotificationService 로그 (`docker compose logs api | grep telegram`)
5. 수동 테스트:
   ```bash
   curl -X POST -H "Authorization: Bearer <JWT>" \
     http://localhost:8000/api/v1/admin/telegram-test
   ```

### 5.4 거래소 API 호출 실패 (-1003 / -2010 / -2022 등)
- `-1003`: rate limit. backoff 필요
- `-2010`: insufficient balance / NEW_ORDER_FILTER_REJECT
- `-2022`: ReduceOnly Order is rejected — 포지션 없는데 reduce 시도 (3.1 의 자동 정리 작동)
- backend 의 `app/utils/backoff.py` 적용 확인

### 5.5 메모리 / CPU 스파이크
```bash
docker stats               # 컨테이너별 리소스
free -h                    # VPS 메모리
df -h                      # 디스크
```
- prometheus TSDB 가 disk 많이 차지하면 retention 줄임 (`--storage.tsdb.retention.time=15d`)

### 5.6 좀비 STOPPING 자동 정리가 안 됨
**조건 점검**:
- `reconcile_worker` 가 30초마다 정상 실행되는지 (`docker compose logs scheduler`)
- 거래소 실 포지션 = 0 인지 (`get_position_risk` 결과)
- DB 의 `current_position_qty` 가 0 인지

대부분 Redis lock 경합 없으면 자동 처리. 안 되면 수동 SQL.

### 5.7 realized_pnl 값이 이상
- 중복 누적 버그 (commit 이전): 이미 fix `f5ad...` (2026-05-02)
- 운영 중 발견 시:
  ```sql
  -- 같은 strategy 의 EXIT order 들 + realized_pnl 일관성 확인
  SELECT id, executed_qty, avg_price, status FROM orders WHERE strategy_instance_id={id} AND purpose='EXIT';
  -- 정상 PnL 계산: SHORT = sum(qty × (entry - exit)), LONG 반대
  ```
- 차이 있으면 SQL 보정 (`UPDATE strategy_instances SET realized_pnl=... WHERE id=...`)

---

## 6. 백업 / 복원

### 6.1 자동 백업
- `db-backup` 컨테이너가 매일 03:00 UTC 실행
- 위치: `backend/db_backups/{daily,weekly,monthly,last}/`
- 정책: 일 7개 / 주 4개 / 월 6개

### 6.2 수동 백업
```bash
docker compose exec db-backup /backup.sh
```

### 6.3 복원
```bash
# 1. 활성 전략 모두 STOP (필수)
# 2. backend 컨테이너 정지
docker compose stop api scheduler user-stream

# 3. DB 복원
gunzip -c backend/db_backups/daily/binance_auto_trader-{YYYYMMDD}.sql.gz | \
  docker compose exec -T db psql -U postgres binance_auto_trader

# 4. backend 재기동
docker compose start api scheduler user-stream
docker compose logs api --tail=20
```

### 6.4 Neon Cloud 사용 시
- Neon UI 의 "Restore" 또는 "Branching" 기능 활용
- 시점 복구 가능 (Neon plan 따라 24h~30일)

---

## 7. 보안 체크 (Production)

### 7.1 자격증명 노출 의심
- 즉시 모두 갱신 (`.env`):
  - `SECRET_KEY` (JWT 무효화)
  - DB password (Neon UI 에서 reset)
  - `TELEGRAM_BOT_TOKEN` (BotFather Revoke)
  - `ENCRYPTION_KEY` (DB 마이그레이션 필요 → `deploy/encryption_key_migration.py`)
- backend 재시작
- Binance API 키 회전

### 7.2 정기 회전 (분기 1회 권장)
- SECRET_KEY 회전 (사용자 재로그인 필요)
- ENCRYPTION_KEY 마이그레이션
- 거래소 API 키 권한 재확인

### 7.3 IP whitelist (mainnet)
- Binance API key 의 trusted IP 만 활성
- DigitalOcean Cloud Firewall + ufw (80/443/22 만 in)

---

## 8. 메트릭 + 알림

### 8.1 Prometheus (`http://localhost:9090`)
주요 메트릭:
- `user_stream_events_total{event_type}`
- `position_reconcile_total{status}` — `success`/`miss`/`orphan_stopped`/`zombie_stopped`
- `position_qty_mismatch_total{symbol, side}` — DB vs 거래소 불일치
- `strategy_take_profit_total{symbol, side, level}`
- `strategy_stop_loss_total{...}`
- `notification_send_total{channel, status}` (있다면)

### 8.2 Grafana (`http://localhost:3000`)
- Admin: `admin / Admin1234!` (변경 권장)
- Dashboard: `binance-auto-trader/dashboards/`

### 8.3 Sentry
- production: `.env` 의 `SENTRY_DSN` 설정
- 에러 발생 시 자동 알림 (Sentry UI 또는 webhook)

### 8.4 외부 가용성
- UptimeRobot 무료 — `https://trader.yourdomain.com/health` 5분 간격
- 다운 시 텔레그램/이메일 알림

---

## 9. 자주 쓰는 명령어 cheatsheet

### 9.1 Docker
```bash
docker compose up -d --build           # 빌드 + 기동
docker compose restart api             # 단일 서비스 재시작
docker compose logs <서비스> --tail=N -f
docker compose ps
docker compose down                    # 모두 정지 (volumes 보존)
docker stats                           # 리소스 사용량
```

### 9.2 DB
```bash
docker compose exec db psql -U postgres binance_auto_trader
# 또는 Neon: psql "<DATABASE_URL>"
```

### 9.3 PowerShell DB query (Windows)
```powershell
python -c @"
import psycopg2
from psycopg2.extras import RealDictCursor
db_url = [l.split('=',1)[1].strip() for l in open('.env', encoding='utf-8').read().splitlines() if l.startswith('DATABASE_URL=')][0].replace('postgresql+psycopg2://','postgresql://')
with psycopg2.connect(db_url) as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
    cur.execute("...your SQL...")
    for r in cur.fetchall(): print(r)
"@
```

### 9.4 Test
```bash
docker compose exec api pytest tests/unit/ -v
# 또는 host 에서
cd backend && python -m pytest tests/unit/ -q
```

---

## 10. 알려진 제약 / 주의

1. **Binance hedge mode**: 같은 (symbol, position_side) 단일 포지션. 중복 strategy 금지 (안전장치 적용).
2. **listenKey 60분 만료**: keepalive_worker 가 30분 간격 ping (자동).
3. **EXIT FILLED 중복 이벤트**: idempotent gate 적용 (`f5ad...` 2026-05-02).
4. **emergency_close race**: status STOPPING 먼저 commit (`f5ad...` 2026-05-02).
5. **realized_pnl 정확성**: fee/funding 미반영 — Binance Trade History 가 정확.
6. **ENCRYPTION_KEY 변경**: DB 의 거래소 자격증명 마이그레이션 필요. 변경 전 `deploy/encryption_key_migration.py` 사용.

---

## 11. 비상 연락 + 참조

- **Binance Status**: https://www.binance.com/api/status
- **Binance Futures API docs**: https://binance-docs.github.io/apidocs/futures/en/
- **Neon Console**: https://console.neon.tech/
- **이 시스템의 spec**: `SYSTEM-SPEC.md`
- **audit findings**: `AUDIT-FINDINGS.md`
- **production 배포**: `DEPLOYMENT-DIGITALOCEAN.md`
- **mainnet 체크리스트**: `MAINNET-CHECKLIST.md`

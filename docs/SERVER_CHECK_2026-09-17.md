# 🩺 서버 점검 (2026-09-17 05:35~05:50 UTC, 읽기 전용)

사장님: 「서버 상태를 점검해줘 용량 속도 등등」

## 요약

| 항목 | 상태 | 값 |
|---|---|---|
| 🚨 **DB 백업** | **실제로 안 되고 있음** | 매일 백업 파일 **504바이트** — 운영 DB(외부 Neon 582MB)가 아니라 거의 빈 로컬 `db` 컨테이너(7.5MB)를 백업 중 |
| 🟠 컨테이너 로그 | 크기 제한 없음 | api **2.5GB** · scheduler **2.8GB** · 시세 스트림 406MB (scheduler 약 75KB/분 ≈ 하루 100MB) |
| 디스크 | 여유 | 48GB 중 31GB 사용 (66%) · 여유 17GB |
| 메모리 | 여유 | 7.8GB 중 1.4GB 사용 · 사용 가능 6.4GB · 스왑 없음 |
| CPU | 여유 (순간 부하 있음) | 2코어 · 평소 유휴 약 90% · 부하 평균 0.6~2.5 |
| API 속도 | 정상 | `/health` 3~6ms · DB 왕복 2ms(첫 연결 56ms) |
| 운영 DB (Neon, PostgreSQL 16) | 582MB | paper_trades 329MB(13.9만 행) · positions 107MB(56만 행) |
| Redis | 정상 | 80MB · 키 9.1만 · 초당 약 420건 · 밀려난 키 0 |
| 오류 로그 | 없음 | 최근 30분 scheduler·api ERROR 0건 · 작업 겹침 경고 0건 |
| 배포 | 최신 | VPS `1a65e5f` (Fix 374~376) · 05:35 재시작 · Fix 375·376 검사 PASS |
| 가동 시간 | 128일 | |

## 1. 🚨 백업

- `db-backup` 설정이 `POSTGRES_HOST: db` (로컬 컨테이너).
  - 운영 앱은 `.env` 의 DATABASE_URL 로 **Neon** 을 쓴다.
  - 그래서 매일 「성공」 로그와 healthy 표시가 뜨지만, 백업 안에 테이블이 하나도 없다 (`COPY` 0개).
- 지금 운영 데이터를 지키는 것은 **Neon 자체의 복원 기능뿐**이다.
  - 보관 기간은 요금제에 따라 다르다 → Neon 콘솔에서 확인 필요.
- **조치 (사장님)** — 이번 커밋에서 `docker-compose.yml` 이 `.env` 변수로 백업 대상을 바꿀 수 있게 됐다.
  1. VPS `backend/.env` 에 아래 값을 넣는다.
     - `BACKUP_PG_HOST` · `BACKUP_PG_USER` · `BACKUP_PG_PASSWORD` · `BACKUP_PG_DB` · `BACKUP_PG_SSLMODE=require`
     - 값은 DATABASE_URL 과 같다. 호스트는 `-pooler` 가 **없는** 직접 호스트를 쓴다.
  2. `docker compose up -d db-backup`
  3. 다음 날 `ls -la db_backups/daily` 로 파일 크기가 수십 MB 인지 확인한다.
  4. 필요하면 즉시 한 번 실행: `docker compose exec db-backup /backup.sh`
- ⚠️ 운영 DB 582MB 를 매일 받으면 백업 폴더가 커진다.
  - 보관 규칙은 일 7 · 주 4 · 월 6이고, 압축 뒤 대략 수십 MB × 17개로 예상한다 (추정).

## 2. 🟠 로그 크기

- Docker 기본(json-file)에 크기 제한이 없었다.
  - `/etc/docker/daemon.json` 없음.
  - compose 에도 `logging` 설정이 없었다.
- 로그가 커서 `docker compose logs --since 8m` 도 1분 넘게 걸린다. 장애 진단이 느려진다.
- **이번 커밋:** 모든 서비스에 `max-size 50m × max-file 5` (서비스당 최대 250MB, Claude가 정함).
- **적용 (사장님):** `docker compose up -d` — 로그 설정은 컨테이너를 **다시 만들어야** 바뀐다. `restart` 로는 안 바뀐다.
  - 옛 거대 로그 파일은 컨테이너 재생성 때 함께 지워진다.
  - 그 전에 남기고 싶으면 `docker compose logs api > /root/api-log-backup.txt` (용량 주의).

## 3. 디스크 정리 여지 (선택)

- Docker 빌드 캐시 **11.3GB** 회수 가능: `docker builder prune -f`
  - 실행 중인 서비스에 영향 없음. 다음 빌드가 조금 느려질 뿐이다.
- systemd 저널 1.0GB: `journalctl --vacuum-size=200M`

## 4. CPU·속도

- 5초 간격으로 8번 측정했다.
  - api: 평소 0.2%. 대시보드 새로고침이 몰릴 때 순간 30~100% (uvicorn 프로세스 1개 = 코어 1개).
  - scheduler: 10~20%. 주기적으로 110~120% (여러 워커가 겹치는 순간).
- 8분간 API 요청 약 700건 (초당 1.5건), 거의 전부 대시보드 자동 조회다.
  - `/strategies` 122건 = 약 4초마다 → **대시보드가 여러 탭에 열려 있을 가능성**. 안 쓰는 탭을 닫으면 api 순간 부하가 준다.
- Prometheus 가 api 의 `/metrics` 를 긁는데 404 다.
  - 앱 지표가 수집되지 않는다 (Grafana 대시보드가 비어 있을 수 있음). 급하지 않다.

## 5. DB 증가

- `paper_trades` 가 전체의 57% (329MB) 다. 가상매매 기록(엔진·스냅샷 JSON)이 크다.
- ⚠️ Neon 요금제 저장 한도를 확인할 것. 무료 요금제 한도는 0.5GB 수준이고, 지금 582MB 다.
- 한도가 걱정되면 선택지가 둘이다.
  - 오래된 백필 행(`source=backfill`)을 정리한다.
  - `chart_state` 스냅샷을 가볍게 한다.
  - 둘 다 **DB 삭제 작업이라 사장님 승인 후에만** 한다.

## 6. CPU 를 늘려야 할 때 (사장님 질문 「2코어에서 더 추가해야 하면 어떻게」)

### 현재 사양 (droplet 메타데이터 · lscpu 확인)
- DigitalOcean 싱가포르(sgp1) · droplet `570311447`
- vCPU 2개 (Intel Xeon Platinum 8168) · 메모리 8GB · 디스크 50GB
- 공인 IP `159.65.137.250` 은 droplet 기본 IP 다 (예약 IP 아님).
  사양 변경(resize)으로는 IP 가 바뀌지 **않으므로** 바이낸스 API 키의 IP 허용 목록은 그대로 둬도 된다.
- CPU steal 0 (다른 손님 영향 없음).

### 지금은 늘릴 필요가 없다
- 평소 유휴 약 90%, 부하 평균 0.6~2.5 (코어 2개 기준).
- 늘릴 신호 (하나라도 **며칠 계속**되면):
  - `uptime` 부하 평균(15분)이 계속 2 이상
  - scheduler 로그에 `skipped: maximum number of running instances` / `was missed` 가 반복
  - `/health` 응답이 계속 100ms 이상
  - `vmstat 1 5` 의 `st`(steal) 가 계속 5 이상 → 공유 CPU 문제, 전용 CPU 요금제 검토

### 🚨 코어만 늘리면 빨라지지 않는 부분
- 이 앱은 파이썬 프로세스 4개다: api(uvicorn 1개) · scheduler(1개) · user-stream · mark-price-stream.
- 파이썬은 한 프로세스가 사실상 **코어 1개**만 쓴다 (GIL).
  - scheduler 가 순간 120% 까지 오르는 것은 스레드 대기·C 라이브러리 몫이다.
  - **scheduler·api 하나하나를 더 빠르게 하지는 못한다.**
- 코어를 늘리면 좋아지는 것:
  - 네 프로세스 + Redis·Grafana 가 서로 덜 기다린다.
  - 대시보드 새로고침 때 api 순간 100% 가 scheduler 를 밀어내지 않는다.
- 코어를 **제대로** 쓰려면 코드 쪽 작업이 같이 필요하다 (Claude 작업, 사장님 요청 시):
  1. **api 여러 프로세스**: `uvicorn --workers 2`.
     - 단, 시작할 때 도는 작업(`_poll_health_metrics`)이 프로세스 수만큼 겹치므로, 한 프로세스만 돌게 정리한 뒤에 켠다.
  2. **scheduler 나누기**: 무거운 분석 작업을 두 번째 scheduler 컨테이너로 옮긴다.
     - 대상: 가상매매(`paper_trading`) · 차트 학습 · 차트 타이밍 · 손실 원인.
     - 매매 워커는 지금 컨테이너에 둔다. 작업마다 Redis 잠금(`guarded_job`)이 있어 중복 실행은 막힌다.

### 사양 변경 방법 (DigitalOcean 화면 · 사장님)
1. **먼저 확인:** 자동매매 중단 상태인지, 그리고 **열린 포지션이 있는지**.
   - 🚨 손절·익절은 거래소에 걸어 둔 주문이 아니라 **서버 워커(tp_sl, 15초 주기)가 감시**한다.
   - 서버가 꺼져 있는 동안에는 열린 포지션에 손절이 **작동하지 않는다**.
   - 가능하면 포지션이 없을 때, 아니면 바이낸스 앱에서 손절 주문을 직접 걸어 두고 진행한다.
2. **스냅샷:** Droplet → Backups/Snapshots → Take snapshot.
   - 운영 DB 는 Neon 이라 스냅샷에 없다 → §1 백업을 먼저 고쳐 두는 것이 좋다.
3. **전원 끄기:** Power → Turn off (서버 안에서 `poweroff` 도 가능).
4. **Resize:** Droplet → Resize.
   - **「CPU and RAM only」 를 고른다.** 디스크를 안 늘리면 나중에 다시 작은 사양으로 **되돌릴 수 있다**.
   - 「Disk, CPU and RAM」 은 디스크가 커져 **되돌릴 수 없다** — 디스크는 지금 66% 라 급하지 않다.
   - 추천 순서: 같은 계열에서 **4 vCPU / 8GB 이상**.
     공유 CPU(Basic)로 충분하다 — steal 0. 전용 CPU(General Purpose·CPU-Optimized)는 steal 이 문제일 때만.
   - 가격은 DigitalOcean 화면의 현재 요금을 확인한다 (여기 적지 않는다 — 수시로 바뀜).
5. **전원 켜기:** Power On.
   - docker 는 부팅 시 자동 시작(`enabled`)이고, 컨테이너도 `restart: unless-stopped` 라 스스로 올라온다.
   - 예외: prometheus 는 `restart=no` 라(compose 에 restart 줄이 없음) 직접 `docker compose up -d prometheus`.
6. **확인** (서버에서):
   ```bash
   nproc && cd ~/binance-auto-trader/backend && docker compose ps && docker compose exec -T scheduler python scripts/verify_fix364_deploy.py
   ```
   `nproc` 가 새 코어 수, 컨테이너 전부 Up, 검사 PASS 면 끝.
   Kill-Switch·자동매매 중단 상태는 DB 설정이라 재시작해도 그대로다.

- 걸리는 시간: 끄고 켜는 시간 포함 보통 수 분 (CPU·RAM 만 바꿀 때).
- 되돌리기: 같은 화면에서 원래 사양으로 다시 Resize (「CPU and RAM only」 로 바꿨을 때만 가능).

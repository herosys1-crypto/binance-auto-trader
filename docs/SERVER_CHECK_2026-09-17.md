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

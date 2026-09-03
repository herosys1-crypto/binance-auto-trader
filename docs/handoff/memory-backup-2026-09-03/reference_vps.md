---
name: ""
metadata: 
  node_type: memory
  originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
---

VPS SSH 후 작업 위치: **`~/binance-auto-trader/backend`** (홈 디렉터리 하위).

❌ **잘못된 경로 사례**: `/opt/binance-auto-trader/backend` — 존재하지 않음. 사장님이 cd 실패 보고함 (2026-05-21).

## VPS IP — 2 IP 같은 droplet (2026-06-02 발견)

| IP | 용도 | 비고 |
|---|---|---|
| **`159.65.137.250`** | **사장님 실 사용 (HTTP, web 접속 + SSH)** | `http://159.65.137.250/admin-ui#dashboard` |
| `152.42.232.195` | 대체 IP — 같은 droplet | hostname 양쪽 다 `binance-trader-prod` |

→ 두 IP 모두 SSH 가능. hostname 같음 = **하나의 droplet (DigitalOcean) 의 multi-IP**.

## SSH 접속 (PowerShell from Windows)

사장님 SSH 키 = `C:\Users\user\.ssh\id_ed25519` (정상 동작 확인됨, 2026-06-02).

```powershell
# 호스트키 변경 시 (재시작 등)
ssh-keygen -R 159.65.137.250

# Interactive 접속 (사장님이 평소 작업 — VPS 안에서 명령 직접 실행)
ssh root@159.65.137.250

# 한 줄 원격 실행
ssh root@159.65.137.250 "cd ~/binance-auto-trader/backend && git pull origin main && docker compose restart api"
```

## 표준 배포 명령 (PR 머지 후)

**VPS 안에서 (사장님이 SSH 들어간 후)**:
```bash
cd ~/binance-auto-trader/backend
git pull origin main             # "Updating ..." 메시지 확인 (Already up to date 면 PR 미머지)
git log --oneline -5             # 새 커밋들 확인
docker compose restart api scheduler   # 변경한 부분만 (mark-price-stream / user-stream 도 필요시)
```

**컨테이너 서비스 이름 (`backend-api` 가 아님)**:
- `api` (FastAPI, 빌드 시 static 포함)
- `scheduler` (worker — reconcile/tp_sl/stage_trigger/sync_health 등)
- `user-stream` (Binance WebSocket)
- `mark-price-stream` (markPrice 1s 실시간 PnL)
- `db` (postgres 16), `redis` (redis 7), `db-backup`, `grafana`, `prometheus`

## DB / Redis 명령

```bash
# DB 이름 = binance_auto_trader (postgres 가 아님!)
docker compose exec db psql -U postgres -d binance_auto_trader -c "SELECT id, symbol, status FROM strategy_instances WHERE id = 9;"

# Redis peak key 패턴 = strategy:{id}:peak_pnl_pct
docker compose exec redis redis-cli GET "strategy:9:peak_pnl_pct"
docker compose exec redis redis-cli KEYS "strategy:*:peak_pnl_pct"

# scheduler leader lock
docker compose exec redis redis-cli GET "sched:leader"

# API ban 마커
docker compose exec redis redis-cli GET "api_backoff:account:1:ban_until_ms"
```

## Static 자산 캐시 (2026-06-02 #40 fix 적용)

`NoCacheStaticFiles` + HTML script 태그에 `?v=20260602` cache buster.
→ **사장님 일반 F5 만으로 새 JS 즉시 받음** (Ctrl+Shift+R / 시크릿 모드 불필요).
→ 다음 release 부터 같은 사고 재발 X.

## 주의

- VPS 가 종종 옛 브랜치 (예: `fix/...`) 에 있어 `git pull origin main` 만으로는 main 의 최신 변경을 받지 못할 수 있음. 의심 시 `git checkout main` 후 pull.
- **PowerShell 에서 `&&` 안 됨** (PowerShell 5.1) — `;` 또는 SSH 한 줄 (`ssh ... "cmd1 && cmd2"`) 안에선 OK (bash 가 평가).
- VPS 안에서는 **SSH 다시 X** — `root@binance-trader-prod:~#` prompt = 이미 VPS, 명령 직접 실행.
- smoke test 가 컨테이너 시작 직후 `/health` 일시 실패할 수 있음 → 60초 대기 후 재실행 권장.

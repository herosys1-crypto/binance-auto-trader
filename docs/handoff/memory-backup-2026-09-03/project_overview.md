---
name: Binance Auto Trader 프로젝트 개요
description: 프로젝트 + VPS 배포 상태 + 5-21 안전망 5종 + 외부 포지션 가시성 머지 완료 (#77/#78 PHB/RONIN ~$384 손실 사례 후속)
type: project
originSessionId: 7267a196-3d53-4c24-9363-6694e7fbeedd
---
**프로젝트**: Binance Futures USDⓢ-M 자동매매 — testnet on VPS 운영 중, mainnet 전환 준비 단계.

**Why**: 사용자 직접 운용. 옵션 C 다단계 (1~10) + TP1~10 + Crisis Recovery + Zombie Guardian.

**How to apply**:
- 시스템 정의: `SYSTEM-SPEC.md`, `AUDIT-FINDINGS.md`, `DEVELOPMENT_SPEC.md`
- 운영: `backend/RUNBOOK.md`
- mainnet 전환: `MAINNET-CHECKLIST.md`, `VPS-DEPLOY-CHECKLIST.md`
- 정책 (TP/trailing/crisis): `TP_TRAILING_LOGIC_FINAL.md`

**구성**:
- `backend/` — FastAPI + SQLAlchemy + Alembic + Redis (8 컨테이너)
- `backend/app/services/` — strategy / stream / tp_sl_orchestrator / risk / zombie_guardian / notification / account_kill_switch / account_daily_loss_limiter
- `backend/app/workers/` — reconcile / stage_trigger / auto_reentry / daily_loss_aggregator / heartbeat / user_stream
- `backend/app/static/index.html` — **1,178줄** + 32 JS 모듈 in `backend/app/static/js/` (5-15 Phase 3 분리 완료)
- `backend/scripts/` — rotate_encryption_key, check_binance_key 등
- `deploy/` — vps-bootstrap.sh, generate-secrets.sh, validate-readiness.sh, smoke-test.sh

**현재 상태 (2026-05-19, main = 052b6c1 + VPS 배포 최신 — 아래 5-17~19 절 참조)**:
- PR #23 머지: Phase 3 UI 모듈화 + 사용자 보고 대응 + 정책 진화 (89 commits, 5-08~5-15)
- 추가 머지: leverage UX 3건 fix (`575c10a`, 2c53d1e merge)
  1. 롱 기본 leverage 1 → 2 (사용자 매번 직접 변경하던 패턴 제거)
  2. 「이전 전략 불러오기」 시 bp.leverage 적용 (이전엔 항상 default 로 떨어짐)
  3. 전략 인스턴스 방향 컬럼에 leverage 같이 표시 (예: 「📉 숏 2x」)
- pytest **684 passed** (이전 465 → +219, 신규 회귀 테스트 다수)
- index.html 5,875 → 1,178줄 (-79.9%) + JS 모듈 0 → 32개
- **5-15 VPS 배포 완료 (2회)**: 1차 PR #23 → 2차 leverage UX. 둘 다 smoke test 13/13 통과

**VPS — 5-15 시점 운영 환경 (검증됨)**:
- **IP**: `159.65.137.250` (DigitalOcean SGP1 8GB)
- **옛 IP (stale)**: `152.42.232.195` (5-07 핸드오프) — 5-08 이후 재배포되며 변경됨
- **운영 URL**: `http://159.65.137.250/` (nginx port 80)
- **SSH**: `ssh -i ~/.ssh/id_ed25519 root@159.65.137.250` ← `root` 사용자 (5-07 의 `trader@` 도 stale)
- **Repo 위치**: `/root/binance-auto-trader/`
- **컨테이너**: api / scheduler / user-stream / redis (기타 db-backup/grafana/prometheus 도 가능)
- **DB**: Neon Cloud (외부) 사용 — VPS 의 docker postgres 는 미사용

**배포 절차 (검증된 5-15 패턴)**:
1. 로컬에서 `git archive --format=tar.gz HEAD -o /tmp/repo.tar.gz`
2. `scp -i ~/.ssh/id_ed25519 $env:TEMP\repo.tar.gz root@159.65.137.250:/tmp/`
3. SSH 후 VPS 에서: `tar -xzf /tmp/repo.tar.gz -C /root/binance-auto-trader --overwrite`
4. **반드시 `find /root/binance-auto-trader -name '*.sh' -exec sed -i 's/\r$//' {} \;`** (Windows tar 의 CRLF 제거 — dos2unix 미설치)
5. `cd /root/binance-auto-trader/backend && docker compose -f docker-compose.yml -f ../docker-compose.production.yml build --no-cache api && docker compose ... up -d --force-recreate api`
6. `sleep 10 && bash /root/binance-auto-trader/deploy/smoke-test.sh`

**5-15 세션 완료 작업 (PR #23, 89 commits 통합)**:
- Phase 3 UI 모듈 분리 30 commits (cm-* / dashboard-refresh / templates-panel / indicators / strategies-list / strategy-detail / chart-detail / accounts-modal / add-position-modal / strategy-actions / admin-shortcuts / page-router / auth-bootstrap)
- 사용자 보고 대응: #21 SAGAUSDT, #26 JELLYJELLY (4차), #33 AVAAIUSDT, #40 BUSDT, #41 ESPORTSUSDT, #57 MLNUSDT, #96 archive, #102 add_margin path, #VICUSDT orphan order
- 정책 진화: trailing TP v3~v7, crisis template 별 임계, ensure_isolated_margin 자동 호출
- 안전망: orphan open order 감지 (Zombie Guardian 3차), archive nonzero CRITICAL, force-stop endpoint
- DB: hot-path 인덱스 3개 + N+1 회귀 테스트 (Phase 5)

**5-17~18 세션 (rate-limit ban 종합 + 메인넷 전 검토, main = b8c6a83)**:
- 사용자 보고: Binance 418 IP ban 2분→13분 승격, 20~40분 반복
- 근본원인: check_api_ban 가드가 reconcile 에만 적용 → tp_sl/stage_trigger/auto_reentry
  가 ban 윈도우 중 hammering → ban 연장 스파이럴
- Fix (3 commit, VPS 3회 배포 + main 머지 + 브랜치 정리 완료):
  1. `2460592` is_account_banned/maybe_record_ban_from_exc 헬퍼 + 3워커 ban 가드
     + ensure_isolated_margin Redis 1h 캐시 (weight 절감)
  2. `ba26312` reconcile flat 레코드(positionAmt=0) orphan 자동정리 — #53 BASUSDT stuck
  3. `d699cae` detect_orphan_exchange_open_orders ban 가드 (메인넷 전 검토서 발견)
- #53 BASUSDT 수동 force-stop 완료 (거래소 flat 확인 후 STOPPED)
- 검토 결론: 다른 호출사이트 안전 확인 (BinanceClient 무retry / emergency_close
  bounded / user_stream backoff OK / stream fetch 이벤트기반)

**🔴 메인넷 전 반드시 (코드 아닌 운영 — 미적용 시 안전망 비활성)**:
모든 안전망 default 가 None → .env 미설정이면 통째 비활성. smoke 에서
`DAILY_LOSS_LIMIT_USDT 미설정` 확인. 메인넷 키 전환 전 VPS .env 에 필수:
```
DAILY_LOSS_LIMIT_USDT=<자본10%>   # ★최우선 (미설정=무제한 손실)
MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT=3
MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE=5.0
ALLOWED_SYMBOLS_CSV=BTCUSDT,ETHUSDT  # + UI 화이트리스트 토글 ON (현재 OFF 추정)
MAX_LEVERAGE=5
MIN_LIQUIDATION_DISTANCE_PCT=5
```
상세: `MAINNET-CHECKLIST.md` line 153/164-190

**5-18 추가 (symbol-sync stale, main = ed47865)**:
- 사용자 보고: EDENUSDT 등 비거래 심볼이 dropdown 에 노출
- 진짜원인: EDENUSDT 는 testnet 에 `PENDING_TRADING` 으로 존재 (없는 게 아님).
  DB 에 과거 stale `TRADING` 박혀 only_trading 필터 통과 → dropdown 노출
- Fix `e94dcf9`: symbol_sync 가 ① 정상 update 로 status 교정 (TRADING→PENDING)
  ② exchangeInfo 에 완전히 없는 TRADING 심볼 → DELISTED sweep (빈값 시 skip)
- VPS 배포 + 수동 sync 실행: synced=706 TRADING=587 DELISTED=0,
  EDENUSDT→PENDING_TRADING 교정 확인 (dropdown 에서 제외됨)
- 일일 03:00 UTC cron (`symbol_sync_daily`, 기존) 이 이제 등록+정리 자동 (사용자 요청 기능 = 이미 존재 + 이 fix 로 완성)

**5-19 추가 (emergency_close -4131, main = 9609df2)**:
- 사용자 보고 #62 MLNUSDT: 강제청산 MARKET 이 Binance -4131 PERCENT_PRICE
  거부 (저유동성 호가 얇음) → STOPPING stuck + EMERGENCY_CLOSE_PLACE_FAILED 루프
- Fix `682abee`: _percent_price_bounds + _emergency_close_limit_fallback —
  -4131 시 PERCENT_PRICE 밴드 경계가 LIMIT GTC 폴백 (SELL=하한 ceil,
  BUY=상한 floor, hedge 라 reduceOnly 없음). 신규 4 + 회귀 11 passed
- VPS 배포 + #62 수동 emergency_close 재호출 → 이번엔 MARKET 성공
  (호가 회복됨, 폴백 미발동) → #62 STOPPED qty=0 해소 완료
- 폴백은 안전망으로 대기 (향후 -4131 자동 처리)
- ★ 배포 교훈: SCP 가 깨진 tar 전송 가능 (네트워크 불안정 95KB/s).
  추출 전 반드시 `gzip -t /tmp/repo.tar.gz && ls -la` 무결성 검증.
  깨졌으면 build 가 옛 코드로 됨 (silent no-op). 정상 크기 ≈ 606KB

**5-19 추가 #2 (stage-trigger -2019 마진부족, main = e1f48d9)**:
- 사용자 보고: 13개 동시 전략으로 가용 증거금 소진 → 다음 단계 진입
  -2019 "Margin is insufficient" → is_triggered=False 라 매 10초 재시도
  → 주문 spam(rate-limit 기여) + Telegram spam (ban/-4131/flat 동일 클래스)
- Fix `163d840`: _is_margin_insufficient + (strategy,stage) Redis 30분
  쿨다운 + 알림 1회 dedup (fail-open). 쿨다운 중 단계 skip, 만료 후 1회
  재시도. 신규 7 + stage 회귀 140 passed. VPS 배포 완료 (grep=2 정상)
- spam 차단만 (사후). 사전 예방은 아래 #3.

**5-19 추가 #3 (전체 계획자본 예약 가드 — -2019 사전 예방, main = 052b6c1)**:
- 사용자 요청: "단계별 설정금액까지 포지션 진입한 걸로 계산해서 잔액 운영"
- 근본: 생성 시 required_margin 을 availableBalance(이미 진입 단계만 반영)
  와만 비교 → 기존 전략 미진입 단계 미반영 → 다수 통과 후 누적 -2019
- Fix `3faa51b` (strategy_service 0-C 가드): 모든 활성 전략을 「전체 단계
  다 진입」 가정으로 Σ(total_capital/leverage + additional_margins) 예약
  + 신규 계획마진 ≤ totalWalletBalance 검증. 초과 시 ValueError(생성 차단).
  신규 3 + capital/create/reentry 회귀 23 passed. VPS 배포 완료 (grep=1)
- 효과: 잔액 넘는 전략은 생성 자체가 막힘 → -2019 원천 예방
- ★ 기존 13개는 소급 X (이미 생성됨). #2 쿨다운이 spam 막고, 운영상
  포지션 일부 정리/입금으로 점차 정상화. 신규 생성부터 예약 가드 적용.
  메인넷 전 동시 전략 수/자본 배분 반드시 조정 (실제 돈이면 -2019=청산불가 위험)

**5-20 추가 (markPrice 라이브 PNL, main = d300bcf, PR #24 머지)**:
- 사용자 보고: UBUSDT 도구 PNL -74.19 vs Binance -87.29 (13 USDT 차이). STG/PROM/PTB 등도 5~13 USDT stale.
- 근본: reconcile 2분 주기로만 mark_price 갱신 + ACCOUNT_UPDATE 이벤트 사이엔 unrealized_pnl 정지.
- Fix `43efc62` (스쿼시 `d300bcf`):
  1. `app/services/mark_price_cache.py` — Redis 캐시 (key `mark_price:{symbol}`, TTL 60s) + `calc_unrealized_pnl` 헬퍼 (LONG/SHORT 부호 처리, mget 으로 N+1 회피)
  2. `app/workers/mark_price_stream_consumer.py` — Binance fstream `<symbol>@markPrice@1s` 다중 구독. 30s 마다 활성 심볼 재조사 → SUBSCRIBE/UNSUBSCRIBE 동적. 끊김 시 exponential backoff 재연결. testnet 자동 분기 (URL: `wss://stream.binancefuture.com/stream`).
  3. `app/api/v1/strategies/helpers.py` 에 `apply_live_unrealized_pnl[_batch]` — list/get 엔드포인트가 캐시 hit 시 라이브 마크로 재계산, miss 시 DB stored 값 fallback (backward-compat)
- 신규 단위 15 + 전체 회귀 710 통과
- VPS 배포 완료 (5-20 오후): 5개 컨테이너 running (db/redis/api/scheduler/**mark-price-stream**). 10 심볼 SUBSCRIBE 확인 (활성 포지션 전부 — PHB/RONIN 포함). Redis 캐시 10키 갱신 중. UBUSDT 실시간 마크 0.12318620 수신 확인.
- 기대 효과: 마크 가격 stale 2분→1초, PNL 차이 5~13 USDT→±0.1 USDT
- 알아둘 점: VPS 운영팀이 SSH 세션을 유지 중. 본 세션에서 PowerShell 에서 `ssh root@152.42.232.195` 시도했으나 timeout (옛 IP, 5-15 이후 stale). 사장님이 이미 다른 방식으로 VPS 연결 유지 중 (실제 운영 IP 는 `159.65.137.250` 으로 기록돼 있으나 진위 미확인 — 다음 세션 검증 필요).
- HANDOFF 문서: `HANDOFF-2026-05-20-MARK-PRICE-LIVE-PNL.md` (PR 대기 시점 작성, 머지 후 배포까지 완료된 상태)
- 후속 (별도 PR 후보): 외부 포지션 가시성 명확화 (UI "종료 숨김" 토글 동작 점검), mark-price-stream Prometheus 메트릭/알림, commission 차감 (영향 미미)

**5-21 추가 (안전망 5 PR 머지 + 외부 포지션, main ≈ `f346fee` 머지 commit)**:
- 사용자 보고 (5-20 후속): #77 PHB +359 USDT 피크 → -24 회귀 (~$384 손실). #78 RONIN 도 유사. 원인: STOPPING 갇힘 → `_NOT_FOR_TP_SL` 필터로 TP 평가 차단 → TP3 임계 통과해도 미발동. 며칠간 갇힘 사장님 인지 못 함 (UI 종료 숨김 토글에 가려짐).
- 5개 PR 머지 완료 (Phase 1 → 2 → 2B → 3 → 외부 포지션, GitHub PR #29/#30/#31/#32 추정):
  1. **Phase 1** (`f9b27b0` → `20f9b72`): STOPPING 가시성 (frontend TERMINAL_STATUSES 에서 분리) + 5분 갇힘 텔레그램 + UI 「⚠️ 갇힘 N분」 배지 + reconcile_worker `_detect_stopping_stuck` (이후 Phase 2 에서 자동 status 전환으로 진화)
  2. **Phase 2 + 2B** (`047385d`): `MANUAL_CLEANUP_REQUIRED` 신규 status (ACTIVE_LIKE 포함, TERMINAL 미포함, 자동 STOPPED 차단) + emergency_close 3초 post-verify + 10초 후 자동 재시도 1회 + `POST /strategies/{id}/acknowledge-manual-cleanup` (사장님 명시적 ack) + TP/SL/ENTRY MARKET 검증 확장 (is_full_close 분기 — TP 부분 청산은 status 유지)
  3. **Phase 3** (`3438240`): ENTRY MARKET 사전 마진 검증 (`_preflight_entry_market_check`) — `PreflightCheckFailed` 예외 → 400 친절 에러, 거래소 호출 0 (`PREFLIGHT_BLOCKED` RiskEvent)
  4. **외부 포지션** (`f346fee` ish): `GET /api/v1/positions/external` + 대시보드 「📊 외부 포지션」 카드 + 수동 새로고침. 추적 안 되는 거래소 포지션 (PHB/RONIN 같은 도구 밖 진입) 표시. 자동 관리 X.
- 신규 RiskEvent type 8종: `STOPPING_STUCK_DETECTED`, `EMERGENCY_CLOSE_RETRY_ATTEMPTED`, `EMERGENCY_CLOSE_RETRY_SUCCEEDED`, `EMERGENCY_CLOSE_VERIFY_FAILED`, `PARTIAL_CLOSE_VERIFY_FAILED`, `ENTRY_VERIFY_FAILED`, `PREFLIGHT_BLOCKED`, `MANUAL_CLEANUP_ACKNOWLEDGED`
- 전체 회귀 **765 passed** (이전 720 + 신규 45). 회귀 0건.
- VPS 배포 패턴 (5-21 검증): `cd ~/binance-auto-trader/backend` (NOT `/opt/...`), **반드시 `git checkout main` 명시 후 `git pull`** (VPS 가 종종 옛 브랜치 `fix/pnl-display-and-loss-alert-clarity` 등에 있음). smoke 14/14 (이전 13/13 에서 1 추가 — DAILY_LOSS_LIMIT_USDT/SENTRY_DSN 권장 경고는 무관). VPS IP **`152.42.232.195`** 가 5-21 시점 실제 운영 IP (5-15 기록의 `159.65.137.250` 은 이후 변경된 듯).
- ★ GitHub PR 워크플로 교훈 (사장님 GitHub 웹 UI 만 사용): (1) Phase 1 PR 을 의도치 않게 3번 만들었음 (#26/#27/#29 — 같은 변경 3번 머지) — URL `/pull/new/` 가 머지 후에도 같은 페이지 보여서 헷갈림. (2) Stacked PR 머지 시 순서 따라야 — Phase 2/2B/3 PR 이 옛 main 시점에서 만들어져 force-push 로 rebase 정리 1회 (claude 가 worktree 에서 force-push). 자세한 패턴: `feedback_pr_workflow.md`.
- 미해결 후속 (운영 검증 후 사장님 결정): Commission realized_pnl 차감 (2-3h), Ops 툴 `make diagnose-stuck` (1-2h), Prometheus alert 자동화 (3-4h)
- HANDOFF 문서: `HANDOFF-2026-05-21-SAFETY-NETS.md` (워크트리 루트, 5 PR 통합 요약)

**5-31 추가 (Binance Demo API 차단 발견 + 운영 일시 정지, main = 53af9b4)**:
- 사장님 보고: -1109 "Invalid account" 에러로 다음 단계 진입/긴급청산/증거금 추가 모두 실패
- 전수 진단 결과:
  - 사장님이 사용 중인 환경 = **Binance Demo Trading** (`demo.binance.com`)
  - 우리 시스템은 `is_testnet=True` 일 때 **`testnet.binancefuture.com`** 호출 — **다른 인프라**
  - demo trading API endpoint 는 **`demo-fapi.binance.com`** (BINANCE 가 demo 의 API 관리 페이지에 공식 명시)
- 추가 발견: **demo-fapi.binance.com 으로 endpoint 옮겨도 -1109** (auth/canTrade 통과, 가격필터/notional 통과, 그러나 valid 신규주문은 모두 거부)
  - 새 API 키 발급해도 동일 → 키 권한 문제 아닌 **Binance Demo 의 정책상 차단** (web UI 만 거래 허용, API 신규주문 금지로 추정)
  - demo.binance.com **웹 UI 청산도 "Invalid account" 토스트** — 모바일도 동일 → demo 계정 자체가 server-side 로 잠긴 상태
- 사장님 환경에서 **`testnet.binancefuture.com` 접속 불가** (한국망에서 차단된 듯)
- ⚠️ **결론**: 자동매매 불가 (demo API 차단 + testnet 접속 불가). 실제 돈 손실 0원 (모두 가상)
- 운영 임시 조치 (5-31 적용):
  ```bash
  # Redis ban 마커로 모든 워커가 account #1 호출 skip → -1109 spam 차단
  docker compose exec -T redis redis-cli SET "api_backoff:account:1:ban_until_ms" \
    $(( ($(date +%s) + 86400) * 1000 )) EX 86400
  docker compose exec -T redis redis-cli SET "api_backoff:account:1:notified" "1" EX 86400
  ```
  - scheduler 정상 동작 중, 로그에 `[tp_sl/stage-trigger] API ban active account=1 — skip cycle` 깨끗하게 표시
  - 모든 테스트 데이터 보존 (전략/주문/이벤트/계정)
  - 5-31 다음 5-31+1 ban TTL 만료 → 만료 전 환경 결정 또는 ban 재설정 필요
- 운영 재개 방법 (환경 정해지면):
  ```bash
  docker compose exec -T redis redis-cli DEL "api_backoff:account:1:ban_until_ms" "api_backoff:account:1:notified"
  ```
- 향후 옵션 (사장님 결정):
  - **A. testnet 복귀**: Cloudflare WARP 등 VPN 으로 testnet.binancefuture.com 접속 → 새 가입 → 키 → 등록
  - **B. 메인넷 전환**: 실제 돈, MAINNET-CHECKLIST 의 .env 안전망 필수
  - **C. Demo 정책 변경 대기**: Binance 가 demo API 거래 허용할 때까지 대기
- 다음 세션 코드 fix 후보 (시급도 낮음):
  - -1109 영구 cooldown 가드 (-2019/-4131 패턴) — Binance 정책 변경 등에 대비
  - BinanceClient base_url 옵션 추가 (`demo-fapi.binance.com` 도 지원) — 환경 분리 명확화

**다음 세션 시작 시**:
1. `git log --oneline main -3` (= `53af9b4` 또는 그 이후)
2. SSH: 사장님이 별도 방식으로 연결 유지 중 (이전 메모 IP `159.65.137.250` 정확 여부 미확인 — 5-20 세션에서 PowerShell 로 `152.42.232.195` 시도 timeout, 그러나 사장님은 VPS 안에서 작업 가능했음). 다음 세션엔 사장님께 현재 IP 확인 권장.
3. `docker compose ps` 로 **5 컨테이너** running 확인 (api/scheduler/user-stream/redis/**mark-price-stream**). mark-price-stream 추가됐음에 주의.
4. mark-price-stream 헬스 체크: `docker compose logs mark-price-stream --since 5m | grep "markPrice"` → "markPrice SUBSCRIBE N 심볼" 또는 "markPrice stream 연결됨" 확인. Redis: `docker compose exec redis redis-cli KEYS "mark_price:*"` 활성 전략 수만큼 키 있어야 함.
5. ban 재발 여부: `docker compose logs scheduler --since 1h | grep -i "API ban"`
6. 배포 시: SCP 후 `gzip -t /tmp/repo.tar.gz` 무결성 검증 필수 (5-19 교훈)
7. PnL 정확도 점검: 도구 UI vs Binance UI 의 unrealized_pnl 차이가 0.1 USDT 이내면 markPrice 라이브 정상 동작 중
8. 운영 이슈 / 사용자 보고 / mainnet 전환 절차 등 업무 별 진행

---

**2026-06-01 메인넷 첫날 (mainnet 진입 + 8개 critical fix)**:
- 새 Sub-Account API 키 + IP 화이트리스트 `159.65.137.250` 등록 + 500 USDT 이체
- 운영 첫날 8 chain bug 발견 → 모두 root cause = **2026-04-23 Binance WebSocket migration** (`/ws/<key>` → `/private/ws/<key>`) 미반영
- 8개 fix 머지: 차트 testnet 분리, 자동 stage trigger (STAGE_OPEN_PENDING fix), realized_pnl 동기화 worker, 잔액 「전체 단계 예약」 모드 (#30), Phase A/B/C/D wallet 안전망 (#36)
- 사장님 요구 핵심: **"거래소 잔액 기준으로 모든게 운영" + "수시로 비교분석해서 간략한 보고서로 최근동향에 알려줘요"**
- ALLOUSDT (#2) 어제 -31,519 size 차이 발견 (다른 sub-account 가 같은 symbol 진입) → strategy 종료로 자동 해결됨
- PORTALUSDT (#5/#6) STOPPING 갇힘 → 자동 청산 완료

**2026-06-02 (오늘 — task #38~#54, 총 17개 PR 진행 / main 머지 = 0a3e30b 기준 12개 / 4개 미머지 대기)**:

사장님 「추천으로 진행해줘」 패턴으로 우선순위 자동 진행. PR 목록:

| PR | 핵심 | 효과 |
|---|---|---|
| #38 | **`sync_health_monitor`** — 매 5분 DB↔Binance 비교 worker (수량/평단/uPnL) | 차이 발견 시 「최근 활동」 알림 (30분 dedup), 정상 시 6h 1회 summary |
| #39 | **Binance 비교 인라인 row** — 전략 인스턴스 카드 행 아래 | `📊 Binance: Size/Entry/BE/Mark/Margin/PNL ⏱ HH:MM:SS` 표시 |
| #40 | **`NoCacheStaticFiles` + cache buster** | 사장님 일반 F5 만으로 새 JS 즉시 받음 (Ctrl+Shift+R 불필요). **6-02 cache 사고 영구 해결** |
| #41 | 심볼 클릭 → Binance 선물 차트 새 탭 | 「시장 순위」 + 「전략 인스턴스」 + ranking 모달 |
| #42 | **비교 차이 자동 시각 강조** | 차이 발견 시 행 배경 빨강 + `⚠ 차이 N건` + tooltip 우리 DB 값 |
| #43 | **STOPPED 분류 3-way** | 🚫진입실패 / 🎯자동익절 / 🤖자동손절 / ✋수동손절 명확 구분 + summary 카운트 |
| #44 | **`reserved_for_strategies` 보강** | `max(계획_total_capital, Binance_실_init_margin)` — 수동 증거금/포지션 추가 반영 |
| #45 | **🔴 qty race fix** | ACCOUNT_UPDATE(pa) + ORDER_TRADE_UPDATE(delta) 중복 차감 → partial 청산도 actual_position REST 우선 (MYXUSDT alert 3회 원인) |
| #46 | **5초 polling 보강 + 15초 캐시** | 잔액 카드 + 시스템 배너 polling 추가 + Binance accountInfo Redis 15s 캐시 |
| #47 | **`commission` 즉시 차감** | ENTRY+EXIT 양쪽 — gross PnL stale 1분 → net 즉시 정확 (USDT 만 처리) |
| #48 | **TP/SL UI ROI 명시 + 동적 USDT 손실 미리보기** | 사장님 sl=79 → -71 헷갈림 재발 방지. `💰 예상 손실: 자본 180 × ROI 79% / 2x = 약 71.10 USDT` 실시간 |
| #49 | **`detect_orphan_db_orders`** — DB→거래소 sync | DB NEW 인데 거래소 openOrders 에 없음 = 외부 cancel 감지 → 자동 CANCELED 정정 (✅ GitHub PR #50 머지 완) |
| **미머지 (4개) — 사장님 GitHub PR 생성 + 머지 + 배포 필요** | | |
| #50 | **Hedge mode 자동 가드** — 신규 계정 등록 시 (6-01 -4061 재발 방지) | branch: `feat/hedge-mode-auto-guard-on-account-create-2026-06-02` |
| #51 | **「최근 활동」 type 필터 + 검색** — client-side, audit 보존 | branch: `feat/activity-feed-type-filter-search-2026-06-02` |
| #52 | **silent except 로깅 12개 위치** (tp_sl + stream_service) | branch: `fix/silent-except-logging-tp-sl-stream-2026-06-02` (이건 GitHub PR #51/#52 로 이미 머지됨 — 사장님 중복 클릭 가능성) |
| #53 | **mark-price-stream 헬스 체크** — silent 끊김 자동 감지 (`_check_mark_price_stream`) | branch: `feat/mark-price-stream-health-check-2026-06-02` |
| #54 | **binance_changelog_monitor 보강** — User Data Streams URL 추가 + last_check_at | branch: `feat/binance-changelog-monitor-boost-2026-06-02` |

**MYXUSDT (#9) 거래 검증 (6-02 핵심 운영 사례)**:
- 3단계 진입 + 수동 포지션 추가 595 → TP1~TP4 정상 발동 (총 gross +24.76 USDT)
- 3회 「포지션 수량 불일치」 alert → PR #45 로 root cause 해결 (race condition)
- trailing SL 정책 = TP3+ 발동 + stage≥3 + peak≥5% + retrace≥5%p (동시 만족 시 잔량 전량 청산)
- **사장님 결정 = 현재 정책 유지** (TP3 후 -5% 회귀 = peak ≈ +26.98%, 현재 +23.86% = retrace 3.12%p < 5%p → 미발동 정상)
- 가격 0.27870 → 0.29264 (+5%) 도달 시 자동 전량 청산 예정

**VPS 환경 확정 (6-02 발견)**:
- VPS IP **2개 = 같은 droplet** (hostname `binance-trader-prod`): `159.65.137.250` (사장님 실 사용 HTTP) + `152.42.232.195` (대체)
- DB 이름 = **`binance_auto_trader`** (`postgres` 아님)
- Redis peak key = `strategy:{id}:peak_pnl_pct`
- 컨테이너 서비스명 = `api` (`backend` 아님), `scheduler`, `user-stream`, `mark-price-stream`, `db`, `redis`, `grafana`, `prometheus`, `db-backup`
- 사장님 SSH 키 (Windows) = `C:\Users\user\.ssh\id_ed25519` ✅ 정상

---

**2026-06-03 (task #44~#58, 총 19개 PR 모두 main 머지 완료 — `7e64385` 기준)**:

사장님 사상 완전 구현 + critical fix + dead code 정리 + UI 강화 — 모두 머지 완료.

| PR | 핵심 | 사장님 의도/효과 |
|---|---|---|
| #55 | 크라이시스 UI 정확화 + SL 미발동 경고 | LABUSDT(#16) -161% 사고 원인 명확화 |
| #56 | 증거금/포지션 추가 → `total_capital` 자동 합산 | 사장님 청산 늦추기 노력 100% 보호 |
| **#57** | **🔴 SL 정책 = 투자금 대비 -80% (레버리지 무관)** | **사장님 명시 사상 정확 구현** — "투자금에 -80%일때 실행, 레버리지 상관없이" |
| #58 | 수정 모드 시작가 자동 현재가 | 옛 가격 stale → 트리거가/평단/청산가 현재가 기준 재계산 |
| #60 | 빈 단계 자동 압축 + trigger 누적 (PR #59 silent drop 대체) | 사장님 "4단계가 3단계가 되어 한단계식 당기면 되고, 3단계 trigger 10% 누적" |
| **#61** | **🚨 frontend testnet=true 하드코드 제거** (cm-preview.js + multi-symbol.js) | **사장님 mainnet 운영 중 testnet 가격 사용 사고 잠재 차단** |
| #62 | `_execute_crisis_action` dead code 정리 (91줄 → 26줄 NotImplementedError + docstring) | Stage 2 보호 미연결 명시, 미래 wire-up 정보 보존 |
| #63 | Pydantic 422 list detail 친절 파싱 (#18 후속) | 422 발생 시 어느 필드 invalid 명확 표시 (사장님 자동 진단) |
| #64 | 「전략 인스턴스」 카드 SL 한도 시각화 | 4단계 색상 (회/노/주/빨강) — 사장님 SL 발동 임박 즉시 인지 |
| #65 | 「전략 인스턴스」 카드 정렬 옵션 (7가지) | 🚨 SL 임박 / 손실 큰 순 등 — 사장님 위험 우선 확인 |
| #66 | `daily_summary_worker` 신설 (KST 00:00) | 매일 운영 요약 텔레그램 — 사장님 매일 아침 한눈에 |
| #67 | 「💼 거래소 계정」 모달 통합 표시 | 잔액/uPnL/활성/마진 — 다중 계정 비교 가능 |
| #68 | SL 진행률 80% Telegram 알림 | 사장님 화면 안 봐도 즉시 인지 — 자본 기준 (PR #57) |
| **#69** | **다중 Sub-Account 등록 폼 + 「전략 인스턴스」 계정 필터** | 모달 내 직접 등록 (Swagger UI 대체) — 사장님 다중 운영 시작 |
| **#70** | **🔒 HTTPS 자동 설정 (self-signed + Let's Encrypt)** | API key 평문 전송 차단 — `deploy/setup-https-*.sh` 스크립트 |
| #71 | 「최근 활동」 계정별 필터 | 다중 계정 운영 효율 (window._strategiesById 매핑) |
| #72 | 대시보드 잔액 카드 = 다중 계정 합산 | 모든 active 계정 병렬 호출 + tooltip 개별 |
| #73 | **🛡 API key 인증 정기 검증 (30분)** | 사장님 큰 사고 사전 차단 (만료/회수/IP 변경/-2014/-1003) |

**사장님 사상 완전 구현 검증**:
- ✅ 투자금 -80% 손실 시 청산 (레버리지 무관) — PR #57
- ✅ 증거금/포지션 추가 → SL 한도 자동 보호 — PR #56
- ✅ 모든 단계 진입 후만 SL 평가 (기존 정책 유지)
- ✅ 빈 단계 자동 압축 + trigger 누적 — PR #60
- ✅ 수정 시 현재가 기준 재계산 — PR #58
- ✅ 크라이시스 ≠ 손절 명확화 — PR #55
- ✅ SL 진행률 시각화 — PR #64

**silent bug 정리 (6-03)**:
- ✅ testnet=true 하드코드 (cm-preview / multi-symbol) — PR #61
- ✅ _execute_crisis_action dead code — PR #62
- ✅ 422 응답 list detail 파싱 (사장님 진단 도움) — PR #63
- ✅ 종합 검색 결과 = 추가 silent bug 0건 (TODO/FIXME/hardcoded 모두 청소)

**MYXUSDT (#9) 거래 검증 (6-02 운영 사례)**:
- 5단계 TP1~TP4 정상 발동, +24.76 USDT
- 「포지션 수량 불일치」 alert 3회 → PR #45 race fix
- trailing 정책 = TP3+ + stage>=3 + peak>=5% + retrace>=5%p (사장님 정책 유지 결정)

**LABUSDT (#16) 사고 분석 (6-03 핵심)**:
- 옛 strategy (PR #56/#57 적용 전) → 자본 추가 시 SL 한도 미갱신 → -210 USDT 손실
- 신규 strategy 부터 PR #56 + #57 적용 → 사장님 자본 노력 100% 보호

**사장님 운영 안전망 6-layer (6-03 마무리)**:
| Layer | Worker/Service | 주기/트리거 | 통보 |
|---|---|---|---|
| 1 | sync_health_monitor | 5분 | DB ↔ Binance 차이 |
| 2 | endpoint_health_monitor | 30분 | WS/ORDER/REST/mark-price/**API auth** |
| 3 | realized_pnl_sync_worker | 1분 | realized_pnl 정확화 |
| 4 | daily_summary_worker | 매일 KST 00:00 | 운영 요약 텔레그램 |
| 5 | _maybe_send_sl_progress_alert (TP/SL evaluate cycle) | SL 80% 도달 시 (1h dedup) | 사장님 즉시 인지 |
| 6 | **_check_account_auth** (endpoint_health 통합) | 30분 / 1일 dedup | **API key 만료/회수/IP 변경 즉시 알림** |

**다중 Sub-Account 운영 시스템 (6-03 완성)**:
- Binance Sub 한도: VIP 0 = 200개 (사장님 충분)
- VPS 효율 한도: **N = 10개** (CPU 80% 기준, 2vCPU/8GB)
- 등록 방법: 「💼 계정」 모달 「➕ 계정 추가」 폼 (Swagger UI 불필요)
- 자동 검증: PR #50 (Hedge mode + IP whitelist + Futures 권한)
- 다중 계정 UI:
  • 잔액 카드 = 모든 계정 합산 (PR #72)
  • 「💼 계정」 모달 = 잔액/uPnL/활성/마진 통합 (PR #67)
  • 「전략 인스턴스」 = 계정 필터 (PR #69)
  • 「최근 활동」 = 계정 필터 (PR #71)
- 안전망: 6-layer 자동 모든 계정 적용
- 사장님 작업: ① Sub-Account 2개 생성 + USDT 이체 → ② API key 발급 (IP 159.65.137.250) → ③ 모달 등록 → 자동 운영

**다음 세션 시작 시 우선순위**:
1. `git log --oneline main -10` 확인 → 6-03 마지막 main = `7e64385` (PR #73 API key auth monitor)
2. VPS 배포 확인 — `ssh root@159.65.137.250 "cd ~/binance-auto-trader/backend && git log --oneline -3"` → fe87cd1 면 최신
3. 사장님 화면 검증:
   - 새 strategy 만들기 → SL 미리보기 = "투자금 × 80% (레버리지 무관)" 확인
   - 빈 단계 입력 → 자동 압축 + trigger 누적 동작
   - 「전략 인스턴스」 카드 → SL 진행률 색상 표시
   - 모달 시작가 자동 현재가 (수정 모드)
4. 다음 우선순위 후보:
   - **#21** 메인 계정 「읽기 전용 모드」 추가 (사장님 통합 모니터링 — 큰 가치)
   - **#22** 심볼별 차트 + Order Book + 수동 거래 UI 통합
   - **#9** Sentry DSN 활성화 (사장님이 Sentry 계정 만든 후)
   - **#10** HTTPS 적용 (nginx + Let's Encrypt)
   - **#37** Virtual Sub → Normal Sub 마이그레이션 (사장님 결정 후)
   - 사장님 직접 발견한 운영 이슈
5. **사장님이 새 기능 만들 예정 (2026-06-03 마무리)** — 다음 세션 시작 시 사장님 명시 요구 들은 후 진행.
   - 사장님이 「추천」 시 우선순위 = #21 메인 계정 「읽기 전용 모드」

**LABUSDT (#16) 시점 미해결**:
1. `git log --oneline main -10` 확인 → 6-02 마지막 main = `0a3e30b` (silent except 로깅)
2. **미머지 4개 PR 처리 (사장님 GitHub 웹 UI 머지)**:
   - PR `feat/hedge-mode-auto-guard-on-account-create-2026-06-02` (#17)
   - PR `feat/activity-feed-type-filter-search-2026-06-02` (#16)
   - PR `feat/mark-price-stream-health-check-2026-06-02` (#14)
   - PR `feat/binance-changelog-monitor-boost-2026-06-02` (#33)
3. 머지 후 VPS 배포: `cd ~/binance-auto-trader/backend && git pull origin main && docker compose restart api scheduler`
4. VPS `docker compose ps` 확인 + scheduler 로그 `grep sync_health` 첫 알림 발송 검증
5. 사장님 화면 검증 — 「전략 인스턴스」 카드 아래 Binance 비교 행 + 「운영 통계 상세」 새 분류 카운트 + 「최근 활동」 type 필터
6. 다음 우선순위 후보:
   - **#21** 메인 계정 「읽기 전용 모드」 추가 (사장님 통합 모니터링)
   - **#22** 심볼별 차트 + Order Book + 수동 거래 UI
   - **#9** Sentry DSN 설정 (silent error 가시성)
   - **#10** 대시보드 HTTPS 적용 (보안)
   - **#15** testnet 잔재 정리 (Binance Demo 마이그레이션 후)
   - **#37** Virtual Sub → Normal Sub 마이그레이션
   - **#12** _execute_crisis_action dead code 정리
   - **#18** 템플릿 저장 422 fix (사장님 실제 재현 시나리오 + F12 Network 응답 필요)
   - 사장님 직접 발견 운영 이슈
7. 사장님 「추천으로 진행해줘」 시 → **#21 메인 계정 읽기 전용 모드** 진행 권장 (사장님 자주 사용할 운영 가치 큰 작업)

**오늘 17개 PR 진행 성과 (사장님 「추천으로 진행해줘」 패턴 자동 진행)**:
- 자동 모니터링 4개: sync_health / mark-price health / endpoint health / Binance changelog
- 데이터 정확성 4개: qty race fix / commission 차감 / reserved 보강 / polling+캐시
- UI 강화 6개: Binance 비교 (인라인+강조) / 심볼→차트 link / cache 영구해결 / TP/SL ROI / 활동 필터
- 안전성 3개: Hedge mode 자동 가드 / silent except 로깅 / 통계 분류 3-way

---

**2026-06-03 마무리 추가 (PR #74 + Neon DB 보안 회전, task #59 #60 완료)**:

**PR #74 — WebSocket URL path → query string 마이그레이션**:
- 트리거: `binance_changelog_monitor` (PR #54) 가 Binance WebSocket Change Notice 페이지 변경 자동 감지
- WebFetch 로 변경 내용 확인 → 신 권장 형식 `/private/ws?listenKey=<key>` (query string) 발견, 옛 형식 `/private/ws/<key>` (path) 도 계속 작동
- 사전 마이그레이션 (사장님 안전 마진): `binance_user_stream_consumer.py` line 63 = `f"{self.ws_base_url}/private/ws?listenKey={self.listen_key}"`
- VPS 배포 후 의심 (1시간 ORDER_TRADE_UPDATE 0건) → 사장님 sed rollback (path 형식 임시) → 진단 결과 거래 활동 자체 없음 (정상) 확인 → git checkout 으로 main (query 형식) 복귀 + restart 완료
- 최종 상태: VPS host 파일 = git main 100% 일치, user-stream = query 형식 정상 작동
- 검증: ORDER_TRADE_UPDATE 이벤트는 사장님 다음 거래 발생 시 자동 검증 (이상 시 즉시 sed rollback 가능 — 옛 path 형식도 검증된 작동)

**🚨 Neon DB credentials 긴급 회전 (보안 사고 즉시 대응)**:
- 사고: 진단 중 `docker compose exec api env | grep DATABASE_URL` 로 Neon connection string 평문 노출 (대화 + 학습 risk)
- 즉시 Neon Console (https://console.neon.tech/) → Reset password (2번 reset — 사장님 메모장 password 미스매치로 한 번 추가):
  - 옛 password 1: `npg_5zVX9lPSQZon` (대화 노출)
  - 옛 password 2: `npg_eY7bBnyWK2HD` (사장님 read -s 입력 시 화면 실수로 노출)
  - 새 password (현재 작동): 마스킹 (사장님 메모장 → .env)
- Connection pooling 토글 OFF + `channel_binding=require` 제거 = 옛 시스템과 100% 호환 형식 유지
- 변환: `postgresql://...&channel_binding=require` → `postgresql+psycopg2://...?sslmode=require` (prefix + 끝 정리)
- VPS .env nano 편집 + `docker compose up -d --force-recreate api scheduler user-stream` → 모든 컨테이너 정상 작동
- `.env.backup` 즉시 삭제 (옛 password 흔적 제거)
- 최종 검증: api `/health` = `{"status":"ok"}`, scheduler `Scheduler started`, user-stream `wss://...query 형식` 모두 정상

**사장님 작업 패턴 추가 인식 (다음 세션 참조)**:
- 사장님이 단순 한 줄 명령 안내가 가장 안전 — 복잡한 자동화 (sed/grep 파이프) 보다 nano 직접 편집 + 한 명령씩 안내가 사장님 이해 + 실수 방지 우선
- password 노출 risk: read -s 입력 후 사장님이 paste 시 다른 명령 실행됨 (read 가 password 받고 나머지가 셸 명령으로 실행되며 셸 prompt 가 password 로 오염) — 다음엔 read -s 대신 nano 편집만 안내
- sed 자동 명령 시 사장님이 잘못 복사하면 path 와 escape 문제 → 가능하면 nano + 수동 편집 권장
- Neon Console UI 친절히 단계별 (토글/Reset/Show/Copy/메모장) 안내 = 사장님이 정확히 따라할 수 있음

**다음 세션 시작 시 우선순위 (6-03 마무리 최종 update)**:
1. `git log --oneline main -10` 확인 → 6-03 마지막 main = `7e64385`(+ PR #74 머지 commit)
2. VPS 배포 확인 — `ssh root@159.65.137.250 "cd ~/binance-auto-trader/backend && git status"` → `working tree clean` 확인 (사장님 sed 변경 복귀됨)
3. user-stream URL = query 형식 확인 — `docker compose logs user-stream --tail=3 | grep "Starting Binance"` → `/private/ws?listenKey=...` 표시
4. 사장님 거래 발생 시 query 형식 자동 검증 — `docker compose logs user-stream --since 1h | grep ORDER_TRADE_UPDATE | head -3` 이벤트 보이면 OK
5. **사장님 직접 작업 대기**:
   - HTTPS 적용 (`bash deploy/setup-https-self-signed.sh` — PR #70 도구)
   - Sub-Account 추가 (2개 더 — 모달 등록)
   - 메모장 password 부분 삭제 (수동 보안 정리)
6. 다음 우선순위 후보 (사장님 결정):
   - **#21** 메인 계정 「읽기 전용 모드」 추가 (가장 추천)
   - **#22** 심볼별 차트 + Order Book + 수동 거래 UI 통합
   - **#9** Sentry DSN 활성화
   - **#37** Virtual Sub → Normal Sub 마이그레이션 (필요 시)

---

**2026-06-05 추가 (PR #75~#80 + HTTPS 적용 + 사장님 사상 옵션 A, main = `05fa463`)**:

**오전 (Binance docs 대응 + Neon DB password)**:
- `binance_websocket_change_notice` 페이지 변경 자동 감지 (PR #54 worker)
- WebFetch 분석 → mark-price-stream 의 옛 `/stream` endpoint = 차단 위험 발견
- PR #75 머지: `wss://fstream.binance.com/stream` → `/market/stream` (신 endpoint)
- VPS 배포 + force-recreate 시 mark-price-stream password 캐시 잔재 발견 → 모든 컨테이너 (api/scheduler/user-stream/mark-price-stream) force-recreate 완료

**오후 (잔액/마진 표시 명확화 + 사장님 사상 옵션 A)**:
- 사장님 「잔액 2110 의미 모호 + 포지션 진입 표현 이해 안 됨」 보고
- PR #76: 잔액 카드 큰 글씨 = 지갑 총액 (= "내 돈") + 수량/마진 컬럼 라벨 추가
- PR #77: 잔액 카드 3구간 분해 = 🔒 실 / 📦 예약 / 💵 자유 명확 표시
- PR #78: 「계획 마진」 표현 + ⚠️ 계획 초과 알림 (1차)
- PR #79+#80: **옵션 A — total_capital = 사장님 자본 (마진 단위)** 사상 정확 반영
  - 발견: backend = 이미 사장님 사상 정확 (PR #57 SL = `total_capital × sl_pct/100` = 자본 × 80% = 마진 × 80%)
  - UI plannedMargin 계산만 wrong (`sCap / sLev` → `sCap`)
  - 바이낸스 스타일 단순화: `수량 N / 마진 X / 자본 Y USDT (진입률 Z%)`
  - 거래 규모 (= 자본 × lev) = tooltip 으로만

**HTTPS 자동 적용 완료**:
- `sudo bash deploy/setup-https-self-signed.sh` 실행
- nginx 1.24 + self-signed 인증서 (10년 유효, CN=159.65.137.250)
- HTTP → HTTPS 자동 redirect + 보안 헤더 (x-frame-options 등)
- 사장님 접속 URL: **`https://159.65.137.250/admin-ui#dashboard`**

**미해결 (다음 세션 진단 우선)**:
- **Binance 비교 행 표시 안 됨** (PR #39 의 `_binanceCompareRow` 호출 X)
  - 진단 완료: backend OK + DB OK (exchange_account_id=1) + 코드 OK (grep 3회 매치)
  - 시크릿 모드에서도 안 보임 = 브라우저 캐시 X
  - 추정 원인: nginx static 파일 캐시 또는 JS 모듈 silent fail
  - 다음 세션: F12 Console 직접 진단 (`fetch('/api/v1/exchange-accounts/1/binance-positions')`) + DOM 강제 출력 PR 작성 가능

**사장님 작업 패턴 보강 (다음 세션 참조)**:
- 사장님이 코드 명령을 bash 에 paste 시도 (잘못 인식) → 사장님께 코드는 "코드" 표시로 안내 우선
- PR 머지 시점에 우리가 추가 commit push 가능 — 사장님이 1차만 머지 시 = 새 PR 작성 필요 (PR #79, #80 으로 분리)
- `total_capital` 정확한 의미: **사장님 입력 자본 = 마진 단위** (사장님 사상 PR #57 commit 메시지 명시) — backend 코드 + UI 모두 일치 필요

**다음 세션 시작 시 우선순위 (6-05 마무리 최종 update)**:
1. `git log --oneline main -5` 확인 → 최신 = `54e5c64` (PR #84)
2. VPS 배포 상태 확인 (HTTPS 작동 + 모든 컨테이너 Up)
3. **🧹 진단 박스 제거 PR 머지 안내** (사장님 미머지):
   - branch: `chore/remove-binance-compare-debug-box-2026-06-05`
   - URL: github.com/herosys1-crypto/binance-auto-trader/pull/new/chore/...
   - 머지 후 = 사장님 화면 우측 하단 디버깅 박스 사라짐
4. **사장님 직접 작업**:
   - EPICUSDT 자본 결정 (현재 1,860 그대로 vs ✏️ 수정으로 입금 1,000 USDT 반영)
   - Sub-Account 추가
5. 다음 우선순위:
   - **#21** 메인 계정 「읽기 전용 모드」 (큰 작업)
   - **#22** 심볼 차트 + Order Book + 수동 거래 UI

---

**2026-06-05 추가 (PR #82~#84 — 사장님 6-02 핵심 요구 마침내 해결!)**:

**오후 결정적 해결**:
- 사장님 6-02 부터 미해결: "포지션에 실 바이낸스 데이터 수시 가져와 표현"
- 코드 (PR #39) + DB + backend 모두 정상이었으나 사장님 화면에 안 보임
- PR #81: 진단 박스 (우측 하단 검정+초록 박스) 강제 추가 → 사장님 캡쳐 1번으로 원인 5분 만에 발견:
  - `🎯 fetch accountIds: [] | acc=undefined`
  - = backend `StrategyDetailResponse` schema 에 `exchange_account_id` 필드 누락!
- PR #82 머지: schema 1줄 추가 + changelog_monitor v2 통합 → **즉시 해결!**
- 사장님 캡쳐 검증 (15:57): `🪙 Binance: ✓ 일치 Size 19224 / Margin 144.66 USDT (ISOLATED) ...`

**자본 자동 동기화 (PR #84)**:
- 사장님 보고: "EPICUSDT 자금 추가했는데 시스템에 반영 X"
- 원인: PR #56 = 우리 시스템 통과 시만 적용. Binance UI 직접 추가 = 우회
- Fix: reconcile_worker (30초 주기) 에 자동 동기화 추가:
  - `binance_actual_margin = max(isolatedMargin, positionInitialMargin)`
  - `if binance_actual > DB total_capital × 1.05 + 차이 > 1 USDT`: DB 자동 갱신
  - RiskEvent (TOTAL_CAPITAL_AUTO_SYNC) audit log
- 사장님 EPICUSDT 케이스: Binance 1,421 < DB 1,860 = 갱신 X (정확)
- 미래 사장님 자본 추가 시 = 자동 보호

**changelog_monitor v2 (사장님 알림 부담 영구 제거)**:
- 6-05 오늘 같은 페이지 알림 3번 (05:10, 06:10, 12:26)
- v2 개선:
  - Dedup 24h: 같은 페이지 = 하루 1번만 알림
  - Diff 자동 추출: 이전 vs 신규 본문 라인 단위 (15줄씩)
  - 영향 자동 평가: `endpoint/listenkey/deprecat` 등 키워드 매칭 → ⚠️ vs ✓
- 사장님이 URL 안 가도 알림 메시지만 보고 우선순위 판단

**사장님 EPICUSDT 자본 결정 보류 (다음 세션)**:
- DB: 1,860 USDT (사장님 strategy 생성 시 입력)
- Binance 실 마진: 1,421 USDT (가격 변동 + 사장님 증거금 추가)
- 시나리오:
  - A — 그대로 유지 (보수)
  - B — Binance 실 마진 기준 (1,421)
  - C — 입금 1,000 USDT 일부 반영 (예: 2,860)
- 사장님 결정 후 ✏️ 수정 모드로 변경

**오늘 6-05 PR 총 14개 + Sentry 적용 + 미머지 1 (PR #89)**:
- #75 mark-price-stream `/market/stream`
- #76 잔액 카드 + 수량/마진 컬럼 명확화
- #77 잔액 카드 3구간 분해
- #78 「계획 마진」 표현
- #79 옵션 A (1차)
- #80 옵션 A (2차) + 바이낸스 스타일
- #81 진단 박스 (디버깅)
- **#82 changelog v2 + Binance 비교 행 fix (사장님 핵심 해결!)**
- #83 자본 자동 동기화 1차 (중복 머지)
- **#84 자본 자동 동기화 (사장님 노력 영구 보호)**
- #85/#86 진단 박스 제거 (중복 머지)
- **#87 TP 청산 = total_capital × 25% (v1, 사장님 의도 1차)**
- **#88 TP 청산 = max(DB, Binance isolated) × 25% (v2 사장님 명시 의도, 머지 대기)**

**🔔 Sentry 적용 + N+1 청소 완료 (PR #89 commits 2개)**:
- 사장님 Sentry 가입 (herosys1@gmail.com) + 프로젝트 `binance-auto-trader` (Python/FastAPI)
- Error monitoring 만 활성 (5K errors/mo 무료 한도 충분)
- VPS .env: `SENTRY_DSN`, `SENTRY_ENV=mainnet`, `SENTRY_TRACES_SAMPLE_RATE=0.1`, `SENTRY_PROFILES_SAMPLE_RATE=0.0`
- 모든 backend 컨테이너 force-recreate 후 = 사장님 테스트 메시지 정상 전송 ✅
- ⭐ **Sentry 적용 5분 만에 첫 silent issue 자동 발견!**
  - Issue: "N+1 Query" in `/api/v1/admin/recent-activity`
  - 원인: `monitoring.py` L228, L245 의 `r.strategy_instance.symbol` lazy load
  - 폴링 1회 (limit=20) = 21 쿼리 → 사장님 24h 폴링 = ~70만 추가 쿼리/일
- **PR #89 commit 1** (`b92fb0f`): `/recent-activity` N+1 fix (selectinload RiskEvent + Notification)
  - 쿼리 N+1 → 2 (95% 감소)
  - Sentry 가치 즉시 증명!
- **PR #89 commit 2** (`a9aa1f8`): `/notifications-by-title` 선제 fix (사장님 TP/TRAIL 카운트 클릭 endpoint)
  - 같은 패턴 backend grep → 추가 발견 → 선제 fix
  - Sentry 발견 전에 예방 청소
- backend `.strategy_instance.` grep 결과 = monitoring.py 만 N+1 hotspot (다른 endpoint = 깨끗)
- ⚠️ DSN 대화 노출 — 다음 세션에 회전 권장 (Sentry Settings → Generate New Key)

**TP 청산 = 사장님 명시 의도 (PR #87+#88)**:
- 사장님 메시지: "TP1 부터 익절은 포지션과 증거금 포함해서 전체금액에 25%씩 익절"
- "수동포지션과 증거금 추가한 금액모두를 기준"
- 옛: `current_qty × close_ratio` (qty 만 25%)
- 신: `max(qty 기준, capital_based)` 채택 + `capital_based = (effective_margin × ratio × lev) / avg_entry`
- `effective_margin = max(total_capital, latest_position.isolated_margin)` ← 사장님 의도 100%
- 사장님이 어디서 추가하든 (✏️ 수동 / Binance UI 직접) = 30초 내 자동 반영
- 사장님 EPICUSDT TP3 시뮬레이션: 청산 qty 1,132 → 2,394 (2.1배 ↑)

**오늘 진행 양 (압도적)**:
- 6-01: mainnet 진입 + 8 critical fix
- 6-02: 17개 PR
- 6-03: 20개 PR + Neon DB 회전
- **6-05: 11개 PR + HTTPS + 사장님 6-02 핵심 해결 + 자본 자동 동기화**

---

**2026-06-06 추가 (PR #100~#104 — EPICUSDT 진단 + 사장님 자본 보호 시스템 critical fix, main = `00b8147` + #105 HANDOFF 머지 대기)**:

**오전~오후 (EPICUSDT 미청산 의문 → 4가지 silent bug 발견)**:
- 사장님 EPICUSDT (#23) "TP3 진행 + -5% 하락 + 미청산" 의문 → 진단 시작
- docker compose exec python -c "..." stdout buffering 으로 0 라인 출력 (`-u` + `flush()` 도 무효)
- **PR #100** spec/crisis-mode-final: 사장님 사상 영구 보존 (CRISIS_MODE_FINAL_SPEC.md)
  - 사장님 명시: "TP1 tp2 tp3 일 실행되고 최고가 대비 -5% = 모든 포지션 청산. 다른 정책 없음"
  - 시스템 정상 TRAILING_TP 와 100% 동일 정책 (Crisis = TP threshold override 만)
  - DEAD CODE `_execute_crisis_action` / `_eval_crisis_mode_tp_sl` = 사장님 의도 X
- **PR #101** diagnostic endpoint: HTTP API 로 docker exec 우회
  - `GET /api/v1/admin/diagnostic/strategy/{id}` (인증 필요)
  - status / peak / crisis / trailing_conditions / trailing_should_fire 즉시 확인
- **PR #102** diagnostic v2: notifications + tp_orders + status_mismatch_check 추가

**진단 결과 (사장님 EPICUSDT #23)**:
- status = TP2_DONE_PARTIAL (TP3 미발동)
- max_profit_pct = 10.36% < TP3 임계 +15% = 미달
- redis_peak_pnl_pct = 10.36% ✅, current_pnl_ratio = -10.82%
- 시스템 = 정상 (TP3 발동 X → trailing armed X = 사장님 의도 만족)
- 다만 = notifications = 3건 (TP1 #198 6/4 + **TP1 #232 6/5** + TP2 #233 6/5)
- TP1 중복 발송 + UI 단순 카운트 → 사장님 「3/10 = TP3」 오해 → 의문 발생

**🚨 결정적 silent bug 발견 + fix (PR #103)**:
- `lifecycle.py` L411 의 audit log:
  ```python
  "close_order_id": str(close_order.get("orderId"))  # ← Order 모델 = dict 아님!
  ```
- = `close_order` 는 SQLAlchemy `Order` 모델 객체 → `.get()` 호출 시 AttributeError
- 흐름: 거래소 = 청산 성공 ✅ → DB audit log 시 unhandled exception → 500 → UI "실패" 표시
- = **사장님 Sub-Account 운영 = Manual TP 유일 청산 수단 = 단일 핵심 장애점**
- Fix: `close_order.exchange_order_id` + `close_order.status` + `executed_qty` + `avg_price` 직접 access
- 응답 message 강화: "Binance #orderId status=FILLED 체결=qty @ price" (사장님 즉시 검증)

**🛡 사장님 Sub-Account 청산 한계 인식 (critical)**:
- 사장님 지적: Binance 메인 웹 UI 에서 Sub-Account 포지션 직접 청산 불가능!
  (https://www.binance.com/en/futures/EPICUSDT = Main 계정만 보임)
- = 사장님 청산 수단 = 2가지뿐:
  1. 「💰 수동 익절」 모달 (우리 시스템)
  2. 자동 trailing TP (TP3 미발동 시 = 영원히 안 함)
- → 향후 모든 권장 = "Binance UI 직접 청산" 절대 X = 우리 시스템 의존 100%
- **PR #104**: 「💰 수동 익절」 버튼 재활성화 (PR #87 비활성화 → audit bug fix 완료 = 즉시 재활성화)

**사장님 검증 OK**:
- 「💰 수동 익절」 10% 시도 → 토스트:
  `Binance #1348272632 status=FILLED 체결=254.7 @ 0.61090590 ※ 1h 보호 활성`
- = 모든 검증 통과 + 거래소 청산 완료 + 사장님 즉시 검증
- **사장님 자본 보호 시스템 = 완전 복구** 🛡

**EPICUSDT 현재 상태 (사장님 결정 대기)**:
- qty = -2547.6 → -2292.9 (10% 청산 후)
- PNL = -77 USDT (-11.74% ROI)
- Margin = 661 / 2760 USDT
- 옵션: A(추가 청산 25/50/75/100%) / B(잔여 유지 + 시장 회복) / C(자본 추가 + 회복)

**오늘 6-06 PR 총 5개 (모두 머지) + HANDOFF (머지 대기)**:
- #100 docs(crisis): 사장님 크라이시스 모드 최종 사상 명확화
- #101 feat(diagnostic): /admin/diagnostic/strategy/{id} endpoint
- #102 feat(diagnostic): v2 — notifications + tp_orders + status mismatch
- **#103 🚨 fix(manual-tp): audit log silent bug — close_order.get → .attribute** (결정적)
- #104 fix(ui): 「💰 수동 익절」 버튼 재활성화 — Sub-Account 유일 청산 수단
- #105 (대기) docs: HANDOFF 2026-06-06 EPICUSDT MANUAL TP FIX

**다음 세션 시작 시 우선순위 (6-06 마무리)**:
1. `git log --oneline main -10` 확인 → 최신 = `00b8147` (+ PR #105 HANDOFF 머지 시 그 이후)
2. **사장님 EPICUSDT 결정** (A/B/C) 알려달라
3. **사장님 trailing 정책 결정**:
   - 현재 유지 (TP3 후 trailing — 사장님 사상 정확) → 다음 PR 없음
   - **TP1 후 trailing** (Sub-Account 청산 한정 = 더 안전) → PR 작성
4. **다음 세션 PR 우선순위 (사장님 결정 후)**:
   - ⭐⭐⭐ trailing armed = TP1 후 변경 (사장님 선택 시)
   - ⭐⭐ Admin emergency_close endpoint (안전망 — manual-tp fail 시)
   - ⭐ UI 익절 카운트 정확화 (DB status 기준 or distinct TP level)
   - TP1 중복 발송 원인 추적 (6/5 14:13 왜 TP1 다시?)
   - DEAD CODE 제거 + cleanup
   - **#21** 메인 계정 「읽기 전용 모드」 (기존 pending)

**진단 명령 (즉시 사용 가능)**:
- 대시보드 console F12: `api('/admin/diagnostic/strategy/{id}').then(r => console.log(JSON.stringify(r, null, 2)))`
- 반환: status / peak / trailing_conditions / notifications_tp / tp_orders / status_mismatch_check

**사장님 작업 패턴 추가 인식 (다음 세션 참조)**:
- 사장님이 markdown 의 주석 (`# ← 설명`) 을 bash 에 paste 시도 → syntax error
- → 다음엔 코드 블록 안에 주석 넣지 말기 + 정확한 명령만 별도 제공
- docker compose exec python -c "..." = stdout buffering 으로 0 라인 출력 (사장님 환경 일관 패턴)
- → HTTP API endpoint 가 가장 안전한 진단 수단

---

**2026-06-07 추가 (PR #109~#116 + HOTFIX critical + 개발 헌법 영구 보존, main = `0aa0f01`)**:

**오전 EPICUSDT 「↻ 설정만 수정」 500 → 2단계 fix**:
- 사장님 보고: 「↻ 설정만 수정」 = "설정 수정 실패: 500: Internal Server Error"
- 1차 진단: calculate_preview 의 None 필드 (start_price/total_capital/tp1-3/SL) 의심
- **PR #109** settings-update 방어 (1차): None 사전 검증 + try/except + logger.exception
- 사장님 = "같은 500 에러" → Sentry 확인 → **진짜 원인 1번 만에 발견**:
  - `IntegrityError: duplicate key value violates unique constraint "uq_strategy_templates_name"`
  - = template name 누적 `{old_name}_inplace_s{id}_{ts}` 5번 호출 시 = 120 chars 초과 = truncated → 같은 prefix → unique 위반
- **PR #110** template name 누적 fix (2차): regex `(_inplace_s\d+_\d+)+` 정리 + microsecond 추가
- 사장님 「↻ 설정만 수정」 = 다음 시도부터 정확 작동

**🚨 결정적 사고 (제 책임)**:
- 어제 PR (#108 auto-tp total_capital 차감) = `logger.info`/`logger.warning` 사용
- 옛 코드도 logger 사용 (L380/L398/L428) but try/except 안 silent
- 모듈 level `logger = logging.getLogger(__name__)` 정의 누락!
- → 어제 fix 가 = TP 청산 핵심 path 노출 → NameError 즉시 폭발
- → **모든 자동 TP 평가 실패** (06-07 07:04)
- → ALLOUSDT (#33) 외부 청산 트리거 (07:06, 거래소 자체 정리)
- → 사장님 자본 보호 시스템 = 실질 마비!
- 사장님 보고: "[시스템 오류] error=name 'logger' is not defined"

**🚨 HOTFIX 즉시 (PR #111~#115, 5번 중복 머지)**:
- `import logging` + `logger = logging.getLogger(__name__)` 1줄 추가
- 사장님 = 같은 PR 5번 머지 (GitHub Create PR 함정)
- 영향 0 (같은 commit = 동일 1줄 = 중복 무효)
- VPS 배포 후 = 자동 TP 평가 정상 재개

**사장님 명령 = 개발 헌법 영구 보존**:
사장님 명시: "메인넷 = 실 자금 = 이전 개발과 로직 검정 후 개발 + 문제 없게 코드 작성.
개발에 대한 정의를 하나 하자. 차후 개발에 적용할 정의를 만들어줘."

**PR #116** docs(principles) 신규 작성 (`DEVELOPMENT_PRINCIPLES_2026-06-07.md` 361줄):

5대 핵심 원칙 (절대):
1. 메인넷 = 실 자금 = 최우선 보호
2. 사장님 사상 = 코드보다 우선
3. Silent bug = 절대 금지
4. 검증 없는 코드 = 금지
5. 대칭성 검증 (양방향)

5가지 사고 패턴 (반복 금지):
- **Type Assumption** (ORM vs dict) — close_order.get() 사례
- **Missing Module-Level Definition** (logger 등)
- **Unbounded Accumulation** (template name 누적)
- **Asymmetric Policy** (PR #56 추가만)
- **Worker Conflict Unchecked** (사장님 의도 vs 자동 stage)

PR 작성 5단계 절차 (필수):
1) 사상 검증 (spec + 메모리)
2) 기존 코드 분석 (import + 정의 grep)
3) 변경 영향 분석 (silent fail + worker + 대칭성)
4) 코드 작성 (변수 정의 → 사용 + 타입 정확)
5) PR 전 grep 검증 (py_compile + import + logger)

5-layer 사장님 안전망:
1. 코드 작성 절차
2. CI 자동 검증
3. VPS smoke test
4. 배포 후 5분 silent 감지
5. 사장님 운영 확인 + Sentry

**미머지 PR 5건 (모두 헌법 5단계 검정 통과)**:
- `fix/manual-tp-deduct-total-capital-2026-06-06` (수동 익절 후 total_capital 차감)
- `fix/auto-tp-deduct-total-capital-2026-06-06` (자동 TP 후 차감 + COMPLETED 시 = 0)
- `fix/rename-free-to-available-2026-06-06` (「자유」 → 「운용 가용」)
- `fix/reserved-remaining-balance-2026-06-06` (「예약」 → 「예약(남은)」)
- `docs/handoff-2026-06-06-epicusdt-manual-tp-fix` (어제 HANDOFF)
- `docs/handoff-2026-06-07-development-principles` (오늘 HANDOFF, 신규 push)

**오늘 6-07 PR 총 9개 (머지 8 + HANDOFF 1 신규 push)**:
- #109 settings-update 방어 (1차)
- #110 template name 누적 fix
- #111~#115 HOTFIX logger × 5 (중복)
- #116 개발 헌법 (361줄)
- HANDOFF 2026-06-07 (신규 push)

**잠재 위험 (사장님 인지)**:
1. EPICUSDT total_capital = 2,760 (옛 값) — 정확값 1,863 (수동 익절 10%+25% 반영)
2. ALLOUSDT 외부 청산 (07:06) = 옛 자동 청산 = 사장님 손실 확인 필요
3. EPICUSDT 운용 가용 -32 USDT (예약 101%) = 신규 strategy 차단 (안전망 정상)

**제 책임 인정 + commitment**:
- 2026-06-05~07 = 5건 silent bug 야기
- 메인넷 실 자금 인식 부족
- 향후: 헌법 5단계 100% 적용 + grep 사전 확인 + 대칭성 검토 + Silent fail 절대 금지

**다음 세션 시작 시 우선순위 (6-07 마무리)**:
1. `git log --oneline main -5` 확인 → 최신 = `0aa0f01` (#116) + 신규 #117 HANDOFF 머지 시 그 이후
2. **미머지 PR 5건 = 1건씩 순차 머지** (헌법 5단계 적용 + 5분 silent 감지)
3. **EPICUSDT total_capital 동기화 결정**:
   - A. PR #107 머지 → 다음 자동/수동 TP 부터 자동 차감
   - B. PR #107 머지 + 사장님 「✏️ 수정」 → total_capital = 1,863 수동 입력
4. **ALLOUSDT 사고 분석** (사장님 손실 확인)
5. **#21 메인 계정 「읽기 전용 모드」** (큰 작업)
6. **CI 강화** (Layer 2) — `python -m py_compile` 자동

---

## 📌 MEMORY.md 인덱스에서 이관한 잔여 항목 (2026-08-26 인덱스 압축)

**6-11 시점 「다음 세션 우선순위」 중 위 본문에 없던 잔여**:
1. `max_profit_pct` null fix — 분석용 필드이며 **silent bug 아님** (오탐 주의)
2. `_resolve_close_reason` = STOPPED 분류 fix 필요
3. PR **#125** settings sync 미반영
4. **BANKUSDT** = 「헌법 효과 13건」 (6-08 누적) 중 1건 사례
5. EPICUSDT total_capital 1,863 해소 / ALLOUSDT 사고 분석 / #21 메인 계정 「읽기 전용 모드」 (상세 = 위 6-07 기록)

**헌법 18개 (6-11 시점 전체 목록)**: 메인넷 실자금 / 사장님 사상 우선 / silent bug 금지 / 검증 없는 코드 금지 / 대칭성 / 단일 진실 / 자동 검증 / silent 차단 알림 / TP audit / 운영자 우선 / 자동 현재가 / Crisis 영구 비활성 / 「수정 모드」 옛 세팅 보존 / 「현재가」 1단계 평단 + 2단계+ 누적 / spec single source / 코드↔spec 동기 / 에이전트 자동 / critical 즉시 spec 갱신

**기획서 10건 (영구)**: DEVELOPMENT_PRINCIPLES (헌법 ⭐) / CRISIS_MODE_FINAL / TP_TRAILING_LOGIC / CODE_OPTIMIZATION / SENTRY_MONITORING / TP1_THRESHOLD_OPTION / TRAILING_RETRACE_POLICY / STRATEGY_EDIT_LOGIC (v1+v2) / STRATEGY_EDIT_MODE_C (v1+v2) / SYSTEM_MASTER_SPEC (2026-06-08 마스터 통합 ⭐)

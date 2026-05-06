# HANDOFF — 2026-05-06 (집 → 사무실)

5-06 새벽~오전 동안 11개 PR 작업 (그 중 7개가 오늘 새 commit, 4개는 이전 세션에서 PR #1~#4 처리). 사무실에서 이어받기 위한 인계서. **branch: `main` (모든 PR 머지 완료, 추가 작업 branch 없음).**

---

## 📌 한 줄 요약

**5-06 세션 7개 PR (#5~#11) 모두 main 머지 완료.** 운영 통계 정확화 + UX 개선 + #96/#103 critical 사례 영구 방어 + **TP1~10 익절 10단계 확장 (사용자 요청)** + **24h/주/월 변동률 순위 검색 (사용자 요청)**. **alembic 0010 → 0012 production 적용**. 회귀 가드 329 → **377 passed** (+48). 시스템 안정.

---

## 🛠️ 5-06 세션 origin/main 에 들어간 7개 commit

```
fe00fda feat(market): symbols ranking endpoint + new-strategy modal integration (#11)
fa199ca feat(tp): TP1-10 take-profit stages (#10)
0620805 fix(risk): trailing TP fallback when Redis peak key volatile (#9)
aaaada2 feat(stats): clickable stats cells -> breakdown modal + autotranslate block (#8)
559ef95 feat(soft-delete): DELETE strategies -> archive (#7)
98f5dbb fix(ui): tiny-price start-price autofill + realized label autotranslate workaround (#6)
5adb538 fix(stats): strategy-based win rate + UI label clarity (#5)
```

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

### Backend
- `backend/alembic/versions/0011_strategy_instances_archived.py` — soft delete
- `backend/alembic/versions/0012_strategy_templates_tp6_to_tp10.py` — TP6~10 컬럼

### Tests (329 → 377, +48 신규)
- `test_admin_stats_winrate.py` (6) — 승률 strategy 단위
- `test_admin_stats_breakdown.py` (6) — 운영 통계 상세 endpoint
- `test_strategy_soft_delete.py` (7) — archive 동작
- `test_peak_pnl_redis_fallback.py` (7) — peak DB fallback
- `test_tp10_stages.py` (18) — TP1~10 확장
- `test_symbol_ranking_route_order.py` (4) — ranking endpoint route order

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
기대: **377 passed**

---

## 🎯 사무실에서 이어갈 작업 (우선순위 순)

### 우선순위 1: 신규 기능 운영 검증 (15분)
- 「📈 시장 순위」 클릭 → 13 period tab + 방향 toggle 모두 정상 작동
- 새 전략 모달 안에서 ranking → 「↑ 선택」 → 심볼/시작가 자동 채움
- TP1~10 default 채워진 새 strategy 시작 → TP10 까지 정상 progression

### 우선순위 2: 사용자 요청 #2 — "전체 로직 정리 검증"
사용자가 5-06 세션에 추가로 요청한 작업이지만 시간 부족으로 이연. 검증 범위:
- 익절 (TP1~10) — fix 후 점검
- 트레일링 (peak fallback 후 점검)
- 손절 (-50% capital)
- 크라이시스 모드 (5+ 단계 + -30%)
- 단계 진입 (auto + manual)
- 재진입 (auto_reentry_worker)
- 좀비 자동 정리 (zombie_guardian)
- 각 영역마다 spec (`SYSTEM-SPEC.md`) cross-check + 회귀 커버리지 확인.
- 추정 시간: 2-3시간

### 우선순위 3: scheduler 자동 사이클 verification (선택)
세션 중 일시적으로 #103 trailing 자동 발동 안 보이는 현상 발견. 결국 자가 회복했지만 lock TTL 20s + Interval 10s 의 ½ 빈도 + 일시적 mark price 변동이 원인일 가능성. 별도 확인 안 했으니 디버그 가치.

### 우선순위 4: mainnet 직전 보안 로테이션 (mainnet 가기 전 필수)
- `.env` Neon DB password
- SECRET_KEY / ENCRYPTION_KEY (단, 기존 데이터 영향 신중히)
- Telegram BOT_TOKEN

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

**작성: 2026-05-06 새벽 집 PC. 다음 작업: 사무실 Pull → 신규 기능 운영 검증 → 우선순위 2 (전체 로직 정리 검증) → mainnet 보안 로테이션.**

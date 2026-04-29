# 인계서 — 사무실 → 집 (2026-04-29 저녁)

> 오전 세션 인계서: `HANDOFF-2026-04-29-NEXT-SESSION.md`
> 이 문서: 오후 작업 누적 + 집 PC 진입 가이드

---

## 1. 집 PC 첫 진입 — 5분 동기화

집 PC 도착하시면 PowerShell 에서 순서대로:

### 1-A. 코드 최신화

```
cd C:\Users\user\바이낸스\binance-auto-trader
git pull origin main
```

이번 세션 누적 커밋 약 3~5건 자동 반영됩니다 (Bug #15 + UX #16~28).

### 1-B. NEON 비밀번호 동기화 ⚠️ 필수

사무실 PC 에서 NEON 비밀번호를 회전했습니다. 집 PC `backend/.env` 도 같은 비밀번호로 맞춰야 합니다.

새 비밀번호는 사무실에서 메모해둔 위치 (1Password 또는 임시 메모장) 에서 확인:

```
cd C:\Users\user\바이낸스\binance-auto-trader\backend
notepad .env
```

`DATABASE_URL=postgresql://neondb_owner:기존비밀번호@...` 의 비밀번호 부분만 새 값으로 교체. 호스트/DB명은 절대 건드리지 마세요.

저장 후 닫기 (Ctrl+S → 닫기).

### 1-C. 컨테이너 재기동

```
docker compose up -d --force-recreate api scheduler user-stream
```

10~20초 대기 후:

```
docker compose logs --tail 30 api
```

`Application startup complete` 확인. `password authentication failed` 가 보이면 .env 비밀번호 다시 확인.

### 1-D. NEON 연결 검증

```
docker compose exec api python -c "from app.core.database import SessionLocal; from app.models.exchange_account import ExchangeAccount; db = SessionLocal(); print('accounts:', db.query(ExchangeAccount).count()); db.close()"
```

`accounts: 2` 나오면 동기화 완료.

### 1-E. (선택) ngrok 외부 접속

집에서 모바일로도 접속하시려면:

```
ngrok http --url=morbidity-sleek-moocher.ngrok-free.dev 8000
```

새 PowerShell 창 띄워두고 유지. 로컬만 쓰시면 `http://localhost:8000/admin-ui` 로 직접.

---

## 2. 오후 (2026-04-29) 누적 변경

### 2.1 발견 + 수정한 critical 버그

| # | 버그 | 위치 | 상태 |
|---|---|---|---|
| 15 | -4164 notional too small (BTCUSDT min 50) | `create_quick_validation_templates.py` capital 100~300 으로 상향 | ✅ |

### 2.2 UX 개선 (대량)

| UX# | 내용 | 위치 |
|---|---|---|
| 16 | 시작가 자동 버튼 — 현재가/-0.1%/+0.1% 만 (이전 ±1/5/10% 제거) | `index.html` |
| 17 | 종료된 (대기 단계) 전략 🗑 삭제 버튼 + DELETE endpoint | `index.html` + `strategies.py` |
| 18 | 사이드별 기본 레버리지 (SHORT 2x / LONG 1x) + 별도 입력 필드 | `index.html` + `strategy_service.py` + `schema/strategy.py` |
| 19 | QUICK 정리 3-way 모드 (안전/cascade/**force**) — force 는 활성 전략 시장가 청산까지 | `admin.py` + `index.html` |
| 20 | 활성 전략 클릭 시 차트 + 단계가/평단/청산 가로선 표시 | `index.html` |
| 21 | 차트 1h/4h/1d 타임프레임 토글 + 청산예정가 가로선 | `index.html` |
| 22 | **TradingView Lightweight Charts 도입** — 캔들 + 줌/팬/Y스크롤 | `index.html` |
| 23 | 보조지표 **BB(20,2) / RSI(14) / MACD(12,26,9) / OBV** | `index.html` |
| 24 | 청산가 OOR 인디케이터 + 한 화면 fit (모든 패널) | `index.html` |
| 25 | 청산라인 항상 표시 (기본 ON) + 심볼 클릭 시 즉시 스크롤 | `index.html` |
| 26 | 청산예정가 = **체결분 기준 isolated 계산** + 🔄 새로고침 버튼 | `index.html` |
| 27 | 가격축 우측 → **좌측** 이동 (모든 4개 차트) | `index.html` |
| 28 | 청산 라인 굵기 4px (최대) | `index.html` |

### 2.3 인프라

- ✅ NEON 비밀번호 회전 (사무실 PC) — 보안 강화
- ⏳ 집 PC NEON .env 동기화 (위 1-B 단계에서)

### 2.4 Testnet 검증 진행 상황

- ✅ `_quick_5stage_short_validation`, `_quick_5stage_long_validation` 템플릿 등록
- ✅ Bug #15 수정 후 BTCUSDT SHORT/LONG 시작 성공
- ✅ Strategy #52 (SHORT) + #53 (LONG) Stage 1 진입 체결 확인
- ✅ Telegram "전략 시작" + "1단계 진입" 알림 정상
- ⏳ Stage 2~5 자동 트리거 검증 진행 중 (BTC 변동성 대기)
- ⏳ TP1~5 + SL 풀 사이클 검증

---

## 3. 시스템 현재 상태

### NEON DB
- `strategy_instances`: 활성 2건 (#52 SHORT, #53 LONG, 둘 다 BTCUSDT testnet)
  - **참고**: 더 추가하셨거나 #52 가 REENTRY_READY 일 수도 있음 — 진입 시 확인
- `strategy_templates`: 35+ (그 중 _quick_ 2개 활성)
- `exchange_accounts`: 2 (id=1 testnet active, id=2 비활성)
- `symbols`: 705 (TRADING 586)

### Git
- branch: `main`
- 최신 commit 은 push 완료 상태 (집 PC 에서 `git pull` 만 하면 됨)
- working tree 깨끗 (커밋 다 했음 가정)

### Docker (사무실 PC 기준 — 집 PC 도 동일 패턴)
- 8 containers 모두 Up (NEON 사용)
- `DATABASE_URL` NEON 가리킴 (.env 에서)

---

## 4. 다음 우선순위 작업

집 PC 에서 동기화 완료 후 진행 가능한 작업:

### A. 🔴 권장 — testnet stages 2~5 + TP/SL 라이브 검증 마무리

1. 대시보드에서 활성 전략 클릭 → 새로 만든 차트 (UX #20~28) 확인
2. BTC 변동성 모니터링 (1d/4h 타임프레임 차트)
3. 단계 자동 트리거 시 텔레그램 알림 도착 확인
4. TP1 (0.5%) 발동까지 모니터링
5. 전체 사이클 종료 후 **🔥 완전 정리 (force)** 로 일괄 청소

### B. 🟡 선택 — 집 PC 외부 접속 셋업

- ngrok 영구 도메인 (`morbidity-sleek-moocher`) 사용
- 또는 다른 ngrok 계정으로 별도 도메인

### C. 🟡 선택 — 메인넷 전환 준비

testnet 검증 완료 후:

- [ ] mainnet API 키 발급 (Binance 본 계정)
- [ ] exchange_accounts 신규 row 추가
- [ ] mainnet 잔고 충전 (작은 금액부터, 5~10 USDT)
- [ ] VPS 마이그레이션 (24/7 운영)
- [ ] 첫 mainnet 거래 검증

---

## 5. 새 차트 사용 가이드

전략 인스턴스 행 클릭 → **차트 카드** (자동 스크롤)

### 메인 차트
- 캔들 (1d 기본) + BB 보라 라인
- **좌측 가격축**: 가격 눈금 + 단계가/평단/청산 라벨
- 🟢 체결 진입가 (실선) / 🟡 예정 진입가 (점선) / 🔵 평단가 / 🔴 **청산예정가 (4px 굵은 점선)**
- 우상단 빨간 배지 "↑ 청산 X.XX" — 범위 밖일 때 (클릭 시 자동 포함)
- 헤더: "심볼 · 방향 · 레버리지 · 단계 · 캔들 수 · **청산예정 X (체결분 기준)**"

### 인터랙션
- 마우스 휠 = 줌
- 드래그 = 좌우 팬
- 가격축 (좌측) 드래그 = 위아래 Y 스크롤
- 호버 = 크로스헤어 + 가격/시간 표시

### 컨트롤 버튼
- **1h / 4h / 1d** 타임프레임 토글
- 🔄 **새로고침** — 단계 체결 후 평단/청산가 갱신용
- 📐 **청산가 포함됨 (끄기)** — 캔들 영역 확대하려면 클릭

### 보조지표 패널 (메인 차트 아래)
- 📊 RSI(14) — 30/70 기준선 (90px)
- 📈 MACD(12,26,9) — 라인 + 시그널 + 히스토그램 (100px)
- 📉 OBV — 누적 거래량 (90px)
- 모두 시간축 동기화 (메인 차트 줌하면 같이 움직임)
- 모두 좌측 가격축

---

## 6. 청산예정가 계산 공식 (체결분 기준)

```
SHORT: liq = avg_entry × (1 + 1/leverage - MMR)
LONG : liq = avg_entry × (1 - 1/leverage + MMR)

MMR (유지증거금율) = 0.005 (Tier 1 기본)
```

| 케이스 | 결과 |
|---|---|
| BTCUSDT SHORT 2x @ 77,089 | liq ≈ 77,089 × 1.495 = 115,238 |
| BTCUSDT LONG 2x @ 77,080 | liq ≈ 77,080 × 0.505 = 38,925 |
| SHORT 5x @ 100 | liq ≈ 100 × 1.195 = 119.5 |
| SHORT 10x @ 100 | liq ≈ 100 × 1.095 = 109.5 |

**거래소 cross-margin 청산가** (DB `liquidation_price`) 와 **isolated 계산** 이 10% 이상 다르면 헤더에 둘 다 표시됨.

다음 단계 체결 시:
1. 평단 변경 → 청산가도 자동 변경
2. 차트 헤더 우측 **🔄** 클릭 → 즉시 갱신
3. 또는 행 다시 클릭 → 자동 갱신

---

## 7. 자주 쓰는 명령 모음

### 활성 전략 확인
```
docker compose exec api python -c "from app.core.database import SessionLocal; from app.models.strategy_instance import StrategyInstance; db = SessionLocal(); rows = db.query(StrategyInstance).filter(~StrategyInstance.status.in_(['STOPPED','COMPLETED','CLOSED'])).all(); [print(f'#{r.id} {r.symbol} {r.side} {r.status} qty={r.current_position_qty}') for r in rows]; print('Total active:', len(rows)); db.close()"
```

### 거래소 실제 포지션 확인
```
docker compose exec api python -c "from app.core.database import SessionLocal; from app.integrations.binance.client import BinanceClient; from app.repositories.exchange_account_repository import ExchangeAccountRepository; from app.core.crypto import decrypt_text; db = SessionLocal(); acc = ExchangeAccountRepository(db).get(1); c = BinanceClient(api_key=decrypt_text(acc.api_key_enc), api_secret=decrypt_text(acc.api_secret_enc), is_testnet=acc.is_testnet); pr = c.get_position_risk(symbol='BTCUSDT'); pr = pr if isinstance(pr, list) else [pr]; [print(f\"{p['symbol']} {p['positionSide']}: amt={p['positionAmt']}\") for p in pr]; db.close()"
```

### 잔재 정리 (testnet 끝나고 한 방에)
대시보드 우하단 **"_quick_* 정리"** → **3 (force)** 입력 → 추가 confirm → 완료.

또는 PowerShell:
```
docker compose exec api python /app/cleanup_testnet_strategies.py
```

### 컨테이너 재시작
```
docker compose restart api
```

### 빠른 전체 재시작 (NEON 비밀번호 변경 후 등)
```
docker compose up -d --force-recreate api scheduler user-stream
```

---

## 8. 주의 사항

### ⚠️ NEON 비밀번호
- 양 PC `.env` 가 같은 비밀번호여야 함
- 채팅에 노출하지 말 것 (이번엔 회전했음)
- 1Password 또는 안전한 곳에 보관

### ⚠️ Mainnet 전환 전 필수
- testnet 풀 사이클 (stages 1~5 + TP1~5 + SL) 검증 완료
- VPS 24/7 가동 (또는 PC 항상 켜두기)
- 작은 금액부터 시작 (5~10 USDT)

### ⚠️ "🔴 완전 정리 (force)"
- testnet 에서는 안전
- mainnet 에서는 활성 전략의 실제 포지션을 시장가 청산 → 손실 확정 가능
- 클릭 전 추가 confirm 다이얼로그 있음 — 신중히

---

## 9. 다음 세션 시작 시 환영 멘트

"이어받았습니다. 사무실 PC NEON 회전 완료. 집 PC `.env` 비밀번호 동기화부터 진행하시고, 그 후 testnet stages 2~5 검증 / 메인넷 준비 / VPS 마이그레이션 중 어느 쪽으로 진행하시겠습니까?"

---

## 10. 파일 위치 빠른 참조

| 항목 | 경로 |
|------|------|
| 프로젝트 루트 | `C:\Users\user\바이낸스\binance-auto-trader\` |
| 환경 변수 | `backend\.env` (NEON URL) |
| 메인 UI 코드 | `backend\app\static\index.html` |
| 차트 함수 | `_renderDetailChart()` (Lightweight Charts) |
| 검증 템플릿 생성 스크립트 | `backend\create_quick_validation_templates.py` |
| 잔재 정리 스크립트 | `backend\cleanup_testnet_strategies.py` |
| 운영 매뉴얼 | `OPERATIONS.md` |
| 변경 이력 | `CHANGELOG.md` |
| 오전 인계서 | `HANDOFF-2026-04-29-NEXT-SESSION.md` |
| 이 인계서 | `HANDOFF-2026-04-29-OFFICE-TO-HOME-EVENING.md` |

---

작성: 2026-04-29 저녁 (사무실 PC)

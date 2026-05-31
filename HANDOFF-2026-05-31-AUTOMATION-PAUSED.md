# Handoff — 2026-05-31 자동매매 일시 정지 + 다음 환경 결정 대기

## 🎯 한 줄 요약

**Binance Demo API 의 -1109 차단 정책 + 사장님 환경에서 testnet.binancefuture.com 접속 불가 → 자동매매 일시 정지 (Redis ban + 활성 전략 5건 archive). 환경 결정되면 본 문서의 절차로 즉시 클린 재시작.**

---

## 📌 5-31 시점 상태 (변경 금지)

| 항목 | 값 |
|---|---|
| main HEAD | `53af9b4` (PR #32 머지) |
| VPS | `159.65.137.250`, 4 컨테이너 정상 작동 |
| scheduler | 🟢 실행 중 — Redis ban 으로 모든 워커가 account #1 호출 skip |
| 활성 전략 | **0건** (5건 archive 완료) |
| 누적 통계 | 79건 / 92.96% 승률 / -242.53 USDT realized (보존) |
| Redis ban TTL | 24h (5-31 16:xx 부터, 만료 시 spam 재개 주의) |
| Demo 측 포지션 | 5개 stuck (Binance demo 잠금 — 가상 USDT, 무해) |
| 실제 돈 손실 | 0원 |

### 5-31 진단 결과 (핵심)
1. 사장님 환경 = `demo.binance.com` (Binance Demo Trading)
2. Demo 의 공식 futures API endpoint = `demo-fapi.binance.com` (Binance 가 공식 명시)
3. **Demo API 는 모든 신규 주문을 -1109 "Invalid account" 로 차단** (정책상, 키 권한 무관)
4. Demo 웹 UI 자체도 5-31 시점 "Invalid account" 토스트 — 계정 server-side 잠김
5. `testnet.binancefuture.com` 은 사장님 한국망에서 접속 불가
6. 우리 시스템 코드는 정상 — endpoint 매칭 문제

---

## 🚀 환경 결정 후 클린 재시작 절차

### 경로 A. testnet via VPN (가상 돈, 가장 안전)

#### A-1. testnet 접속 확보
- Cloudflare WARP (무료 VPN) 설치 → 활성화
- `https://testnet.binancefuture.com/` 접속 시도
- 접속되면 회원가입 (testnet 전용) → faucet 으로 가상 USDT 받기

#### A-2. testnet API 키 발급
- testnet 페이지에서 API 키 생성
- 권한: **Enable Reading + Enable Futures** 둘 다 체크
- IP Access: Unrestricted (테스트라 단순화)
- **API Key + Secret Key 즉시 메모장에 둘 다 복사** (Secret 은 한 번만 표시!)

#### A-3. 대시보드에서 키 교체
- `http://159.65.137.250/` 로그인
- 「💼 계정」 → account #1 줄 「🔑 키 변경」
- prompt 1: 새 API Key 붙여넣기 → 확인
- prompt 2: 새 Secret Key 붙여넣기 → 확인
- prompt 3: **빈 칸** 또는 `testnet` → 확인 (testnet 환경 유지)
- 「✅ 키 회전 완료. 텔레그램 audit 발송됨」 알림 확인

#### A-4. Redis ban 해제 (자동매매 재개)
VPS 에서 한 번에:

```
docker compose exec -T redis redis-cli DEL "api_backoff:account:1:ban_until_ms" "api_backoff:account:1:notified"
```

#### A-5. 검증 (선택)
검증 스크립트 (아래 「검증 명령」 절) 실행 → `NEW KEY OK` 나오면 완료. 다음 cycle 부터 시스템 정상 동작.

---

### 경로 B. 메인넷 전환 (실제 돈 ⚠️)

> testnet 검증이 충분하다 판단되는 경우만. 실제 손실 가능.

#### B-1. 메인넷 .env 안전망 적용 (필수)
VPS `/root/binance-auto-trader/backend/.env` 에 모두 설정되어 있어야:
```
DAILY_LOSS_LIMIT_USDT=<자본의 10%>   # ★ 미설정=무제한 손실
MAX_CONCURRENT_STRATEGIES_PER_ACCOUNT=3
MAX_STRATEGY_CAPITAL_PCT_OF_BALANCE=5.0
ALLOWED_SYMBOLS_CSV=BTCUSDT,ETHUSDT
MAX_LEVERAGE=5
MIN_LIQUIDATION_DISTANCE_PCT=5
```
+ 대시보드 「💼 계정」 의 「🔒 심볼 화이트리스트 적용」 토글 ON

상세: `MAINNET-CHECKLIST.md`

#### B-2. ENCRYPTION_KEY 회전 (보안 권장)
`backend/scripts/rotate_encryption_key.py` 절차에 따라 회전.

#### B-3. 메인넷 API 키 발급
- `https://www.binance.com/` 로그인 → API Management
- 새 키 생성 — 권한: **Enable Futures Trading 만** (Spot 등 끄기 — 최소 권한)
- **IP Access: Restrict access to trusted IPs only** + VPS IP `159.65.137.250` 추가 (보안 강화)
- Secret 즉시 복사

#### B-4. 대시보드에서 키 교체 + 환경 전환
- 「💼 계정」 → 「🔑 키 변경」
- prompt 1: 메인넷 API Key
- prompt 2: 메인넷 Secret Key
- prompt 3: **`mainnet`** 입력 → 확인 (환경 전환)
- ⚠️ 환경 전환은 활성 strategy 0건일 때만 가능 — 현재 0건이라 OK
- 강한 확인 다이얼로그 → 진행 확인

#### B-5. Redis ban 해제
경로 A-4 와 동일.

#### B-6. 최소 자본 테스트 전략 1개로 시작
- 큰 자본 X. 일단 10~20 USDT 짜리 작은 strategy 1개 → 정상 작동 확인
- 텔레그램 알림 빠짐없이 오는지 확인
- 며칠 운영 후 자본 늘리기

---

## 🔧 검증 명령 (키 교체 + ban 해제 후 1회 실행 권장)

```
docker compose exec -T api python -c "
import requests, hmac, hashlib, time
from app.core.database import SessionLocal
from app.core.crypto import decrypt_text
from app.models.exchange_account import ExchangeAccount
from sqlalchemy import select
db=SessionLocal()
acc=db.execute(select(ExchangeAccount).where(ExchangeAccount.is_active.is_(True))).scalars().first()
ak=decrypt_text(acc.api_key_enc); sk=decrypt_text(acc.api_secret_enc); db.close()
BASE = 'https://testnet.binancefuture.com' if acc.is_testnet else 'https://fapi.binance.com'
ts=int(time.time()*1000)
qs=f'symbol=BTCUSDT&side=BUY&positionSide=LONG&type=LIMIT&quantity=0.001&price=10000&timeInForce=GTC&timestamp={ts}&recvWindow=5000'
sig=hmac.new(sk.encode(),qs.encode(),hashlib.sha256).hexdigest()
r=requests.post(f'{BASE}/fapi/v1/order?{qs}&signature={sig}',headers={'X-MBX-APIKEY':ak},timeout=10)
print('endpoint:', BASE, 'is_testnet:', acc.is_testnet)
print('status:', r.status_code, r.text[:200])
"
```

**기대 결과 판정**:
- ✅ `400 -4164 "Order's notional must be no smaller than 50"` → **거래 권한 OK** (단지 0.001 BTC × 10000 = $10 라 최소 명목가 미달이라 자연 reject). 시스템 자동매매 가능.
- ❌ `400 -1109 "Invalid account"` → 키 권한 문제 또는 환경 mismatch — 재확인
- ❌ `400 -2014/-2015` → 키 자체 무효 — 재발급
- 다른 에러 → 메시지 따라 조치

---

## 🛡 ban TTL 만료 임박 시 (환경 미정 + 24h 가까이 경과)

> ban TTL 만료되면 워커들이 다시 -1109 시도 → spam. **24h 안에 환경 결정 못 했으면** ban 갱신:

```
docker compose exec -T redis redis-cli SET "api_backoff:account:1:ban_until_ms" $(( ($(date +%s) + 86400) * 1000 )) EX 86400 && docker compose exec -T redis redis-cli SET "api_backoff:account:1:notified" "1" EX 86400 && echo "ban 24h 연장 완료"
```

> ⚠️ DEL 명령은 **환경 결정 후** 에만 (자동매매 재개 신호). 그 전에 누르면 spam 시작.

---

## 📂 추가 정보

### 데모 측 5개 stuck 포지션 처리
- Binance 측 demo 계정 server-side 잠김
- 우리 시스템·API 로는 청산 불가, demo 웹 UI 도 동일
- **가상 USDT — 무시해도 무해**
- demo 측 자체가 풀리면 (Binance 가 데모 환경 복구하면) 그때 웹에서 직접 정리
- 우리 DB 의 5개 strategy 는 이미 archive 됨 — 시스템 view 와 분리됨

### 코드 개선 후보 (시간 있을 때, 시급도 낮음)
- **-1109 영구 cooldown 가드**: 이전 -2019/-4131 와 같은 패턴. account 단위 1h 쿨다운 + 알림 1회 dedup. 향후 Binance 정책 변경/-1109 재발 시 자동 처리.
- **BinanceClient base_url 옵션 확장**: `is_demo` 같은 신규 옵션으로 `demo-fapi.binance.com` 지원 (Binance Demo 가 API 거래 허용하게 되면 즉시 사용 가능).

### 관련 파일/위치
- 메모리: `~/.claude/projects/.../memory/project_overview.md` (5-31 절 참조)
- api_backoff: `backend/app/core/api_backoff.py`
- 이전 핸드오프: `HANDOFF-2026-05-20-MARK-PRICE-LIVE-PNL.md`, `HANDOFF-2026-05-21-SAFETY-NETS.md`

---

## ✅ 체크리스트 (환경 결정 후)

- [ ] 새 환경 (testnet via VPN / 메인넷) 의 API 키 발급 — Secret 메모 즉시
- [ ] 메인넷이면: .env 안전망 6개 모두 적용 확인
- [ ] 대시보드 「🔑 키 변경」 으로 새 키 등록 — 환경 입력 (testnet/mainnet/빈칸)
- [ ] Redis ban 해제: `redis-cli DEL "api_backoff:account:1:ban_until_ms" "api_backoff:account:1:notified"`
- [ ] 검증 명령 실행 → `400 -4164` 확인 (notional 작아서 OK)
- [ ] (메인넷만) 작은 자본 (10~20 USDT) 테스트 strategy 1개 생성 → 정상 작동 확인
- [ ] Telegram 알림 흐름 확인 (heartbeat / 거래 알림 등)
- [ ] 며칠 운영 후 (메인넷이면) 자본 점진 증가

수고하십시오 🙌

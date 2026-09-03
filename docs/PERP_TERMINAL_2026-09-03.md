# 선물거래 터미널 (perp-terminal) — 2026-09-03

바이낸스 USD-M 무기한 선물 거래 터미널 화면을 **우리 서버에 실시간 API 로** 구축한 것.
시안(캔들 차트 + 호가 + 체결 + 주문 패널 + 포지션/미체결/주문/체결 탭)을 그대로 옮겼다.

접속 URL: **`https://<서버주소>/static/perp-terminal.html`**
(심볼 지정: `?symbol=SOLUSDT` — 없으면 마지막 선택 심볼, 그것도 없으면 `SOLUSDT`)

> 기본 심볼을 BTCUSDT 로 두지 않은 이유: BTCUSDT 는 Fix 303 자동매매 제외 목록에 있어
> 첫 화면부터 「제외 심볼」 경고가 떠서 오해를 산다.

---

## 1. 무엇을 만들었나 (파일 목록)

### 새 파일 (2개)

| 파일 | 크기 | 내용 |
|---|---|---|
| `backend/app/static/perp-terminal.html` | ~144 KB / 2,940줄 | 화면 전체 (HTML + CSS + JS 단일 파일) |
| `backend/app/api/v1/terminal.py` | ~72 KB | 터미널 전용 집계 엔드포인트 6개 |

### 기존 파일 수정 (4개 — 전부 최소 변경)

| 파일 | 변경 |
|---|---|
| `backend/app/api/router.py` | `terminal_router` import + `include_router` **2줄** |
| `backend/app/api/v1/market.py` | IP ban 가드(`_guard_ip_ban` / `_note_ip_ban`) 추가 |
| `backend/app/api/v1/exchange_accounts.py` | `binance-open-orders-summary` 에 ban 가드 + 캐시 |
| `backend/app/api/v1/admin/templates.py` | `cleanup-quick` 이 `TERMINAL_` 접두어도 정리 (아래 6절) |

기존 페이지(`index.html` 등)는 **한 줄도 건드리지 않았다.**

---

## 2. 아키텍처 — 왜 공개시세와 계정을 갈랐나

```
                 ┌──────────────────────────────────────┐
   브라우저 ─────▶│ wss://fstream.binance.com  (직결)     │  공개 시세
                 │  kline / depth20 / aggTrade /        │  = 서버를 안 거친다
                 │  markPrice / ticker                  │
                 └──────────────────────────────────────┘

                 ┌──────────────────────────────────────┐
   브라우저 ─────▶│ 우리 서버 /api/v1/terminal/*          │  계정 데이터
                 │   └─▶ 바이낸스 서명 API (API 키)       │  = 반드시 서버 경유
                 └──────────────────────────────────────┘
```

### 공개 시세 = 브라우저가 바이낸스 WebSocket 에 직결

**이유는 IP ban 이다.** 이 저장소는 2026-08-26 에 **Binance IP ban(418) 무한연장 사고**를
겪었다. 서버에서 공개 시세를 폴링하면 그 위험이 다시 커진다.
`market.py` 의 `/depth` 주석이 이미 정답을 적어 놓았다 —
「초기 fetch 후 = frontend = WebSocket 직접 연결」.

브라우저가 직접 붙으면:
- 서버 IP 부담 **0** (사용자 브라우저 IP 를 쓴다)
- 100ms 주기 호가를 서버 폴링으로 흉내 낼 필요가 없다
- 탭이 여러 개여도 서버 weight 는 늘지 않는다

초기 스냅샷 1회만 `/api/v1/market/*` 프록시로 받고, 그 뒤는 전부 WS 로 갱신한다.

### 계정 데이터(잔고·포지션·미체결) = 서버 API 로만

`/fapi/v2/account`, `/fapi/v2/positionRisk`, `/fapi/v1/openOrders` 는 전부 **서명 호출**이라
API 키가 필요하다. **브라우저에 키를 내려보내는 순간 끝**이므로 예외 없이 서버가 대신 부른다.
폴링 주기는 5~60초로 넉넉히 잡고, 서버에 Redis 캐시를 둬서 업스트림 호출을 묶었다.

### 부하 산정 (탭 1개 기준, 코드에서 산출)

| 경로 | 폴링 | 서버 캐시 | weight/분 |
|---|---|---|---|
| `/terminal/account` | 5초 | 15초 | 8 |
| `/binance-positions` | 5초 | 30초 | 10 |
| `/terminal/symbol-status` | 15초 | 30초(워커와 공유) | 0~80 |
| `/terminal/symbol-meta` | 30초 | 20초 | 6 |
| `/positions/external` | 60초 | 없음 | 5 |
| `/terminal/open-orders` | 5초/15초 | 5초/30초 | 12 (종목 지정) ~ 80 (전체) |
| **합계** | | | **≈ 121 ~ 191** |

Binance USD-M 한도는 **2,400 weight/분** → 탭 1개 ≈ 5~8%, 탭 5개여도 25~40%.

> 🚨 미체결은 「현재 종목만 보기」를 끄면 weight 가 **1 → 40 으로 40배** 뛴다.
> 그래서 서버 TTL(5초/30초)과 폴링 주기(5초/15초)를 **둘 다** 비대칭으로 걸었다.
> 하나만으로는 부족하다.

---

## 3. 엔드포인트 표

### 신설 — `/api/v1/terminal/*` (`terminal.py`)

| 경로 | 인증 | 폴링 | 무엇을 주는가 |
|---|---|---|---|
| `GET /terminal/capabilities` | **필요** | 1회(부팅) | 주문 경로가 살아 있는지. **거래소 호출 0** |
| `GET /terminal/account` | **필요** | 5초 | 지갑/마진 잔고, 미실현손익, 유지증거금, 증거금비율 |
| `GET /terminal/open-orders` | **필요** | 5초/15초 | 미체결 주문 + 취소 가능 여부 |
| `GET /terminal/symbol-status` | **필요** | 15초 | 진입 게이트 판정(제외 심볼·순위·24h) |
| `GET /terminal/symbol-meta` | ⚠️ **불필요** | 30초 | 틱/스텝/최소수량/최소명목, 펀딩, 미결제약정 |
| `GET /terminal/positions` | **필요** | — | 포지션+전략 조인. **🚨 현재 프런트가 안 쓴다 (7절)** |

### 재사용 — 기존 엔드포인트

| 경로 | 인증 | 폴링 | 용도 |
|---|---|---|---|
| `GET /market/klines` | 불필요 | 심볼 전환 시 1회 | 캔들 초기 스냅샷 |
| `GET /market/depth` | 불필요 | 1회 + 고장 시 15초 | 호가 초기 스냅샷 |
| `GET /market/ticker24h` | 불필요 | 1회 + 고장 시 15초 | 24h 통계 |
| `GET /exchange-accounts` | 필요 | 부팅 | 계정 목록 |
| `GET /exchange-accounts/{id}/balance` | 필요 | 폴백 | 잔고 (terminal/account 실패 시) |
| `GET /exchange-accounts/{id}/binance-positions` | 필요 | 5초 | 거래소 포지션 |
| `GET /strategies?include_archived=false` | 필요 | 10초 | 전략 목록(포지션 조인용) |
| `GET /positions/external` | 필요 | 60초 | 도구 밖 포지션 |
| `GET /orders?limit=200[&status_filter=FILLED]` | 필요 | 10초 | 주문/체결 탭 |
| `GET /symbols/{symbol}` | 필요 | 폴백 | 심볼 메타 (symbol-meta 실패 시) |
| `POST /admin/strategy-templates` | 필요 | 주문 시 | 주문 ① |
| `POST /strategies` | 필요 | 주문 시 | 주문 ② |
| `POST /strategies/{id}/start` | 필요 | 주문 시 | 주문 ③ |
| `POST /strategies/{id}/stop` | 필요 | 버튼 | 포지션 청산 |
| `DELETE /strategies/{id}/open-orders/{orderId}` | 필요 | 버튼 | 미체결 취소 |

### 브라우저 → 바이낸스 직결 (서버 무관)

```
wss://fstream.binance.com/market/stream       (결합, SUBSCRIBE)
wss://fstream.binance.com/market/ws/<stream>  (개별, 3회 실패 시 폴백)
  streams: <sym>@kline_<iv> / <sym>@depth20@100ms / <sym>@aggTrade
           / <sym>@markPrice@1s / <sym>@ticker
```
지수 백오프(1초~30초, jitter), 세대(gen) 번호로 옛 소켓 콜백 무효화,
탭 비활성 시 폴링·감시견 정지 + 복귀 시 재동기(최소 20초 간격) 구현됨.

---

## 4. 🚨 주문 발주 정책 — 왜 전략 경로를 태우는가

### 근거: 수동 진입이 전체 손실의 94.3%

실측 (2026-09-03):

| 구분 | 건수 | 손익 | 건당 |
|---|---|---|---|
| **수동 진입** | 791건 | **−13,401 USDT** | −16.94 |
| 자동 (BOTTOM 전략 제외) | 472건 | **+245 USDT** | +0.52 |

**수동이 손실의 94.3% 를 만들었다.** 그래서 이 터미널의 주문 버튼은
**거래소로 raw 주문을 직접 쏘지 않는다.**

### 3-콜 체인

```
①  POST /admin/strategy-templates      → TERMINAL_<시각>_<키4자> 일회용 템플릿
②  POST /strategies                    → 🚨 여기서 안전 게이트가 전부 걸린다
③  POST /strategies/{id}/start         → 1단계 주문 발송
```

②를 태우기 때문에 아래 안전장치가 **그대로 적용된다**:

- Fix 303 심볼 제외
- Fix 310 / 325 순위 게이트 (상승 50 + 하락 50 = 100개)
- Fix 327 지지선 7점 판정
- force SL (강제 손절)
- 부분 손절 (10 USDT 잔량 유지)
- 합의 게이트(confluence), 동시 보유 상한, 일일 한도

**raw `place_order` 는 이 전부를 우회한다.** 그래서 쓰지 않는다.

### 추가 안전장치

- **확인 모달 필수** — 심볼·방향·수량·금액·레버리지·예상청산가를 다시 보여주고
  「확인」을 눌러야 진행.
- **전송 직전 재검사** — 모달이 떠 있는 동안 제외 심볼로 바뀌거나 토큰이 만료될 수 있으므로
  `submitOrder` 자신이 마지막으로 한 번 더 게이트를 본다.
- **Idempotency-Key** — 3콜 각각에 모달 키 기반 키를 붙여 중복 발주를 막는다.
- **`/terminal/capabilities` 가 null 이면 주문 버튼 비활성** + 사유를 화면에 표시.
- ②가 막히면 ①에서 만든 템플릿을 **자동으로 지운다** (고아 방지, 아래 6절).

> 차단 사유(예 `[Fix310] …`)는 **가공하지 않고 그대로** 모달에 띄운다.
> 사장님이 「왜 막혔는지」를 나에게 물어야만 알 수 있는 상태로 두지 않기 위해서다.

---

## 5. 배포 방법 (사장님이 직접)

이 작업에서는 **배포·재시작·실주문을 일절 하지 않았다.**

```bash
ssh <VPS>
cd ~/binance-auto-trader
git pull
sudo systemctl restart api          # ⚠️ 서비스명은 api / scheduler (backend 아님)
```

정적 파일은 `_NoCacheStaticFiles` 라 **캐시가 안 걸린다** → 새로고침만으로 반영된다.
(`?v=` 갱신 불필요)

접속: `https://<서버주소>/static/perp-terminal.html`

### 배포 직후 확인 순서 (권장 — 거래소 호출이 적은 것부터)

1. `/api/v1/terminal/capabilities` — **거래소 호출 0**. 여기서 500 이면 코드 문제.
2. `/api/v1/terminal/symbol-status?symbol=SOLUSDT` — 게이트 판정.
3. `/api/v1/terminal/account?account_id=1` — 서명 호출 첫 검증.
4. **토큰 없이** `/api/v1/terminal/account` → **401 이 나오는지** 눈으로 확인.
5. 화면 열고: 호가가 흐르는가 / 「호가 지연」·「가격 지연」 배지가 계속 떠 있지 않은가.
6. 미체결 탭에 유형·상태·시각이 실제로 찍히는가.
7. 소액 1건으로 주문 3콜 체인을 끝까지 태워 본다.

배포 후 한 번은 `get_request_counts(5)` / `get_current_weight()` 로 실제 분당 weight 를
찍어 2절의 계산을 검증할 것. **2026-08-26 때도 추정이 아니라 Fix 118 실측이 원인을 갈랐다.**

---

## 6. 되돌리는 법

이 작업은 **새 파일 2개 + 기존 파일 4개 최소 수정**이라 되돌리기가 쉽다.

### 전체 되돌리기

```bash
cd ~/binance-auto-trader
git revert <이 커밋 해시>
sudo systemctl restart api
```

### 화면만 끄기 (가장 빠름 — 재시작 불필요)

```bash
mv backend/app/static/perp-terminal.html backend/app/static/perp-terminal.html.off
```
→ 즉시 404. 기존 화면·워커는 **전혀 영향 없다.**

### 엔드포인트만 끄기

`backend/app/api/router.py` 에서 아래 2줄을 지우고 `api` 재시작:
```python
from app.api.v1.terminal import router as terminal_router
api_router.include_router(terminal_router)
```

### 주문만 막기 (화면은 유지)

`/terminal/capabilities` 가 주문 불가를 반환하게 하면 CTA 가 자동으로 비활성화되고
사유가 화면에 뜬다. 화면을 지울 필요가 없다.

### 누적된 일회용 템플릿 정리

```
POST /api/v1/admin/strategy-templates/cleanup-quick?cascade=true
```
2026-09-03 부로 `_quick_` 뿐 아니라 **`TERMINAL_` 접두어도 함께** 정리한다.
`force=true` 는 영구 차단돼 있고(사장님 지시), **진행 중인 전략은 절대 건드리지 않는다**
(참조 전략이 있으면 삭제 대신 비활성화).

---

## 7. 남은 한계 · 다음 할 일

### 🚨 최우선 — 포지션 표가 두 곳에서 판정된다

`/terminal/positions` 는 **아무도 부르지 않는다.** 프런트는
`/binance-positions` + `/strategies` 를 받아 **프런트에서 조인**한다.
= 같은 판정(배지·단계·잔량·tracked 여부)이 서버와 프런트 **두 곳**에 있다.
이 저장소가 반복해서 당한 실패 방식이다.

둘 중 하나를 반드시 하라:
- **(A)** 프런트 `renderPositions` 를 `/terminal/positions` 로 옮기고 프런트 조인을 지운다 (권장)
- **(B)** `/terminal/positions` 를 지운다

실서버 검증 없이 (A) 를 하는 것이 더 위험해서 최종통합에서는 손대지 않았다.
`terminal.py:750` 에 같은 경고를 코드에도 남겼다.

### 실검증이 안 된 것 (배포·실주문 금지 제약)

- **서명 엔드포인트 4개**(`/terminal/account` · `/positions` · `/open-orders` · `/symbol-status`)는
  **한 번도 실호출로 검증되지 않았다.** 특히 `/fapi/v1/openOrders` 행 필드
  (orderId/clientOrderId/positionSide/stopPrice/executedQty/time)는 공개 경로가 아니라 실응답
  대조를 못 했다. 결손이면 **빈 칸**으로 나가지 조용히 0 이 되지는 않게 돼 있다.
- **주문 3-콜 체인은 페이로드 스키마 검증까지만** 했다. 소액 1건을 태워 봐야 확정된다.
- **인증 강제는 코드로만 확인**했다(FastAPI dependant 트리 전수). 실제 401 응답은 못 받아 봤다.
- **헤지/원웨이 모드 미검증** — 원웨이면 `positionSide=BOTH` 라 `positionAmt` 부호 폴백을 탄다.
  첫 배포 때 포지션↔전략 매칭이 어긋나지 않는지 눈으로 볼 것.
- 새 코드에 대한 **자동 테스트 없음**(요구 밖).

### 알려진 결함

- **`/exchange-accounts/{id}/binance-user-trades` 는 존재하지 않는다.**
  「현재 종목만 보기」를 켜면 체결 탭이 10초마다 404 를 받는다.
  화면은 죽지 않고 **우리 DB 의 FILLED 주문으로 폴백**하고 사유를 문구로 띄운다.
  없는 것을 임의로 다른 경로로 돌리면 표시 내용이 조용히 달라지므로 그대로 뒀다.
- **`/terminal/symbol-meta` 무인증** — 지시가 「공개 데이터는 market.py 와 같은 정책」이라
  유지했다. 형식 검증 + 심볼 화이트리스트 + 분당 40회 예산으로 증폭은 막았지만,
  외부인이 예산을 다 태우면 사장님 화면의 24h·펀딩·미결제가 전부 「모름」으로 뜬다.
  인증/IP rate limit 은 **사장님 판단 사항**. `market.py` 4개 route 도 같은 노출 상태다.
- **CSP 헤더가 없다.** `escapeHtml` 이 XSS 의 유일한 방어선이다. 근본 해결은 `/static` 응답에
  CSP 를 붙이는 것인데 기존 페이지 전체에 영향이 가서 이번 범위에서 안 했다.
- **Redis 가 죽으면 방어가 한꺼번에 사라진다.** Fix 117 티커 공유캐시도, Fix 124 weight
  카운터도, 터미널의 모든 캐시도 전부 Redis 기반이다. 그때 `/terminal/symbol-status` 는
  탭 1개당 160 weight/분이 된다. 근본 대응은 `client.py` 프로세스 로컬 폴백 캐시.
- **`market.py` 에 서버측 캐시가 없고 weight 회계도 없다**(ban 가드만 넣었다).
  Fix 124 거버너가 보는 누적 weight 는 실제보다 항상 적다.
- **토큰 수명 60분, 자동 갱신 없음** — 오래 열어 두면 401 배너가 반드시 뜬다(요구 밖).
- **예상 청산가는 근사식**이다(MMR 티어 테이블이 저장소에 없다). 화면·모달에 「근사」 라벨 있음.
- **확인 모달의 「수량」과 실제 체결 수량이 0.01% 수준으로 어긋날 수 있다.**
  서버로 가는 것은 `capital`(2자리 반올림)이고 수량은 서버가 `capital×leverage/price` 로
  되계산한다. 「보이는 값 = 보내는 값」은 **가격에만** 정확히 맞는다.
- **주문 템플릿 파라미터가 프런트에 하드코딩**돼 있다
  (`tp1/2/3_percent` 3/5/10, `stop_loss_percent_of_capital: 90`, `reentry_policy`, `trigger_mode`).
  보안 문제는 아니지만 **실자금 손절·익절 값**이라 사장님 확인이 필요하다.
- **WS 결합 스트림이 3회 연속 실패해 raw 폴백으로 넘어가면 세션 내내 폴백에 남는다**
  (네트워크가 회복돼도 결합으로 안 돌아온다). 소켓이 5개로 유지되는 것 외에 서버 부하는 없다.
- **포지션 행의 「미실현 손익」을 서버 값 대신 (표시가−진입가)×수량 으로 재계산한다.**
  펀딩비가 빠지고 마크 출처가 달라 바이낸스 앱 숫자와 어긋날 수 있다.
- **세로가 짧은 화면(1440×900 등)에서는 호가가 8+8행만 보인다.** 뷰포트 세로 ≥1081px 이면
  13+13 이 전부 보인다. 중간가는 항상 정중앙이고 잘리는 것은 먼 호가뿐이다.

### WS 스트림에 대한 정정 (중요)

앞선 검증에서 「`@depth20@100ms` 가 0건」으로 보고됐으나, **최종통합에서 정반대를 재현했다.**
같은 PC·같은 순간 계측:

| URL | 10초간 수신 |
|---|---|
| `/market/stream` + SUBSCRIBE | markPrice 10, kline 13, aggTrade 16, ticker 5, **depth20 0** |
| `/stream` + SUBSCRIBE | **depth20 93, 나머지 전부 0** |
| `/market/ws/btcusdt@aggTrade` | aggTrade 93 |
| `/ws/btcusdt@aggTrade` | **0** |

같은 순간 REST `/fapi/v1/aggTrades` 는 **0.6초 전** 체결을 돌려준다 = 시장은 살아 있다.
→ **어느 스트림이 도착하는지가 연결마다 다르다.** URL 은 정상이고 코드 결함이 아니다.
이 관측은 **개발 환경 망 특성**이며, 사장님 브라우저에서는 다를 수 있다.

**이 정정이 낳은 실제 수정**: depth 만 감시하던 것을 **가격계열까지** 감시하도록 넓혔다
(아래 8절). 어느 쪽이든 죽을 수 있다는 것이 실측으로 확인됐기 때문이다.

---

## 8. 최종통합에서 고친 것 (2026-09-03)

| # | 문제 | 수정 |
|---|---|---|
| 1 | **가격계열 스트림이 죽으면 녹색 불 뒤에서 현재가가 얼어붙는다.** depth 만 감시하고 있었다 | `priceWatchdog()` 신설 — 12초 침묵 시 연결 표시를 「가격 지연 N초」로 바꾸고 15초마다 REST 스냅샷으로 대체. 회복되면 자동 복귀 |
| 2 | 감시견이 부팅 직후 「지연」을 번쩍이고 스냅샷을 중복 호출 | `S.streamSince` 도입 — 한 건도 못 받았을 때는 **연결 시작 시각**부터 잰다 |
| 3 | `TERMINAL_` 템플릿을 지울 방법이 아예 없었다 (주문 1건당 1행 영구 누적) | `cleanup-quick` 이 `TERMINAL_` 접두어도 정리. 활성 전략 보호 로직은 그대로 적용 |
| 4 | 같은 초에 두 번 확인하면 템플릿 이름 충돌 | 이름에 모달 키 4자를 붙여 확인 1회당 유일 보장 |
| 5 | ①만 성공하고 ②가 막히면 템플릿이 **고아로 남는다** (게이트 차단은 자주 일어난다) | ② 실패 시 템플릿 자동 삭제. 실패해도 무시하고 ②의 차단 사유를 그대로 보여 준다 |
| 6 | `/terminal/positions` 가 죽은 코드인 줄 모르고 지나갈 수 있다 | 엔드포인트 docstring 최상단에 경고 + 다음 사람이 할 일 (A)/(B) 명시 |

### 검증 결과

- **Python 문법**: 변경된 5개 파일 전부 `ast.parse` 통과
- **JS 문법**: 인라인 스크립트 88,437자 `node --check` 통과
- **테스트**: `52 failed, 1714 passed` — 세 번 모두 같은 수
  ① 수정 전 우리 트리 ② 별도 worktree 로 뽑은 **깨끗한 baseline** ③ 수정 후 우리 트리.
  52건은 로컬에 `ENCRYPTION_KEY` 가 없어 `app.main` import 가 죽는 **환경 실패**다.
  유효한 Fernet 키를 넣고 다시 돌리면 그중 49건이 사라지고, 남는 3건
  (`test_strategy_status_constants` 2건 + `test_static_assets_integrity` 1건)은
  **baseline 에서도 똑같이 실패**한다(양쪽 `3 failed, 107 passed`). → **회귀 0건.**
- **`templates.py` 를 직접 고쳤으므로 별도 대조**: `-k "template or cleanup"`
  → 우리 트리 `9 failed, 51 passed` / baseline `9 failed, 51 passed`,
  **실패한 9건의 test id 까지 완전히 동일.**
- ⚠️ 검증 중 다른 세션이 같은 브랜치에 `Fix 328` 등 2개 커밋을 올렸다.
  위 ③ 실행은 그 커밋들을 **포함한** 상태이고 결과는 동일했다.
  다만 `Fix 328` 은 상수 4개만 선언되고 **아직 아무 데서도 쓰이지 않는다**(미완).
- **경로 대조**: 프런트가 부르는 22개 URL 전수 대조 →
  `binance-user-trades` **1건만 백엔드에 없음**(위에 기재, 폴백 동작 확인)
- **외부 응답 형태**: 공개 엔드포인트 4개를 실제 호출해 백엔드가 파싱하는 필드 전부 존재 확인
  (`ticker/24hr`, `premiumIndex`, `openInterest`, `depth` — 결손 0)

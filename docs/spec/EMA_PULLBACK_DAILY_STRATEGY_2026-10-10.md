# EMA 추세·눌림목 전략 (일봉) — 이식용 명세서

> 다른 자동매매 시스템에 그대로 옮겨 쓸 수 있도록 **판정 규칙·숫자·참조 구현·운영 규칙·검증 결과**를 한 파일에 담았다.
> 원본: binance-auto-trader Fix 423·424·425 (2026-10-09). 아래 참조 구현은 운영 코드(`app/services/ema_pullback.py`)와
> **코인 상위 25종목 일봉 16,554회 판정에서 신호 215건 포함 불일치 0건**으로 대조를 마쳤다 (2026-10-10).

---

## 1. 한 줄 요약

**일봉 기준으로 상승(하락) 추세가 살아 있고 EMA 10/20/50이 정배열(역배열)일 때, 가격이 EMA20·50까지 눌렸다가
거래량을 동반해 다시 추세 방향으로 마감하면 진입한다. EMA20에서 너무 멀리 달아난 날은 쫓지 않는다.**

| 항목 | 값 |
|---|---|
| 판정 봉 | **일봉(1D) 완성봉만** — 진행 중 봉으로 진입 판정 금지 |
| 방향 | LONG / SHORT 양방향 (추세 필터가 한쪽만 허용) |
| 대상 | **코인 무기한 선물만** (주식·금·원유 등 TradFi 제외) |
| 판정 시각 | 일봉 마감 직후 하루 1회 (바이낸스 = UTC 00:00 + 수 초 정착 여유) |
| 손절 | 최근 10봉 박스 저점(SHORT 는 고점) |
| 익절 | 원본 규칙에 없음 — 검증은 2R 고정으로 했다 (§7) |

---

## 2. 원본 규칙 (출처 YAML, 요지)

```yaml
Trend_Filter:
  - Price > EMA20 and EMA20 slope UP   → Bias = LONG ONLY
  - Price < EMA20 and EMA20 slope DOWN → Bias = SHORT ONLY
Entry_Triggers:
  - EMA alignment (10 > 20 > 50)
  - Wait for pullback to EMA20 / EMA50
  - Verify Volume support
  - Execute upon candle close confirmation
Risk_Management:
  - Stop Loss: below recent consolidation low (macro: EMA200 breakdown)
  - Scale up 30–50% only when EMA + Fibonacci + Volume converge
```

원본에 숫자가 없는 곳은 아래 §4 표처럼 정했다 (전부 파라미터로 바꿀 수 있다).

---

## 3. 진입 신호 판정 (LONG 기준, SHORT 는 전부 반대)

`j` = 방금 닫힌 일봉, `c/h/l/v` = 종가·고가·저가·거래량, `E10/E20/E50` = 종가 EMA.

| # | 조건 | LONG 식 | SHORT 식 |
|---|---|---|---|
| ① 추세 | 가격이 EMA20 위 + EMA20 상승 | `c[j] > E20[j]` 그리고 `E20[j] > E20[j-3]` | `c[j] < E20[j]` 그리고 `E20[j] < E20[j-3]` |
| ② 정배열 | EMA 10 > 20 > 50 | `E10[j] > E20[j] > E50[j]` | `E10[j] < E20[j] < E50[j]` |
| ③ 눌림 | 최근 5봉(오늘 포함) 안에 저가가 EMA20 또는 EMA50 의 +0.2% 이내까지 내려옴 | `any(l[i] ≤ E20[i]×1.002 or l[i] ≤ E50[i]×1.002)` | `any(h[i] ≥ E20[i]×0.998 or h[i] ≥ E50[i]×0.998)` |
| ③ 유지 | 그 5봉 동안 종가가 EMA50 −0.2% 아래로 안 감 | `all(c[i] ≥ E50[i]×0.998)` | `all(c[i] ≤ E50[i]×1.002)` |
| ③ 확정 | 오늘 종가가 EMA20 위 + 어제 종가보다 위 | `c[j] > E20[j]` 그리고 `c[j] > c[j-1]` | `c[j] < E20[j]` 그리고 `c[j] < c[j-1]` |
| ④ 거래량 | 오늘 거래량 ≥ 직전 20봉 평균 × 1.2 | `v[j] ≥ 1.2 × mean(v[j-20 : j])` | 같음 |
| ⑤ 추격 금지 | 오늘 종가가 EMA20 에서 10% 안 | `(c[j]−E20[j]) / E20[j] × 100 ≤ 10` | `(E20[j]−c[j]) / E20[j] × 100 ≤ 10` |

**진입 신호 = ① ∧ ② ∧ ③(눌림·유지·확정) ∧ ④ ∧ ⑤.** 진입가 = 신호 봉 종가(또는 다음 봉 시가).

- ⑤ 는 운영 첫날 실제로 생긴 문제(5일 안에 EMA 에 닿은 뒤 폭등해 종가가 EMA20 의 2배인 날도 신호)를 막으려 추가했다.
- EMA200 은 판정에 쓰지 않는다 — 기록만 한다 (상장 200일 미만 코인도 판정 가능).

### 손절
- LONG: 최근 10봉(오늘 포함) 최저가 / SHORT: 최근 10봉 최고가
- 진입가 대비 손절폭(가격 %)은 **0.3% ~ 15% 로 자른다** (너무 좁으면 스프레드에 죽고, 너무 넓으면 15% 로 묶음)
- 일봉 박스라 손절폭이 넓다 — 검증에서 평균 약 11% (§7)

### 증액(30~50%) — ⚠️ 아직 쓰지 말 것
원본은 「EMA + 피보나치 + 거래량이 겹칠 때만 30~50% 증액」. 겹침 정의:
최근 40봉 스윙 고저 대비 눌림 깊이가 **0.382 ~ 0.618** + 거래량 확인 + 정배열.
**검증 결과 겹친 신호가 오히려 성과가 같거나 나빴다**(§7) → 원본 시스템도 기록만 하고 증액 주문은 내지 않는다.

---

## 4. 파라미터 (기본값)

| 이름 | 기본 | 의미 | 출처 |
|---|---|---|---|
| `slope_bars` | 3 | EMA20 기울기 = 오늘 vs N봉 전 | 정함 |
| `touch_bars` | 5 | 눌림 확인 창 (봉) | 정함 |
| `touch_tol_pct` | 0.2 | EMA 터치 허용 오차 (%) | 정함 |
| `vol_mult` | 1.2 | 거래량 배수 | 정함 |
| `vol_n` | 20 | 평균 거래량 창 | 정함 |
| `box_bars` | 10 | 손절 박스 (봉) | 정함 |
| `max_ext_pct` | **10** | 추격 금지: 종가-EMA20 거리 상한 (%) | 운영자 결정 |
| `fib_bars` | 40 | 증액 판단 스윙 (기록 전용) | 정함 |
| `ready_near_pct` | 2 | 진입 준비 구간 (%) | 정함 |
| 최소 봉 수 | 65 | 이보다 적으면 판정 안 함 | 계산 |

> EMA 계산: **시작값 = 첫 종가**, `k = 2/(n+1)`, `EMA[t] = EMA[t-1] + k×(c[t] − EMA[t-1])`.
> SMA 로 시드하는 라이브러리(TA-Lib 등)를 쓰면 초기 구간 값이 달라 신호가 미세하게 어긋날 수 있다 — 이식할 때 맞춰라.

---

## 5. 진입 준비 알림 (사람이 직접 매매할 때)

진입 신호(마감 확정)가 나기 **전에**, 눌림이 진행 중인 종목을 알려 준다. 주문은 내지 않는다.

- 조건: 어제까지(완성봉) **① 추세 ∧ ② 정배열**이 맞고, **오늘 진행 중 봉의 현재가**가
  - LONG: `E20 × (1 − 0.002) ≤ 현재가 ≤ E20 × (1 + 0.02)` 그리고 `현재가 > E50`
  - SHORT: `E20 × (1 − 0.02) ≤ 현재가 ≤ E20 × (1 + 0.002)` 그리고 `현재가 < E50`
- 주기: 15분마다 확인, **같은 종목·방향은 하루 1번만** 알림
- 함께 보내는 정보: 현재가, EMA20 과의 거리(%), 손절 후보(최근 10봉 저점·고점)
- 진입 신호 알림은 일봉 마감 직후 봉당 1번

---

## 6. 운영 규칙 (원본 시스템 설정)

| 항목 | 값 | 이유 |
|---|---|---|
| 대상 종목 | 24h 거래대금 상위 60 중 **코인 무기한만** (바이낸스 `underlyingType == COIN`, `contractType == PERPETUAL`) | 주식·금 무기한(`TRADIFI_PERPETUAL`)이 거래대금 상위에 섞여 들어온다 |
| 증거금 | 1회 10 USDT · 레버리지 2 | 검증 전 최소 금액 |
| 2% 룰 | 한 거래 최대 손실 ≤ 총자산 × 2% (손절폭으로 증거금 상한) | 손절폭이 넓은 일봉 전략에 필수 |
| 동시 보유 | 이 전략 전용 최대 2개 | |
| 1회 진입 | 같은 종목 보유 중이면 신호 무시 · 추가 매수 없음 | |
| 재진입 쿨다운 | 같은 종목 20시간 | 다음 날 신호는 허용(판정 시각 흔들림 여유) |
| 판정 데이터 | 완성봉만 · 마지막 완성봉이 「지금 기준 직전 봉」이 아니면(묵은 응답) 판정 안 함 | 거래소 지연 응답으로 옛 신호를 새 신호로 보는 사고 방지 |
| 기본 모드 | **그림자(신호만 기록) → 검증 뒤 실주문** | §8 |

---

## 7. 검증 결과 (공개 시세 백테스트)

조건: 바이낸스 USDT-M 코인 무기한, 거래대금 상위 60종목, 일봉 최대 1,500봉(상장 짧으면 그만큼),
진입 = 신호 봉 종가, 손절 = §3 손절(0.3~15% 클램프), **익절 = 2R**, 최대 30봉 보유 뒤 종가 청산,
같은 봉에 손절·익절 둘 다 닿으면 손절로 처리(보수적), **수수료·슬리피지 미반영**.

| | 신호 | 승률 | 평균 | 연도별 평균 |
|---|---|---|---|---|
| **LONG** | 559 | 42% | **+0.19R** | 2023 +0.25 · 2024 +0.38 · **2025 −0.14** · 2026 +0.16 |
| **SHORT** | 853 | 40% | **+0.05R** | 2023 −0.26 · 2024 +0.20 · 2025 +0.24 · 2026 −0.03 |
| 평균 손절폭 | | | 11.4% | |
| 겹침(증액 후보) | LONG 329 · SHORT 441 | | LONG +0.15R · SHORT −0.05R | 증액 근거 없음 |

비교 (같은 규칙을 다른 봉으로):
- **15분봉**: 40종목 15.6일 LONG −0.03R · SHORT −0.05R → 일봉이 낫다
- 추격 금지(⑤)·코인만 적용 전: LONG 1,110건 +0.19R(2025 −0.28) · SHORT −0.01R → 적용 뒤 신호 절반, 손실 해 완화

⚠️ 해석할 때:
1. **생존 편향** — 「지금」 거래대금 상위 종목만 골랐다. 사라진 코인이 빠져 LONG 이 유리하게 나온다.
2. **장세 의존** — LONG 은 2025년 손실. 한 장세만 좋은 규칙일 수 있다.
3. **수수료 미반영** — 평균 +0.05R 수준(SHORT)은 수수료·펀딩비를 빼면 본전 이하일 수 있다.
4. 손절폭 평균 11% → 2% 룰을 지키면 포지션이 작아진다.

---

## 8. 이식할 때 권장 절차

1. 아래 참조 구현을 그대로 옮기고, **자기 시스템의 EMA 함수와 값을 대조**한다(시드 방식).
2. 처음 2주 이상은 **그림자(신호만 기록)** — 신호 날짜·종목·방향·진입가·손절가·confluence 를 남긴다.
3. 그림자 성과를 §7 과 비교: LONG 평균이 수수료 후에도 플러스인지, 연속 손실 길이가 감당 가능한지.
4. 실주문은 **LONG 만, 최소 금액**부터. SHORT·증액은 그 뒤 따로 판정.

---

## 9. 참조 구현 (Python 3, 외부 라이브러리 없음)

입력: **완성된 일봉만** 담은 리스트 `o, h, l, c, v` (오래된 → 최신). 마지막 원소 = 방금 닫힌 일봉.

```python
"""EMA 추세·눌림목 (일봉) — 독립 참조 구현. 외부 라이브러리 없음. 입력은 완성된 일봉만."""

PARAMS = {
    "slope_bars": 3,        # EMA20 기울기: 오늘 vs 3봉 전
    "touch_bars": 5,        # 최근 5봉 안에 EMA20/50 터치
    "touch_tol_pct": 0.2,   # 터치 허용 오차 %
    "vol_mult": 1.2,        # 확정봉 거래량 ≥ 직전 20봉 평균 × 1.2
    "vol_n": 20,
    "box_bars": 10,         # 손절 = 최근 10봉 저점(SHORT 고점)
    "fib_bars": 40,         # 증액 판단용 스윙 구간
    "max_ext_pct": 10.0,    # 확정봉 종가가 EMA20 에서 10% 안
    "ready_near_pct": 2.0,  # 진입 준비 = 현재가가 EMA20 의 +2% 안 (SHORT 는 −2%)
}


def ema(values, n):
    """시작값 = 첫 종가 (SMA 시드 아님). k = 2/(n+1)."""
    k = 2.0 / (n + 1)
    out = [float(values[0])]
    for x in values[1:]:
        out.append(out[-1] + k * (float(x) - out[-1]))
    return out


def min_bars(p=PARAMS):
    return max(60, p["fib_bars"], p["box_bars"], p["vol_n"], p["touch_bars"], p["slope_bars"]) + 5


def signal(o, h, l, c, v, side, p=PARAMS):
    """마지막 봉(= 방금 닫힌 일봉)에서 진입 신호인가. 반환 (bool, detail)."""
    j = len(c) - 1
    d = {"trend": False, "align": False, "pullback": False, "volume": False, "near": False,
         "stop": None, "ext_pct": None, "vol_ratio": None, "fib": None, "confluence": False}
    if side not in ("LONG", "SHORT") or j < min_bars(p) - 5:
        return False, d
    e10, e20, e50 = ema(c, 10), ema(c, 20), ema(c, 50)
    sb, tb, tol = p["slope_bars"], p["touch_bars"], p["touch_tol_pct"] / 100.0
    L = side == "LONG"
    a = j - tb + 1
    if L:
        d["trend"] = c[j] > e20[j] and e20[j] > e20[j - sb]
        d["align"] = e10[j] > e20[j] > e50[j]
        touched = any(l[i] <= e20[i] * (1 + tol) or l[i] <= e50[i] * (1 + tol) for i in range(a, j + 1))
        held = all(c[i] >= e50[i] * (1 - tol) for i in range(a, j + 1))
        confirm = c[j] > e20[j] and c[j] > c[j - 1]
        d["stop"] = min(l[j - p["box_bars"] + 1:j + 1])
        d["ext_pct"] = (c[j] - e20[j]) / e20[j] * 100
    else:
        d["trend"] = c[j] < e20[j] and e20[j] < e20[j - sb]
        d["align"] = e10[j] < e20[j] < e50[j]
        touched = any(h[i] >= e20[i] * (1 - tol) or h[i] >= e50[i] * (1 - tol) for i in range(a, j + 1))
        held = all(c[i] <= e50[i] * (1 + tol) for i in range(a, j + 1))
        confirm = c[j] < e20[j] and c[j] < c[j - 1]
        d["stop"] = max(h[j - p["box_bars"] + 1:j + 1])
        d["ext_pct"] = (e20[j] - c[j]) / e20[j] * 100
    d["pullback"] = touched and held and confirm
    base = v[j - p["vol_n"]:j]
    avg = sum(base) / len(base)
    if avg > 0:
        d["vol_ratio"] = v[j] / avg
        d["volume"] = d["vol_ratio"] >= p["vol_mult"]
    d["near"] = d["ext_pct"] <= p["max_ext_pct"]
    fb = p["fib_bars"]
    hi, lo_ = max(h[j - fb + 1:j + 1]), min(l[j - fb + 1:j + 1])
    if hi > lo_:
        depth = (hi - min(l[a:j + 1])) / (hi - lo_) if L else (max(h[a:j + 1]) - lo_) / (hi - lo_)
        d["fib"] = depth
        d["confluence"] = 0.382 <= depth <= 0.618 and d["volume"] and d["align"]
    ok = d["trend"] and d["align"] and d["pullback"] and d["volume"] and d["near"]
    return ok, d


def ready(o, h, l, c, v, live, side, p=PARAMS):
    """진입 준비: 어제까지(완성봉) 추세·정배열 OK + 오늘 현재가(live)가 EMA20 근처. 알림 전용."""
    _ok, d = signal(o, h, l, c, v, side, p)
    if len(c) < min_bars(p) or not live or live <= 0:
        return False
    e20, e50 = ema(c, 20)[-1], ema(c, 50)[-1]
    tol, near = p["touch_tol_pct"] / 100.0, p["ready_near_pct"] / 100.0
    if side == "LONG":
        zone = e20 * (1 - tol) <= live <= e20 * (1 + near) and live > e50
    else:
        zone = e20 * (1 - near) <= live <= e20 * (1 + tol) and live < e50
    return d["trend"] and d["align"] and zone
```

### 사용 예 (바이낸스 공개 API, 키 불필요)

```python
import json, urllib.request

def daily_closed(symbol, limit=300):
    rows = json.loads(urllib.request.urlopen(
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1d&limit={limit}").read())
    rows = rows[:-1]                                   # 마지막 = 진행 중 봉 → 버린다
    cols = list(zip(*[(float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in rows]))
    return [list(x) for x in cols]                     # o, h, l, c, v

o, h, l, c, v = daily_closed("FILUSDT")
for side in ("LONG", "SHORT"):
    ok, d = signal(o, h, l, c, v, side)
    if ok:
        print(side, "진입 신호", "종가", c[-1], "손절", d["stop"], "EMA20 거리 %", round(d["ext_pct"], 2))
```

---

## 10. 원본 시스템에서의 위치 (참고)

| 역할 | 파일 |
|---|---|
| 판정 (운영) | `backend/app/services/ema_pullback.py` — `signal()`, `ready_state()` |
| 자동매매 (그림자/실주문) | `backend/app/workers/external_strategies_worker.py` — 일봉 전용 루프 |
| 진입 준비·신호 알림 | `backend/app/workers/emapb_watch_worker.py` (15분) → 텔레그램 + 대시보드 카드 |
| 가상매매 규칙 | `emapb_long` / `emapb_short` (하루 마지막 15분봉에서 일봉 판정) |
| 백테스트 | `backend/scripts/entry_condition_study/emapb_quick_backtest.py [상위N] 1d` |
| 설정 키 | `emapb_*` (모드·방향·증거금·쿨다운·판정 봉·준비 구간·추격 상한·코인만·알림) |

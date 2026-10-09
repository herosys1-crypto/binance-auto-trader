# 후지모토 「3역 호전」 · 마하세븐 「속임수 돌파」 (일봉) — 이식용 명세서

> 다른 자동매매 시스템에 그대로 옮겨 쓸 수 있도록 **판정 규칙·숫자·참조 구현·운영 규칙·검증 결과**를 한 파일에 담았다.
> 원본: binance-auto-trader Fix 368(2026-09-12, 15분봉) → **Fix 427(2026-10-10, 일봉 전환)**. 출처 문서: 사장님 첨부
> `rufu_trading_strategy.md`(후지모토) · `mach7_ma_strategy.md`(마하세븐). 아래 참조 구현은 운영 코드(`app/services/external_strategies.py`)와
> **코인 상위 20종목 일봉 6,102회 판정에서 후지모토 단계 신호 189건 · 마하세븐 41건 · 스윙 손절 모두 불일치 0건**으로 대조를 마쳤다 (2026-10-10).
> 같은 형식의 EMA 추세·눌림목 명세: `EMA_PULLBACK_DAILY_STRATEGY_2026-10-10.md`.

---

## 1. 한 줄 요약

| 전략 | 아이디어 | 진입 | 손절 |
|---|---|---|---|
| **후지모토 3역 호전** | 바닥에서 RSI → MACD → 일목 순으로 신호가 「세 번」 좋아지면 1:2:7 로 나눠 산다 (SHORT 거울) | 1차 RSI 30 재돌파 → 2차 다이버전스+골든크로스 → 3차 일목 전환 | 최근 20봉 스윙 저점(고점) |
| **마하세븐 속임수 돌파** | 200일선이 오르는데 30일선을 잠깐 깼다가 2봉 연속 되찾으면 = 개미 털기(숏트랩) 끝 → 산다 (SHORT 거울) | 1회 | 함정 3봉의 최저(최고)점 |

| 공통 | 값 |
|---|---|
| 판정 봉 | **일봉(1D) 완성봉만** — 진행 중 봉 금지 · 판정은 일봉 마감 직후 하루 1회 |
| 방향 | LONG / SHORT 양방향 |
| 2% 룰 | 한 거래 최대 손실 ≤ 총자산 × 2% → 최대 명목 = 총자산 × 2% ÷ 손절폭% |
| 손절폭 클램프 | 진입가 대비 0.3% ~ 15% |

> 마하세븐 출처는 원래 「30일선·200일선」 = **일봉**이다. 15분봉 시절(Fix 368)에는 봉 수만 옮겼고, 일봉 전환으로 출처와 같아졌다.

---

## 2. 지표 정의 (이식할 때 반드시 맞출 것)

| 지표 | 정의 |
|---|---|
| RSI14 | **Wilder 평활**. 첫 값 = 처음 14개 변화(상승분·하락분)의 단순 평균, 이후 `avg = (avg×13 + 이번)/14`. 하락 평균 0 이면 RSI≈100 |
| MACD 12/26/9 | EMA(12) − EMA(26), 시그널 = 그 MACD 의 EMA(9). **EMA 시작값 = 첫 값**(SMA 시드 아님). 35봉 미만이면 전부 0 |
| 일목 9/26/52 | 전환선 = 9봉 (최고+최저)/2 · 기준선 = 26봉 · 선행스팬 A = (전환+기준)/2 · 선행스팬 B = 52봉 (최고+최저)/2 |
| 구름(j 봉 위) | **26봉 전에 계산된** 선행스팬 A/B → 상단 = max, 하단 = min |
| 후행스팬 조건 | 오늘 종가 > 26봉 전 종가 |
| SMA30·SMA200 | 종가 단순 이동평균 |
| 다이버전스(창 30봉) | 창 `[j−30, j]` 을 반으로 나눠 앞쪽·뒤쪽 각각의 종가 극값 위치를 찾는다. 상승 = 뒤쪽 저점 종가가 더 낮고 RSI 는 더 높음 / 하락 = 뒤쪽 고점 종가가 더 높고 RSI 는 더 낮음 |

---

## 3. 후지모토 「3역 호전」 판정 (마지막 완성봉 j)

최소 봉 수: `j ≥ 52 + 26 = 78` 그리고 RSI[j], RSI[j−1] 존재.

| 단계 | 비중 | LONG | SHORT |
|---|---|---|---|
| **1차** | 10% | `RSI[j−1] < 30 ≤ RSI[j]` (30 재돌파) | `RSI[j−1] > 70 ≥ RSI[j]` (70 아래로 꺾임) |
| **2차** | 20% | 상승 다이버전스 ∧ MACD 골든크로스(`m[j−1] ≤ s[j−1]` ∧ `m[j] > s[j]`) ∧ `m[j] < 0` (영선 아래) | 하락 다이버전스 ∧ 데드크로스(`m[j−1] ≥ s[j−1]` ∧ `m[j] < s[j]`) ∧ `RSI[j] < 50` |
| **3차** | 70% | 전환선이 기준선 상향 돌파(`t[j−1] ≤ k[j−1]` ∧ `t[j] > k[j]`) ∧ 종가 > 구름 상단 ∧ 종가 > 26봉 전 종가 | 전환선 하향 돌파 ∧ 종가 < 구름 하단 |

- 운영 흐름: **1차 조건으로 진입** → 같은 포지션에 2차 조건이 나오면 2차 비중 추가 → 3차 조건이면 3차 추가 (`preserve` = 평단 갱신, 단계 순서 고정).
- 비중 1:2:7 × 가족 배정액(원본 100 USDT). 각 단계 증거금도 2% 룰 상한.
- 손절: 1차 진입 때 **최근 20봉 스윙 저점(고점)** 을 손절가로 고정 → 2·3차 추가 뒤에는 새 평단 기준으로 같은 가격까지의 ROI 로 다시 환산.

## 4. 마하세븐 「속임수 돌파」 판정 (마지막 완성봉 j)

최소 봉 수: `j ≥ 200 + 5`.

| 조건 | LONG | SHORT |
|---|---|---|
| 큰 추세 | `SMA200[j] > SMA200[j−5]` (우상향) | `SMA200[j] < SMA200[j−5]` (우하향) |
| 함정 | 2봉 전 종가 < SMA30 (이탈) ∧ 어제·오늘 종가 > SMA30 (2봉 연속 복귀) | 2봉 전 종가 > SMA30 ∧ 어제·오늘 종가 < SMA30 |
| 각도 | 30선 5봉 기울기 `(SMA30[j] − SMA30[j−5]) / SMA30[j−5] × 100 ≥ 0.5` (출처 「30도」 → 기울기 %로 대체) | 없음 (출처대로) |
| 손절 | 최근 3봉 최저가 | 최근 3봉 최고가 |

- 1회 진입 (추가 없음). 증거금 원본 50 USDT + 2% 룰 상한.

---

## 5. 운영 규칙 (원본 시스템 설정)

| 항목 | 후지모토 | 마하세븐 |
|---|---|---|
| 모드 | `fujimoto_mode` off · **shadow(기본, 신호만 기록)** · on | `mach7_mode` 같음 |
| 배정 | 가족 100 USDT × 10/20/70% | 1회 50 USDT |
| 동시 보유 | 전용 2 | 전용 2 |
| 재신호 쿨다운 | 같은 종목 20시간 (일봉: 다음 날 허용) | 20시간 |
| 레버리지 | 2 | 2 |
| 대상 | 24h 거래대금 상위 60 (≥ 5,000,000 USDT) | 같음 |
| 판정 | 일봉 마감(UTC 00:00) + 5초 정착 뒤 완성봉 · 같은 봉 재판정 금지(봉별 기록 키) | 같음 |

---

## 6. 검증 결과

### 6-1. 일봉 백테스트 (공개 시세)
조건: 바이낸스 USDT-M **코인** 무기한, 거래대금 상위 60, 일봉 최대 1,500봉, 진입 = 신호 봉 종가, 손절 = §3·§4 (0.3~15% 클램프),
**익절 = 2R**, 최대 30봉 뒤 종가 청산, 같은 봉 손절·익절 = 손절(보수적), **수수료·펀딩 미반영**, 생존 편향(지금 상위 종목).
단계 추가 없이 **각 신호를 독립 진입으로** 측정.

| 규칙 | 건수 | 승률 | 평균 | 연도별 평균 R | 손절폭 |
|---|---|---|---|---|---|
| 후지모토 1차 LONG | 767 | 37% | **+0.02R** | 2023 +0.45 · 2024 −0.25 · 2025 −0.07 · 2026 +0.07 | 11.3% |
| 후지모토 1차 SHORT | 973 | 30% | **−0.20R** | 2023 −0.47 · 2024 −0.06 · 2025 −0.07 · 2026 −0.21 | 10.4% |
| **후지모토 3차 단독 LONG** | 416 | 41% | **+0.12R** | 2023 +0.13 · 2024 +0.47 · **2025 −0.38** · 2026 +0.20 | 14.0% |
| 후지모토 3차 단독 SHORT | 818 | 40% | 0.00R | 2023 +0.02 · 2024 −0.06 · 2025 +0.09 · 2026 −0.05 | 13.9% |
| 마하세븐 LONG | 206 | 28% | **−0.23R** | 2023 +0.13 · 2024 −0.33 · 2025 −0.74 · 2026 +0.38 | 10.6% |
| 마하세븐 SHORT | 1095 | 33% | **−0.11R** | 2023 −0.11 · 2024 −0.22 · 2025 −0.12 · 2026 −0.04 | 9.7% |

### 6-2. 15분봉 시절 운영 가상매매 판정 (2026-10-02, 9/12~10/02 실시간 19,107건)
- 마하세븐: 어떤 장세·잣대에서도 기준선 이하 → **실주문 금지**
- 후지모토: 실주문이 들어가는 1차가 기준선보다 나쁨 → **실주문 금지**. 3차(일목) 단독 LONG 만 후보.

### 6-3. 결론
- 일봉에서도 결론은 같다: **마하세븐 = 손실, 후지모토 1차 진입 = 본전·손실, 3차 단독 LONG 만 플러스(+0.12R, 2025 손실)**.
- 원본 시스템은 둘 다 **그림자(기록만)** 로 일봉 성과를 더 모은다. 이식한다면 **후지모토 3차(일목 전환) 단독 LONG** 만 후보로, 그림자 검증부터.

---

## 7. 이식할 때 권장 절차

1. 아래 참조 구현을 옮기고 **자기 RSI·MACD·일목 값과 대조**한다 (RSI 는 Wilder, EMA 시드는 첫 값, 구름은 26봉 전 값).
2. 2주 이상 **그림자** — 신호일·종목·방향·단계·진입가·손절가를 남긴다.
3. 실주문은 후보(후지모토 3차 단독 LONG)만, 최소 금액부터.

---

## 8. 참조 구현 (Python 3, 외부 라이브러리 없음)

입력: **완성된 일봉만** `h, l, c` (오래된 → 최신). 마지막 원소 = 방금 닫힌 일봉.

```python
"""후지모토 「3역 호전」 · 마하세븐 「속임수 돌파」 (일봉) — 독립 참조 구현. 외부 라이브러리 없음. 입력은 완성된 일봉만."""

RSI_N, RSI_OS, RSI_OB, RSI_MID = 14, 30.0, 70.0, 50.0
MACD_F, MACD_S, MACD_SIG = 12, 26, 9
TENKAN, KIJUN, SENKOU_B, SHIFT = 9, 26, 52, 26
MA_SHORT, MA_LONG, CONFIRM, TREND_LB, STOP_BARS = 30, 200, 2, 5, 3


def sma(v, n):
    out, s = [None] * len(v), 0.0
    for i, x in enumerate(v):
        s += x
        if i >= n:
            s -= v[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def ema(v, n):
    k, out = 2.0 / (n + 1), [float(v[0])]
    for x in v[1:]:
        out.append(out[-1] + k * (x - out[-1]))
    return out


def macd(c):
    if len(c) < MACD_S + MACD_SIG:
        z = [0.0] * len(c)
        return z, list(z)
    m = [a - b for a, b in zip(ema(c, MACD_F), ema(c, MACD_S))]
    return m, ema(m, MACD_SIG)


def rsi(c, n=RSI_N):
    """Wilder 평활. 첫 값 = 처음 n개 변화의 단순 평균."""
    out = [None] * len(c)
    if len(c) <= n:
        return out
    g = sum(max(c[i] - c[i - 1], 0) for i in range(1, n + 1)) / n
    l = sum(max(c[i - 1] - c[i], 0) for i in range(1, n + 1)) / n
    out[n] = 100 - 100 / (1 + (g / l if l else 1e9))
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
        out[i] = 100 - 100 / (1 + (g / l if l else 1e9))
    return out


def _mid(h, l, n):
    out = [None] * len(h)
    for i in range(n - 1, len(h)):
        out[i] = (max(h[i - n + 1:i + 1]) + min(l[i - n + 1:i + 1])) / 2
    return out


def ichimoku(h, l):
    t, k = _mid(h, l, TENKAN), _mid(h, l, KIJUN)
    a = [None if (x is None or y is None) else (x + y) / 2 for x, y in zip(t, k)]
    return t, k, a, _mid(h, l, SENKOU_B)


def cloud(a, b, j):
    """j 봉 위 구름 = 26봉 전에 계산된 선행스팬 A/B → (상단, 하단)."""
    i = j - SHIFT
    if i < 0 or a[i] is None or b[i] is None:
        return None
    return max(a[i], b[i]), min(a[i], b[i])


def _argext(v, s, e, lowest):
    idx = s
    for i in range(s, e):
        if (v[i] < v[idx]) if lowest else (v[i] > v[idx]):
            idx = i
    return idx


def divergence(c, r, j, lb, bullish):
    """창(lb 봉)을 반으로 나눠 각 반쪽 극값 비교. 상승: 가격 저점↓ RSI 저점↑ / 하락: 가격 고점↑ RSI 고점↓."""
    if j < lb or lb < 4:
        return False
    a0, a1 = j - lb, j - lb // 2
    i1, i2 = _argext(c, a0, a1, bullish), _argext(c, a1, j + 1, bullish)
    if r[i1] is None or r[i2] is None:
        return False
    return (c[i2] < c[i1] and r[i2] > r[i1]) if bullish else (c[i2] > c[i1] and r[i2] < r[i1])


def fujimoto(h, l, c, side, div_lb=30):
    """마지막 봉 j 에서 1·2·3차 조건 {1: bool, 2: bool, 3: bool}."""
    out = {1: False, 2: False, 3: False}
    j = len(c) - 1
    r = rsi(c)
    if j < SENKOU_B + SHIFT or r[j] is None or r[j - 1] is None:
        return out
    m, s = macd(c)
    t, k, sa, sb = ichimoku(h, l)
    cl = cloud(sa, sb, j)
    ok_tk = None not in (t[j - 1], k[j - 1], t[j], k[j])
    if side == "LONG":
        out[1] = r[j - 1] < RSI_OS <= r[j]
        out[2] = divergence(c, r, j, div_lb, True) and m[j - 1] <= s[j - 1] and m[j] > s[j] and m[j] < 0
        out[3] = (ok_tk and t[j - 1] <= k[j - 1] and t[j] > k[j] and cl is not None and c[j] > cl[0]
                  and c[j] > c[j - SHIFT])
    else:
        out[1] = r[j - 1] > RSI_OB >= r[j]
        out[2] = divergence(c, r, j, div_lb, False) and m[j - 1] >= s[j - 1] and m[j] < s[j] and r[j] < RSI_MID
        out[3] = ok_tk and t[j - 1] >= k[j - 1] and t[j] < k[j] and cl is not None and c[j] < cl[1]
    out = {n: bool(v) for n, v in out.items()}
    return out


def swing_stop(h, l, side, lookback=20):
    return min(l[-lookback:]) if side == "LONG" else max(h[-lookback:])


def mach7(h, l, c, side, min_slope_pct=0.5):
    """마지막 봉 j 에서 성립? (bool, detail{trend, trap, slope_pct, stop})."""
    d = {"trend": None, "trap": False, "slope_pct": None, "stop": None}
    j = len(c) - 1
    s, L = sma(c, MA_SHORT), sma(c, MA_LONG)
    if j < MA_LONG + TREND_LB or L[j] is None or L[j - TREND_LB] is None or any(s[j - i] is None for i in range(CONFIRM + 1)):
        return False, d
    n = CONFIRM
    if side == "LONG":
        d["trend"] = L[j] > L[j - TREND_LB]
        d["trap"] = c[j - n] < s[j - n] and all(c[j - i] > s[j - i] for i in range(n))
        base = s[j - TREND_LB]
        d["slope_pct"] = (s[j] - base) / base * 100 if base else None
        d["stop"] = min(l[j - STOP_BARS + 1:j + 1])
        ok = bool(d["trend"] and d["trap"] and d["slope_pct"] is not None and d["slope_pct"] >= min_slope_pct)
    else:
        d["trend"] = L[j] < L[j - TREND_LB]
        d["trap"] = c[j - n] > s[j - n] and all(c[j - i] < s[j - i] for i in range(n))
        d["stop"] = max(h[j - STOP_BARS + 1:j + 1])
        ok = bool(d["trend"] and d["trap"])
    return ok, d
```

### 사용 예 (바이낸스 공개 API, 키 불필요)

```python
import json, urllib.request

def daily_closed(symbol, limit=400):
    rows = json.loads(urllib.request.urlopen(
        f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval=1d&limit={limit}").read())[:-1]   # 진행 중 봉 버림
    return [float(r[2]) for r in rows], [float(r[3]) for r in rows], [float(r[4]) for r in rows]

h, l, c = daily_closed("BTCUSDT")
for side in ("LONG", "SHORT"):
    st = fujimoto(h, l, c, side)
    if any(st.values()):
        print("후지모토", side, st, "손절", swing_stop(h, l, side))
    ok, d = mach7(h, l, c, side)
    if ok:
        print("마하세븐", side, "손절", d["stop"])
```

---

## 9. 원본 시스템에서의 위치 (참고)

| 역할 | 파일 |
|---|---|
| 판정 (운영) | `backend/app/services/external_strategies.py` — `fujimoto_stages()`, `mach7_signal()`, `swing_stop()`, `risk_capped_margin()` |
| 자동매매 (그림자/실주문) | `backend/app/workers/external_strategies_worker.py` (60초, 일봉 완성봉당 1회) |
| 가상매매 규칙 | `fujimoto_l1_rsi · l2_div_gc · l3_ichimoku · s1_rsi · s2_div_dc · s3_ichimoku · mach7_trap_long · mach7_trap_short` (일봉 마감 뒤 1시간 창, 하루 1회) |
| 백테스트 | `backend/scripts/entry_condition_study/ext_daily_backtest.py [상위N]` |
| 설정 키 | `fujimoto_*` · `mach7_*` · `ext_interval`(기본 1d) · `ext_universe_top_n` · `ext_stop_pct_min/max` · `ext_leverage` |

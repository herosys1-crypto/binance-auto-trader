"""🔬 15분봉 「최상단(천장)」 + 볼밴 중단 실증 연구 (v140)

사장님 지시 2026-08-14:
  "15분봉 최상단과 볼밴 중단을 기준으로 매매를 할수 있게 변경해줘.
   1시간 4시간을 보조역할을 할수 있게 해줘.
   15분봉 최상단을 예측하는 시스템으로 학습해줘.
   macd obv rsi vol 이렇게 같이 분석하면 정확도가 가장높은것 같아 같이 사용해줘"

= 임계값을 **추측하지 않고** 실제 캔들에서 뽑아냅니다.

연구 항목:
  1. 15m 「천장」을 기계적으로 라벨링 → 기저 발생률(base rate)
  2. MACD / OBV / RSI / Volume / BB 각 신호의 **단독 예측력**(precision·lift)
  3. 🎯 **사장님 가설 검증** = 4개를 같이 보면 정말 정확도가 오르는가?
     (k개 이상 동시 충족 → precision 곡선)
  4. 천장 이후 **BB 중단** 도달률 / 소요 시간 / 하락폭
  5. BB 중단 도달 후 **반등 vs 이탈** 비율
  6. 1H·4H 추세가 **보조**로서 얼마나 도움이 되는가

라벨 정의 (미래 참조는 **라벨에만** 사용, 신호 계산에는 절대 사용 X):
  bar i 가 천장 ⟺ high[i] 가 [i-8, i+8] 구간 최고 AND
                   이후 8봉 내 최저가가 high[i] 대비 -DROP% 이하

사용:
    python scripts/study_15m_top_bbmid.py --cache <klines_cache 경로>
"""
from __future__ import annotations

import argparse
import bisect
import glob
import json
import os
from collections import defaultdict

# ----------------------------------------------------------------------
# 파라미터 (연구용 — 결과를 보고 로직 임계값을 정합니다)
# ----------------------------------------------------------------------
BB_PERIOD = 20
BB_STD = 2.0
RSI_PERIOD = 14
PIVOT_K = 8          # 앞뒤 8봉(=2시간) 최고 → 국소 천장
FWD_BARS = 8         # 이후 8봉(=2시간) 내 하락 확인
DROP_PCT = 1.5       # 천장 인정 최소 하락폭
MID_TRACK_BARS = 32  # BB 중단 도달 추적 (=8시간)
AFTER_MID_BARS = 8   # BB 중단 도달 후 반등/이탈 판정 구간
BOUNCE_PCT = 1.0     # 반등 인정
BREAK_PCT = 1.0      # 이탈 인정


# ----------------------------------------------------------------------
# 지표 (analysis.py 와 동일 계산식 — 일관성 유지!)
# ----------------------------------------------------------------------
def sma(vals, p):
    out = [None] * len(vals)
    s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= p:
            s -= vals[i - p]
        if i >= p - 1:
            out[i] = s / p
    return out


def ema(vals, p):
    out = [None] * len(vals)
    if len(vals) < p:
        return out
    k = 2 / (p + 1)
    prev = sum(vals[:p]) / p
    out[p - 1] = prev
    for i in range(p, len(vals)):
        prev = vals[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def bollinger(closes, p=BB_PERIOD, mult=BB_STD):
    mid = sma(closes, p)
    up, lo = [None] * len(closes), [None] * len(closes)
    for i in range(len(closes)):
        if mid[i] is None:
            continue
        w = closes[i - p + 1: i + 1]
        m = mid[i]
        var = sum((c - m) ** 2 for c in w) / p
        sd = var ** 0.5
        up[i] = m + mult * sd
        lo[i] = m - mult * sd
    return mid, up, lo


def rsi(closes, p=RSI_PERIOD):
    out = [None] * len(closes)
    if len(closes) < p + 1:
        return out
    gain = loss = 0.0
    for i in range(1, p + 1):
        d = closes[i] - closes[i - 1]
        gain += max(d, 0.0)
        loss += max(-d, 0.0)
    ag, al = gain / p, loss / p
    out[p] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(p + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (p - 1) + max(d, 0.0)) / p
        al = (al * (p - 1) + max(-d, 0.0)) / p
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def macd_hist(closes):
    """MACD(12,26,9) 히스토그램 — 입력과 길이 동일."""
    e12, e26 = ema(closes, 12), ema(closes, 26)
    line = [None] * len(closes)
    for i in range(len(closes)):
        if e12[i] is not None and e26[i] is not None:
            line[i] = e12[i] - e26[i]
    idx = [i for i, v in enumerate(line) if v is not None]
    hist = [None] * len(closes)
    if len(idx) < 9:
        return hist, line
    sig_vals = ema([line[i] for i in idx], 9)
    for j, i in enumerate(idx):
        if sig_vals[j] is not None:
            hist[i] = line[i] - sig_vals[j]
    return hist, line


def obv_series(closes, vols):
    out = [0.0] * len(closes)
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            out[i] = out[i - 1] + vols[i]
        elif closes[i] < closes[i - 1]:
            out[i] = out[i - 1] - vols[i]
        else:
            out[i] = out[i - 1]
    return out


# ----------------------------------------------------------------------
def load(path):
    d = json.load(open(path))
    return d.get("15m") or [], d.get("1h") or [], d.get("4h") or []


def cols(kl):
    return ([int(k[0]) for k in kl], [float(k[1]) for k in kl], [float(k[2]) for k in kl],
            [float(k[3]) for k in kl], [float(k[4]) for k in kl], [float(k[5]) for k in kl])


def htf_trend(kl, p_fast=20, p_slow=50):
    """상위 타임프레임 추세 = EMA20 vs EMA50 (UP/DOWN/FLAT)."""
    if len(kl) < p_slow + 2:
        return [], []
    times = [int(k[0]) for k in kl]
    closes = [float(k[4]) for k in kl]
    f, s = ema(closes, p_fast), ema(closes, p_slow)
    tr = []
    for i in range(len(kl)):
        if f[i] is None or s[i] is None:
            tr.append(None)
        elif f[i] > s[i] * 1.001:
            tr.append("UP")
        elif f[i] < s[i] * 0.999:
            tr.append("DOWN")
        else:
            tr.append("FLAT")
    return times, tr


def trend_at(times, trends, ts):
    if not times:
        return None
    j = bisect.bisect_right(times, ts) - 1
    return trends[j] if 0 <= j < len(trends) else None


# ----------------------------------------------------------------------
def analyze_symbol(path, rows, mid_stats, htf_rows):
    k15, k1h, k4h = load(path)
    if len(k15) < 120:
        return
    t, o, h, l, c, v = cols(k15)
    n = len(c)
    mid, up, lo = bollinger(c)
    r = rsi(c)
    hist, _line = macd_hist(c)
    obv = obv_series(c, v)
    vol_ma = sma(v, 20)

    t1, tr1 = htf_trend(k1h)
    t4, tr4 = htf_trend(k4h)

    start = max(BB_PERIOD + 35, PIVOT_K)
    for i in range(start, n - FWD_BARS - 1):
        if mid[i] is None or up[i] is None or r[i] is None or hist[i] is None or vol_ma[i] in (None, 0):
            continue

        # ---------- 라벨 (미래 사용 = 라벨 전용!) ----------
        win_hi = max(h[i - PIVOT_K: i + PIVOT_K + 1])
        is_pivot = h[i] >= win_hi - 1e-12
        fwd_low = min(l[i + 1: i + 1 + FWD_BARS])
        drop = (fwd_low - h[i]) / h[i] * 100
        is_top = bool(is_pivot and drop <= -DROP_PCT)

        # ---------- 신호 (i 시점까지만!) ----------
        band = up[i] - lo[i]
        pct_b = (c[i] - lo[i]) / band if band > 0 else 0.5
        rng = h[i] - l[i]

        # 📊 사장님 4대 지표
        sig_rsi = r[i] >= 70
        sig_rsi_hi = r[i] >= 80
        sig_macd = (hist[i] < hist[i - 1]) and (hist[i - 1] >= hist[i - 2]) and hist[i] > 0
        obv_slope = obv[i] - obv[i - 5]
        sig_obv = obv_slope < 0
        vr = v[i] / vol_ma[i]
        sig_vol = (v[i] < v[i - 1]) and (max(v[i - 3:i]) / vol_ma[i] >= 1.5)

        # 다이버전스 (가격 신고가인데 지표는 못 따라옴)
        prev_hi_idx = max(range(i - 20, i), key=lambda x: h[x])
        price_hh = h[i] > h[prev_hi_idx]
        div_rsi = bool(price_hh and r[prev_hi_idx] is not None and r[i] < r[prev_hi_idx])
        div_obv = bool(price_hh and obv[i] < obv[prev_hi_idx])
        div_macd = bool(price_hh and hist[prev_hi_idx] is not None and hist[i] < hist[prev_hi_idx])

        # 볼밴
        sig_bb_touch = h[i] > up[i]
        sig_bb_close = c[i] > up[i]
        sig_pctb = pct_b >= 1.0
        wick = (h[i] - max(o[i], c[i])) / rng if rng > 0 else 0.0
        sig_wick = wick >= 0.5

        combo4 = sum((sig_rsi, sig_macd, sig_obv, sig_vol))
        combo4_div = sum((div_rsi, div_macd, div_obv, sig_vol))

        rows.append({
            "is_top": is_top,
            "sig_rsi": sig_rsi, "sig_rsi_hi": sig_rsi_hi,
            "sig_macd": sig_macd, "sig_obv": sig_obv, "sig_vol": sig_vol,
            "div_rsi": div_rsi, "div_macd": div_macd, "div_obv": div_obv,
            "sig_bb_touch": sig_bb_touch, "sig_bb_close": sig_bb_close,
            "sig_pctb": sig_pctb, "sig_wick": sig_wick,
            "combo4": combo4, "combo4_div": combo4_div,
            "tr1": trend_at(t1, tr1, t[i]), "tr4": trend_at(t4, tr4, t[i]),
        })

        # ---------- 천장 이후 BB 중단 행동 ----------
        if is_top:
            reached = None
            for j in range(i + 1, min(i + 1 + MID_TRACK_BARS, n)):
                if mid[j] is None:
                    continue
                if l[j] <= mid[j]:
                    reached = j
                    break
            rec = {
                "bars_to_mid": (reached - i) if reached else None,
                "drop_to_mid": ((mid[reached] - h[i]) / h[i] * 100) if reached else None,
                "tr1": trend_at(t1, tr1, t[i]), "tr4": trend_at(t4, tr4, t[i]),
            }
            if reached and reached + AFTER_MID_BARS < n:
                base = mid[reached]
                seg_hi = max(h[reached + 1: reached + 1 + AFTER_MID_BARS])
                seg_lo = min(l[reached + 1: reached + 1 + AFTER_MID_BARS])
                up_pct = (seg_hi - base) / base * 100
                dn_pct = (seg_lo - base) / base * 100
                rec["bounce"] = up_pct >= BOUNCE_PCT
                rec["breakdown"] = dn_pct <= -BREAK_PCT
                rec["up_pct"] = up_pct
                rec["dn_pct"] = dn_pct
            mid_stats.append(rec)

    htf_rows.append(1)


# ----------------------------------------------------------------------
def precision(rows, cond):
    sel = [r for r in rows if cond(r)]
    if not sel:
        return 0, 0.0
    return len(sel), sum(1 for r in sel if r["is_top"]) / len(sel) * 100


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.cache, "*.json")))
    if args.limit:
        files = files[:args.limit]

    rows, mid_stats, htf_rows = [], [], []
    for n, f in enumerate(files, 1):
        try:
            analyze_symbol(f, rows, mid_stats, htf_rows)
        except Exception as e:
            print(f"  skip {os.path.basename(f)}: {e}")
        if n % 40 == 0:
            print(f"  ... {n}/{len(files)} 심볼 처리 (표본 {len(rows):,})", flush=True)

    total = len(rows)
    tops = sum(1 for r in rows if r["is_top"])
    base = tops / total * 100 if total else 0
    print("\n" + "=" * 74)
    print(f"🔬 15m 천장 연구 — 심볼 {len(files)}개 / 캔들 표본 {total:,}개")
    print(f"   천장 라벨: 앞뒤 {PIVOT_K}봉 최고 + 이후 {FWD_BARS}봉 내 {DROP_PCT}% 이상 하락")
    print(f"   ▶ 기저 발생률(base rate) = {tops:,}건 / {total:,} = **{base:.2f}%**")
    print("=" * 74)

    print("\n### 1) 신호별 단독 예측력")
    print(f"{'신호':<22}{'해당봉':>10}{'천장확률':>10}{'배수(lift)':>12}")
    print("-" * 56)
    singles = [
        ("RSI ≥ 70", lambda r: r["sig_rsi"]),
        ("RSI ≥ 80", lambda r: r["sig_rsi_hi"]),
        ("MACD 히스토 꺾임", lambda r: r["sig_macd"]),
        ("OBV 5봉 하락", lambda r: r["sig_obv"]),
        ("Volume 정점후 감소", lambda r: r["sig_vol"]),
        ("RSI 다이버전스", lambda r: r["div_rsi"]),
        ("MACD 다이버전스", lambda r: r["div_macd"]),
        ("OBV 다이버전스", lambda r: r["div_obv"]),
        ("BB 상단 터치(고가)", lambda r: r["sig_bb_touch"]),
        ("BB 상단 종가 돌파", lambda r: r["sig_bb_close"]),
        ("%B ≥ 1.0", lambda r: r["sig_pctb"]),
        ("윗꼬리 ≥ 50%", lambda r: r["sig_wick"]),
    ]
    for name, fn in singles:
        n_, p_ = precision(rows, fn)
        print(f"{name:<22}{n_:>10,}{p_:>9.2f}%{p_/base if base else 0:>11.2f}x")

    print("\n### 2) 🎯 사장님 가설 검증 — MACD+OBV+RSI+Vol 을 같이 보면?")
    print(f"{'동시 충족 개수':<22}{'해당봉':>10}{'천장확률':>10}{'배수(lift)':>12}")
    print("-" * 56)
    for k in range(5):
        n_, p_ = precision(rows, lambda r, k=k: r["combo4"] >= k)
        print(f"{k}개 이상{'':<15}{n_:>10,}{p_:>9.2f}%{p_/base if base else 0:>11.2f}x")

    print("\n   (다이버전스 버전 = RSI/MACD/OBV 다이버전스 + Volume)")
    for k in range(5):
        n_, p_ = precision(rows, lambda r, k=k: r["combo4_div"] >= k)
        print(f"   {k}개 이상{'':<12}{n_:>10,}{p_:>9.2f}%{p_/base if base else 0:>11.2f}x")

    print("\n### 3) 볼밴 조건을 얹으면?")
    print(f"{'조건':<34}{'해당봉':>10}{'천장확률':>10}{'배수':>10}")
    print("-" * 64)
    def ndiv(r):
        return sum((r["div_rsi"], r["div_macd"], r["div_obv"]))

    combos = [
        ("다이버전스 1개+", lambda r: ndiv(r) >= 1),
        ("다이버전스 2개+", lambda r: ndiv(r) >= 2),
        ("다이버전스 3개(전부)", lambda r: ndiv(r) >= 3),
        ("다이버전스 1개+ AND BB상단터치", lambda r: ndiv(r) >= 1 and r["sig_bb_touch"]),
        ("다이버전스 2개+ AND BB상단터치", lambda r: ndiv(r) >= 2 and r["sig_bb_touch"]),
        ("다이버전스 3개 AND BB상단터치", lambda r: ndiv(r) >= 3 and r["sig_bb_touch"]),
        ("다이버전스 2개+ AND %B≥1.0", lambda r: ndiv(r) >= 2 and r["sig_pctb"]),
        ("다이버전스 2개+ AND 윗꼬리", lambda r: ndiv(r) >= 2 and r["sig_wick"]),
        ("다이버전스 2개+ AND BB터치 AND 윗꼬리", lambda r: ndiv(r) >= 2 and r["sig_bb_touch"] and r["sig_wick"]),
        ("다이버전스 2개+ AND RSI≥70", lambda r: ndiv(r) >= 2 and r["sig_rsi"]),
        ("다이버전스 2개+ AND Vol소진", lambda r: ndiv(r) >= 2 and r["sig_vol"]),
        ("다이버전스 2개+ AND BB터치 AND RSI≥70", lambda r: ndiv(r) >= 2 and r["sig_bb_touch"] and r["sig_rsi"]),
    ]
    for name, fn in combos:
        n_, p_ = precision(rows, fn)
        print(f"{name:<34}{n_:>10,}{p_:>9.2f}%{p_/base if base else 0:>9.2f}x")

    print("\n### 4) 1H·4H 추세를 보조로 얹으면? (기준: 다이버전스 2개+ AND BB상단터치)")
    print(f"{'상위 추세':<26}{'해당봉':>10}{'천장확률':>10}{'배수':>10}")
    print("-" * 56)
    core = lambda r: sum((r["div_rsi"], r["div_macd"], r["div_obv"])) >= 2 and r["sig_bb_touch"]
    for label, fn in [
        ("(보조 없음)", core),
        ("1H DOWN", lambda r: core(r) and r["tr1"] == "DOWN"),
        ("1H UP", lambda r: core(r) and r["tr1"] == "UP"),
        ("4H DOWN", lambda r: core(r) and r["tr4"] == "DOWN"),
        ("4H UP", lambda r: core(r) and r["tr4"] == "UP"),
        ("1H+4H 둘 다 DOWN", lambda r: core(r) and r["tr1"] == "DOWN" and r["tr4"] == "DOWN"),
        ("1H+4H 둘 다 UP", lambda r: core(r) and r["tr1"] == "UP" and r["tr4"] == "UP"),
    ]:
        n_, p_ = precision(rows, fn)
        print(f"{label:<26}{n_:>10,}{p_:>9.2f}%{p_/base if base else 0:>9.2f}x")

    print("\n### 5) 천장 이후 볼밴 중단(20SMA) 행동")
    tot = len(mid_stats)
    reached = [m for m in mid_stats if m["bars_to_mid"]]
    print(f"  천장 {tot:,}건 중 {MID_TRACK_BARS}봉(8시간) 내 BB중단 도달 = "
          f"{len(reached):,}건 (**{len(reached)/tot*100 if tot else 0:.1f}%**)")
    if reached:
        bars = sorted(m["bars_to_mid"] for m in reached)
        drops = sorted(m["drop_to_mid"] for m in reached)
        print(f"  도달 소요 봉수: 중앙값 {bars[len(bars)//2]}봉 "
              f"({bars[len(bars)//2]*15}분) / 평균 {sum(bars)/len(bars):.1f}봉")
        print(f"  천장→BB중단 하락폭: 중앙값 {drops[len(drops)//2]:.2f}% / "
              f"평균 {sum(drops)/len(drops):.2f}%")
    judged = [m for m in reached if "bounce" in m]
    if judged:
        b = sum(1 for m in judged if m["bounce"] and not m["breakdown"])
        k = sum(1 for m in judged if m["breakdown"] and not m["bounce"])
        both = sum(1 for m in judged if m["bounce"] and m["breakdown"])
        none = len(judged) - b - k - both
        print(f"\n  BB중단 도달 후 {AFTER_MID_BARS}봉(2시간) 판정 ({len(judged):,}건):")
        print(f"    반등만 (+{BOUNCE_PCT}%↑)  = {b:,} ({b/len(judged)*100:.1f}%)")
        print(f"    이탈만 (-{BREAK_PCT}%↓)  = {k:,} ({k/len(judged)*100:.1f}%)")
        print(f"    양방향 흔들림          = {both:,} ({both/len(judged)*100:.1f}%)")
        print(f"    무반응                 = {none:,} ({none/len(judged)*100:.1f}%)")

        print(f"\n  상위 추세별 BB중단 반등률 (보조 역할 검증!):")
        by = defaultdict(lambda: [0, 0])
        for m in judged:
            key = f"1H={m['tr1']} / 4H={m['tr4']}"
            by[key][0] += 1
            if m["bounce"] and not m["breakdown"]:
                by[key][1] += 1
        for key in sorted(by, key=lambda x: -by[x][0])[:6]:
            n_, w_ = by[key]
            print(f"    {key:<28}{n_:>6,}건  반등 {w_/n_*100:>5.1f}%")
    print()


if __name__ == "__main__":
    main()

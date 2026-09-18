"""사장님 첨부 전략서 「볼린저 밴드 & 거래량 가중 CCI(세력 CCI)」 백테스트 — 404종목 캐시 차트 (9/9~9/18).

전략서 그대로:
  BB = 전형가격(H+L+C)/3 의 SMA20 ± 2σ(모표준편차) · BandWidth = (UB−LB)/MB×100
  세력 CCI = (TP−MB)/(0.015·MD) × clip(V / SMA(V,20), 0.5, 3.0)
  A 스퀴즈 돌파: BandWidth ≤ 최근 100봉 하위 20% & 종가>MB & 세력CCI 0선 상향 & V > 1.2×SMA(V)   (숏은 반대)
     A+ = A & 종가 ≥ UB×0.99 (옵션)
  B 눌림목: MB > MB[−3] & 저가 ≤ MB < 종가 & 세력CCI 음→양 (숏은 반대)
청산 두 가지로 잰다:
  own  = 전략서 청산: 하드 SL = min(진입봉 저가, MB) · 종가가 MB 반대 이탈 또는 세력CCI 0선 역돌파면 종가 청산 ·
         1.5R 에서 50% 익절 후 SL 본절 · 이후 직전 봉 저가(숏은 고가) 이탈 시 청산 · 최대 96봉 · 수수료 왕복 0.1%
  live = 우리 실매매 청산 규칙(손절 −25 ROI · TP1 15 · 트레일링) 24시간 — 기회 지도와 같은 자
비교 기준 = 같은 6시간 창에 아무 데나 들어간 평균 (opportunity.parquet, live 청산 24h)
ROI = 가격변동 × 레버리지 2 (가상매매와 같은 자)
"""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
BACKEND = Path(__file__).resolve().parents[2]   # backend/
sys.path.insert(0, str(BACKEND))
LEV = 2.0
FEE_ROI = 0.1 * LEV            # 왕복 0.1% × 레버리지
N, K, VF = 20, 2.0, 1.2
HOR = {"15m": 96, "1h": 24}    # own 청산 최대 봉 (15m 24h / 1h 24h)
MS = {"15m": 900_000, "1h": 3_600_000}


def indicators(o, h, l, c, v):
    tp = (h + l + c) / 3
    s = pd.Series(tp)
    mb = s.rolling(N).mean().values
    sd = s.rolling(N).std(ddof=0).values
    ub, lb = mb + K * sd, mb - K * sd
    md = s.rolling(N).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True).values
    cci = (tp - mb) / (0.015 * md)
    vs = pd.Series(v).rolling(N).mean().values
    vw = np.clip(v / (vs + 1e-12), 0.5, 3.0)
    fc = cci * vw
    bw = (ub - lb) / mb * 100
    bw_rank = pd.Series(bw).rolling(100).apply(lambda x: (x <= x[-1]).mean(), raw=True).values   # 현재 폭의 최근 100봉 내 백분위
    return dict(tp=tp, mb=mb, ub=ub, lb=lb, fc=fc, vs=vs, bw=bw, bw_rank=bw_rank)


def signals(h, l, c, v, I):
    mb, ub, lb, fc, vs, br = I["mb"], I["ub"], I["lb"], I["fc"], I["vs"], I["bw_rank"]
    fc1 = np.roll(fc, 1)
    mb3 = np.roll(mb, 3)
    volok = v > vs * VF
    sq = br <= 0.20
    S = {}
    S["A_L"] = sq & (c > mb) & (fc1 <= 0) & (fc > 0) & volok
    S["A_S"] = sq & (c < mb) & (fc1 >= 0) & (fc < 0) & volok
    S["A+_L"] = S["A_L"] & (c >= ub * 0.99)
    S["A+_S"] = S["A_S"] & (c <= lb * 1.01)
    S["B_L"] = (mb > mb3) & (l <= mb) & (c > mb) & (fc1 < 0) & (fc > 0)
    S["B_S"] = (mb < mb3) & (h >= mb) & (c < mb) & (fc1 > 0) & (fc < 0)
    for k in S:
        S[k][:110] = False
    return S


def own_exit(side, i, o, h, l, c, I, hor):
    """전략서 청산. 반환 ROI(레버리지·수수료 반영)."""
    long = side == "L"
    e = c[i]
    sl = min(l[i], I["mb"][i]) if long else max(h[i], I["mb"][i])
    risk = (e - sl) if long else (sl - e)
    if risk <= 0:
        risk = e * 0.002
        sl = e - risk if long else e + risk
    tp1 = e + 1.5 * risk if long else e - 1.5 * risk
    rem, real, tp_hit = 1.0, 0.0, False
    mv = (lambda p: (p / e - 1) * 100 * LEV) if long else (lambda p: (1 - p / e) * 100 * LEV)
    last = min(len(c) - 1, i + hor)
    for j in range(i + 1, last + 1):
        # 1) 손절 (본절 포함) 먼저
        if (long and l[j] <= sl) or (not long and h[j] >= sl):
            return real + rem * mv(sl) - FEE_ROI
        # 2) 1.5R 50% 익절 → SL 본절
        if not tp_hit and ((long and h[j] >= tp1) or (not long and l[j] <= tp1)):
            real += 0.5 * mv(tp1); rem = 0.5; tp_hit = True; sl = e
        # 3) 조건부 컷 (종가)
        if (long and (c[j] < I["mb"][j] or I["fc"][j] < 0)) or (not long and (c[j] > I["mb"][j] or I["fc"][j] > 0)):
            return real + rem * mv(c[j]) - FEE_ROI
        # 4) 익절 뒤 트레일링 = 직전 봉 저가/고가
        if tp_hit:
            sl = max(sl, l[j - 1]) if long else min(sl, h[j - 1])
    return real + rem * mv(c[last]) - FEE_ROI


def _m15(b5):
    g = {}
    for x in b5:
        g.setdefault(x[0] // 900_000 * 900_000, []).append(x)
    out = []
    for t in sorted(g):
        xs = sorted(g[t], key=lambda x: x[0])
        if len(xs) == 3:
            out.append([t, xs[0][1], max(x[2] for x in xs), min(x[3] for x in xs), xs[-1][4], sum(x[5] for x in xs)])
    return out


def run(sym):
    import opportunity_scan as OS
    from app.services import paper_trading as PT
    try:
        bars = OS._load(sym)
    except Exception:
        return []
    b15 = _m15(bars["5m"][0])
    series = {"15m": b15, "1h": bars["1h"][0]}
    t15 = np.array([x[0] for x in b15])
    out = []
    for tf, b in series.items():
        if len(b) < 150:
            continue
        a = np.array(b, dtype=float)
        t, o, h, l, c, v = a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]
        I = indicators(o, h, l, c, v)
        S = signals(h, l, c, v, I)
        for key, m in S.items():
            side = key[-1]
            for i in np.nonzero(m)[0]:
                close_t = int(t[i]) + MS[tf]
                r_own = own_exit(side, i, o, h, l, c, I, HOR[tf])
                j = int(np.searchsorted(t15, close_t))     # live 청산 = 진입 뒤 15분봉 96개 (24h)
                if j + 96 > len(b15) or j >= len(t15) or t15[j] != close_t:
                    continue
                fwd = b15[j:j + 96]
                r_live = PT.run_live_like("LONG" if side == "L" else "SHORT", float(c[i]), fwd, tp1_pct=PT.TP1_FLAT,
                                          variants=(), horizon=96)["roi"]
                out.append({"symbol": sym, "tf": tf, "sig": key, "side": side, "t": close_t,
                            "roi_own": r_own, "roi_live": r_live})
    return out


if __name__ == "__main__":
    syms = sorted(p.stem for p in (HERE / "klines").glob("*.json"))
    rows = []
    with ProcessPoolExecutor(max_workers=6) as ex:
        for i, r in enumerate(ex.map(run, syms, chunksize=4)):
            rows.extend(r)
            if i % 100 == 0:
                print(i, len(rows), flush=True)
    d = pd.DataFrame(rows)
    d["t"] = pd.to_datetime(d.t, unit="ms", utc=True)
    d.to_parquet(HERE / "bbcci_signals.parquet", index=False)
    print("신호", len(d))

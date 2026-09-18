"""기회 지도 — 규칙이 신호를 낸 자리만이 아니라 **모든 종목 · 모든 1시간 마감**에 진입했다고 치고,
그 자리의 차트 상태(진입 시각에 닫힌 봉만 = 미래참조 없음)와 실매매 청산 규칙으로 낸 ROI 를 기록한다.

청산 = paper_trading.run_live_like (실코드와 같은 손절 −25 ROI · TP1 15 에서 25% 부분익절 · 트레일링),
시간 만료 = 24시간(15분봉 96개). **24시간이 다 지난 자리만** 쓴다 → 빨리 끝난 거래만 남는 검열 편향 없음.
"""
import bisect
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).parent
BACKEND = Path(__file__).resolve().parents[2]   # backend/
sys.path.insert(0, str(BACKEND))

H = 96                      # 24h of 15m bars
IVS = {"1d": ("d1", 60), "4h": ("h4", 60), "1h": ("h1", 60), "5m": ("m5", 120)}
TF = ("pctb", "rsi14", "atr14_pct", "macd_dir", "ema_align", "vol_ratio20", "bb_width_pct", "from_hi_pct", "from_lo_pct")
BB = ("state", "trend", "pos", "bars_since_below_lower", "bars_since_above_upper", "dist_mid_pct")
MS15 = 900_000


def _load(sym):
    from app.services import chart_state as CS
    raw = json.loads((HERE / "klines" / f"{sym}.json").read_text())
    out = {}
    for iv in IVS:
        b = CS.normalize(raw.get(iv) or [], iv)
        seen, uniq = set(), []
        for x in b:
            if x[0] not in seen:
                seen.add(x[0]); uniq.append(x)
        uniq.sort(key=lambda x: x[0])
        out[iv] = (uniq, [x[0] + CS.MS[iv] for x in uniq])
    return out


def _m15(b5):
    """5분봉 → 15분봉 (세 개가 다 있는 구간만)."""
    g = {}
    for x in b5:
        g.setdefault(x[0] // MS15 * MS15, []).append(x)
    out = []
    for t in sorted(g):
        xs = sorted(g[t], key=lambda x: x[0])
        if len(xs) != 3:
            continue
        out.append([t, xs[0][1], max(x[2] for x in xs), min(x[3] for x in xs), xs[-1][4], sum(x[5] for x in xs)])
    return out


def scan(sym):
    from app.services import chart_state as CS
    from app.services import paper_trading as PT
    th = dict(CS.THRESHOLDS)
    try:
        bars = _load(sym)
    except Exception as e:           # noqa: BLE001
        return []
    b15 = _m15(bars["5m"][0])
    if len(b15) < H + 10:
        return []
    t15 = [x[0] for x in b15]
    h1, h1c = bars["1h"]
    rows = []
    for k in range(60, len(h1)):
        t = h1c[k - 1]                              # 이 시각에 막 마감한 1시간봉 = h1[k-1]
        j = bisect.bisect_left(t15, t)              # 진입 뒤 첫 15분봉 (open ≥ t)
        if j <= 0 or j + H > len(b15) or t15[j] != t:
            continue
        fwd = b15[j:j + H]
        if any(fwd[i + 1][0] - fwd[i][0] != MS15 for i in range(H - 1)):
            continue                                # 빈 구간 있으면 버림
        entry = b15[j - 1][4]
        feat = {"symbol": sym, "t": t, "entry": entry}
        ok = True
        for iv, (key, lim) in IVS.items():
            b, closes = bars[iv]
            jj = bisect.bisect_right(closes, t)
            sl = b[max(0, jj - lim):jj]
            if len(sl) < 30:
                ok = False; break
            blk = CS._block(iv, sl, th)
            if "error" in blk:
                ok = False; break
            for f in TF:
                feat[f"{key}_{f}"] = blk.get(f)
            if "bb" in blk:
                for f in BB:
                    feat[f"{key}_bb_{f}"] = blk["bb"].get(f)
        if not ok:
            continue
        c24 = h1[k - 25][4] if k >= 25 else None
        feat["chg24"] = (h1[k - 1][4] / c24 - 1) * 100 if c24 else None
        feat["ret4h"] = (h1[k - 1][4] / h1[k - 5][4] - 1) * 100
        for side in ("LONG", "SHORT"):
            r = PT.run_live_like(side, entry, fwd, tp1_pct=PT.TP1_FLAT, variants=(), horizon=H)
            s = side[0].lower()
            feat[f"roi_{s}"] = r["roi"]
            feat[f"mfe_{s}"] = r["mfe"]
            feat[f"mae_{s}"] = r["mae"]
            feat[f"hit_{s}"] = r["hit"]
        rows.append(feat)
    return rows


if __name__ == "__main__":
    import pandas as pd
    syms = sorted(p.stem for p in (HERE / "klines").glob("*.json"))
    out = []
    with ProcessPoolExecutor(max_workers=6) as ex:
        for i, rows in enumerate(ex.map(scan, syms, chunksize=4)):
            out.extend(rows)
            if i % 50 == 0:
                print(f"{i}/{len(syms)} · 행 {len(out)}", flush=True)
    df = pd.DataFrame(out)
    df["t"] = pd.to_datetime(df.t, unit="ms", utc=True)
    df.to_parquet(HERE / "opportunity.parquet", index=False)
    print("끝:", len(df), "행 ·", df.symbol.nunique(), "종목 ·", df.t.min(), "~", df.t.max())

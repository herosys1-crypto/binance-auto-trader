"""방향 계층 N 장기 백테스트 (2026-11-11 사장님 「실패원인을 알면 수정해서 성공으로 … 모든 전략을 개선하는 방향으로 · 전면 개편도 가능」).

가상매매 63일은 장세가 사실상 두 번(9월 상승 · 10월 하락)뿐이라 방향 규칙을 검증하기에 표본이 모자란다.
→ data.binance.vision 월별 15분봉(공개 · 무게 0)으로 24개월을 다시 돌려, 장세가 여러 번 바뀐 구간에서
   「직전 24h 에 마감된 무작위 거래가 나빴던 쪽으로 진입」(가설 N, D-113)이 버티는지 본다.

모형: 고정 종목군 × 4시간마다(00·04·…·20 UTC) LONG·SHORT 둘 다 진입(= 가상매매 무작위 기준선과 같은 역할)
      청산 = paper_trading.run_live_like (TP1 15 · 손절 −25 ROI · 트레일링 · 48h 만료, 추가 lot 없음) · 비용 0.4%p.
D 일 방향 = D 00:00 UTC 전 H 시간 안에 **마감된** 거래의 방향별 평균 (미래 참조 없음).
한계: 종목군 = 지금 살아 있는 유동성 큰 종목(생존 편향) · 추가 lot 없음 · 수수료는 고정 가정.

실행(로컬, 저장소 backend 폴더에서): py -3.14 -X utf8 scripts/entry_condition_study/direction_backtest_2026_11_11.py
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import math
import statistics as st
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.services import paper_trading as PT  # noqa: E402

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache_15m_vision"
SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT",
           "LTCUSDT", "BCHUSDT", "TRXUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "SUIUSDT", "SEIUSDT",
           "INJUSDT", "TIAUSDT", "FILUSDT", "ATOMUSDT", "ETCUSDT", "UNIUSDT", "AAVEUSDT", "WIFUSDT", "1000PEPEUSDT",
           "1000SHIBUSDT", "ORDIUSDT", "STXUSDT", "FETUSDT", "WLDUSDT", "JUPUSDT", "ENAUSDT", "ONDOUSDT", "TONUSDT",
           "LDOUSDT", "CRVUSDT", "GALAUSDT", "SANDUSDT"]
MONTHS = [(y, m) for y in (2024, 2025, 2026) for m in range(1, 13) if (2024, 11) <= (y, m) <= (2026, 10)]
STEP = 16                 # 4시간 = 15분봉 16개
COST = 0.4
HOURS = (6, 12, 24, 48, 72)
MS_DAY = 86_400_000


def month_bars(sym: str, y: int, m: int) -> list[list[float]]:
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"{sym}-15m-{y}-{m:02d}.csv"
    if not f.exists():
        url = f"https://data.binance.vision/data/futures/um/monthly/klines/{sym}/15m/{sym}-15m-{y}-{m:02d}.zip"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                z = zipfile.ZipFile(io.BytesIO(r.read()))
            f.write_text(z.read(z.namelist()[0]).decode("utf-8"), encoding="utf-8")
        except urllib.error.HTTPError:
            f.write_text("", encoding="utf-8")       # 없는 달(상장 전) = 빈 파일로 표시
        time.sleep(0.05)
    out = []
    for row in csv.reader(io.StringIO(f.read_text(encoding="utf-8"))):
        if not row or not row[0].isdigit():
            continue                                # 머리글
        out.append([int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4])])
    return out


def simulate() -> list[tuple[str, int, int, float]]:
    """(side, entry_ms, close_ms, roi) — 종목·4시간마다 LONG·SHORT."""
    trades = []
    for k, sym in enumerate(SYMBOLS):
        bars = [b for y, m in MONTHS for b in month_bars(sym, y, m)]
        bars.sort(key=lambda b: b[0])
        if len(bars) < 1000:
            print(f"  {sym}: 봉 부족 ({len(bars)}) → 제외")
            continue
        n0 = len(trades)
        for j in range(0, len(bars) - 1, 1):
            if (bars[j][0] // 900_000) % STEP != STEP - 1:   # 4시간 경계 직전 봉의 종가에서 진입
                continue
            after = bars[j + 1:j + 1 + PT.LIVE_HORIZON]
            if len(after) < PT.LIVE_HORIZON:
                break
            entry = bars[j][4]
            for side in ("LONG", "SHORT"):
                r = PT.run_live_like(side, entry, after, tp1_pct=PT.TP1_FLAT, variants=())
                eb = int(r.get("exit_bar") if r.get("exit_bar") is not None else len(after) - 1)
                trades.append((side, bars[j][0] + 900_000, after[min(eb, len(after) - 1)][0] + 900_000, float(r["roi"])))
        print(f"  [{k + 1}/{len(SYMBOLS)}] {sym}: 봉 {len(bars):,} · 거래 {len(trades) - n0:,}")
    return trades


def score(name: str, res: list[tuple[dt.date, float, str]]) -> None:
    if len(res) < 5:
        print(f"{name}: 날 부족")
        return
    vv = [v for _, v, _ in res]
    mu = sum(vv) / len(vv)
    lo = mu - 1.645 * st.stdev(vv) / math.sqrt(len(vv))
    dd = sorted(vv)[:-3]
    q = defaultdict(list)
    for d, v, _ in res:
        q[f"{d.year}Q{(d.month - 1) // 3 + 1}"].append(v)
    qs = " ".join(f"{k} {sum(x) / len(x):+.2f}" for k, x in sorted(q.items()))
    print(f"{name}: {mu:+.2f}/날 · 90%하한 {lo:+.2f} · 상위3일빼면 {sum(dd) / len(dd):+.2f} · +일 {sum(1 for v in vv if v > 0)}/{len(vv)} · "
          f"LONG일 {sum(1 for *_, s in res if s == 'LONG')}\n    분기: {qs}")


def main() -> None:
    print(f"종목 {len(SYMBOLS)} · {MONTHS[0]}~{MONTHS[-1]} · 4시간마다 LONG·SHORT")
    trades = simulate()
    day = defaultdict(lambda: [0, 0.0])
    closed = {"LONG": [], "SHORT": []}
    for s, e, c, r in trades:
        x = day[(s, e // MS_DAY)]
        x[0] += 1
        x[1] += r
        closed[s].append((c, r))
    for s in closed:
        closed[s].sort()
    keys = {s: [c for c, _ in closed[s]] for s in closed}
    days = sorted({d for _, d in day})
    import bisect
    mean = {k: v[1] / v[0] - COST for k, v in day.items()}
    D2 = lambda d: dt.date(1970, 1, 1) + dt.timedelta(days=d)   # noqa: E731
    print(f"\n거래 {len(trades):,} · 날 {len(days)}")
    score("항상 LONG", [(D2(d), mean[("LONG", d)], "LONG") for d in days if ("LONG", d) in mean])
    score("항상 SHORT", [(D2(d), mean[("SHORT", d)], "SHORT") for d in days if ("SHORT", d) in mean])
    for hours in HOURS:
        for label, contrarian in (("역방향(진 쪽)", True), ("같은 방향(이긴 쪽)", False)):
            res = []
            for d in days:
                t0 = d * MS_DAY
                t1 = t0 - hours * 3_600_000
                m = {}
                for s in closed:
                    seg = closed[s][bisect.bisect_left(keys[s], t1):bisect.bisect_left(keys[s], t0)]
                    if len(seg) >= 20:
                        m[s] = sum(r for _, r in seg) / len(seg)
                if len(m) < 2:
                    continue
                long_better = m["LONG"] > m["SHORT"]
                side = ("SHORT" if long_better else "LONG") if contrarian else ("LONG" if long_better else "SHORT")
                if (side, d) in mean:
                    res.append((D2(d), mean[(side, d)], side))
            score(f"[{hours:>2}h] {label}{' ← 사전 등록' if hours == 24 and contrarian else ''}", res)

    # 신호 세기 걸러내기: |LONG 평균 − SHORT 평균| 이 큰 날만 역방향 24h. 기준은 앞 12개월에서 고르고 뒤 12개월로 채점(반대도).
    print("\n== 신호 세기 (24h 역방향) — 앞에서 고른 문턱으로 뒤 채점 · 안 하는 날 = 0")
    sig = []
    for d in days:
        t0 = d * MS_DAY
        m = {}
        for s in closed:
            seg = closed[s][bisect.bisect_left(keys[s], t0 - 86_400_000):bisect.bisect_left(keys[s], t0)]
            if len(seg) >= 20:
                m[s] = sum(r for _, r in seg) / len(seg)
        if len(m) == 2:
            side = "SHORT" if m["LONG"] > m["SHORT"] else "LONG"
            if (side, d) in mean:
                sig.append((D2(d), abs(m["LONG"] - m["SHORT"]), mean[(side, d)], side))
    half = sig[len(sig) // 2][0]
    parts = {"앞": [x for x in sig if x[0] < half], "뒤": [x for x in sig if x[0] >= half]}
    for tr, te in (("앞", "뒤"), ("뒤", "앞")):
        gaps = sorted(x[1] for x in parts[tr])
        best = None
        for q in (0.0, 0.25, 0.5, 0.75):
            thr = gaps[int(q * (len(gaps) - 1))]
            v = [x[2] for x in parts[tr] if x[1] >= thr]
            per_day = sum(v) / len(parts[tr])
            if best is None or per_day > best[0]:
                best = (per_day, q, thr)
        _, q, thr = best
        te_sel = [x for x in parts[te] if x[1] >= thr]
        te_all = sum(x[2] for x in parts[te]) / len(parts[te])
        te_v = sum(x[2] for x in te_sel) / len(parts[te])
        per_trade = sum(x[2] for x in te_sel) / max(len(te_sel), 1)
        print(f"{tr}에서 고름 → {te} 채점: 문턱 하위 {q:.0%}(={thr:.2f}) · 매매일 {len(te_sel)}/{len(parts[te])} · "
              f"매매일 평균 {per_trade:+.2f} · 날 전체 기준 {te_v:+.2f} (걸러내기 없음 {te_all:+.2f})")


if __name__ == "__main__":
    main()

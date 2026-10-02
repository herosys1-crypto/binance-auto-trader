"""볼밴 스윙 그림자 신호 사후 채점 — 9/14 백테스트(docs/spec/BB_SWING_STRATEGY_2026-09-14.md 2절)와 같은 실행 근사.

데이터: bbswing/shadow_*.jsonl (bbswing_shadow_dump.py 출력 — 그림자 TTL 이 7일이라 주 1회 이상 덤프해 쌓는다).
봉: bbswing/kl15/{심볼}.json (없으면 바이낸스 공개 API 15m 1500봉, 로컬 IP). 최신 봉이 필요하면 kl15/ 를 지우고 다시 돌린다.

1차 = 신호봉 종가, 2·3차 = 1차 체결가 −2% / −4% (SHORT 는 반대), 레버 2,
손절 = 평단 ROI −10 (가격 −5%), TP = 평단 ROI +5/+10/+15/+20 (가격 +2.5/5/7.5/10%) 25%씩,
TP1 뒤 고점 대비 가격 3% 회귀에 잔량, taker 0.05%/체결, 봉 안은 불리한 쪽 먼저.
"""
import json, os, sys, time, urllib.request, collections, statistics

import glob

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bbswing")
LEV, FEE, SLP, TRAIL = 2.0, 0.0005, 0.05, 0.03
STEP_GAP = 0.02
TPS = [0.025, 0.05, 0.075, 0.10]
BAR = 15 * 60 * 1000

rows = [json.loads(l) for f in sorted(glob.glob(os.path.join(HERE, "shadow_*.jsonl")))
        for l in open(f, encoding="utf-8") if l.strip()]
meta = [r for r in rows if r.get("_meta")]
uniq = {(r["symbol"], r["side"], r["bar_ts"]): r for r in rows if not r.get("_meta")}   # 덤프가 겹쳐도 한 번만
sigs = sorted(uniq.values(), key=lambda r: r["bar_ts"])

cache = os.path.join(HERE, "kl15")
os.makedirs(cache, exist_ok=True)


def klines(sym):
    p = os.path.join(cache, sym + ".json")
    if os.path.exists(p):
        return json.load(open(p))
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=15m&limit=1500"
    for _ in range(3):
        try:
            d = json.load(urllib.request.urlopen(url, timeout=20))
            json.dump(d, open(p, "w"))
            time.sleep(0.15)
            return d
        except Exception as e:  # noqa
            err = e
            time.sleep(1)
    print("kline fail", sym, err, file=sys.stderr)
    return []


KL = {}
for s in sorted({r["symbol"] for r in sigs}):
    KL[s] = {int(k[0]): (float(k[1]), float(k[2]), float(k[3]), float(k[4])) for k in klines(s)}


def sim(sig, caps, stages=3):
    """반환 (pnl USDT, 결과, 체결 단계수, 종료 ts)."""
    sym, side = sig["symbol"], sig["side"]
    d = 1 if side == "LONG" else -1
    kl = KL.get(sym) or {}
    t0 = sig["bar_ts"]
    if t0 not in kl:
        return None
    e1 = kl[t0][3]
    lv = [e1 * (1 - d * STEP_GAP * i) for i in range(3)][:stages]
    qty_full = [caps[i] * LEV / lv[i] for i in range(len(lv))]
    filled = [False] * len(lv)
    filled[0] = True
    cash = -qty_full[0] * e1 * FEE            # 실현 손익 누계
    pos = qty_full[0]; cost = qty_full[0] * e1
    tp_done = 0; peak = None; init_q = None
    t = t0 + BAR
    last = max(kl)
    while t <= last:
        o, h, l, c = kl[t]
        adv, fav = (l, h) if d == 1 else (h, l)
        # 1) 불리한 쪽: 추가 체결 (TP1 전만) → 손절 → 트레일링
        if tp_done == 0:
            for i in range(1, len(lv)):
                if not filled[i] and (adv - lv[i]) * d <= 0:
                    filled[i] = True
                    pos += qty_full[i]; cost += qty_full[i] * lv[i]
                    cash -= qty_full[i] * lv[i] * FEE
        avg = cost / pos
        slp = avg * (1 - d * SLP)
        if (adv - slp) * d <= 0:
            cash += pos * (slp - avg) * d - pos * slp * FEE
            return cash, ("TP후손절" if tp_done else "손절"), sum(filled), t
        if tp_done and peak is not None:
            tr = peak * (1 - d * TRAIL)
            if (adv - tr) * d <= 0:
                px = tr if (o - tr) * d > 0 else o
                cash += pos * (px - avg) * d - pos * px * FEE
                return cash, "트레일링", sum(filled), t
        # 2) 유리한 쪽: TP 단계
        while tp_done < 4:
            tpx = avg * (1 + d * TPS[tp_done])
            if (fav - tpx) * d < 0:
                break
            if init_q is None:
                init_q = pos
            q = min(pos, init_q * 0.25)
            cash += q * (tpx - avg) * d - q * tpx * FEE
            cost -= q * avg; pos -= q; tp_done += 1
            if pos <= 1e-12:
                return cash, "TP4", sum(filled), t
        if tp_done:
            peak = fav if peak is None else (max(peak, fav) if d == 1 else min(peak, fav))
        t += BAR
    avg = cost / pos
    c = kl[last][3]
    return cash + pos * (c - avg) * d, "미결(평가)", sum(filled), last


def report(name, res):
    if not res:
        print(f"{name}: 0건"); return
    p = [x["pnl"] for x in res]
    n = len(p); w = sum(1 for v in p if v > 0)
    mid = sorted(x["ts"] for x in res)[n // 2]
    def avg(f):
        s = [x["pnl"] for x in res if f(x)]
        return f"{statistics.mean(s):+.2f}({len(s)})" if s else "-"
    syms = sorted({x["sym"] for x in res})
    odd = set(syms[0::2])
    out = collections.Counter(x["out"] for x in res)
    st3 = sum(1 for x in res if x["st"] == 3) / n
    print(f"{name}: n={n} 승률 {w/n:.1%} 건당 {statistics.mean(p):+.3f} 합 {sum(p):+.1f} | "
          f"앞 {avg(lambda x: x['ts'] < mid)} 뒤 {avg(lambda x: x['ts'] >= mid)} "
          f"홀 {avg(lambda x: x['sym'] in odd)} 짝 {avg(lambda x: x['sym'] not in odd)} | 3차 {st3:.0%} | {dict(out)}")


def run(side, caps, stages, constrained):
    res = []
    busy = {}                     # sym → 종료 ts (같은 심볼·방향 활성 = 진입 안 함)
    open_ends = []                # 동시 보유 상한용
    day_cnt = collections.defaultdict(list)
    for s in sigs:
        if s["side"] != side:
            continue
        t = s["bar_ts"]
        if busy.get(s["symbol"], 0) > t:
            continue
        if constrained:
            open_ends = [e for e in open_ends if e > t]
            if len(open_ends) >= 2:
                continue
            day_cnt[s["symbol"]] = [x for x in day_cnt[s["symbol"]] if x > t - 86400000]
            if len(day_cnt[s["symbol"]]) >= 2:
                continue
        r = sim(s, caps, stages)
        if r is None:
            continue
        pnl, out, st, end = r
        busy[s["symbol"]] = end
        if constrained:
            open_ends.append(end); day_cnt[s["symbol"]].append(t)
        res.append({"pnl": pnl, "out": out, "st": st, "ts": t, "sym": s["symbol"], "end": end})
    return res


print("meta:", json.dumps(meta[-1]["last_cycle"], ensure_ascii=False) if meta else None)
for side in ("LONG", "SHORT"):
    print(f"\n=== {side} ===")
    report("A 백테스트 단위 100/200/300 · 전 단계 · 제약 없음", run(side, [100, 200, 300], 3, False))
    report("B 현행 10/100/200 · 전 단계 · 제약 없음", run(side, [10, 100, 200], 3, False))
    report("C 현행 10/100/200 · 1차만(2·3차 게이트 막힘)", run(side, [10, 100, 200], 1, False))
    report("D 현행 10/100/200 · 동시2·하루2 실운영 제약", run(side, [10, 100, 200], 3, True))
    # 일별
    res = run(side, [10, 100, 200], 3, False)
    by = collections.defaultdict(list)
    for x in res:
        by[time.strftime("%m-%d", time.gmtime(x["ts"] / 1000))].append(x["pnl"])
    print("  일별(B):", " ".join(f"{k} {sum(v):+.0f}({len(v)})" for k, v in sorted(by.items())))

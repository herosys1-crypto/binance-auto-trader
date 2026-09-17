"""방향별 공통 진입 조건 — 모든 규칙(기준선 제외)을 합쳐 발견(사전등록 이전)에서 고르고, 검증(이후)에서 규칙별로 확인."""
import json
import numpy as np
import pandas as pd
import analyze as A   # 같은 전처리·함수 재사용 (analyze.py 의 규칙별 루프도 한 번 돈다)

d = A.d
out = {}
for side in ("LONG", "SHORT"):
    g = d[(d.side == side) & ~d.rule.str.startswith("baseline_")]
    disc, hold = g[g.opened_at < A.PREREG], g[g.opened_at >= A.PREREG]
    disc = disc.copy(); disc["half"] = (disc.opened_at >= disc.opened_at.median()).astype(int)
    min_n = int(0.15 * len(disc))
    res = []
    for sp in A.cond_masks(disc):
        s = A.score(disc, A.apply(disc, sp), min_n)
        if s and s["pmin"] > 0:
            res.append((sp, s))
    res.sort(key=lambda x: -x[1]["pmin"])
    top = res[:30]
    combos = []
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            a, b = top[i][0], top[j][0]
            if a[1] == b[1]:
                continue
            s = A.score(disc, A.apply(disc, a) & A.apply(disc, b), min_n)
            if s and s["pmin"] > top[i][1]["pmin"]:
                combos.append(((a, b), s))
    combos.sort(key=lambda x: -x[1]["pmin"])
    cands = [t[0] for t in top[:12]] + [c[0] for c in combos[:8]]
    rows = []
    for sp in cands:
        ev_d, ev_h = A.evaluate(disc, sp), A.evaluate(hold, sp)
        per_rule = {}
        for rule, gr in hold.groupby("rule"):
            e = A.evaluate(gr, sp)
            if e.get("n", 0) >= 20:
                per_rule[rule] = {"n": e["n"], "ex": e["ex"], "rest": e["rest_ex"], "roi": e["roi"]}
        rows.append({"cond": A.name(sp), "spec": sp, "disc": ev_d, "hold": ev_h, "rules": per_rule})
    out[side] = rows
    print(f"\n######## {side}  발견 n={len(disc)} 검증 n={len(hold)}")
    for r in rows:
        a, h = r["disc"], r["hold"]
        lift = h["ex"] - h["rest_ex"]
        better = sum(1 for v in r["rules"].values() if v["ex"] > v["rest"])
        print(f"{r['cond'][:80]:80s} 발견 {a['share']:.0%} ex{a['ex']:+.2f}(나머지{a['rest_ex']:+.2f}) | 검증 {h['share']:.0%} ex{h['ex']:+.2f} 나머지{h['rest_ex']:+.2f} 차{lift:+.2f} roi{h['roi']:+.2f} 승{h['win']:.0%} t{h['t']:+.1f} 날{h['days_pos']}/{h['days']} 규칙개선 {better}/{len(r['rules'])}")
json.dump(out, open("side_conditions.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=float)

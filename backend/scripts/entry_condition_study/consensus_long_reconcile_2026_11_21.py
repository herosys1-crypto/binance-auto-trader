"""consensus_long 대조 (읽기 전용): 11/11 edge(같은 날·방향·시장폭 칸 무작위) vs 11/16 (같은 날·방향 무작위) 차이 원인.
실행: docker compose exec -T api python - < scripts/entry_condition_study/consensus_long_reconcile_2026_11_21.py
"""
import datetime as dt
from collections import defaultdict
from sqlalchemy import text
from app.core.database import SessionLocal

SQL = text("""SELECT rule, side, opened_at, snapshot->>'market_breadth' mb, (engines->'live'->>'roi')::float roi
 FROM paper_trades WHERE source='live' AND status='CLOSED' AND engines->'live'->>'roi' IS NOT NULL
 AND side='LONG' AND (rule='consensus_long' OR rule LIKE 'baseline_%')""")
db = SessionLocal(); R = db.execute(SQL).fetchall(); db.rollback(); db.close()

def bk(mb):
    try: v = float(mb)
    except Exception: return '?'
    return 'low' if v < .4 else 'high' if v > .6 else 'mid'

rows = [dict(rule=r.rule, d=r.opened_at.date(), b=bk(r.mb), roi=r.roi) for r in R]
cl = [x for x in rows if x['rule'] == 'consensus_long']
bl = [x for x in rows if x['rule'] != 'consensus_long']
print('baseline rules:', sorted({x['rule'] for x in bl}))
print('consensus_long n', len(cl), 'days', min(x['d'] for x in cl), '~', max(x['d'] for x in cl))
print('consensus_long breadth buckets:', dict(__import__('collections').Counter(x['b'] for x in cl)))

def means(key):
    m = defaultdict(lambda: [0, 0.0])
    for x in bl:
        y = m[key(x)]; y[0] += 1; y[1] += x['roi']
    return {k: v[1] / v[0] for k, v in m.items()}

m_day = means(lambda x: x['d'])
m_dayb = means(lambda x: (x['d'], x['b']))

def report(tag, xs):
    if not xs: print(tag, 'n0'); return
    raw = sum(x['roi'] for x in xs) / len(xs)
    e1 = [x['roi'] - m_dayb[(x['d'], x['b'])] for x in xs if (x['d'], x['b']) in m_dayb]
    e2 = [x['roi'] - m_day[x['d']] for x in xs if x['d'] in m_day]
    # 날 단위: 같은 날 무작위 대비 이긴 날
    byd = defaultdict(list)
    for x in xs:
        if x['d'] in m_day: byd[x['d']].append(x['roi'] - m_day[x['d']])
    win = sum(1 for v in byd.values() if sum(v) / len(v) > 0)
    byd2 = defaultdict(list)
    for x in xs:
        if (x['d'], x['b']) in m_dayb: byd2[x['d']].append(x['roi'] - m_dayb[(x['d'], x['b'])])
    win2 = sum(1 for v in byd2.values() if sum(v) / len(v) > 0)
    # 같은 날 무작위 중 low 칸 vs 전체 차이 (칸 효과)
    gap = [m_dayb[(x['d'], 'low')] - m_day[x['d']] for x in xs if (x['d'], 'low') in m_dayb and x['d'] in m_day]
    f = lambda v: f"{sum(v)/len(v):+.2f}" if v else '—'
    print(f"{tag}: n{len(xs)} 원{raw:+.2f} 순{raw-0.4:+.2f} | 칸맞춤 edge {f(e1)} (n{len(e1)}·이긴 날 {win2}/{len(byd2)}) | 날만 edge {f(e2)} (n{len(e2)}·이긴 날 {win}/{len(byd)}) | 무작위 low칸−전체 {f(gap)}")

today = max(x['d'] for x in rows)
report('전체', cl)
report('11/11 이전', [x for x in cl if x['d'] < dt.date(2026, 11, 11)])
report('최근30일(10/17~)', [x for x in cl if x['d'] >= today - dt.timedelta(days=30)])
report('10/17 이전', [x for x in cl if x['d'] < today - dt.timedelta(days=30)])
mo = defaultdict(list)
for x in cl: mo[x['d'].strftime('%Y-%m')].append(x)
for k in sorted(mo): report('월 ' + k, mo[k])
# 무작위 LONG 칸별 평균 (전체)
mb = defaultdict(list)
for x in bl: mb[x['b']].append(x['roi'])
print('무작위 LONG 칸별:', {k: (len(v), round(sum(v) / len(v), 2)) for k, v in mb.items()})
lowcl = [x for x in cl if x['b'] == 'low']
report('consensus_long low칸만', lowcl)

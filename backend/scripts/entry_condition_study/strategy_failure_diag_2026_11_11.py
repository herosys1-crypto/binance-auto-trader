"""실패 전략 정밀 진단 (2026-11-11 사장님 「실패한 전략들의 문제를 정밀하고 분석해서 그문제를 모두 개선할수 있는 데이트로 분석해서 정리해서 전략을 개선해줘」) — 읽기 전용.

규칙×방향마다 손실을 쪼갠다: SL 비율 · 처음부터 역행(MFE<3) · 토해냄(MFE≥10 인데 손실) · MFE/MAE 를 같은 방향 무작위와 비교,
앞/뒤 기간 순수익, 방향 계층 N(직전 24h 마감 무작위가 나빴던 쪽, D-113) 맞을 때/틀릴 때.
개선안 3가지(장세칸 고르기 · 청산 엔진 고르기 · 방향 N)는 한 기간에서 고르고 다른 기간에서 채점(안 고른 거래 = 0)한다.
SINCE=YYYY-MM-DD 를 주면 그 날 이후 진입만 본다(≈11/25 전진 판정: SINCE=2026-11-11).
실행: docker compose exec -T api python - < scripts/entry_condition_study/strategy_failure_diag_2026_11_11.py
"""
import os
import bisect, datetime as dt
from collections import defaultdict
from sqlalchemy import text
from app.core.database import SessionLocal
COST=0.4
ENG=['live','house','live_be10','live_sl15','live_lock5','live_trend','live_trail3','live_trail8','live_trend0','live_stale24']
SQL=text("""SELECT rule, side, opened_at, closed_at, snapshot->>'market_breadth' mb,
 engines->'live'->>'hit' hit, (engines->'live'->>'mae')::float mae, (engines->'live'->>'mfe')::float mfe, (engines->'live'->>'bars')::int bars,
 """+",".join(f"(engines->'{e}'->>'roi')::float {e}" for e in ENG)+"""
 FROM paper_trades WHERE source='live' AND status='CLOSED' AND engines->'live'->>'roi' IS NOT NULL""")
db=SessionLocal(); R=db.execute(SQL, execution_options={"stream_results":True}).fetchall(); db.rollback(); db.close()
SINCE=os.environ.get('SINCE')
rows=[]
for r in R:
    if SINCE and r.opened_at.date() < dt.date.fromisoformat(SINCE): continue
    try: mb=float(r.mb) if r.mb is not None else None
    except Exception: mb=None
    b='?' if mb is None else ('low' if mb<.4 else 'high' if mb>.6 else 'mid')
    rows.append(dict(rule=r.rule, side=r.side, d=r.opened_at.date(), o=r.opened_at, c=r.closed_at, b=b, hit=r.hit, mae=r.mae or 0, mfe=r.mfe or 0, bars=r.bars or 0, roi={e:getattr(r,e) for e in ENG}))
days=sorted({x['d'] for x in rows}); mid=days[len(days)//2]
H=lambda d:'A' if d<mid else 'B'
# matched random (live) and per engine
bm={e:defaultdict(lambda:[0,0.0]) for e in ENG}
for x in rows:
    if x['rule'].startswith('baseline_'):
        for e in ENG:
            v=x['roi'][e]
            if v is not None: y=bm[e][(x['side'],x['d'],x['b'])]; y[0]+=1; y[1]+=v
bmm={e:{k:v[1]/v[0] for k,v in m.items()} for e,m in bm.items()}
# direction layer N (24h contrarian, closed before D)
cl={'LONG':[],'SHORT':[]}
for x in rows:
    if x['rule'].startswith('baseline_') and x['c'] and x['roi']['live'] is not None: cl[x['side']].append((x['c'],x['roi']['live']))
for s in cl: cl[s].sort()
ks={s:[c for c,_ in cl[s]] for s in cl}
sig={}
for D in days:
    t0=dt.datetime.combine(D,dt.time(0),tzinfo=dt.timezone.utc); t1=t0-dt.timedelta(hours=24); m={}
    for s in cl:
        seg=[r for _,r in cl[s][bisect.bisect_left(ks[s],t1):bisect.bisect_left(ks[s],t0)]]
        if len(seg)>=20: m[s]=sum(seg)/len(seg)
    if len(m)==2: sig[D]='SHORT' if m['LONG']>m['SHORT'] else 'LONG'
def net(xs,e='live'):
    v=[x['roi'][e] for x in xs if x['roi'][e] is not None]
    return (sum(v)/len(v)-COST, len(v)) if v else (None,0)
def edge(xs,e='live'):
    v=[x['roi'][e]-bmm[e][(x['side'],x['d'],x['b'])] for x in xs if x['roi'][e] is not None and (x['side'],x['d'],x['b']) in bmm[e]]
    return sum(v)/len(v) if v else None
g=defaultdict(list)
for x in rows: g[(x['rule'],x['side'])].append(x)
# random profile per side
def prof(xs):
    n=len(xs); 
    sl=[x for x in xs if x['hit']=='SL']; tm=[x for x in xs if x['hit']=='TIME']; tr=[x for x in xs if x['hit']=='TRAIL']
    never=sum(1 for x in xs if x['mfe']<3)/n
    giveback=sum(1 for x in xs if x['mfe']>=10 and x['roi']['live']<=0)/n
    loss_sl=sum(x['roi']['live'] for x in sl); loss_tm=sum(x['roi']['live'] for x in tm if x['roi']['live']<0)
    return dict(sl=len(sl)/n, tr=len(tr)/n, tm=len(tm)/n, never=never, giveback=giveback, sl_share=loss_sl/max(1e-9,(loss_sl+loss_tm)) , mfe=sum(x['mfe'] for x in xs)/n, mae=sum(x['mae'] for x in xs)/n)
for s in ('LONG','SHORT'):
    xs=[x for x in rows if x['rule'].startswith('baseline_') and x['side']==s]
    p=prof(xs); n_,c_=net(xs)
    print(f"[무작위 {s}] n{len(xs)} 순{n_:+.2f} SL{p['sl']:.0%} 트레일{p['tr']:.0%} 시간{p['tm']:.0%} 처음부터역행{p['never']:.0%} 토해냄{p['giveback']:.0%} 평균MFE{p['mfe']:.1f} MAE{p['mae']:.1f}")
print("\n규칙|방향|n|순/건|edge|앞|뒤|SL%|역행%|토해냄%|MFE|MAE|방향N맞을때|틀릴때|교차검증: 장세칸 / 청산엔진 / 방향N")
out=[]
for (ru,s),xs in g.items():
    if ru.startswith('baseline_') or len(xs)<300: continue
    n_,c=net(xs); e_=edge(xs); a,_=net([x for x in xs if H(x['d'])=='A']); bq,_=net([x for x in xs if H(x['d'])=='B'])
    p=prof(xs)
    al,_=net([x for x in xs if sig.get(x['d'])==s]); mis,_=net([x for x in xs if sig.get(x['d']) and sig.get(x['d'])!=s])
    # 교차검증: 한 기간에서 고르고 다른 기간에서 채점, 두 방향 평균 (기준 = 같은 기간 그대로)
    cv={}
    for fix in ('bucket','engine','dirN'):
        sc=[]; base=[]
        for tr_,te_ in (('A','B'),('B','A')):
            TR=[x for x in xs if H(x['d'])==tr_]; TE=[x for x in xs if H(x['d'])==te_]
            if len(TR)<100 or len(TE)<100: sc=None; break
            b0,_=net(TE); base.append(b0)
            if fix=='bucket':
                ok={bk for bk in ('low','mid','high') if (net([x for x in TR if x['b']==bk])[0] or -9)>0 and net([x for x in TR if x['b']==bk])[1]>=50}
                v,k=net([x for x in TE if x['b'] in ok]); sc.append((v if v is not None else 0.0)*k/len(TE) if k else 0.0)   # 안 고른 칸은 0 (거래 안 함)
            elif fix=='engine':
                best=max([e_ for e_ in ENG if net(TR,e_)[1]>=100 and net(TE,e_)[1]>=100] or ['live'],key=lambda e_: net(TR,e_)[0])
                sc.append(net(TE,best)[0])
            else:
                v,k=net([x for x in TE if sig.get(x['d'])==s]); sc.append((v or 0.0)*k/len(TE))
        cv[fix]=None if sc is None else (sum(sc)/2, sum(base)/2)
    out.append((n_,ru,s,len(xs),e_,a,bq,p,al,mis,cv))
out.sort()
f=lambda v:'—' if v is None else f"{v:+.2f}"
for n_,ru,s,n,e_,a,bq,p,al,mis,cv in out:
    cvs=" / ".join('—' if cv[k] is None else f"{cv[k][0]:+.2f}(기준{cv[k][1]:+.2f})" for k in ('bucket','engine','dirN'))
    print(f"{ru}|{s[0]}|{n}|{n_:+.2f}|{f(e_)}|{f(a)}|{f(bq)}|{p['sl']:.0%}|{p['never']:.0%}|{p['giveback']:.0%}|{p['mfe']:.1f}|{p['mae']:.1f}|{f(al)}|{f(mis)}|{cvs}")

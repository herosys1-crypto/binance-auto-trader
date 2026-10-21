"""S4 실주문 ↔ 가상 같은 진입 짝 대조 (2026-10-22 운영팀 회의 「다시 켜기 전 조건 ③ 실주문-가상 괴리」) — 읽기 전용.
짝 = 같은 심볼 · 가상 진입이 실주문 생성 3시간 전 ~ 1시간 뒤 중 가장 가까운 것 · 실주문 ROI = 시스템 몫(Fix 434) ÷ 총 증거금 × 100.
운영:  docker compose exec -T api python - < scripts/entry_condition_study/s4_live_vs_paper_2026_10_22.py
"""
import sys; sys.path.insert(0,"/app")
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, text
from app.core.database import SessionLocal
from app.models.strategy_instance import StrategyInstance as SI
from app.models.strategy_template import StrategyTemplate as ST
from app.services import auto_family_registry as AF, human_share as HS
KST=timezone(timedelta(hours=9)); now=datetime.now(timezone.utc)
db=SessionLocal()
rows=db.execute(select(SI.id,SI.symbol,SI.side,SI.status,SI.realized_pnl,SI.created_at,SI.started_at,SI.stopped_at,SI.avg_entry_price,SI.total_capital,SI.leverage,SI.entry_origin,SI.last_error_message,ST.strategy_type,ST.name)
  .join(ST,ST.id==SI.strategy_template_id).where(SI.created_at>=now-timedelta(days=40))).all()
s4=[r for r in rows if (f:=AF.family_for(strategy_type=r.strategy_type,template_name=r.name,entry_origin=r.entry_origin,created_at=r.created_at)) is not None and f.key=="rf_zone_s4"]
sp=HS.split_for(db,[(r.id,r.side,r.realized_pnl) for r in s4])
q=text("""select id, symbol, opened_at, closed_at, entry_price, chg_24h, close_reason, (engines->'live'->>'roi')::float roi,
 engines->'live'->>'exit_reason' er from paper_trades where source='live' and rule='zone_s4_spike_top_short' and symbol=:s and opened_at between :a and :b order by abs(extract(epoch from (opened_at - :c)))""")
print("id | 심볼 | 생성 KST | 상태 | 실주문 시스템 USDT | 실주문 ROI% | 가상 ROI% | 차(실−가상) | 진입가 실/가상 차% | 가상 마감 사유 | 실주문 메모")
tot=[0,0,0]
for r in sorted(s4,key=lambda r:r.created_at):
    sysv=float(sp[r.id]["system"] or 0)
    if r.status not in ("COMPLETED","STOPPED","CLOSED","LIQUIDATED"): continue
    if not r.avg_entry_price and abs(sysv)<1e-9:
        print(r.id, r.symbol, r.created_at.astimezone(KST).strftime("%m-%d %H:%M"), r.status, "체결 없음(시도만)"); continue
    cap=float(r.total_capital or 10); roi_live=sysv/cap*100
    p=db.execute(q,{"s":r.symbol,"a":r.created_at-timedelta(hours=3),"b":r.created_at+timedelta(hours=1),"c":r.created_at}).first()
    if p is None or p.roi is None:
        print(r.id, r.symbol, r.created_at.astimezone(KST).strftime("%m-%d %H:%M"), r.status, f"{sysv:+.2f}", f"{roi_live:+.1f}", "가상 짝 없음"); continue
    ed=(float(r.avg_entry_price)/float(p.entry_price)-1)*100 if r.avg_entry_price and p.entry_price else None
    d=roi_live-p.roi; tot[0]+=1; tot[1]+=d; tot[2]+=(ed or 0)
    print(r.id, r.symbol, r.created_at.astimezone(KST).strftime("%m-%d %H:%M"), r.status, f"{sysv:+.2f}", f"{roi_live:+.1f}", f"{p.roi:+.1f}", f"{d:+.1f}",
          "—" if ed is None else f"{ed:+.2f}", f"{p.close_reason or ''}/{p.er or ''}", (r.last_error_message or "")[:50].replace("\n"," "))
if tot[0]: print(f"짝 {tot[0]} · 평균 차(실−가상) {tot[1]/tot[0]:+.2f}%p · 평균 진입가 차 {tot[2]/tot[0]:+.2f}%")
db.close()

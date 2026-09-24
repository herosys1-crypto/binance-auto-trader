"""📋 매일 점검 (2026-09-20 사장님 「모든 자동매매를 분석해서 성공할 방법을 계속적으로 찾아줘 … 가상매매를 통해서 검증하고 수정해줘」)

**읽기만 한다** — 설정·주문을 바꾸지 않는다. 운영에서 이렇게 돌린다 (VPS 안에서 api 컨테이너):
    ssh root@<VPS> "cd ~/binance-auto-trader/backend && docker compose exec -T api python -" < daily_review.py

한 번 돌리면 순서대로 나온다:
  ① 지금 상태   — 전면 중단 · 실주문 ON 인 가족 · 손실 차단기 발동
  ② 실거래      — 가족별 최근 7일·30일 실현 손익 (사람 전략 제외)
  ③ 가상매매     — 규칙별 같은 6시간 창 무작위 대비 (마감 건) · 사전등록 채택 후보
  ④ 새 구간      — L1·S4(Fix 379) · 장세 전환 R1·R2(Fix 385) · 조건부 피라미딩 A1·A2(Fix 382)
  ⑤ 오늘의 결론   — 문턱을 넘은 것 / 뒤집힌 것 / 사장님이 정할 것

문턱 (Claude가 정함 · docs/learning 문서들과 같은 값):
  · 채택 후보 = paper_report_v3 의 adopt (클러스터 300 · 날짜 7 · t 2.0 · 필터는 긍정일 70%)
  · 실거래 경고 = 가족 최근 7일 실현 합 < −30 (손실 차단기와 같은 값)
"""
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import fmean

sys.path.insert(0, "/app")
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.paper_trade import PaperTrade as P
from app.models.strategy_instance import StrategyInstance as SI
from app.models.strategy_template import StrategyTemplate as ST
from app.models.system_setting import SystemSetting
from app.services import auto_family_registry as AF
from app.services import family_loss_breaker as FB
from app.services import rule_families as RF
from app.services.auto_trading_halt import halt_enabled

DAYS_REPORT = 10          # 보고서 창 (판정은 그 안의 사전등록 블록이 한다)
WARN_USDT = 30.0


def line(t=""):
    print(t, flush=True)


def setting(db, key):
    r = db.get(SystemSetting, key)
    return None if r is None else str(r.value).strip()


def roi_of(eng, engine="live"):
    return ((eng or {}).get(engine) or {}).get("roi")


def win6(t):
    return t.replace(minute=0, second=0, microsecond=0, hour=t.hour // 6 * 6)


def main() -> None:
    db = SessionLocal()
    now = datetime.now(timezone.utc)
    try:
        line(f"📋 매일 점검 — {now:%Y-%m-%d %H:%M} UTC")

        # ── ① 지금 상태 ──────────────────────────────────────────────
        line("\n① 지금 상태")
        line(f"  자동매매 전면 중단: {'예 (사람 전략만 주문)' if halt_enabled(db) else '아니오 — 실주문 ON 가족이 주문한다'}")
        on_rules = [f for f in RF.FAMILIES if RF.mode_of(db, f.key) == "on"]
        sh_rules = [f for f in RF.FAMILIES if RF.mode_of(db, f.key) == "shadow"]
        line(f"  규칙 가족: 실주문 ON {len(on_rules)} ({', '.join(f.short or f.key for f in on_rules) or '없음'}) · 그림자 {len(sh_rules)}")
        fams = [f.key for f in AF.known_families()]
        st = FB.all_states(db, fams, now=now)
        tripped = [k for k, v in st.items() if v["tripped"]]
        line(f"  손실 차단기: {'발동 ' + ', '.join(tripped) if tripped else '발동 없음'} (기준 최근 {st[fams[0]]['days']}일 −{st[fams[0]]['limit']:g})")

        # ── ② 실거래 ────────────────────────────────────────────────
        line("\n② 실거래 (가족별 실현 손익 USDT · 사람 전략 제외)")
        rows = FB._closed_rows(db, now - timedelta(days=30))   # 🚨 끝난 판정 = TERMINAL status (stopped_at 만 보면 COMPLETED 가 빠진다)
        # 🚨 Fix 400: 사람이 「포지션 추가」로 키운 몫은 따로 센다 (가족 판정 성과를 흐리지 않게).
        agg = defaultdict(lambda: [0.0, 0, 0.0, 0, 0.0, 0])   # 30일 합·건, 7일 합·건, 사람몫30·건
        for row in rows:
            rp, ca, sa, origin, stype, name = row[0], row[1], row[2], row[3], row[4], row[5]
            fam = AF.family_for(strategy_type=stype, template_name=name, entry_origin=origin, created_at=ca)
            if fam is None:
                continue
            p = float(rp or 0)
            share = FB.family_share(*FB._cap_pair(row))
            a = agg[fam.label]
            a[0] += p * share
            a[1] += 1
            if share < 1.0:
                a[4] += p - p * share
                a[5] += 1
            if sa >= now - timedelta(days=7):
                a[2] += p * share
                a[3] += 1
        if not agg:
            line("  최근 30일에 끝난 자동 전략이 없다 (전면 중단 중이면 정상)")
        for lab, (s30, n30, s7, n7, hp, hn) in sorted(agg.items(), key=lambda kv: kv[1][0]):
            warn = " ⚠ 차단기 기준 초과" if s7 < -WARN_USDT else ""
            human = f" · 사람이 키운 몫 {hp:+.1f} ({hn}건 개입)" if hn else ""
            line(f"  {lab:28s} 30일 {s30:+8.1f} ({n30:3d}건) · 7일 {s7:+7.1f} ({n7:2d}건){warn}{human}")
        line(f"  자동 합계: 30일 {sum(v[0] for v in agg.values()):+.1f} · 7일 {sum(v[2] for v in agg.values()):+.1f}")

        # ── ③ 가상매매 ──────────────────────────────────────────────
        line("\n③ 가상매매 — 규칙별 (마감 건 · 같은 6시간 창 무작위 대비)")
        prows = db.execute(select(P.rule, P.side, P.status, P.opened_at, P.engines, P.snapshot["market_breadth"].astext)
                           .where(P.source == "live", P.opened_at >= now - timedelta(days=DAYS_REPORT))).all()
        base = defaultdict(list)
        for rule, side, status, t, eng, br in prows:
            if rule.startswith("baseline_") and status == "CLOSED" and roi_of(eng) is not None:
                base[(side, win6(t))].append(roi_of(eng))
        bm = {k: fmean(v) for k, v in base.items() if len(v) >= 3}
        per = defaultdict(list)
        for rule, side, status, t, eng, br in prows:
            r = roi_of(eng)
            if rule.startswith("baseline_") or status != "CLOSED" or r is None or (side, win6(t)) not in bm:
                continue
            per[(side, rule)].append((r, r - bm[(side, win6(t))], br))
        for side in ("LONG", "SHORT"):
            items = sorted(((k[1], v) for k, v in per.items() if k[0] == side), key=lambda x: -fmean(e for _, e, _ in x[1]))
            line(f"  {side}:")
            for rule, v in items:
                if len(v) < 20:
                    continue
                line(f"    {rule:28s} {len(v):5d}건 · ROI {fmean(r for r, _, _ in v):+6.2f} · "
                     f"초과 {fmean(e for _, e, _ in v):+5.2f} · 승률 {sum(1 for r, _, _ in v if r > 0) / len(v):.0%}")

        line("\n   사전등록 채택 후보 (paper_report_v3 · 클러스터 300 · 날짜 7 · t 2.0)")
        from app.workers.paper_trading_worker import build_report_v3_from_db
        rep = build_report_v3_from_db(db, days=DAYS_REPORT)
        items = (rep.get("adoption") or {}).get("items") or []
        if not items:
            line("    (아직 없음 — 표본이 문턱에 못 미치거나 성과가 기준 미달)")
        for it in items:
            line(f"    ✅ {it['kind']} {it['side']} {it['name']} · 클러스터 {it.get('clusters')} · 날짜 {it.get('days', it.get('days_with_both'))}")

        # ── ④ 새 구간 ───────────────────────────────────────────────
        line("\n④ 새 구간 · 사전등록 (배포 뒤 새 표본만)")
        for name in ("zone_l1_rebound_long", "zone_s4_spike_top_short"):
            v = per.get(("LONG" if name.endswith("long") else "SHORT", name), [])
            if v:
                hi = [r for r, _, b in v if b is not None and float(b) >= 0.55]
                lo = [r for r, _, b in v if b is not None and float(b) <= 0.45]
                line(f"  {name:26s} {len(v):4d}건 · ROI {fmean(r for r, _, _ in v):+6.2f} · 초과 {fmean(e for _, e, _ in v):+5.2f}"
                     f" | 오르는 장 {len(hi)}건 {fmean(hi):+.2f}" + (f" · 내리는 장 {len(lo)}건 {fmean(lo):+.2f}" if lo else ""))
            else:
                line(f"  {name:26s} 마감 표본 없음")
        blocks = rep.get("blocks") or {}
        for blk in ("all", "prereg"):
            fl = ((blocks.get(blk) or {}).get("filters") or {})
            for side in ("LONG", "SHORT"):
                for fname, s in (fl.get(side) or {}).items():
                    if fname.startswith(("R1", "R2", "P8", "P9", "P10")) and s["kept"]["n"]:
                        line(f"  [{blk}] {fname:26s} 통과 {s['kept']['n']:4d}건 {s['kept']['mean']:+6.2f} · "
                             f"제외 {s['excluded']['n']:4d}건 {s['excluded']['mean'] if s['excluded']['mean'] is not None else 0:+6.2f} · "
                             f"긍정일 {s['day_edge']['positive_days']}/{s['day_edge']['days_with_both']}{' ✅' if s.get('adopt') else ''}")
        for nm, s in ((blocks.get("all") or {}).get("adds_cond") or {}).items():
            k, e = s["kept"], s["excluded"]
            line(f"  {nm:26s} 통과 {k['n']:4d}건 합 {k['pnl_sum']:+8.1f} · 제외 {e['n']:4d}건 합 {e['pnl_sum']:+8.1f} · "
                 f"통과가 나은 날 {s['days_better']}/{s['days_both']}")

        # ── ⑤ 결론 ─────────────────────────────────────────────────
        line("\n⑤ 오늘의 결론")
        todo = []
        if tripped:
            todo.append(f"손실 차단기 발동 {', '.join(tripped)} — 원인을 보고 풀지 결정 (관제실 「손실 차단」 → 허용)")
        for lab, (s30, n30, s7, n7) in agg.items():
            if s7 < -WARN_USDT:
                todo.append(f"실거래 {lab} 최근 7일 {s7:+.1f} — 차단기가 막았는지 확인")
        if items:
            todo.append(f"채택 후보 {len(items)}건 — 켤지 사장님 결정")
        if not halt_enabled(db) and on_rules:
            todo.append(f"실주문 ON {len(on_rules)}종이 주문 중 — 위 실거래 표로 확인")
        if not todo:
            todo.append("문턱을 넘은 변경 없음 — 표본을 더 쌓는다")
        for t in todo:
            line(f"  · {t}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

"""운영팀 배치 「실주문처럼」 재기 (2026-10-16 사장님 「가상매매 결과로 자동매매 전략 개선」) — 읽기 전용.

질문: 운영팀 전진 검증(D)은 고른 칸의 **모든** 가상 행을 평균한다(하루 수천 건). 실주문은 가족마다 하루 최대 1건이다.
      하루 1건(또는 3건)만 들어가도 운영팀 배치가 지금 실주문 가족 규칙보다 나은가?
방법: 날짜 D 마다 strategy_council 과 같은 규칙으로 칸(rule, side, 시장폭 구간)을 고른다(학습창 [D−13, D−3], n≥30·평균>0·무작위 대비>0).
  정책 A1 / A3 = 그날 고른 칸에 든 가상 행 중 진입 시각이 이른 1건 / 3건 (방향별)
  정책 L  = 지금 실주문 가족과 같은 규칙: LONG bottom_331 · 시장폭<0.4 첫 1건 / SHORT zone_s4_spike_top_short · 24h +10% 이상 첫 1건
  무작위 = baseline 행 중 이른 1건 (방향별)
결과 = live 엔진 roi(%) 와 순수익(roi − 0.4, Fix 452 가정). 끝난 행만.
운영:  docker compose exec -T api python - < scripts/entry_condition_study/council_realistic_2026_10_16.py
      채점 시작일만 바꾸기: docker compose exec -T -e SCORE_FROM=2026-10-17 -e DAYS=60 api python - < 이 파일

10/16 추가(사장님 「1 2 3 진행해줘」):
  § J  가설 J 사전 등록 판정(SCORE_FROM 이 있을 때) — 기준은 아래 J_* 상수. 10/16 이전 27일은 이미 본 탐색 표본이라
       **2026-10-17 KST 이후 진입만** 센다(하루 = KST).
  § S  「작게 여러 건」 모의 — 같은 하루 위험(10 USDT)을 1건 × 10U / 3건 × 3.33U 로 나눴을 때 하루 손익(USDT)의 평균·흔들림·최악
  § X  LONG 날 사이 이어짐 — 전날 규칙 LONG 평균이 나쁘면 다음 날도 나쁜가(급락 2~3일 묶음 뒤 반등)
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app")

from sqlalchemy import text  # noqa: E402

from app.core.database import SessionLocal  # noqa: E402
from app.services import strategy_council as SC  # noqa: E402

import os  # noqa: E402

DAYS = int(os.environ.get("DAYS") or 34)
SCORE_FROM = os.environ.get("SCORE_FROM")           # "YYYY-MM-DD" — 이 날부터만 채점(학습창은 그 전 데이터도 씀)
NET = 0.4
KST_OFF = timedelta(hours=9)                         # 하루 = KST(실주문 「하루 최대」 와 같은 경계, auto_family_registry)
DAY_RISK = 10.0                                      # 가족당 하루 위험 USDT(지금 실주문 단일 10U)
# 가설 J (2026-10-16 사전 등록, 판정 ≈ 2026-11-15): 「운영팀 SHORT 첫 1건(A1)」 이 「S4 규칙 첫 1건(L)」 보다 낫다.
#   통과 = ① 두 정책 모두 n ≥ 30 ② A1 순수익 평균 − L 순수익 평균 ≥ +1.0%p ③ A1 순수익 > 무작위 ④ 둘 다 있는 날 A1 이 이긴 날 > 진 날
#   기각 = n ≥ 30 인데 ② 가 0 이하 · 그 밖은 보류. (숫자는 Claude가 정함)
J_MIN_N, J_MARGIN = 30, 1.0
LIVE_RULES = {"LONG": "bottom_331", "SHORT": "zone_s4_spike_top_short"}

SQL = text("""
    SELECT rule, side, opened_at, (opened_at AT TIME ZONE 'UTC')::date AS d, engines->'live'->>'roi' AS roi,
           snapshot->>'market_breadth' AS mb, chg_24h
    FROM paper_trades
    WHERE source = 'live' AND status = 'CLOSED' AND opened_at > :since AND engines->'live'->>'roi' IS NOT NULL
""")


def num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def main():
    db = SessionLocal()
    rows = []
    try:
        res = db.execute(SQL, {"since": datetime.now(timezone.utc) - timedelta(days=DAYS)},
                         execution_options={"stream_results": True})
        for r in res:
            roi = num(r.roi)
            if roi is None or r.side not in ("LONG", "SHORT"):
                continue
            mb = num(r.mb)
            rows.append((str(r.rule), r.side, r.opened_at, (r.opened_at + KST_OFF).date(), roi, mb if mb is not None and 0 <= mb <= 1 else None, num(r.chg_24h)))
    finally:
        db.close()
    p = SC.clean_params()
    lo, hi = p["lo"], p["hi"]

    # 날짜·칸별 집계 (학습용) — strategy_council.pick 과 같은 기준
    base_db = defaultdict(lambda: [0, 0.0])
    cell_day = defaultdict(lambda: [0, 0.0])
    by_day_rows = defaultdict(list)
    for rule, side, at, d, roi, mb, chg in rows:
        b = SC.bucket(mb, lo, hi)
        if rule.startswith(SC.BASE_PREFIX):
            x = base_db[(side, d, b)]; x[0] += 1; x[1] += roi   # noqa: E702
        else:
            c = cell_day[(rule, side, b, d)]; c[0] += 1; c[1] += roi   # noqa: E702
        by_day_rows[d].append((at, rule, side, b, roi, mb, chg))
    days = sorted(by_day_rows)

    def pick(D):
        start, end = D - timedelta(days=p["gap"] + p["train_days"] - 1), D - timedelta(days=p["gap"])
        agg = defaultdict(lambda: [0, 0.0, 0, 0.0])
        covered = {d for (_r, _s, _b, d) in cell_day if start <= d <= end}
        for (rule, side, b, d), (n, s) in cell_day.items():
            if start <= d <= end:
                a = agg[(rule, side, b)]; a[0] += n; a[1] += s   # noqa: E702
                bm = base_db.get((side, d, b))
                if bm and bm[0]:
                    a[2] += n; a[3] += s - n * (bm[1] / bm[0])
        sel = {k for k, a in agg.items() if a[0] >= p["min_n"] and a[1] / a[0] > 0 and a[2] and a[3] / a[2] > 0}
        return sel, len(covered) >= (p["train_days"] + 1) // 2

    pol = defaultdict(lambda: defaultdict(list))     # policy → side → [roi...]
    daily = []
    usd = defaultdict(lambda: defaultdict(list))     # 정책·크기 → side → [하루 손익 USDT]
    h2h = defaultdict(lambda: [0, 0])                # side → [A1 이긴 날, 진 날]
    long_day = {}                                    # d → 규칙 LONG(시장폭<0.4) 평균
    for D in days:
        lv = [x[4] for x in by_day_rows[D]
              if x[2] == "LONG" and not x[1].startswith(SC.BASE_PREFIX) and x[5] is not None and x[5] < 0.4]
        if len(lv) >= 30:
            long_day[D] = sum(lv) / len(lv)
        if SCORE_FROM and D.isoformat() < SCORE_FROM:
            continue
        sel, ok = pick(D)
        if not ok:
            continue
        rs = sorted(by_day_rows[D], key=lambda x: x[0])
        line = {"d": D.isoformat()}
        for side in ("LONG", "SHORT"):
            insel = [x for x in rs if x[2] == side and (x[1], side, x[3]) in sel]
            for k, nm in ((1, "A1"), (3, "A3")):
                for x in insel[:k]:
                    pol[nm][side].append(x[4])
            if insel:
                line[f"A1_{side}"] = round(insel[0][4], 2)
                usd["A·1×10U"][side].append(DAY_RISK * insel[0][4] / 100)
                usd["A·3×3.3U"][side].append(sum(DAY_RISK / 3 * x[4] / 100 for x in insel[:3]))
            want = LIVE_RULES[side]
            cond = (lambda x: x[5] is not None and x[5] < 0.4) if side == "LONG" else (lambda x: x[6] is not None and x[6] >= 10)
            liv = [x for x in rs if x[1] == want and x[2] == side and cond(x)]
            if liv:
                pol["L"][side].append(liv[0][4]); line[f"L_{side}"] = round(liv[0][4], 2)   # noqa: E702
                usd["L·1×10U"][side].append(DAY_RISK * liv[0][4] / 100)
                usd["L·3×3.3U"][side].append(sum(DAY_RISK / 3 * x[4] / 100 for x in liv[:3]))
            if insel and liv and insel[0][4] != liv[0][4]:
                h2h[side][0 if insel[0][4] > liv[0][4] else 1] += 1
            bas = [x for x in rs if x[1].startswith(SC.BASE_PREFIX) and x[2] == side]
            if bas:
                pol["무작위"][side].append(bas[0][4])
        daily.append(line)

    print(f"# 운영팀 배치 「하루 1건」 재기 — 가상 끝난 행 {len(rows):,} · 채점 날 {len(daily)}일 · 순수익 = roi − {NET}")
    print("| 정책 | 방향 | 건 | 평균 roi | 순수익 | 이긴 비율 | 최악 |")
    print("|---|---|---|---|---|---|---|")
    for nm in ("A1", "A3", "L", "무작위"):
        for side in ("LONG", "SHORT"):
            v = pol[nm][side]
            if v:
                m = sum(v) / len(v)
                print(f"| {nm} | {side} | {len(v)} | {m:+.2f} | {m - NET:+.2f} | {sum(x > 0 for x in v) / len(v):.0%} | {min(v):+.1f} |")
    import statistics as st
    print("\n## § S 「작게 여러 건」 — 하루 위험 10 USDT 를 1건/3건으로 (하루 손익 USDT, 수수료 전)")
    print("| 정책·크기 | 방향 | 날 | 하루 평균 | 흔들림(표준편차) | 최악의 날 | 플러스 날 |")
    print("|---|---|---|---|---|---|---|")
    for nm in ("L·1×10U", "L·3×3.3U", "A·1×10U", "A·3×3.3U"):
        for side in ("LONG", "SHORT"):
            v = usd[nm][side]
            if len(v) >= 2:
                print(f"| {nm} | {side} | {len(v)} | {sum(v) / len(v):+.2f} | {st.pstdev(v):.2f} | {min(v):+.2f} | "
                      f"{sum(x > 0 for x in v)}/{len(v)} |")

    print("\n## § X LONG 날 사이 이어짐 (규칙 LONG · 시장폭<0.4 · 하루 30건 이상인 날)")
    print("⚠️ 「진입한 날」 결과끼리의 상관 = 그날엔 아직 모르는 값(최대 48h 뒤 끝남) → 규칙으로 못 씀. 10/16 실시간 대리값"
          "(어제 「끝난」 LONG 평균 → 오늘 진입) 은 r = +0.05 · 나쁜 날 뒤 오히려 +1.32 → 「손실 다음 날 LONG 쉬기」 기각.")
    ds = sorted(long_day)
    pairs = [(long_day[a], long_day[b]) for a, b in zip(ds, ds[1:]) if (b - a).days == 1]
    if len(pairs) >= 5:
        xs, ys = [a for a, _ in pairs], [b for _, b in pairs]
        mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
        den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
        r = sum((x - mx) * (y - my) for x, y in pairs) / den if den else 0.0
        after_bad = [b for a, b in pairs if a < -3]
        after_bad2 = [long_day[c] for a, b, c in zip(ds, ds[1:], ds[2:])
                      if (c - a).days == 2 and long_day[a] < -3 and long_day[b] < -3]
        print(f"이어진 날 짝 {len(pairs)} · 전날→다음날 상관 r = {r:+.2f}")
        print(f"전날 < −3% 다음 날 평균 {sum(after_bad) / len(after_bad):+.2f} (n {len(after_bad)})" if after_bad else "전날 < −3% 다음 날 없음")
        print(f"이틀 연속 < −3% 다음 날 평균 {sum(after_bad2) / len(after_bad2):+.2f} (n {len(after_bad2)})"
              if after_bad2 else "이틀 연속 < −3% 다음 날 없음")
        print(f"전체 날 평균 {sum(long_day.values()) / len(long_day):+.2f} (n {len(long_day)})")

    if SCORE_FROM:
        a, l_, b = pol["A1"]["SHORT"], pol["L"]["SHORT"], pol["무작위"]["SHORT"]
        w, lo_ = h2h["SHORT"]
        print(f"\n## § J 가설 J 판정 (SCORE_FROM {SCORE_FROM}) — A1 SHORT n {len(a)} · L SHORT n {len(l_)} · 맞대결 이긴 {w} / 진 {lo_}")
        if len(a) >= J_MIN_N and len(l_) >= J_MIN_N:
            ma, ml = sum(a) / len(a) - NET, sum(l_) / len(l_) - NET
            mb = (sum(b) / len(b) - NET) if b else None
            ok = ma - ml >= J_MARGIN and (mb is None or ma > mb) and w > lo_
            verdict = "✅ 통과" if ok else ("❌ 기각" if ma - ml <= 0 else "⏳ 보류")
            print(f"A1 순수익 {ma:+.2f} · L {ml:+.2f} · 차 {ma - ml:+.2f}%p · 무작위 {'—' if mb is None else f'{mb:+.2f}'} → {verdict}")
        else:
            print("⏳ 표본 부족 — 판정하지 않음")

    print("\n## 날짜별 (A1 = 운영팀 첫 1건 · L = 지금 실주문 규칙 첫 1건)")
    for x in daily:
        print(x)


main()

"""가설 M — 「세력 그림 S4」 (2026-10-21 사전 등록 · 판정 ≈ 2026-11-15, jk 자동 판정에 함께) — 읽기 전용.

배경([[일봉 세 그림 연구 2026-10-21]], s4_pattern_context_2026_10_21.py): S4 가상(필터 안) 9/18~10/20 을 진입 전날까지 마감한 일봉 그림으로 나누면
  ② 세력 펌프·회귀 +4.22(91건 · 29일 · 앞·뒤 +) · ③ 세력 펌프·덤프 +2.72(30) · 랠리 중간 +2.89(110) · 랠리 없음(평범) +0.54(16, 뒤 절반 −)
  → 같은 기간에서 찾은 것이라 **2026-10-21 KST 이후 진입만**으로 다시 잰다.
그림 판정 = s4_pattern_context_2026_10_21.context() 그대로(진입 전날까지 마감 일봉 · 미래 참조 없음 · 시총 안 씀).
  일봉은 진입 종목마다 공개 klines 150개(무게 2) 한 번씩 · 0.25초 간격.

M1 「평범 문맥 S4 빼기」 (통과 기준 Claude가 정함):
   평범(랠리 없음) 칸 n ≥ 30 · 날 ≥ 8 · 날 평균 순수익의 평균 ≤ 0 · 나머지 칸 날 평균의 평균 > 0 → ✅ 빼기 후보
   평범 칸 날 평균의 평균 > 0 → ❌ 기각(지금 그대로) · 그 밖·표본 미달 → ⏳
M2 「② 문맥 크기 키우기」:
   날마다 (② 칸 평균 − 나머지 칸 평균) 을 두 칸이 모두 있는 날만 · 그런 날 ≥ 12 · 차의 평균 > 0 · 날 묶음 부트스트랩 90% 아래 끝 > 0
   · 앞·뒤 절반 차 모두 > 0 → ✅ 후보(크기는 대표님 결정 — 레버리지·청산 거리 함께 제시) · 차의 평균 ≤ 0 → ❌ · 그 밖 ⏳
순수익 = roi − 0.4. 실주문 반영은 대표님 결정.
수동:  docker compose exec -T -e SCORE_FROM=2026-10-21 api python - < scripts/entry_condition_study/s4_pattern_m_2026_11_15.py
"""
from __future__ import annotations

import bisect
import importlib.util
import os
import random
import sys
import time
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, "/app")

HERE = Path(__file__).resolve().parent if "__file__" in globals() else Path("/app/scripts/entry_condition_study")
NET = 0.4
RULE = "zone_s4_spike_top_short"
KST_OFF = timedelta(hours=9)
SCORE_FROM = os.environ.get("SCORE_FROM") or "2026-10-21"
PLAIN = "랠리 없음(평범)"
PUMP2 = "② 펌프·회귀 후보(급등 랠리)"


def _ctx_mod():
    spec = importlib.util.spec_from_file_location("s4ctx", HERE / "s4_pattern_context_2026_10_21.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def label_rows(rows, klines_of, context):
    """rows = [(symbol, opened_at, net)] → [(kst_date, 그림, net)]. klines_of(symbol) = 일봉 리스트(마감 봉만이어도 됨)."""
    out = []
    for sym, at, net in rows:
        kl = klines_of(sym)
        if not kl:
            continue
        opens = [int(k[0]) for k in kl]
        t = bisect.bisect_right(opens, at.timestamp() * 1000) - 2   # 진입 날 봉 바로 앞 = 전날 마감 봉
        if t < 0:
            continue
        out.append(((at + KST_OFF).date(), context(kl, t), net))
    return out


def boot(xs, n=2000, seed=7):
    rnd = random.Random(seed)
    ms = sorted(sum(rnd.choice(xs) for _ in xs) / len(xs) for _ in range(n))
    return ms[int(n * 0.05)], ms[int(n * 0.95)]


def day_means(lab, keep):
    by = defaultdict(list)
    for d, c, v in lab:
        if keep(c):
            by[d].append(v)
    return {d: sum(v) / len(v) for d, v in by.items()}


def verdict_m1(lab):
    plain = [x for x in lab if x[1] == PLAIN]
    pd = day_means(lab, lambda c: c == PLAIN)
    od = day_means(lab, lambda c: c != PLAIN and c != "자료 부족")
    mp = sum(pd.values()) / len(pd) if pd else None
    mo = sum(od.values()) / len(od) if od else None
    head = f"평범 n {len(plain)} · 날 {len(pd)} · 날 평균 {mp if mp is None else round(mp, 2)} · 나머지 날 평균 {mo if mo is None else round(mo, 2)}"
    if len(plain) < 30 or len(pd) < 8 or mp is None or mo is None:
        return "⏳ 표본 부족", head
    if mp <= 0 < mo:
        return "✅ 평범 문맥 빼기 후보", head
    if mp > 0:
        return "❌ 기각(지금 그대로)", head
    return "⏳ 보류", head


def verdict_m2(lab):
    a = day_means(lab, lambda c: c == PUMP2)
    b = day_means(lab, lambda c: c != PUMP2 and c != "자료 부족")
    days = sorted(set(a) & set(b))
    diffs = [a[d] - b[d] for d in days]
    head = f"두 칸 모두 있는 날 {len(days)}"
    if len(days) < 12:
        return "⏳ 표본 부족", head
    h = len(diffs) // 2
    m, (lo, hi) = sum(diffs) / len(diffs), boot(diffs)
    a1, a2 = sum(diffs[:h]) / h, sum(diffs[h:]) / (len(diffs) - h)
    head += f" · 차의 평균 {m:+.2f} (날 묶음 90% {lo:+.2f}~{hi:+.2f}) · 앞 {a1:+.2f} / 뒤 {a2:+.2f}"
    if m > 0 and lo > 0 and a1 > 0 and a2 > 0:
        return "✅ ② 문맥 크기 키우기 후보", head
    if m <= 0:
        return "❌ 기각", head
    return "⏳ 보류", head


def main():  # pragma: no cover — 운영 DB·거래소 필요
    from sqlalchemy import text
    from app.core.database import SessionLocal
    from app.integrations.binance.client import BinanceClient
    ctx = _ctx_mod().context
    db = SessionLocal()
    try:
        q = text("""select symbol, opened_at, chg_24h, (engines->'live'->>'roi')::float roi from paper_trades
                    where source='live' and status='CLOSED' and rule=:r and engines->'live'->>'roi' is not null
                    and opened_at >= (:d)::date - interval '9 hours' order by opened_at, md5(symbol)""")
        raw = db.execute(q, {"r": RULE, "d": SCORE_FROM}).all()
    finally:
        db.close()
    rows = [(r.symbol, r.opened_at, r.roi - NET) for r in raw
            if r.chg_24h is not None and float(r.chg_24h) >= 10 and (r.opened_at + KST_OFF).date().isoformat() >= SCORE_FROM]
    bc = BinanceClient(api_key="", api_secret="")
    cache: dict = {}

    def klines_of(sym):
        if sym not in cache:
            try:
                cache[sym] = bc.get_klines(symbol=sym, interval="1d", limit=150)
            except Exception:  # noqa: BLE001
                cache[sym] = None
            time.sleep(0.25)
        return cache[sym]

    lab = label_rows(rows, klines_of, ctx)
    print(f"# 가설 M — 세력 그림 S4 (SCORE_FROM {SCORE_FROM} KST) · 필터 안 S4 {len(rows)}건 · 그림 붙은 것 {len(lab)} · 순수익 = roi − {NET}")
    by = defaultdict(list)
    for _d, c, v in lab:
        by[c].append(v)
    for c, v in sorted(by.items()):
        print(f"- {c}: n {len(v)} · 평균 {sum(v) / len(v):+.2f} · 이긴 {sum(x > 0 for x in v) / len(v):.0%}")
    v1, h1 = verdict_m1(lab)
    v2, h2 = verdict_m2(lab)
    print(f"M1 판정: {v1} — {h1}")
    print(f"M2 판정: {v2} — {h2}")


if __name__ == "__main__":
    main()

"""🔄 15분봉 20% 이상 급등락 = 추격 vs **반대매매** 정면 비교 (v144)

사장님 지적 2026-08-14:
  "주식과 반대로 생각해줘. 여기는 급등락하는 알트코인 시장이야.
   15분봉으로 **20% 이상** 급등락은 **반대매매가 유리**해. 다시 확인해줘"

⚠️ 제 이전 결론(v141 「급등은 추격」)의 문제점:
   양의 기대값 셀을 **개수로 세었더니** 10~15% 구간 셀이 훨씬 많아서
   그쪽 성향(추격)이 전체 결론을 지배했습니다.
   사장님이 말씀하신 건 **「20% 이상」** 구간입니다. 거기만 떼어내 다시 셉니다.

측정:
  · 15m 롤링 창(1/2/4시간)에서 **20% 이상** 이동한 이벤트만 수집
  · 강도 밴드별(20~25 / 25~30 / 30~40 / 40~60 / 60%+)로 분리
  · 같은 이벤트에 대해 **추격**과 **반대매매**를 나란히 놓고 TP/SL 선착 비교
  · 강도가 올라갈수록 어느 쪽이 유리해지는지 = **교차점**을 찾습니다

사용:
    python scripts/study_15m_counter_trade.py --cache15m <klines_cache>
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.study_pump_dump_20pct import first_touch  # noqa: E402

WINDOWS = [("1시간", 4), ("2시간", 8), ("4시간", 16)]
BANDS = [(20, 25), (25, 30), (30, 40), (40, 60), (60, 9999)]
# ⚠️ 격자가 한쪽에 유리하면 결론이 왜곡됩니다.
#    추세추종형(큰 TP + 작은 SL)과 평균회귀형(작은 TP + 넓은 SL)을 **둘 다** 넣습니다.
TP_SL = [
    # 평균회귀형 (반대매매에 유리한 구조)
    (2.0, 5.0), (2.0, 8.0), (3.0, 5.0), (3.0, 8.0), (5.0, 8.0), (5.0, 10.0),
    # 대칭
    (3.0, 3.0), (5.0, 5.0),
    # 추세추종형 (추격에 유리한 구조)
    (5.0, 3.0), (8.0, 5.0), (10.0, 5.0), (15.0, 7.0),
]
FT_BARS = 16          # 4시간 내 판정
MIN_N = 30


def detect(closes, window, lo, hi, sign):
    """밴드 안 급등(+1)/급락(-1) 이벤트 (쿨다운 = 창 길이)."""
    out, cd = [], 0
    for i in range(window, len(closes)):
        if cd > 0:
            cd -= 1
            continue
        base = closes[i - window]
        if base <= 0:
            continue
        chg = (closes[i] - base) / base * 100
        if lo <= abs(chg) < hi and (chg > 0) == (sign > 0):
            out.append(i)
            cd = window
    return out


def run(files):
    # acc[(kind, band, window, mode, tp, sl)] = {TP,SL,NONE}
    acc: dict = defaultdict(lambda: {"TP": 0, "SL": 0, "NONE": 0})
    counts: dict = defaultdict(int)
    fwd: dict = defaultdict(list)

    for f in files:
        try:
            d = json.load(open(f))
            kl = d.get("15m") if isinstance(d, dict) else d
            if not isinstance(kl, list) or len(kl) < 60:
                continue
        except Exception:
            continue
        highs = [float(k[2]) for k in kl]
        lows = [float(k[3]) for k in kl]
        closes = [float(k[4]) for k in kl]
        n = len(kl)

        for sign, kind in ((+1, "급등"), (-1, "급락")):
            for wlabel, window in WINDOWS:
                for lo, hi in BANDS:
                    for i in detect(closes, window, lo, hi, sign):
                        entry = closes[i]
                        if entry <= 0 or i + FT_BARS >= n:
                            continue
                        counts[(kind, (lo, hi), wlabel)] += 1
                        # 이후 4시간 가격 변화 (부호 그대로)
                        fwd[(kind, (lo, hi), wlabel)].append(
                            (closes[min(i + FT_BARS, n - 1)] - entry) / entry * 100)

                        # 추격 = 급등이면 LONG / 급락이면 SHORT
                        # 반대 = 그 반대
                        for mode, is_long in (
                            ("추격", sign > 0),
                            ("반대", sign < 0),
                        ):
                            for tp, sl in TP_SL:
                                r = first_touch(highs, lows, i, entry, tp, sl,
                                                is_long, FT_BARS)
                                acc[(kind, (lo, hi), wlabel, mode, tp, sl)][r] += 1
    return acc, counts, fwd


def best(acc, kind, band, wlabel, mode):
    out = None
    for (tp, sl) in TP_SL:
        st = acc.get((kind, band, wlabel, mode, tp, sl))
        if not st:
            continue
        tot = st["TP"] + st["SL"] + st["NONE"]
        if tot < MIN_N:
            continue
        ev = (st["TP"] * tp - st["SL"] * sl) / tot
        if out is None or ev > out[0]:
            out = (ev, tp, sl, st["TP"] / tot * 100, tot)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache15m", required=True)
    args = ap.parse_args()
    files = sorted(glob.glob(os.path.join(args.cache15m, "*.json")))

    acc, counts, fwd = run(files)

    print("=" * 92)
    print("🔄 15분봉 **20% 이상** 급등락 — 추격 vs 반대매매 정면 비교")
    print("   (기대값 = TP확률×TP − SL확률×SL, 4시간 내 선착, 같은 봉이면 SL 우선)")
    print(f"   심볼 {len(files)}개 / 표본 {MIN_N}건 미만 구간은 생략")
    print("=" * 92)

    for kind in ("급등", "급락"):
        print(f"\n{'#'*92}\n## {kind} (20% 이상)\n{'#'*92}")
        for wlabel, _ in WINDOWS:
            rows = []
            for band in BANDS:
                n = counts.get((kind, band, wlabel), 0)
                if n < MIN_N:
                    continue
                ch = best(acc, kind, band, wlabel, "추격")
                cn = best(acc, kind, band, wlabel, "반대")
                if not ch or not cn:
                    continue
                f4 = fwd.get((kind, band, wlabel)) or []
                med = sorted(f4)[len(f4) // 2] if f4 else 0.0
                rows.append((band, n, med, ch, cn))
            if not rows:
                continue
            print(f"\n▶ 창 = {wlabel}")
            print(f"   {'강도':<11}{'건수':>6}{'+4h중앙':>9} | "
                  f"{'추격 최적':<11}{'TP율':>7}{'기대값':>9} | "
                  f"{'반대 최적':<11}{'TP율':>7}{'기대값':>9} | 승자")
            print("   " + "-" * 88)
            for band, n, med, ch, cn in rows:
                lbl = f"{band[0]}~{band[1]}%" if band[1] < 9999 else f"{band[0]}%+"
                ch_s = f"+{ch[1]:.0f}/-{ch[2]:.0f}"
                cn_s = f"+{cn[1]:.0f}/-{cn[2]:.0f}"
                if cn[0] > ch[0] + 0.05:
                    win = "🔄 반대매매"
                elif ch[0] > cn[0] + 0.05:
                    win = "➡️ 추격"
                else:
                    win = "= 비슷"
                print(f"   {lbl:<11}{n:>6}{med:>8.2f}% | "
                      f"{ch_s:<11}{ch[3]:>6.1f}%{ch[0]:>+8.2f}% | "
                      f"{cn_s:<11}{cn[3]:>6.1f}%{cn[0]:>+8.2f}% | {win}")

    # ---------- 20% 이상 전체 집계 ----------
    print("\n" + "=" * 92)
    print("📊 20% 이상 **전체 합산** — 어느 쪽이 이기는가")
    print("=" * 92)
    for kind in ("급등", "급락"):
        for wlabel, _ in WINDOWS:
            agg = {}
            for mode in ("추격", "반대"):
                tot_ev = tot_n = 0
                for (tp, sl) in TP_SL:
                    st_sum = {"TP": 0, "SL": 0, "NONE": 0}
                    for band in BANDS:
                        st = acc.get((kind, band, wlabel, mode, tp, sl))
                        if st:
                            for k in st_sum:
                                st_sum[k] += st[k]
                    tot = sum(st_sum.values())
                    if tot < MIN_N:
                        continue
                    ev = (st_sum["TP"] * tp - st_sum["SL"] * sl) / tot
                    if mode not in agg or ev > agg[mode][0]:
                        agg[mode] = (ev, tp, sl, st_sum["TP"] / tot * 100, tot)
            if "추격" not in agg or "반대" not in agg:
                continue
            ch, cn = agg["추격"], agg["반대"]
            win = "🔄 **반대매매**" if cn[0] > ch[0] else "➡️ 추격"
            print(f"  {kind} · {wlabel:<5} (n={ch[4]:,}) | "
                  f"추격 +{ch[1]:.0f}/-{ch[2]:.0f} {ch[0]:+.2f}%  vs  "
                  f"반대 +{cn[1]:.0f}/-{cn[2]:.0f} {cn[0]:+.2f}%  → {win}")
    print()


if __name__ == "__main__":
    main()

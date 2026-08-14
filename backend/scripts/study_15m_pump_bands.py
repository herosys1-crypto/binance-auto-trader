"""🔬 15분봉 급등락 「밴드별」 성과 분석 (v141a)

사장님 지시 2026-08-14:
  "15분봉 급등락은 20% 전후만 흐름을 급등락 실시간 진입 전략으로 알려줘"

= 15m 은 **20% 전후 구간만** 쓰겠다는 뜻.
  그래서 「전후」 범위를 추측하지 않고 **밴드별로 잘라서** 어디가 진짜 좋은지 셉니다.

기존 study_pump_dump_20pct.py 는 「임계값 이상(>=)」 방식이라 20%와 40%가 섞였습니다.
이 스크립트는 **[하한, 상한) 밴드**로 분리해 각 구간을 독립 평가합니다.

사용:
    python scripts/study_15m_pump_bands.py --cache15m <klines_cache>
    # 밴드를 직접 지정 (v147d — 사장님 상한 확대 결정 재측정용)
    python scripts/study_15m_pump_bands.py --cache15m <c> --bands 17.5:22.5,22.5:27.5,17.5:27.5
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

# 15m 롤링 창
WINDOWS = [("1시간", 4), ("2시간", 8), ("4시간", 16)]
# 변동폭 밴드 [하한, 상한)
BANDS = [(10, 15), (15, 17.5), (17.5, 22.5), (22.5, 27.5), (27.5, 35), (35, 999)]
TP_SL = [(5.0, 3.0), (5.0, 5.0), (10.0, 5.0), (15.0, 7.0)]
FT_BARS = 16          # 4시간
FWD = [("+1시간", 4), ("+2시간", 8), ("+4시간", 16)]


def band_label(lo: float, hi: float) -> str:
    return f"{lo:g}~{hi:g}%" if hi < 999 else f"{lo:g}%+"


def detect_band_events(closes, window, lo, hi):
    """롤링 창 변동이 [lo, hi) 밴드에 들어오는 첫 지점 (쿨다운 = 창 길이)."""
    events = []
    cooldown = 0
    for i in range(window, len(closes)):
        if cooldown > 0:
            cooldown -= 1
            continue
        base = closes[i - window]
        if base <= 0:
            continue
        chg = (closes[i] - base) / base * 100
        if lo <= abs(chg) < hi:
            events.append((i, chg))
            cooldown = window
    return events


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache15m", required=True)
    ap.add_argument(
        "--bands", default=None,
        help='밴드 직접 지정 "lo:hi,lo:hi" (미지정 시 기본 BANDS). '
             '겹치는 밴드도 허용 — 합친 밴드와 구성 밴드를 한 번에 비교할 때 씁니다.',
    )
    ap.add_argument("--min-n", type=int, default=40, help="판정 보류 기준 표본 수")
    args = ap.parse_args()

    global BANDS
    if args.bands:
        BANDS = [tuple(float(x) for x in b.split(":")) for b in args.bands.split(",")]

    files = sorted(glob.glob(os.path.join(args.cache15m, "*.json")))
    acc: dict = defaultdict(lambda: {
        "n": 0, "ft": defaultdict(lambda: {"TP": 0, "SL": 0, "NONE": 0}),
        "fwd": defaultdict(list),
    })

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

        for wlabel, window in WINDOWS:
            for lo, hi in BANDS:
                for i, chg in detect_band_events(closes, window, lo, hi):
                    kind = "급등" if chg > 0 else "급락"
                    key = (wlabel, band_label(lo, hi), kind)
                    b = acc[key]
                    b["n"] += 1
                    entry = closes[i]
                    for flabel, fb in FWD:
                        if i + fb < len(closes):
                            b["fwd"][flabel].append((closes[i + fb] - entry) / entry * 100)
                    for tp, sl in TP_SL:
                        for dl, is_long in (("LONG", True), ("SHORT", False)):
                            r = first_touch(highs, lows, i, entry, tp, sl, is_long, FT_BARS)
                            b["ft"][(dl, tp, sl)][r] += 1

    print("=" * 84)
    print("🔬 15분봉 급등락 밴드별 성과 — 「20% 전후」가 정말 좋은지 확인")
    print("   (기대값 = TP확률×TP − SL확률×SL, 수수료 차감 전 / 4시간 내 선착 판정)")
    print("=" * 84)

    for kind in ("급등", "급락"):
        print(f"\n{'#'*84}\n## {kind}\n{'#'*84}")
        for wlabel, _ in WINDOWS:
            print(f"\n▶ 창 = {wlabel}")
            print(f"   {'밴드':<12}{'건수':>7}{'+2시간중앙':>11}  "
                  f"{'최적 TP/SL':<12}{'방향':<7}{'TP선착':>8}{'기대값':>9}")
            print("   " + "-" * 72)
            for lo, hi in BANDS:
                key = (wlabel, band_label(lo, hi), kind)
                b = acc.get(key)
                if not b or b["n"] < args.min_n:   # 표본 부족은 판정 보류
                    if b:
                        print(f"   {band_label(lo,hi):<12}{b['n']:>7}   (표본 부족)")
                    continue
                fwd2 = sorted(b["fwd"].get("+2시간") or [])
                med2 = fwd2[len(fwd2) // 2] if fwd2 else 0.0

                best = None
                for (dl, tp, sl), st in b["ft"].items():
                    tot = st["TP"] + st["SL"] + st["NONE"]
                    if not tot:
                        continue
                    ev = (st["TP"] * tp - st["SL"] * sl) / tot
                    cand = (ev, dl, tp, sl, st["TP"] / tot * 100)
                    if best is None or ev > best[0]:
                        best = cand
                ev, dl, tp, sl, tpr = best
                mark = " ⭐" if ev > 0 else ""
                print(f"   {band_label(lo,hi):<12}{b['n']:>7}{med2:>10.2f}%  "
                      f"{'+'+str(int(tp))+'%/-'+str(int(sl))+'%':<12}{dl:<7}{tpr:>7.1f}%{ev:>+8.2f}%{mark}")
    print()


if __name__ == "__main__":
    main()

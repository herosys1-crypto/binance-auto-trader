"""🔄 15분봉 20%+ 급등락 「소진 후 반대매매」 검증 (v144b)

사장님: "15분봉으로 20% 이상 급등락은 반대매매가 유리해"

앞선 검증(study_15m_counter_trade.py)은 **20%를 넘는 그 순간**(= 움직임 도중)에
진입해서 비교했습니다. 그런데 사장님 말씀은 **급등이 끝난 뒤 반대로 친다**는
뜻일 수 있습니다. 진입 시점이 다르면 결과가 완전히 달라집니다.

그래서 3가지 진입 시점을 **같은 이벤트**에 대해 나란히 비교합니다:

  [A] 도중 진입   : 20% 돌파 순간 바로 반대매매
  [B] 소진 확인   : 고점 형성 후 **직전 봉 저가 이탈**(하락 전환 확인) 시 반대매매
  [C] 되돌림 대기 : 고점 대비 X% 되돌린 뒤 반대매매 (추격 실패 확인)

판정 구간도 4시간 / 12시간 두 가지로 봅니다 (평균회귀는 느릴 수 있음).

사용:
    python scripts/study_15m_counter_after_peak.py --cache15m <klines_cache>
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
MIN_MOVE = 20.0        # 사장님 기준: 20% 이상
PEAK_SEARCH = 8        # 20% 돌파 후 고점 탐색 (2시간)
TP_SL = [
    (2.0, 5.0), (3.0, 5.0), (3.0, 8.0), (5.0, 5.0),
    (5.0, 8.0), (5.0, 3.0), (8.0, 5.0), (10.0, 5.0),
]
HORIZONS = [("4시간", 16), ("12시간", 48)]
MIN_N = 30


def detect(closes, window, sign):
    out, cd = [], 0
    for i in range(window, len(closes)):
        if cd > 0:
            cd -= 1
            continue
        base = closes[i - window]
        if base <= 0:
            continue
        chg = (closes[i] - base) / base * 100
        if abs(chg) >= MIN_MOVE and (chg > 0) == (sign > 0):
            out.append(i)
            cd = window
    return out


def run(files):
    acc: dict = defaultdict(lambda: {"TP": 0, "SL": 0, "NONE": 0})
    n_entry: dict = defaultdict(int)
    n_event: dict = defaultdict(int)

    for f in files:
        try:
            d = json.load(open(f))
            kl = d.get("15m") if isinstance(d, dict) else d
            if not isinstance(kl, list) or len(kl) < 80:
                continue
        except Exception:
            continue
        highs = [float(k[2]) for k in kl]
        lows = [float(k[3]) for k in kl]
        closes = [float(k[4]) for k in kl]
        n = len(kl)

        for sign, kind in ((+1, "급등"), (-1, "급락")):
            for wlabel, window in WINDOWS:
                for i in detect(closes, window, sign):
                    n_event[(kind, wlabel)] += 1
                    is_long = sign < 0     # 반대매매! 급등이면 SHORT, 급락이면 LONG

                    # [A] 도중 진입
                    entries = {"A_도중": i}

                    # ⚠️ 미래 참조 금지!
                    #    「극점」을 i..i+8 전체에서 찾으면 진입 시점에 알 수 없는
                    #    미래 고점을 쓰는 셈입니다. 실시간에서 알 수 있는 것은
                    #    **지금까지의 최고/최저(running extreme)** 뿐입니다.
                    run_ext = highs[i] if sign > 0 else lows[i]
                    found_b = found_c = False
                    for j in range(i + 1, min(i + 1 + PEAK_SEARCH + 8, n)):
                        # j-1 까지의 running extreme 으로만 판단 (j 시점에 알 수 있는 값!)
                        if sign > 0:
                            turned = closes[j] < lows[j - 1]
                            back = (lows[j] - run_ext) / run_ext * 100
                            deep = back <= -3.0
                        else:
                            turned = closes[j] > highs[j - 1]
                            back = (highs[j] - run_ext) / run_ext * 100
                            deep = back >= 3.0
                        if turned and not found_b:
                            entries["B_소진확인"] = j
                            found_b = True
                        if deep and not found_c:
                            entries["C_되돌림3%"] = j
                            found_c = True
                        if found_b and found_c:
                            break
                        # running extreme 갱신 (j 봉 반영 = 다음 루프부터 유효)
                        run_ext = max(run_ext, highs[j]) if sign > 0 else min(run_ext, lows[j])

                    for mode, idx in entries.items():
                        entry = closes[idx]
                        if entry <= 0:
                            continue
                        n_entry[(kind, wlabel, mode)] += 1
                        for hlabel, hbars in HORIZONS:
                            if idx + hbars >= n:
                                continue
                            for tp, sl in TP_SL:
                                r = first_touch(highs, lows, idx, entry, tp, sl,
                                                is_long, hbars)
                                acc[(kind, wlabel, mode, hlabel, tp, sl)][r] += 1
    return acc, n_entry, n_event


def best(acc, key_prefix):
    out = None
    for (tp, sl) in TP_SL:
        st = acc.get(key_prefix + (tp, sl))
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
    acc, n_entry, n_event = run(files)

    print("=" * 96)
    print(f"🔄 15분봉 {MIN_MOVE:.0f}% 이상 급등락 — **반대매매** 진입 시점별 비교")
    print("   [A] 20% 돌파 순간  [B] 전환 확인  [C] **직전 최고점(running) 대비 3% 되돌림** — 미래참조 X")
    print(f"   심볼 {len(files)}개 / 표본 {MIN_N}건 미만 생략 / 같은 봉이면 SL 우선(보수적)")
    print("=" * 96)

    for kind in ("급등", "급락"):
        cw = "SHORT" if kind == "급등" else "LONG"
        print(f"\n{'#'*96}\n## {kind} {MIN_MOVE:.0f}% 이상 → 반대매매 = **{cw}**\n{'#'*96}")
        for wlabel, _ in WINDOWS:
            ev_n = n_event.get((kind, wlabel), 0)
            if ev_n < MIN_N:
                continue
            print(f"\n▶ 창 = {wlabel} (이벤트 {ev_n:,}건)")
            print(f"   {'진입시점':<12}{'판정':<8}{'진입':>7}{'최적 TP/SL':<12}"
                  f"{'TP율':>8}{'기대값':>9}")
            print("   " + "-" * 60)
            for mode in ("A_도중", "B_소진확인", "C_되돌림3%"):
                for hlabel, _ in HORIZONS:
                    b = best(acc, (kind, wlabel, mode, hlabel))
                    if not b:
                        continue
                    ev, tp, sl, tpr, tot = b
                    mark = " ⭐" if ev > 0 else ""
                    print(f"   {mode:<12}{hlabel:<8}{tot:>7}"
                          f"{'+'+str(int(tp))+'/-'+str(int(sl)):<12}"
                          f"{tpr:>7.1f}%{ev:>+8.2f}%{mark}")
    print()


if __name__ == "__main__":
    main()

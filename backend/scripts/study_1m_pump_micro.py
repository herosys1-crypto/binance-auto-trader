"""🔬 1분봉 미시구조로 「지속 vs 전환」 판별력 향상 시도 (v146b)

사장님: "20% 이상 급등하는 심볼을 **1분 5분 차트**를 보고 1차 진입을 결정해야 해"

v146(5분봉만)에서는 조합으로 41:49 → 53:35 까지 갈랐습니다.
여기에 **1분봉 미시구조**를 더하면 더 갈라지는지 확인합니다.

1분봉에서만 보이는 것들:
  · 마지막 5분 안에서의 **초단기 가속** (1m 단위 상승 분포)
  · **매수 흡수** = 큰 음봉이 나와도 바로 되받는가 (하락봉 회복률)
  · **거래량 집중도** = 최근 5분 거래량이 몇 개 봉에 몰렸나 (한 방 vs 지속)
  · **윗꼬리 누적** = 위에서 계속 눌리는가
  · **연속성** = 1m 양봉 비율

판정은 v146과 동일 (5m 기준 20% 급등 → 6시간 내 ±10% 선착).

사용:
    python scripts/study_1m_pump_micro.py --cache5m <5m캐시> --cache1m <1m캐시>
"""
from __future__ import annotations

import argparse
import bisect
import glob
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.study_pump_continuation import (  # noqa: E402
    FWD_BARS, WINDOW_5M, detect, features, first_side,
)

MIN_N = 20
LOOK_1M = 30       # 트리거 직전 30분 (1m 30봉)


def micro_features(o, h, l, c, v, idx) -> dict:
    """1분봉 미시구조 특징 (idx = 트리거 시점의 1m 인덱스, 그 이전만 사용)."""
    s = max(0, idx - LOOK_1M + 1)
    O, H, L, C, V = o[s:idx + 1], h[s:idx + 1], l[s:idx + 1], c[s:idx + 1], v[s:idx + 1]
    n = len(C)
    if n < 10:
        return {}

    # 1) 1m 양봉 비율 (연속성)
    up_ratio = sum(1 for i in range(n) if C[i] > O[i]) / n

    # 2) 매수 흡수 = 음봉 다음 봉이 그 음봉 종가를 회복한 비율
    rec = tot = 0
    for i in range(n - 1):
        if C[i] < O[i]:
            tot += 1
            if C[i + 1] > O[i]:
                rec += 1
    absorb = (rec / tot) if tot else 1.0

    # 3) 거래량 집중도 = 최근 5봉 거래량 / 30봉 거래량 (한 방인가 지속인가)
    v_all = sum(V)
    concentration = (sum(V[-5:]) / v_all) if v_all > 0 else 0.0

    # 4) 윗꼬리 누적 = 봉 범위 대비 윗꼬리 평균
    wicks = []
    for i in range(n):
        rng = H[i] - L[i]
        if rng > 0:
            wicks.append((H[i] - max(O[i], C[i])) / rng)
    upper_wick = sum(wicks) / len(wicks) if wicks else 0.0

    # 5) 초단기 가속 = 최근 5분 상승률 − 그 이전 10분 상승률
    def chg(a, b):
        return (C[b] - C[a]) / C[a] * 100 if C[a] else 0.0
    micro_accel = chg(n - 6, n - 1) - (chg(n - 16, n - 6) if n >= 16 else 0.0)

    return {
        "up_ratio": up_ratio,
        "absorb": absorb,
        "concentration": concentration,
        "upper_wick": upper_wick,
        "micro_accel": micro_accel,
    }


def bucket(name, val):
    if name == "up_ratio":
        return ("양봉<50%", "양봉50~65%", "양봉65%+")[
            0 if val < 0.5 else 1 if val < 0.65 else 2]
    if name == "absorb":
        return ("흡수<40%", "흡수40~60%", "흡수60%+")[
            0 if val < 0.4 else 1 if val < 0.6 else 2]
    if name == "concentration":
        return ("분산<25%", "보통25~40%", "집중40%+")[
            0 if val < 0.25 else 1 if val < 0.40 else 2]
    if name == "upper_wick":
        return ("윗꼬리<20%", "윗꼬리20~35%", "윗꼬리35%+")[
            0 if val < 0.20 else 1 if val < 0.35 else 2]
    if name == "micro_accel":
        return ("초단기<0", "초단기0~2", "초단기2%+")[
            0 if val < 0 else 1 if val < 2 else 2]
    return "?"


MICRO = ["up_ratio", "absorb", "concentration", "upper_wick", "micro_accel"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache5m", required=True)
    ap.add_argument("--cache1m", required=True)
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.cache5m, "*.json")))
    events = []
    missing_1m = 0

    for f5 in files:
        sym = Path(f5).stem
        f1 = os.path.join(args.cache1m, f"{sym}.json")
        if not os.path.exists(f1):
            missing_1m += 1
            continue
        try:
            k5 = json.load(open(f5))
            k1 = json.load(open(f1))
            if not isinstance(k5, list) or not isinstance(k1, list):
                continue
            if len(k5) < WINDOW_5M + FWD_BARS + 40 or len(k1) < 100:
                continue
        except Exception:
            continue

        o5 = [float(k[1]) for k in k5]; h5 = [float(k[2]) for k in k5]
        l5 = [float(k[3]) for k in k5]; c5 = [float(k[4]) for k in k5]
        v5 = [float(k[5]) for k in k5]
        t5 = [int(k[0]) for k in k5]

        t1 = [int(k[0]) for k in k1]
        o1 = [float(k[1]) for k in k1]; h1 = [float(k[2]) for k in k1]
        l1 = [float(k[3]) for k in k1]; c1 = [float(k[4]) for k in k1]
        v1 = [float(k[5]) for k in k1]

        for i in detect(c5, WINDOW_5M):
            if i < 30 or i + FWD_BARS >= len(k5):
                continue
            # 1m 인덱스 정렬 (트리거 5m 봉의 시작 시각 이하 마지막 1m 봉)
            j = bisect.bisect_right(t1, t5[i]) - 1
            if j < LOOK_1M:
                continue
            mf = micro_features(o1, h1, l1, c1, v1, j)
            if not mf:
                continue
            f5f = features(o5, h5, l5, c5, v5, i, WINDOW_5M)
            events.append({
                "f5": f5f, "m1": mf,
                "side": first_side(h5, l5, i, c5[i], 10, 10, FWD_BARS),
            })

    n = len(events)
    print("=" * 88)
    print(f"🔬 1분봉 미시구조 판별력 검증 — 이벤트 {n:,}건 (1m 없는 심볼 {missing_1m}개 제외)")
    print("=" * 88)
    if n < MIN_N:
        print("표본 부족")
        return
    base = sum(1 for e in events if e["side"] == "UP") / n * 100
    print(f"\n기저 지속률 = {base:.1f}%")

    print("\n### 1분봉 단독 특징")
    print(f"   {'특징':<16}{'구간':<16}{'건수':>7}{'지속률':>9}{'배수':>8}")
    print("   " + "-" * 56)
    for name in MICRO:
        g = defaultdict(list)
        for e in events:
            g[bucket(name, e["m1"][name])].append(e)
        for k in sorted(g):
            rows = g[k]
            if len(rows) < MIN_N:
                continue
            up = sum(1 for e in rows if e["side"] == "UP")
            r = up / len(rows) * 100
            mark = " ⭐" if r >= base * 1.3 else (" 🔻" if r <= base * 0.7 else "")
            print(f"   {name:<16}{k:<16}{len(rows):>7}{r:>8.1f}%"
                  f"{r/base if base else 0:>7.2f}x{mark}")

    print("\n### 🎯 v146 조합(5m) + 1분봉 추가 효과")
    def show(label, cond):
        sel = [e for e in events if cond(e)]
        if len(sel) < 15:
            print(f"   {label:<42} n={len(sel):<4} (표본부족)")
            return
        up = sum(1 for e in sel if e["side"] == "UP")
        dn = sum(1 for e in sel if e["side"] == "DOWN")
        r = up / len(sel) * 100
        print(f"   {label:<42} n={len(sel):<4} 지속 {r:5.1f}% ({r/base:.2f}x)  전환 {dn/len(sel)*100:5.1f}%")

    v146_cont = lambda e: e["f5"]["vol_ratio"] >= 4 and e["f5"]["close_pos"] >= 0.7
    v146_rev = lambda e: e["f5"]["accel"] < 0 and e["f5"]["vol_ratio"] < 1
    print("   [지속 신호]")
    show("v146 단독 (거래량4+ AND 종가상단)", v146_cont)
    show("  + 1m 양봉비율 65%+", lambda e: v146_cont(e) and e["m1"]["up_ratio"] >= 0.65)
    show("  + 1m 흡수 60%+", lambda e: v146_cont(e) and e["m1"]["absorb"] >= 0.6)
    show("  + 1m 윗꼬리 20% 미만", lambda e: v146_cont(e) and e["m1"]["upper_wick"] < 0.20)
    show("  + 1m 초단기가속 0 이상", lambda e: v146_cont(e) and e["m1"]["micro_accel"] >= 0)
    print("   [전환 신호]")
    show("v146 단독 (가속<0 AND 거래량<1)", v146_rev)
    show("  + 1m 윗꼬리 35%+", lambda e: v146_rev(e) and e["m1"]["upper_wick"] >= 0.35)
    show("  + 1m 양봉비율 50% 미만", lambda e: v146_rev(e) and e["m1"]["up_ratio"] < 0.5)
    print()


if __name__ == "__main__":
    main()

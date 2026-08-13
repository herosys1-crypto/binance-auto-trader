"""✅ BBTopAnalyzer 구현 검증 (v140)

연구(study_15m_top_bbmid.py)에서 나온 적중률을 **실제 분석기 코드**가
재현하는지 확인합니다. 연구 스크립트와 서비스 코드가 따로 놀면
「문서상 38%인데 실제론 다른」 전형적 silent bug가 되기 때문입니다.

방법:
  캐시된 과거 캔들을 시점별로 잘라 BBTopAnalyzer.analyze() 를 그대로 호출하고
  (미래 참조 없음), 같은 라벨 정의로 실제 천장이었는지 대조합니다.

사용:
    python scripts/validate_bb_top_analyzer.py --cache <klines_cache> --symbols 40
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

from app.services.bb_top_analyzer import BBTopAnalyzer  # noqa: E402

PIVOT_K = 8
FWD_BARS = 8
DROP_PCT = 1.5
WINDOW = 200        # 분석기에 넣을 캔들 수 (KLINE_LIMIT 과 동일)
STEP = 7            # 표본 추출 간격 (전수 조사는 너무 느림)


def is_top(highs, lows, i) -> bool:
    win_hi = max(highs[i - PIVOT_K: i + PIVOT_K + 1])
    if highs[i] < win_hi - 1e-12:
        return False
    fwd_low = min(lows[i + 1: i + 1 + FWD_BARS])
    return (fwd_low - highs[i]) / highs[i] * 100 <= -DROP_PCT


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--symbols", type=int, default=40)
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.cache, "*.json")))[: args.symbols]
    analyzer = BBTopAnalyzer(None)

    by_grade: dict[str, list[int]] = defaultdict(lambda: [0, 0])   # [건수, 천장]
    by_div: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    mid_target: list[float] = []
    total = tops = 0

    for n, f in enumerate(files, 1):
        d = json.load(open(f))
        k15, k1h, k4h = d.get("15m") or [], d.get("1h") or [], d.get("4h") or []
        if len(k15) < WINDOW + FWD_BARS + PIVOT_K + 10:
            continue
        highs = [float(k[2]) for k in k15]
        lows = [float(k[3]) for k in k15]

        for i in range(WINDOW, len(k15) - FWD_BARS - 1, STEP):
            res = analyzer.analyze(
                "TEST", "SHORT",
                klines_15m=k15[i - WINDOW + 1: i + 1],
                klines_1h=k1h, klines_4h=k4h,
            )
            if not res.get("available"):
                continue
            label = is_top(highs, lows, i)
            total += 1
            tops += label
            g = res["grade"]
            by_grade[g][0] += 1
            by_grade[g][1] += label
            by_div[res.get("div_count", 0)][0] += 1
            by_div[res.get("div_count", 0)][1] += label
            if g in ("S", "A"):
                t = (res.get("levels") or {}).get("tp1_target_pct")
                if t:
                    mid_target.append(t)

        if n % 10 == 0:
            print(f"  ... {n}/{len(files)} 심볼 (표본 {total:,})", flush=True)

    base = tops / total * 100 if total else 0
    print("\n" + "=" * 68)
    print(f"✅ BBTopAnalyzer 구현 검증 — 표본 {total:,}개 (심볼 {len(files)}개)")
    print(f"   기저 발생률 = {tops:,}/{total:,} = {base:.2f}%")
    print("=" * 68)

    print(f"\n{'등급':<8}{'건수':>10}{'천장적중':>10}{'배수':>9}{'연구값':>12}")
    print("-" * 52)
    expect = {"S": "38.5%", "A": "32.2%", "B": "29.2%", "C": "25.2%", "D": "—"}
    for g in ("S", "A", "B", "C", "D"):
        cnt, hit = by_grade[g]
        if not cnt:
            continue
        p = hit / cnt * 100
        print(f"{g:<8}{cnt:>10,}{p:>9.2f}%{p/base if base else 0:>8.2f}x{expect[g]:>12}")

    print(f"\n{'다이버전스 수':<14}{'건수':>10}{'천장적중':>10}{'배수':>9}")
    print("-" * 44)
    for k in sorted(by_div):
        cnt, hit = by_div[k]
        p = hit / cnt * 100 if cnt else 0
        print(f"{k}개{'':<11}{cnt:>10,}{p:>9.2f}%{p/base if base else 0:>8.2f}x")

    if mid_target:
        s = sorted(mid_target)
        print(f"\nS/A 등급 진입 시 BB중단까지 거리: 중앙값 {s[len(s)//2]:.2f}% / "
              f"평균 {sum(s)/len(s):.2f}%  (n={len(s):,})")
    print()


if __name__ == "__main__":
    main()

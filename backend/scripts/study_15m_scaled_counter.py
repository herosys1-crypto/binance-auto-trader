"""📊 20%+ 급등락 「분할 진입 역추세」 전략 검증 (v145)

사장님 전략 설명 2026-08-14:
  "20% 이상 급등락하면 빠르게 분할 매수해서 평균이상가 진입을 한 후,
   안정적으로 하락과 상승하면 추가로 진입해서 물량을 확보해서
   안정적인 수익을 만드는 전략이야"

= 단일 진입 + 고정 TP/SL 이 아니라 **단계별 분할 진입으로 평단을 개선**하는 전략.
  우리 시스템의 「단계별 진입」 구조와 정확히 일치합니다.

⚠️ 이 전략은 **성공률이 높게 보이지만 실패 시 손실이 큽니다**.
   v139 백테스트에서 실제로 확인됐습니다:
     9단계 이상 물타기 8건이 **전체 손실의 43%(-9,762 USDT)** 를 만들었음.
   그래서 「성공률」만 보면 안 되고 **실패 케이스의 크기**를 반드시 함께 봐야 합니다.

측정:
  1. 15m 20%+ 급등락 이벤트 → 역방향(급등=SHORT / 급락=LONG) 1단계 진입
  2. 역행할 때마다 STEP% 간격으로 추가 진입 (최대 MAX_STAGES 단계)
  3. **평단 기준** 수익이 TP% 도달하면 성공, 관찰 기간 내 미도달이면 실패
  4. 실패 시 = 최종 평단 손실 + 투입 자본 배수를 기록

산출:
  · 익절 도달률 / 소요 시간
  · 사용 단계 수 분포 (몇 단계까지 갔나)
  · **실패 시 평단 손실** (진짜 위험!)
  · 자본 배수 (1단계 대비 몇 배 투입했나)
  · 기대값 = 성공확률×TP − 실패확률×평균손실

사용:
    python scripts/study_15m_scaled_counter.py --cache15m <klines_cache>
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import defaultdict

WINDOWS = [("1시간", 4), ("2시간", 8), ("4시간", 16)]
MIN_MOVE = 20.0
# 추가 진입 간격(역행 %) × 최대 단계 수
PLANS = [
    ("3%×3단계", 3.0, 3),
    ("3%×5단계", 3.0, 5),
    ("5%×3단계", 5.0, 3),
    ("5%×5단계", 5.0, 5),
    ("5%×7단계", 5.0, 7),
    ("8%×5단계", 8.0, 5),
]
TP_TARGETS = [1.0, 2.0, 3.0]      # 평단 대비 익절 %
HOLD_BARS = 96                    # 관찰 24시간 (15m × 96)
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


def simulate(highs, lows, closes, i, is_long, step, max_stages, tp, n):
    """분할 진입 시뮬레이션.

    각 단계 자본은 **동일**로 가정 (물타기 배수를 쓰면 위험이 더 커짐).
    Returns: (성공?, 소요봉, 사용단계, 평단대비최악손실%, 최종손익%)
    """
    entry0 = closes[i]
    fills = [entry0]                       # 체결가 리스트 (동일 자본)
    next_add = entry0 * (1 + step / 100) if not is_long else entry0 * (1 - step / 100)
    worst = 0.0

    end = min(i + 1 + HOLD_BARS, n)
    for j in range(i + 1, end):
        avg = sum(fills) / len(fills)

        # 추가 진입 (역행 시)
        while len(fills) < max_stages:
            hit_add = (lows[j] <= next_add) if is_long else (highs[j] >= next_add)
            if not hit_add:
                break
            fills.append(next_add)
            next_add = (next_add * (1 - step / 100) if is_long
                        else next_add * (1 + step / 100))
            avg = sum(fills) / len(fills)

        # 평단 기준 손익 (최악 / 익절)
        if is_long:
            adverse = (lows[j] - avg) / avg * 100
            favor = (highs[j] - avg) / avg * 100
        else:
            adverse = (avg - highs[j]) / avg * 100
            favor = (avg - lows[j]) / avg * 100
        worst = min(worst, adverse)

        if favor >= tp:
            return True, j - i, len(fills), worst, tp

    # 미달 = 실패. 관찰 종료 시점 평단 손익
    avg = sum(fills) / len(fills)
    last = closes[end - 1]
    final = ((last - avg) / avg * 100) if is_long else ((avg - last) / avg * 100)
    return False, end - 1 - i, len(fills), worst, final


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache15m", required=True)
    args = ap.parse_args()
    files = sorted(glob.glob(os.path.join(args.cache15m, "*.json")))

    # acc[(kind, wlabel, plan, tp)] = 통계
    acc = defaultdict(lambda: {
        "n": 0, "win": 0, "bars": [], "stages": [], "worst": [],
        "fail_loss": [], "max_stage_hit": 0,
    })

    for f in files:
        try:
            d = json.load(open(f))
            kl = d.get("15m") if isinstance(d, dict) else d
            if not isinstance(kl, list) or len(kl) < 140:
                continue
        except Exception:
            continue
        highs = [float(k[2]) for k in kl]
        lows = [float(k[3]) for k in kl]
        closes = [float(k[4]) for k in kl]
        n = len(kl)

        for sign, kind in ((+1, "급등"), (-1, "급락")):
            is_long = sign < 0          # 역추세!
            for wlabel, window in WINDOWS:
                for i in detect(closes, window, sign):
                    if i + HOLD_BARS >= n:
                        continue
                    for plabel, step, max_st in PLANS:
                        for tp in TP_TARGETS:
                            ok, bars, stages, worst, final = simulate(
                                highs, lows, closes, i, is_long, step, max_st, tp, n)
                            a = acc[(kind, wlabel, plabel, tp)]
                            a["n"] += 1
                            a["stages"].append(stages)
                            a["worst"].append(worst)
                            if stages >= max_st:
                                a["max_stage_hit"] += 1
                            if ok:
                                a["win"] += 1
                                a["bars"].append(bars)
                            else:
                                a["fail_loss"].append(final)

    def med(xs):
        return sorted(xs)[len(xs) // 2] if xs else 0.0

    print("=" * 104)
    print("📊 15분봉 20%+ 급등락 → **분할 진입 역추세** 전략 (사장님 방식)")
    print(f"   각 단계 자본 동일 / 관찰 {HOLD_BARS}봉(24시간) / 평단 기준 익절")
    print(f"   심볼 {len(files)}개 / 표본 {MIN_N}건 미만 생략")
    print("=" * 104)

    for kind in ("급등", "급락"):
        cw = "SHORT" if kind == "급등" else "LONG"
        print(f"\n{'#'*104}\n## {kind} 20%+ → 역추세 {cw} 분할 진입\n{'#'*104}")
        for wlabel, _ in WINDOWS:
            rows = []
            for plabel, _, max_st in PLANS:
                for tp in TP_TARGETS:
                    a = acc.get((kind, wlabel, plabel, tp))
                    if not a or a["n"] < MIN_N:
                        continue
                    wr = a["win"] / a["n"] * 100
                    fl = med(a["fail_loss"]) if a["fail_loss"] else 0.0
                    ev = (a["win"] * tp + sum(a["fail_loss"])) / a["n"]
                    rows.append((plabel, tp, a["n"], wr, med(a["bars"]),
                                 med(a["stages"]), med(a["worst"]), fl,
                                 a["max_stage_hit"] / a["n"] * 100, ev))
            if not rows:
                continue
            print(f"\n▶ 창 = {wlabel}")
            print(f"   {'계획':<11}{'TP':<5}{'표본':>6}{'익절률':>8}{'실패시손실':>10}"
                  f"{'기대값':>9}{'손익분기 실패율':>15}{'안전여유':>10}")
            print("   " + "-" * 88)
            for (plabel, tp, n_, wr, bars, st, worst, fl, mx, ev) in rows:
                # 🎯 결정적 수치: 실패율이 몇 %를 넘으면 기대값이 마이너스가 되는가?
                #    win*TP = fail*|loss|  →  breakeven_fail = TP / (TP + |loss|)
                loss = abs(fl) if fl else 0.0
                be = (tp / (tp + loss) * 100) if loss > 0 else 100.0
                actual_fail = 100 - wr
                margin = be - actual_fail          # 여유가 작을수록 위험!
                flag = " 🚨" if margin < 3 else (" ⚠️" if margin < 6 else "")
                print(f"   {plabel:<11}+{tp:<4.0f}{n_:>6}{wr:>7.1f}%{fl:>9.1f}%"
                      f"{ev:>+8.2f}%{be:>13.1f}%{margin:>+9.1f}%p{flag}")
    print()
    print("=" * 104)
    print("🎯 「손익분기 실패율」 읽는 법")
    print("   = 실패율이 이 값을 넘는 순간 기대값이 마이너스로 뒤집힙니다.")
    print("   「안전여유」 = 손익분기 실패율 − 실측 실패율.")
    print("      🚨 3%p 미만 = 시장 국면이 조금만 나빠져도 손실 전환")
    print("      ⚠️ 6%p 미만 = 주의")
    print()
    print("⚠️ 「익절률」이 높아도 「실패시손실」이 크면 한 번에 다 잃습니다.")
    print("   v139 실거래 실측: 9단계 이상 물타기 8건이 **전체 손실의 43%**를 만들었습니다.")
    print()


if __name__ == "__main__":
    main()

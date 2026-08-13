"""🔀 20% 급등 후 「지속 상승 vs 하락 전환」 판별 연구 (v146)

사장님 전략 2026-08-14:
  "예를 들어 20% 급등 후 100% 급등하는 심볼이 있었어.
   그래서 20% 이상 급등하는 심볼을 1분 5분 차트를 보고 1차 진입을 결정해야 해.
   20% 급등 후 지속 상승하는 경우 진입시점을 잡고 최대 3단계 안에서 고점을 잡아야 해."
  "롱과 숏을 동시에 생각하고 하는 거. 급등 후 하락할 경우 숏, 지속 상승은 롱 짧게"

= **20% 시점에 서서 두 갈래를 가르는 판별기**가 필요합니다:
    · 지속 상승 → **LONG (짧게)**
    · 하락 전환 → **SHORT**

핵심 질문 3개:
  [Q1] 20% 급등한 심볼 중 **몇 %가 계속 가고 몇 %가 꺾이나?** (기저 비율)
  [Q2] 계속 가는 놈은 얼마나 가나? (+50%? +100%?)
  [Q3] **20% 시점에 보이는 어떤 특징**이 그 둘을 가르나? ← 판별 로직의 재료

판정 (미래 참조 없음 — 라벨에만 사용):
  트리거 이후 first-touch 로 **+X% 먼저 vs −X% 먼저**를 가립니다.
  (한 봉 안에 둘 다면 **하락 우선** = 보수적)

특징은 전부 **트리거 시점까지의 데이터**로만 계산합니다.

사용:
    python scripts/study_pump_continuation.py --cache5m <5m캐시> --cache15m <klines_cache>
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import defaultdict

MIN_MOVE = 20.0
WINDOW_5M = 24          # 5m 24봉 = 2시간 (v144에서 2시간 창이 유효했음)
FWD_BARS = 72           # 이후 6시간 관찰 (5m 기준)
# 지속/전환 판정 임계 (양쪽 대칭)
DECIDE = [5.0, 10.0, 20.0]
# 「크게 가는」 기준
BIG_MOVES = [30.0, 50.0, 100.0]
MIN_N = 20


def detect(closes, window):
    out, cd = [], 0
    for i in range(window, len(closes)):
        if cd > 0:
            cd -= 1
            continue
        base = closes[i - window]
        if base <= 0:
            continue
        if (closes[i] - base) / base * 100 >= MIN_MOVE:
            out.append(i)
            cd = window
    return out


def first_side(highs, lows, i, entry, up_pct, dn_pct, bars):
    """+up% 와 −dn% 중 어느 쪽에 먼저 닿나 → 'UP' / 'DOWN' / 'NONE'.

    같은 봉에 둘 다면 DOWN 우선 (보수적).
    """
    up_px = entry * (1 + up_pct / 100)
    dn_px = entry * (1 - dn_pct / 100)
    end = min(i + 1 + bars, len(highs))
    for j in range(i + 1, end):
        if lows[j] <= dn_px:
            return "DOWN"
        if highs[j] >= up_px:
            return "UP"
    return "NONE"


def features(opens, highs, lows, closes, vols, i, window):
    """트리거 시점까지의 데이터로만 계산하는 특징들."""
    seg_lo = i - window
    base = closes[seg_lo]
    move = (closes[i] - base) / base * 100

    # 1) 거래량 급증 = 최근 6봉(30분) 평균 / 그 이전 24봉 평균
    v_recent = sum(vols[i - 5:i + 1]) / 6
    prev = vols[max(0, i - 29):i - 5]
    v_prev = sum(prev) / len(prev) if prev else 0.0
    vol_ratio = v_recent / v_prev if v_prev > 0 else 0.0

    # 2) 가속도 = 최근 30분 상승률 vs 그 이전 30분
    r_recent = (closes[i] - closes[i - 6]) / closes[i - 6] * 100 if closes[i - 6] else 0
    r_prev = (closes[i - 6] - closes[i - 12]) / closes[i - 12] * 100 if i >= 12 and closes[i - 12] else 0
    accel = r_recent - r_prev

    # 3) 연속 양봉 수
    streak = 0
    for j in range(i, max(seg_lo, 0), -1):
        if closes[j] > opens[j]:
            streak += 1
        else:
            break

    # 4) 직진성 = 급등 구간 내 최대 되돌림 (작을수록 강한 직진)
    peak = base
    max_pb = 0.0
    for j in range(seg_lo, i + 1):
        peak = max(peak, highs[j])
        pb = (lows[j] - peak) / peak * 100
        max_pb = min(max_pb, pb)

    # 5) 현재 봉이 고가 근처에서 마감? (윗꼬리 짧음 = 매수 강함)
    rng = highs[i] - lows[i]
    close_pos = (closes[i] - lows[i]) / rng if rng > 0 else 0.5

    # 6) 20% 도달 속도 = 창 내에서 몇 봉 만에 20%를 넘었나
    speed = window
    for j in range(seg_lo + 1, i + 1):
        if (closes[j] - base) / base * 100 >= MIN_MOVE:
            speed = j - seg_lo
            break

    return {
        "move": move,
        "vol_ratio": vol_ratio,
        "accel": accel,
        "streak": streak,
        "straight": max_pb,          # 음수, 0에 가까울수록 직진
        "close_pos": close_pos,
        "speed": speed,
    }


def bucket(name, val):
    """특징 → 구간 라벨."""
    if name == "vol_ratio":
        return ("vol<1", "vol1~2", "vol2~4", "vol4+")[
            0 if val < 1 else 1 if val < 2 else 2 if val < 4 else 3]
    if name == "accel":
        return ("가속<0", "가속0~5", "가속5~15", "가속15+")[
            0 if val < 0 else 1 if val < 5 else 2 if val < 15 else 3]
    if name == "streak":
        return ("연속0~1", "연속2~3", "연속4~6", "연속7+")[
            0 if val <= 1 else 1 if val <= 3 else 2 if val <= 6 else 3]
    if name == "straight":
        return ("되돌림0~3", "되돌림3~6", "되돌림6~10", "되돌림10+")[
            0 if val > -3 else 1 if val > -6 else 2 if val > -10 else 3]
    if name == "close_pos":
        return ("종가하단", "종가중단", "종가상단")[
            0 if val < 0.4 else 1 if val < 0.7 else 2]
    if name == "speed":
        return ("초고속<6봉", "고속6~12", "보통12~18", "완만18+")[
            0 if val < 6 else 1 if val < 12 else 2 if val < 18 else 3]
    if name == "move":
        return ("20~25%", "25~35%", "35~50%", "50%+")[
            0 if val < 25 else 1 if val < 35 else 2 if val < 50 else 3]
    return "?"


FEATURES = ["move", "vol_ratio", "accel", "streak", "straight", "close_pos", "speed"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache5m", required=True)
    ap.add_argument("--cache15m", required=False)
    args = ap.parse_args()
    files = sorted(glob.glob(os.path.join(args.cache5m, "*.json")))

    events = []
    for f in files:
        try:
            kl = json.load(open(f))
            if not isinstance(kl, list) or len(kl) < WINDOW_5M + FWD_BARS + 40:
                continue
        except Exception:
            continue
        opens = [float(k[1]) for k in kl]
        highs = [float(k[2]) for k in kl]
        lows = [float(k[3]) for k in kl]
        closes = [float(k[4]) for k in kl]
        vols = [float(k[5]) for k in kl]
        n = len(kl)

        for i in detect(closes, WINDOW_5M):
            if i < 30 or i + FWD_BARS >= n:
                continue
            fe = features(opens, highs, lows, closes, vols, i, WINDOW_5M)
            entry = closes[i]
            rec = {"f": fe}
            for d in DECIDE:
                rec[f"side{d:.0f}"] = first_side(highs, lows, i, entry, d, d, FWD_BARS)
            # 이후 최대 상승/하락
            seg_hi = max(highs[i + 1:i + 1 + FWD_BARS])
            seg_lo = min(lows[i + 1:i + 1 + FWD_BARS])
            rec["max_up"] = (seg_hi - entry) / entry * 100
            rec["max_dn"] = (seg_lo - entry) / entry * 100
            events.append(rec)

    n_ev = len(events)
    print("=" * 92)
    print(f"🔀 20% 급등(5m 2시간 창) 후 지속 vs 전환 — 이벤트 {n_ev:,}건 / 심볼 {len(files)}개")
    print(f"   판정 = 트리거 후 {FWD_BARS}봉(6시간) 내 +X% vs −X% 선착 (동시면 하락 우선)")
    print("=" * 92)
    if n_ev < MIN_N:
        print("표본 부족")
        return

    print("\n### [Q1] 기저 비율 — 몇 %가 계속 가고 몇 %가 꺾이나")
    print(f"   {'기준':<10}{'지속(UP)':>10}{'전환(DOWN)':>12}{'미결':>8}")
    print("   " + "-" * 42)
    for d in DECIDE:
        k = f"side{d:.0f}"
        up = sum(1 for e in events if e[k] == "UP")
        dn = sum(1 for e in events if e[k] == "DOWN")
        no = n_ev - up - dn
        print(f"   ±{d:<9.0f}{up/n_ev*100:>9.1f}%{dn/n_ev*100:>11.1f}%{no/n_ev*100:>7.1f}%")

    print("\n### [Q2] 계속 가는 놈은 얼마나 가나")
    for b in BIG_MOVES:
        c = sum(1 for e in events if e["max_up"] >= b)
        print(f"   트리거 후 +{b:.0f}% 이상 도달 = {c:,}건 ({c/n_ev*100:.1f}%)")
    ups = sorted(e["max_up"] for e in events)
    dns = sorted(e["max_dn"] for e in events)
    print(f"   최대 상승 중앙값 {ups[len(ups)//2]:.1f}% / 최대 하락 중앙값 {dns[len(dns)//2]:.1f}%")

    print("\n### [Q3] 🎯 20% 시점의 어떤 특징이 둘을 가르나 (기준 ±10%)")
    key = "side10"
    base_up = sum(1 for e in events if e[key] == "UP") / n_ev * 100
    print(f"   (기저 지속률 = {base_up:.1f}%)")
    print(f"   {'특징':<14}{'구간':<14}{'건수':>7}{'지속률':>9}{'배수':>8}{'전환률':>9}")
    print("   " + "-" * 62)
    for name in FEATURES:
        groups = defaultdict(list)
        for e in events:
            groups[bucket(name, e["f"][name])].append(e)
        for g in sorted(groups):
            rows = groups[g]
            if len(rows) < MIN_N:
                continue
            up = sum(1 for e in rows if e[key] == "UP")
            dn = sum(1 for e in rows if e[key] == "DOWN")
            r = up / len(rows) * 100
            mark = " ⭐" if r >= base_up * 1.3 else (" 🔻" if r <= base_up * 0.7 else "")
            print(f"   {name:<14}{g:<14}{len(rows):>7}{r:>8.1f}%"
                  f"{r/base_up if base_up else 0:>7.2f}x{dn/len(rows)*100:>8.1f}%{mark}")
    print()


if __name__ == "__main__":
    main()

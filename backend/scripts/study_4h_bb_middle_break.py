"""🔬 4시간봉 볼밴 중단 이탈 → 하단 도달 실증 연구 (v143)

사장님 지시 2026-08-14:
  "4시간봉 볼밴 중단을 깨지면 추가 하락을 볼밴 하단까지 하고,
   볼밴 하단을 깨고 내려가는건 아주 적은 경우야. 분석해서 매매전략으로 만들어줘"

검증할 가설 2개:
  [가설 1] 4H 종가가 BB 중단을 **하향 이탈**하면 → BB **하단까지** 추가 하락한다
  [가설 2] BB **하단을 깨고 더** 내려가는 경우는 **아주 적다**

측정:
  1. 중단 이탈 이벤트: 직전봉 종가 ≥ 중단 AND 현재봉 종가 < 중단
  2. 이후 N봉 내 저가가 **하단에 닿는가?** (도달률 / 소요 봉수 / 하락폭)
  3. 하단 도달 후 **종가가 하단 아래로 마감**하는가? (= 하단 이탈 = 사장님이 「적다」신 케이스)
  4. 하단 이탈 시 추가 하락폭은?
  5. 매매 규칙 검증:
     · SHORT: 중단 이탈 봉 종가 진입 → TP = 하단, SL = 중단 위 X%
     · LONG : 하단 도달 시 진입 → TP = 중단 복귀, SL = 하단 아래 X%
     (둘 다 TP/SL **선착 판정** = 실제 손익을 가르는 지표)

상단/중단 상향도 대칭으로 함께 잽니다 (헌법 5번).

사용:
    python scripts/study_4h_bb_middle_break.py --cache4h <cache_4h_deep>
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import defaultdict

BB_PERIOD = 20
BB_STD = 2.0
TRACK_BARS = 30       # 이탈 후 추적 (30봉 = 5일)
AFTER_BREAK = 12      # 하단 이탈 후 추가 하락 관찰 (2일)

# SHORT (중단 이탈 → 하단) 규칙: SL 후보 = 중단 위 %
SHORT_SL = [1.0, 2.0, 3.0, 5.0]
# LONG (하단 도달 → 중단 복귀) 규칙: SL 후보 = 하단 아래 %
LONG_SL = [1.0, 2.0, 3.0, 5.0]

# 🆕 v143a 사장님 지시: 「볼밴 **하단을 깨는** 경우」도 자동 제안 대상으로 쓰고 싶다.
#    → 중단 이탈과 **별개 이벤트**로 잡아 기대값을 따로 잰다.
#    (밴드 밖에는 목표로 삼을 밴드가 없으므로 TP 도 고정 %)
BREAK_TP_SL = [(3.0, 3.0), (5.0, 3.0), (5.0, 5.0), (8.0, 5.0), (10.0, 5.0)]


def bollinger(closes):
    n = len(closes)
    mid = [None] * n
    up = [None] * n
    lo = [None] * n
    total = 0.0
    for i, c in enumerate(closes):
        total += c
        if i >= BB_PERIOD:
            total -= closes[i - BB_PERIOD]
        if i >= BB_PERIOD - 1:
            m = total / BB_PERIOD
            w = closes[i - BB_PERIOD + 1: i + 1]
            sd = (sum((x - m) ** 2 for x in w) / BB_PERIOD) ** 0.5
            mid[i], up[i], lo[i] = m, m + BB_STD * sd, m - BB_STD * sd
    return mid, up, lo


def first_touch_px(highs, lows, i, tp_px, sl_px, is_long, max_bars) -> str:
    """TP/SL 선착 (같은 봉이면 SL 우선 = 보수적)."""
    end = min(i + 1 + max_bars, len(highs))
    for j in range(i + 1, end):
        if is_long:
            if lows[j] <= sl_px:
                return "SL"
            if highs[j] >= tp_px:
                return "TP"
        else:
            if highs[j] >= sl_px:
                return "SL"
            if lows[j] <= tp_px:
                return "TP"
    return "NONE"


def _med(xs):
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[len(s) // 2]


def analyze_band_break(kl, acc, down: bool = True):
    """밴드(하단/상단)를 **종가로 깬** 첫 봉에 추세 방향 진입 → TP/SL 선착."""
    n = len(kl)
    highs = [float(k[2]) for k in kl]
    lows = [float(k[3]) for k in kl]
    closes = [float(k[4]) for k in kl]
    mid, up, lo = bollinger(closes)

    cooldown = 0
    for i in range(BB_PERIOD, n - 2):
        if cooldown > 0:
            cooldown -= 1
            continue
        band = lo[i] if down else up[i]
        prev_band = lo[i - 1] if down else up[i - 1]
        if band is None or prev_band is None:
            continue
        # 직전봉은 밴드 안 → 현재봉 종가가 밴드 밖 = 「깼다」
        inside_prev = closes[i - 1] >= prev_band if down else closes[i - 1] <= prev_band
        broke_now = closes[i] < band if down else closes[i] > band
        if not (inside_prev and broke_now):
            continue

        acc["events"] += 1
        cooldown = 3
        entry = closes[i]
        # 이후 추가 이동폭 (참고)
        end = min(i + 1 + TRACK_BARS, n)
        if end > i + 1:
            far = min(lows[i + 1:end]) if down else max(highs[i + 1:end])
            acc["extra_pct"].append(abs((far - entry) / entry * 100))
        for tp, sl in BREAK_TP_SL:
            tp_px = entry * (1 - tp / 100) if down else entry * (1 + tp / 100)
            sl_px = entry * (1 + sl / 100) if down else entry * (1 - sl / 100)
            r = first_touch_px(highs, lows, i, tp_px, sl_px, not down, TRACK_BARS)
            st = acc["ruleC"][(tp, sl)]
            st[r] += 1


def analyze(kl, acc, down: bool = True):
    """down=True: 중단 하향 이탈 → 하단 / down=False: 중단 상향 돌파 → 상단."""
    n = len(kl)
    highs = [float(k[2]) for k in kl]
    lows = [float(k[3]) for k in kl]
    closes = [float(k[4]) for k in kl]
    mid, up, lo = bollinger(closes)

    for i in range(BB_PERIOD, n - 2):
        if mid[i] is None or mid[i - 1] is None:
            continue
        if down:
            crossed = closes[i - 1] >= mid[i - 1] and closes[i] < mid[i]
        else:
            crossed = closes[i - 1] <= mid[i - 1] and closes[i] > mid[i]
        if not crossed:
            continue

        acc["events"] += 1
        entry = closes[i]
        target = lo[i] if down else up[i]
        if target is None or target <= 0:
            continue
        band_pct = abs((target - entry) / entry * 100)      # 진입가→목표 거리
        acc["band_dist"].append(band_pct)

        # ---------- 목표(하단/상단) 도달 여부 ----------
        reach_idx = None
        for j in range(i + 1, min(i + 1 + TRACK_BARS, n)):
            if lo[j] is None or up[j] is None:
                continue
            band = lo[j] if down else up[j]
            hit = lows[j] <= band if down else highs[j] >= band
            if hit:
                reach_idx = j
                break

        if reach_idx is None:
            acc["no_reach"] += 1
            continue
        acc["reached"] += 1
        acc["bars_to_reach"].append(reach_idx - i)
        band_at = lo[reach_idx] if down else up[reach_idx]
        acc["move_pct"].append(abs((band_at - entry) / entry * 100))

        # ---------- 목표 도달 후: 밴드를 뚫고 더 가는가? ----------
        broke = False
        extra = 0.0
        for j in range(reach_idx, min(reach_idx + AFTER_BREAK, n)):
            band = lo[j] if down else up[j]
            if band is None:
                continue
            closed_out = closes[j] < band if down else closes[j] > band
            if closed_out:
                broke = True
                far = min(lows[j:min(j + AFTER_BREAK, n)]) if down else max(highs[j:min(j + AFTER_BREAK, n)])
                extra = abs((far - band) / band * 100)
                break
        if broke:
            acc["broke_band"] += 1
            acc["extra_pct"].append(extra)
        else:
            acc["held_band"] += 1

        # ---------- 규칙 A: 이탈 봉 종가 진입 → TP = 반대 밴드 ----------
        for slp in (SHORT_SL if down else LONG_SL):
            sl_px = entry * (1 + slp / 100) if down else entry * (1 - slp / 100)
            r = first_touch_px(highs, lows, i, target, sl_px, not down, TRACK_BARS)
            st = acc["ruleA"][slp]
            st[r] += 1
            st["tp_pct"].append(band_pct)

        # ---------- 규칙 B: 밴드 도달 시 역방향 진입 → TP = 중단 복귀 ----------
        m_at = mid[reach_idx]
        if m_at:
            e2 = band_at
            tp2 = m_at
            tp2_pct = abs((tp2 - e2) / e2 * 100)
            for slp in LONG_SL:
                sl2 = e2 * (1 - slp / 100) if down else e2 * (1 + slp / 100)
                # ⚠️ 진입 봉(reach_idx) 자체의 저가/고가도 SL 판정에 포함해야 합니다.
                #    밴드를 터치한 그 봉이 바로 SL 까지 뚫는 경우가 실제로 많습니다
                #    (다음 봉부터 재면 승률이 부풀려짐 = 낙관 편향!)
                if down:
                    hit_now = lows[reach_idx] <= sl2
                else:
                    hit_now = highs[reach_idx] >= sl2
                r = "SL" if hit_now else first_touch_px(
                    highs, lows, reach_idx, tp2, sl2, down, TRACK_BARS)
                st = acc["ruleB"][slp]
                st[r] += 1
                st["tp_pct"].append(tp2_pct)


def report(title, acc, down: bool):
    band_word = "하단" if down else "상단"
    dir_word = "하락" if down else "상승"
    print("\n" + "=" * 82)
    print(f"🔬 {title}")
    print("=" * 82)
    ev = acc["events"]
    if not ev:
        print("  이벤트 없음")
        return
    reached = acc["reached"]
    print(f"\n[가설 1] 중단 이탈 → {band_word}까지 추가 {dir_word} 하는가?")
    print(f"   중단 이탈 이벤트 = {ev:,}건")
    print(f"   → {TRACK_BARS}봉(5일) 내 {band_word} 도달 = {reached:,}건 "
          f"(**{reached/ev*100:.1f}%**)")
    print(f"   → 미도달 = {acc['no_reach']:,}건 ({acc['no_reach']/ev*100:.1f}%)")
    if reached:
        print(f"   도달 소요: 중앙값 {_med(acc['bars_to_reach']):.0f}봉 "
              f"({_med(acc['bars_to_reach'])*4:.0f}시간) / 평균 "
              f"{sum(acc['bars_to_reach'])/len(acc['bars_to_reach']):.1f}봉")
        print(f"   진입가→{band_word} 거리: 중앙값 {_med(acc['move_pct']):.2f}% / "
              f"이탈 시점 밴드폭 중앙값 {_med(acc['band_dist']):.2f}%")

    print(f"\n[가설 2] {band_word} 도달 후 **뚫고 더 가는** 경우는 적은가?")
    tot2 = acc["broke_band"] + acc["held_band"]
    if tot2:
        print(f"   {band_word} 도달 {tot2:,}건 중")
        print(f"     · 종가가 밴드 밖으로 마감 (= 이탈) = {acc['broke_band']:,}건 "
              f"(**{acc['broke_band']/tot2*100:.1f}%**)")
        print(f"     · 밴드가 버팀                      = {acc['held_band']:,}건 "
              f"({acc['held_band']/tot2*100:.1f}%)")
        if acc["extra_pct"]:
            print(f"   이탈한 경우 추가 {dir_word}폭: 중앙값 "
                  f"{_med(acc['extra_pct']):.2f}% / 평균 "
                  f"{sum(acc['extra_pct'])/len(acc['extra_pct']):.2f}%")

    for label, key, is_long_entry in (
        (f"규칙 A: 중단 이탈 봉 진입 → TP={band_word}", "ruleA", not down),
        (f"규칙 B: {band_word} 도달 시 역진입 → TP=중단 복귀", "ruleB", down),
    ):
        print(f"\n💰 {label}")
        print(f"   {'SL':<7}{'표본':>7}{'TP율':>8}{'SL율':>8}{'미결':>7}"
              f"{'중앙TP':>8}{'손익비':>8}{'기대값':>9}")
        print("   " + "-" * 62)
        for slp in sorted(acc[key]):
            st = acc[key][slp]
            tot = st["TP"] + st["SL"] + st["NONE"]
            if tot < 30:
                continue
            tpm = _med(st["tp_pct"])
            evp = (st["TP"] * tpm - st["SL"] * slp) / tot
            mark = " ⭐" if evp > 0 else ""
            print(f"   -{slp:<6.1f}{tot:>7,}{st['TP']/tot*100:>7.1f}%"
                  f"{st['SL']/tot*100:>7.1f}%{st['NONE']/tot*100:>6.1f}%"
                  f"{tpm:>7.2f}%{tpm/slp:>7.2f}{evp:>+8.2f}%{mark}")


def report_break(title, acc, down: bool):
    move = "하락" if down else "상승"
    band_word = "하단" if down else "상단"
    print("\n" + "=" * 82)
    print(f"🆕 {title}")
    print("=" * 82)
    ev = acc["events"]
    print(f"   {band_word}을 종가로 깬 이벤트 = {ev:,}건")
    if acc["extra_pct"]:
        print(f"   이후 5일 내 추가 {move}폭: 중앙값 {_med(acc['extra_pct']):.2f}% / "
              f"평균 {sum(acc['extra_pct'])/len(acc['extra_pct']):.2f}%")
    if not ev:
        return
    print(f"\n   {'TP/SL':<12}{'표본':>8}{'TP율':>8}{'SL율':>8}{'미결':>7}{'손익비':>8}{'기대값':>9}")
    print("   " + "-" * 60)
    for (tp, sl) in BREAK_TP_SL:
        st = acc["ruleC"][(tp, sl)]
        tot = st["TP"] + st["SL"] + st["NONE"]
        if tot < 30:
            continue
        evp = (st["TP"] * tp - st["SL"] * sl) / tot
        mark = " ⭐" if evp > 0 else ""
        print(f"   +{tp:.0f}%/-{sl:.0f}%{'':<4}{tot:>8,}{st['TP']/tot*100:>7.1f}%"
              f"{st['SL']/tot*100:>7.1f}%{st['NONE']/tot*100:>6.1f}%{tp/sl:>7.2f}{evp:>+8.2f}%{mark}")


def _acc():
    return {
        "events": 0, "reached": 0, "no_reach": 0,
        "broke_band": 0, "held_band": 0,
        "bars_to_reach": [], "move_pct": [], "band_dist": [], "extra_pct": [],
        "ruleA": defaultdict(lambda: {"TP": 0, "SL": 0, "NONE": 0, "tp_pct": []}),
        "ruleB": defaultdict(lambda: {"TP": 0, "SL": 0, "NONE": 0, "tp_pct": []}),
        "ruleC": defaultdict(lambda: {"TP": 0, "SL": 0, "NONE": 0}),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache4h", required=True)
    args = ap.parse_args()
    files = sorted(glob.glob(os.path.join(args.cache4h, "*.json")))

    down_acc, up_acc = _acc(), _acc()
    brk_down, brk_up = _acc(), _acc()
    used = bars = 0
    for f in files:
        try:
            kl = json.load(open(f))
        except Exception:
            continue
        if not isinstance(kl, list) or len(kl) < BB_PERIOD + 40:
            continue
        used += 1
        bars += len(kl)
        analyze(kl, down_acc, down=True)
        analyze(kl, up_acc, down=False)
        analyze_band_break(kl, brk_down, down=True)
        analyze_band_break(kl, brk_up, down=False)

    print("=" * 82)
    print(f"🔬 4시간봉 볼린저밴드(20,2) 중단 이탈 연구 — 심볼 {used}개 / 캔들 {bars:,}개")
    print("=" * 82)
    report("① 중단 하향 이탈 → 하단 (사장님 가설)", down_acc, down=True)
    report("② 중단 상향 돌파 → 상단 (대칭 검증)", up_acc, down=False)
    report_break("③ 하단을 깬 뒤 SHORT 진입 (사장님 추가 요청)", brk_down, down=True)
    report_break("④ 상단을 깬 뒤 LONG 진입 (대칭)", brk_up, down=False)
    print()


if __name__ == "__main__":
    main()

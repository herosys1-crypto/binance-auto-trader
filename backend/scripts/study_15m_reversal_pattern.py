"""🔄 15분봉 20% 급등락 「반전(V자)」 패턴 연구 (v142)

사장님 지시 2026-08-14:
  "15분봉 20% 전후 급등과 급락은 반대로 움직이는 것을 찾아서
   15분봉 고점 후 하락을, 하락 후 상승 패턴을 분석해봐.
   이것을 활용하면 최고일것 같아 가끔이지만"

= 급등을 그냥 추격하는 게 아니라 **급등 → 고점 → 하락 → 재상승** 전체 흐름을 봅니다.
  「가끔이지만 최고」 = **빈도와 질을 같이** 재야 판단할 수 있습니다.

3단계로 분해:
  [1단계] 급등 감지 → 고점까지 얼마나 더 가나?
  [2단계] 고점 → 하락 (되돌림 깊이 / 소요 시간)
  [3단계] 하락 → 재상승 (되돌림 깊이별 반등 확률·폭·고점 회복률)

그리고 **실제로 매매 가능한 규칙**으로 검증합니다:
  「고점 대비 R% 되돌린 뒤 15m 양봉이 나오면 진입」 → TP/SL 선착 판정
  (되돌림 저점은 미리 알 수 없으므로, 미래를 보지 않는 규칙만 평가!)

급락은 부호를 뒤집어 동일하게 (저점 → 반등 → 재하락).

사용:
    python scripts/study_15m_reversal_pattern.py --cache15m <klines_cache>
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

# 사장님 지정 밴드 (v141a)
BAND = (17.5, 22.5)
WINDOWS = [("1시간", 4), ("2시간", 8), ("4시간", 16)]

PEAK_SEARCH = 16      # 급등 감지 후 고점 탐색 구간 (4시간)
DROP_SEARCH = 16      # 고점 후 하락 탐색 구간 (4시간)
REBOUND_SEARCH = 16   # 저점 후 재상승 탐색 구간 (4시간)

# 되돌림 깊이 버킷 (고점 대비 %)
RETRACE_BUCKETS = [(0, 3), (3, 5), (5, 8), (8, 12), (12, 20), (20, 999)]

# 매매 가능 규칙: 고점 대비 R% 되돌린 후 첫 양봉에 진입
ENTRY_RETRACE = [3.0, 5.0, 8.0, 12.0]
TP_SL = [(3.0, 3.0), (5.0, 3.0), (5.0, 5.0), (10.0, 5.0)]
FT_BARS = 16


# ── 규칙 v2 (개선 트리거) ────────────────────────────────────────────
# v1(「R% 되돌린 뒤 첫 양봉」)은 전 조합 기대값 마이너스였습니다.
# 하락 중 첫 양봉 = 대부분 데드캣 바운스라 칼날을 잡습니다.
# v2 = ① 되돌림이 **얕을 때만**  ② **직전 봉 고가 돌파**로 반전 확인
#      ③ **TP = 고점 자체** (회복률이 높은 구간을 노림)  ④ 너무 깊어지면 포기
V2_MIN_R = [2.0, 3.0, 5.0]      # 최소 되돌림 (이만큼은 빠져야 눌림목)
V2_MAX_R = [8.0, 12.0]          # 이보다 깊으면 진입 포기 (회복률 급락!)
V2_SL_BUFFER = 0.3              # 되돌림 저점 대비 여유 %
# v3 = 진단 결과 「평균 SL > 평균 TP」 = 손익비 역전이 원인.
#      → SL 을 되돌림 저점이 아니라 **고정 %** 로 바꿔 손익비를 강제로 세웁니다.
V3_SL_FIXED = [1.5, 2.0, 3.0]


def first_touch_px(highs, lows, i, tp_px, sl_px, is_long, max_bars) -> str:
    """절대 가격 기준 TP/SL 선착 (같은 봉이면 SL 우선 = 보수적)."""
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


def bucket_label(lo, hi):
    return f"{lo}~{hi}%" if hi < 999 else f"{lo}%+"


def detect_band_events(closes, window, lo, hi, sign):
    """밴드 안 급등(sign=+1) / 급락(sign=-1) 이벤트."""
    events, cooldown = [], 0
    for i in range(window, len(closes)):
        if cooldown > 0:
            cooldown -= 1
            continue
        base = closes[i - window]
        if base <= 0:
            continue
        chg = (closes[i] - base) / base * 100
        if lo <= abs(chg) < hi and (chg > 0) == (sign > 0):
            events.append(i)
            cooldown = window
    return events


def analyze(kl, acc_desc, acc_trade, acc_v2, acc_v3, sign: int) -> None:
    """sign=+1 급등(고점→하락→재상승) / sign=-1 급락(저점→반등→재하락)."""
    n = len(kl)
    highs = [float(k[2]) for k in kl]
    lows = [float(k[3]) for k in kl]
    opens = [float(k[1]) for k in kl]
    closes = [float(k[4]) for k in kl]

    for wlabel, window in WINDOWS:
        for i in detect_band_events(closes, window, BAND[0], BAND[1], sign):
            # ---------- [1단계] 극점 찾기 ----------
            end1 = min(i + PEAK_SEARCH + 1, n)
            if end1 - i < 3:
                continue
            if sign > 0:
                ext_idx = max(range(i, end1), key=lambda x: highs[x])
                ext = highs[ext_idx]
                run_pct = (ext - closes[i]) / closes[i] * 100      # 감지 후 추가 상승
            else:
                ext_idx = min(range(i, end1), key=lambda x: lows[x])
                ext = lows[ext_idx]
                run_pct = (ext - closes[i]) / closes[i] * 100      # 감지 후 추가 하락(음수)

            # ---------- [2단계] 극점 후 되돌림 ----------
            end2 = min(ext_idx + DROP_SEARCH + 1, n)
            if end2 - ext_idx < 3:
                continue
            if sign > 0:
                rev_idx = min(range(ext_idx + 1, end2), key=lambda x: lows[x])
                rev = lows[rev_idx]
            else:
                rev_idx = max(range(ext_idx + 1, end2), key=lambda x: highs[x])
                rev = highs[rev_idx]
            retrace_pct = abs((rev - ext) / ext * 100)
            bars_to_rev = rev_idx - ext_idx

            # ---------- [3단계] 되돌림 후 재이동 ----------
            end3 = min(rev_idx + REBOUND_SEARCH + 1, n)
            if end3 - rev_idx < 3:
                continue
            if sign > 0:
                back = max(highs[rev_idx + 1:end3])
                rebound_pct = (back - rev) / rev * 100
                reclaim = back >= ext
            else:
                back = min(lows[rev_idx + 1:end3])
                rebound_pct = abs((back - rev) / rev * 100)
                reclaim = back <= ext

            b = None
            for lo, hi in RETRACE_BUCKETS:
                if lo <= retrace_pct < hi:
                    b = bucket_label(lo, hi)
                    break
            if b is None:
                continue
            d = acc_desc[(wlabel, b)]
            d["n"] += 1
            d["run"].append(run_pct)
            d["retrace"].append(retrace_pct)
            d["bars_to_rev"].append(bars_to_rev)
            d["rebound"].append(rebound_pct)
            d["reclaim"] += 1 if reclaim else 0

            # ---------- 매매 가능 규칙 ----------
            # 「극점 대비 R% 되돌린 뒤 **첫 반전 봉**에 진입」 (미래 참조 X)
            for R in ENTRY_RETRACE:
                entry_idx = None
                for j in range(ext_idx + 1, min(ext_idx + 1 + DROP_SEARCH, n)):
                    if sign > 0:
                        deep = (lows[j] - ext) / ext * 100 <= -R
                        turn = closes[j] > opens[j]          # 양봉
                    else:
                        deep = (highs[j] - ext) / ext * 100 >= R
                        turn = closes[j] < opens[j]          # 음봉
                    if deep and turn:
                        entry_idx = j
                        break
                if entry_idx is None:
                    acc_trade[(wlabel, R)]["miss"] += 1
                    continue
                t = acc_trade[(wlabel, R)]
                t["n"] += 1
                entry = closes[entry_idx]
                is_long = sign > 0
                for tp, sl in TP_SL:
                    r = first_touch(highs, lows, entry_idx, entry, tp, sl, is_long, FT_BARS)
                    t["ft"][(tp, sl)][r] += 1

            # ---------- 규칙 v2 = 얕은 되돌림 + 직전봉 돌파 + TP는 고점 ----------
            for min_r in V2_MIN_R:
                for max_r in V2_MAX_R:
                    if min_r >= max_r:
                        continue
                    key2 = (wlabel, min_r, max_r)
                    v2 = acc_v2[key2]
                    pull = ext          # 되돌림 극값 (running)
                    entry_idx = None
                    for j in range(ext_idx + 1, min(ext_idx + 1 + DROP_SEARCH, n)):
                        if sign > 0:
                            pull = min(pull, lows[j])
                            depth = (pull - ext) / ext * 100          # 음수
                            if depth <= -max_r:
                                break                                 # 너무 깊음 = 포기!
                            if depth <= -min_r and closes[j] > highs[j - 1]:
                                entry_idx = j
                                break
                        else:
                            pull = max(pull, highs[j])
                            depth = (pull - ext) / ext * 100          # 양수
                            if depth >= max_r:
                                break
                            if depth >= min_r and closes[j] < lows[j - 1]:
                                entry_idx = j
                                break
                    if entry_idx is None:
                        v2["miss"] += 1
                        continue

                    entry = closes[entry_idx]
                    if sign > 0:
                        tp_px = ext                                   # 고점 회복 목표!
                        sl_px = pull * (1 - V2_SL_BUFFER / 100)
                        ok = tp_px > entry > sl_px
                    else:
                        tp_px = ext
                        sl_px = pull * (1 + V2_SL_BUFFER / 100)
                        ok = tp_px < entry < sl_px
                    if not ok:
                        v2["miss"] += 1
                        continue

                    tp_pct = abs((tp_px - entry) / entry * 100)
                    sl_pct = abs((sl_px - entry) / entry * 100)
                    r = first_touch_px(highs, lows, entry_idx, tp_px, sl_px,
                                       sign > 0, FT_BARS)
                    v2["n"] += 1
                    v2[r] += 1
                    v2["tp_pct"].append(tp_pct)
                    v2["sl_pct"].append(sl_pct)
                    v2["pnl"].append(tp_pct if r == "TP" else (-sl_pct if r == "SL" else 0.0))

                    # ---------- 규칙 v3 = SL 을 고정 %로 (손익비 강제) ----------
                    for slf in V3_SL_FIXED:
                        if sign > 0:
                            sl3 = entry * (1 - slf / 100)
                        else:
                            sl3 = entry * (1 + slf / 100)
                        tp3_pct = abs((tp_px - entry) / entry * 100)
                        if tp3_pct < slf * 1.2:
                            continue          # 손익비 1.2 미만이면 진입 안 함!
                        r3 = first_touch_px(highs, lows, entry_idx, tp_px, sl3,
                                            sign > 0, FT_BARS)
                        v3 = acc_v3[(wlabel, min_r, max_r, slf)]
                        v3["n"] += 1
                        v3[r3] += 1
                        v3["tp_pct"].append(tp3_pct)
                        v3["pnl"].append(tp3_pct if r3 == "TP" else (-slf if r3 == "SL" else 0.0))


def _med(xs):
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[len(s) // 2]


def report(title, acc_desc, acc_trade, acc_v2, acc_v3, sign):
    ext_word = "고점" if sign > 0 else "저점"
    rev_word = "하락" if sign > 0 else "상승"
    back_word = "재상승" if sign > 0 else "재하락"
    dir_word = "LONG" if sign > 0 else "SHORT"

    print("\n" + "=" * 88)
    print(f"🔄 {title}")
    print("=" * 88)

    print(f"\n### [1~3단계] {ext_word} 후 {rev_word} → {back_word} 흐름")
    print(f"{'창':<8}{'되돌림구간':<12}{'건수':>7}{'감지후추가':>11}"
          f"{'되돌림중앙':>11}{'소요봉':>8}{back_word+'중앙':>11}{ext_word+'회복':>9}")
    print("-" * 80)
    for wlabel, _ in WINDOWS:
        for lo, hi in RETRACE_BUCKETS:
            key = (wlabel, bucket_label(lo, hi))
            d = acc_desc.get(key)
            if not d or d["n"] < 20:
                continue
            print(f"{wlabel:<8}{bucket_label(lo,hi):<12}{d['n']:>7}"
                  f"{_med(d['run']):>10.2f}%{_med(d['retrace']):>10.2f}%"
                  f"{_med(d['bars_to_rev']):>7.0f}봉{_med(d['rebound']):>10.2f}%"
                  f"{d['reclaim']/d['n']*100:>8.1f}%")

    print(f"\n### 💰 매매 가능 규칙: {ext_word} 대비 R% 되돌린 뒤 첫 "
          f"{'양봉' if sign>0 else '음봉'}에 {dir_word} 진입")
    print(f"{'창':<8}{'R':<6}{'진입':>7}{'미발생':>8}  "
          f"{'최적 TP/SL':<12}{'TP선착':>8}{'기대값':>9}")
    print("-" * 66)
    for wlabel, _ in WINDOWS:
        for R in ENTRY_RETRACE:
            t = acc_trade.get((wlabel, R))
            if not t or t["n"] < 20:
                continue
            best = None
            for (tp, sl), st in t["ft"].items():
                tot = st["TP"] + st["SL"] + st["NONE"]
                if not tot:
                    continue
                ev = (st["TP"] * tp - st["SL"] * sl) / tot
                if best is None or ev > best[0]:
                    best = (ev, tp, sl, st["TP"] / tot * 100)
            if not best:
                continue
            ev, tp, sl, tpr = best
            mark = " ⭐" if ev > 0 else ""
            print(f"{wlabel:<8}{R:<6.0f}{t['n']:>7}{t['miss']:>8}  "
                  f"{'+'+str(int(tp))+'%/-'+str(int(sl))+'%':<12}{tpr:>7.1f}%{ev:>+8.2f}%{mark}")

    print(f"\n### 🎯 규칙 v2 = 얕은 되돌림 + 직전봉 돌파 확인 + TP는 {ext_word} 회복")
    print(f"{'창':<8}{'되돌림':<10}{'진입':>7}{'미발생':>8}{'TP율':>8}{'SL율':>8}"
          f"{'평균TP':>8}{'평균SL':>8}{'기대값':>9}")
    print("-" * 74)
    for wlabel, _ in WINDOWS:
        for min_r in V2_MIN_R:
            for max_r in V2_MAX_R:
                if min_r >= max_r:
                    continue
                v = acc_v2.get((wlabel, min_r, max_r))
                if not v or v["n"] < 20:
                    continue
                n = v["n"]
                ev = sum(v["pnl"]) / n
                mark = " ⭐" if ev > 0 else ""
                print(f"{wlabel:<8}{f'{min_r:.0f}~{max_r:.0f}%':<10}{n:>7}{v['miss']:>8}"
                      f"{v['TP']/n*100:>7.1f}%{v['SL']/n*100:>7.1f}%"
                      f"{_med(v['tp_pct']):>7.2f}%{_med(v['sl_pct']):>7.2f}%{ev:>+8.2f}%{mark}")

    print(f"\n### 🎯 규칙 v3 = v2 + SL 고정 (손익비 강제 / TP는 {ext_word} 회복)")
    print(f"{'창':<8}{'되돌림':<10}{'SL고정':<8}{'진입':>7}{'TP율':>8}{'SL율':>8}"
          f"{'중앙TP':>8}{'손익비':>8}{'기대값':>9}")
    print("-" * 74)
    for wlabel, _ in WINDOWS:
        for min_r in V2_MIN_R:
            for max_r in V2_MAX_R:
                for slf in V3_SL_FIXED:
                    v = acc_v3.get((wlabel, min_r, max_r, slf))
                    if not v or v["n"] < 30:
                        continue
                    n = v["n"]
                    ev = sum(v["pnl"]) / n
                    tpm = _med(v["tp_pct"])
                    mark = " ⭐" if ev > 0 else ""
                    print(f"{wlabel:<8}{f'{min_r:.0f}~{max_r:.0f}%':<10}{slf:<8.1f}{n:>7}"
                          f"{v['TP']/n*100:>7.1f}%{v['SL']/n*100:>7.1f}%"
                          f"{tpm:>7.2f}%{tpm/slf:>7.2f}{ev:>+8.2f}%{mark}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache15m", required=True)
    args = ap.parse_args()
    files = sorted(glob.glob(os.path.join(args.cache15m, "*.json")))

    def _desc():
        return defaultdict(lambda: {"n": 0, "run": [], "retrace": [], "bars_to_rev": [],
                                    "rebound": [], "reclaim": 0})

    def _trade():
        return defaultdict(lambda: {"n": 0, "miss": 0,
                                    "ft": defaultdict(lambda: {"TP": 0, "SL": 0, "NONE": 0})})

    def _v2():
        return defaultdict(lambda: {"n": 0, "miss": 0, "TP": 0, "SL": 0, "NONE": 0,
                                    "tp_pct": [], "sl_pct": [], "pnl": []})

    def _v3():
        return defaultdict(lambda: {'n': 0, 'TP': 0, 'SL': 0, 'NONE': 0,
                                    'tp_pct': [], 'pnl': []})

    pump_d, pump_t, pump_v2, pump_v3 = _desc(), _trade(), _v2(), _v3()
    dump_d, dump_t, dump_v2, dump_v3 = _desc(), _trade(), _v2(), _v3()

    for f in files:
        try:
            d = json.load(open(f))
            kl = d.get("15m") if isinstance(d, dict) else d
            if not isinstance(kl, list) or len(kl) < 80:
                continue
        except Exception:
            continue
        analyze(kl, pump_d, pump_t, pump_v2, pump_v3, +1)
        analyze(kl, dump_d, dump_t, dump_v2, dump_v3, -1)

    print("=" * 88)
    print(f"🔬 15분봉 {BAND[0]:g}~{BAND[1]:g}% 급등락 반전(V자) 패턴 — 심볼 {len(files)}개")
    print("   되돌림 저점은 미리 알 수 없으므로, 매매 규칙은 **미래 참조 없이** 평가했습니다.")
    print("=" * 88)
    report("급등 → 고점 → 하락 → 재상승", pump_d, pump_t, pump_v2, pump_v3, +1)
    report("급락 → 저점 → 상승 → 재하락", dump_d, dump_t, dump_v2, dump_v3, -1)
    print()


if __name__ == "__main__":
    main()

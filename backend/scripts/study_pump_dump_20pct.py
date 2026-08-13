"""🔬 5분봉·15분봉 20% 급등락 실증 연구 (v141)

사장님 지시 2026-08-14:
  "5분봉과 15분봉에서 20% 정도의 급등락을 급등락 실시간 진입 전략으로 해줘"

핵심 질문 = **방향**입니다:
  · 20% 급등 중 진입 → **추격(LONG)** 이 맞나, **역추세(SHORT)** 가 맞나?
  · 기존 v133c 는 「5분 +3% = 즉시 LONG 추격」인데, 20% 급등에서도 같은가?
  → 추측하지 않고 과거 캔들에서 직접 셉니다.

측정 방법:
  1. 롤링 창(예: 5m 12봉=1시간)에서 누적 변동이 ±임계% 도달하는 **첫 순간** = 이벤트
     (같은 급등을 중복 계산하지 않도록 창 길이만큼 쿨다운)
  2. 이벤트 시점 종가를 진입가로 보고, 이후 여러 구간의 수익률을 계산
  3. **추격(급등→LONG)** 과 **역추세(급등→SHORT)** 를 나란히 비교
  4. MFE/MAE (최대 유리/불리 움직임) = TP/SL 설계 근거

사용:
    python scripts/study_pump_dump_20pct.py --cache5m <5m캐시> --cache15m <klines_cache>
"""
from __future__ import annotations

import argparse
import glob
import json
import os
from collections import defaultdict

# 임계값 후보 (사장님 요청 20% 중심으로 주변도 함께 봅니다)
THRESHOLDS = [10.0, 15.0, 20.0, 30.0]

# (라벨, 롤링 창 봉수) — 5m/15m 각각
WINDOWS = {
    "5m": [("30분", 6), ("1시간", 12), ("2시간", 24)],
    "15m": [("1시간", 4), ("2시간", 8), ("4시간", 16)],
}

# 이벤트 이후 관찰 지점 (봉수)
FORWARD = {
    "5m": [("+15분", 3), ("+30분", 6), ("+1시간", 12), ("+2시간", 24), ("+4시간", 48)],
    "15m": [("+30분", 2), ("+1시간", 4), ("+2시간", 8), ("+4시간", 16), ("+8시간", 32)],
}

# MFE/MAE 관찰 구간
MFE_BARS = {"5m": 24, "15m": 8}   # 둘 다 2시간

# 「TP와 SL 중 뭐가 먼저 맞나」 = 실제 손익을 가르는 유일한 지표!
# (MFE/MAE 는 각각의 최댓값일 뿐 순서를 모릅니다)
TP_SL_PAIRS = [(3.0, 3.0), (5.0, 3.0), (3.0, 5.0), (5.0, 5.0), (10.0, 5.0)]
FIRST_TOUCH_BARS = {"5m": 48, "15m": 16}   # 둘 다 4시간


def first_touch(highs, lows, i, entry, tp, sl, is_long, max_bars) -> str:
    """진입 후 TP/SL 중 무엇이 먼저 닿는가 → 'TP' / 'SL' / 'NONE'.

    한 봉 안에서 둘 다 닿을 수 있으면 **SL 우선**으로 봅니다 (보수적 = 실제보다 나쁘게).
    """
    if is_long:
        tp_px, sl_px = entry * (1 + tp / 100), entry * (1 - sl / 100)
    else:
        tp_px, sl_px = entry * (1 - tp / 100), entry * (1 + sl / 100)

    end = min(i + 1 + max_bars, len(highs))
    for j in range(i + 1, end):
        if is_long:
            hit_sl = lows[j] <= sl_px
            hit_tp = highs[j] >= tp_px
        else:
            hit_sl = highs[j] >= sl_px
            hit_tp = lows[j] <= tp_px
        if hit_sl:
            return "SL"          # 보수적: 같은 봉이면 SL 먼저
        if hit_tp:
            return "TP"
    return "NONE"


def cols(kl):
    return ([float(k[2]) for k in kl], [float(k[3]) for k in kl], [float(k[4]) for k in kl])


def detect_events(kl, window: int, threshold: float) -> list[tuple[int, float]]:
    """롤링 창 누적 변동이 ±threshold% 를 처음 넘는 지점 (쿨다운 적용).

    Returns: [(index, 변동률%), ...]  변동률 부호가 급등/급락 구분!
    """
    highs, lows, closes = cols(kl)
    events: list[tuple[int, float]] = []
    cooldown = 0
    for i in range(window, len(kl)):
        if cooldown > 0:
            cooldown -= 1
            continue
        base = closes[i - window]
        if base <= 0:
            continue
        chg = (closes[i] - base) / base * 100
        if abs(chg) >= threshold:
            events.append((i, chg))
            cooldown = window   # 같은 급등을 여러 번 세지 않음
    return events


def study(kl, tf: str, threshold: float, acc: dict) -> None:
    highs, lows, closes = cols(kl)
    n = len(kl)
    mfe_bars = MFE_BARS[tf]

    for wlabel, window in WINDOWS[tf]:
        for i, chg in detect_events(kl, window, threshold):
            is_pump = chg > 0
            entry = closes[i]
            if entry <= 0:
                continue
            key = (wlabel, "급등" if is_pump else "급락")
            bucket = acc.setdefault(key, {
                "n": 0,
                "fwd": defaultdict(list),
                "mfe_long": [], "mae_long": [],
                "mfe_short": [], "mae_short": [],
                "ft": defaultdict(lambda: {"TP": 0, "SL": 0, "NONE": 0}),
            })
            bucket["n"] += 1

            # TP/SL 선착 판정 (양방향 × 여러 TP/SL 조합)
            for tp, sl in TP_SL_PAIRS:
                for dir_label, is_long in (("LONG", True), ("SHORT", False)):
                    res = first_touch(highs, lows, i, entry, tp, sl, is_long,
                                      FIRST_TOUCH_BARS[tf])
                    bucket["ft"][(dir_label, tp, sl)][res] += 1

            # 이후 구간별 가격 변화 (부호 그대로 = 가격 기준!)
            for flabel, fbars in FORWARD[tf]:
                j = i + fbars
                if j < n:
                    bucket["fwd"][flabel].append((closes[j] - entry) / entry * 100)

            # MFE / MAE (2시간)
            end = min(i + 1 + mfe_bars, n)
            if end > i + 1:
                seg_hi = max(highs[i + 1:end])
                seg_lo = min(lows[i + 1:end])
                up = (seg_hi - entry) / entry * 100
                dn = (seg_lo - entry) / entry * 100
                # LONG 진입 관점: 유리=위, 불리=아래
                bucket["mfe_long"].append(up)
                bucket["mae_long"].append(dn)
                # SHORT 진입 관점: 유리=아래(부호 반전), 불리=위
                bucket["mfe_short"].append(-dn)
                bucket["mae_short"].append(-up)


def _stat(xs: list[float]) -> tuple[float, float, float]:
    if not xs:
        return 0.0, 0.0, 0.0
    s = sorted(xs)
    return sum(xs) / len(xs), s[len(s) // 2], sum(1 for x in xs if x > 0) / len(xs) * 100


def report(tf: str, threshold: float, acc: dict) -> None:
    print(f"\n{'='*78}")
    print(f"📊 {tf} · 임계 {threshold:.0f}% 급등락")
    print("=" * 78)
    if not acc:
        print("  이벤트 없음")
        return

    for key in sorted(acc):
        wlabel, kind = key
        b = acc[key]
        print(f"\n▶ {wlabel} 안에 {threshold:.0f}% {kind} — {b['n']:,}건")
        print(f"   {'경과':<10}{'평균':>10}{'중앙값':>10}{'상승비율':>10}")
        print("   " + "-" * 40)
        for flabel, _ in FORWARD[tf]:
            xs = b["fwd"].get(flabel) or []
            if not xs:
                continue
            avg, med, up_ratio = _stat(xs)
            print(f"   {flabel:<10}{avg:>9.2f}%{med:>9.2f}%{up_ratio:>9.1f}%")

        # 방향 판정 = 추격 vs 역추세
        follow = "LONG" if kind == "급등" else "SHORT"
        fade = "SHORT" if kind == "급등" else "LONG"
        f_mfe = b["mfe_long"] if kind == "급등" else b["mfe_short"]
        f_mae = b["mae_long"] if kind == "급등" else b["mae_short"]
        d_mfe = b["mfe_short"] if kind == "급등" else b["mfe_long"]
        d_mae = b["mae_short"] if kind == "급등" else b["mae_long"]

        print(f"\n   {'진입방향':<14}{'MFE중앙':>10}{'MAE중앙':>10}{'MFE평균':>10}{'MAE평균':>10}")
        print("   " + "-" * 54)
        for label, mfe, mae in ((f"추격 {follow}", f_mfe, f_mae), (f"역추세 {fade}", d_mfe, d_mae)):
            if not mfe:
                continue
            _, mfe_med, _ = _stat(mfe)
            _, mae_med, _ = _stat(mae)
            print(f"   {label:<14}{mfe_med:>9.2f}%{mae_med:>9.2f}%"
                  f"{sum(mfe)/len(mfe):>9.2f}%{sum(mae)/len(mae):>9.2f}%")

        # 🎯 TP/SL 선착 = 실제 손익을 가르는 지표! (4시간 내)
        print(f"\n   {'TP/SL':<12}{'방향':<8}{'TP선착':>9}{'SL선착':>9}{'미결':>8}{'기대값':>10}")
        print("   " + "-" * 56)
        for tp, sl in TP_SL_PAIRS:
            for dir_label in (follow, fade):
                is_follow = dir_label == follow
                tag = "추격" if is_follow else "역추세"
                st = b["ft"].get((dir_label, tp, sl))
                if not st:
                    continue
                tot = st["TP"] + st["SL"] + st["NONE"]
                if not tot:
                    continue
                tp_r, sl_r = st["TP"] / tot * 100, st["SL"] / tot * 100
                # 기대값 = TP확률×TP − SL확률×SL (미결은 0 취급 = 보수적)
                ev = (st["TP"] * tp - st["SL"] * sl) / tot
                mark = " ⭐" if ev > 0 else ""
                print(f"   +{tp:.0f}%/-{sl:.0f}%{'':<4}{tag} {dir_label:<3}"
                      f"{tp_r:>8.1f}%{sl_r:>8.1f}%{st['NONE']/tot*100:>7.1f}%{ev:>+9.2f}%{mark}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache5m", required=True)
    ap.add_argument("--cache15m", required=True)
    ap.add_argument("--thresholds", default="")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    ths = [float(x) for x in args.thresholds.split(",")] if args.thresholds else THRESHOLDS

    files5 = sorted(glob.glob(os.path.join(args.cache5m, "*.json")))
    files15 = sorted(glob.glob(os.path.join(args.cache15m, "*.json")))
    if args.limit:
        files5, files15 = files5[:args.limit], files15[:args.limit]

    for th in ths:
        acc5: dict = {}
        for f in files5:
            try:
                kl = json.load(open(f))
                if isinstance(kl, list) and len(kl) > 60:
                    study(kl, "5m", th, acc5)
            except Exception:
                continue
        report("5m", th, acc5)

        acc15: dict = {}
        for f in files15:
            try:
                d = json.load(open(f))
                kl = d.get("15m") if isinstance(d, dict) else d
                if isinstance(kl, list) and len(kl) > 60:
                    study(kl, "15m", th, acc15)
            except Exception:
                continue
        report("15m", th, acc15)
    print()


if __name__ == "__main__":
    main()

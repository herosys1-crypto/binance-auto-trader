"""📊 백테스트 결과 집계 = 신 로직이 과거에 통했는지 검증 (v139)

`backtest_setup_grades.py` 가 만든 results.jsonl 을 읽어서:
  1. 실매매 = 등급/합의별 실제 손익
  2. 추천   = 등급별 추천 이후 실제 수익률 (1h/4h/24h)
  3. 필터 시뮬레이션 = 「D등급을 걸렀다면 손익이 어떻게 달라졌나?」

사용:
    python scripts/analyze_backtest_results.py results.jsonl

읽기 전용.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

MIN_SAMPLE = 10   # 이보다 적으면 「표본 부족」 표시


def _load(path: str) -> tuple[list[dict], list[dict]]:
    trades, suggs = [], []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        (trades if r["kind"] == "trade" else suggs).append(r)
    return trades, suggs


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _fmt_n(n: int) -> str:
    return f"{n}" + ("" if n >= MIN_SAMPLE else " ⚠️")


# ----------------------------------------------------------------------
def _median(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def trade_table(trades: list[dict], key: str, title: str) -> None:
    """⚠️ 평균 손익%는 이상치(소액 자본 × 큰 손익)에 심하게 오염되므로
    **중앙값 + 총 USDT + 승률**을 기준으로 봅니다."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        v = t.get(key)
        buckets[str(v)].append(t)

    print(f"\n### {title}")
    print(f"{'값':<16}{'건수':>7}{'승률':>9}{'중앙손익USDT':>14}{'총손익USDT':>14}{'평균USDT':>12}")
    print("-" * 74)
    for v in sorted(buckets):
        rows = buckets[v]
        wins = sum(1 for r in rows if r["win"])
        usdt = [r["pnl_usdt"] for r in rows]
        total = sum(usdt)
        print(f"{v:<16}{_fmt_n(len(rows)):>7}{wins/len(rows)*100:>8.1f}%"
              f"{_median(usdt):>14.1f}{total:>14.1f}{total/len(rows):>12.1f}")


def sugg_table(suggs: list[dict], key: str, title: str, horizon: str = "ret_4h") -> None:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for s in suggs:
        if s.get(horizon) is None:
            continue
        buckets[str(s.get(key))].append(s)

    print(f"\n### {title}  (기준: {horizon})")
    print(f"{'값':<16}{'건수':>7}{'적중률':>9}{'평균수익%':>12}{'중앙값%':>11}")
    print("-" * 58)
    for v in sorted(buckets):
        rows = buckets[v]
        rets = sorted(r[horizon] for r in rows)
        hits = sum(1 for x in rets if x >= 1.5)     # 예측 방향으로 +1.5% 이상
        med = rets[len(rets) // 2]
        print(f"{v:<16}{_fmt_n(len(rows)):>7}{hits/len(rows)*100:>8.1f}%"
              f"{_mean(rets):>11.2f}%{med:>10.2f}%")


def flag_table(rows: list[dict], flags: list[str], metric: str, title: str,
               is_trade: bool) -> None:
    """조건 ON/OFF 별 성과 비교.

    실매매(is_trade)는 **중앙값**으로 비교 (이상치 오염 회피),
    추천은 4h 수익률 평균으로 비교 (자본 개념이 없어 오염 없음).
    """
    agg = _median if is_trade else _mean
    unit = "USDT" if is_trade else "%"
    print(f"\n### {title}")
    print(f"{'조건':<20}{'Y건수':>7}{'Y'+('중앙' if is_trade else '평균'):>11}"
          f"{'N건수':>7}{'N'+('중앙' if is_trade else '평균'):>11}{'차이':>11}")
    print("-" * 70)
    for f in flags:
        y = [r[metric] for r in rows if r.get(f) is True and r.get(metric) is not None]
        n = [r[metric] for r in rows if r.get(f) is False and r.get(metric) is not None]
        if not y or not n:
            continue
        diff = agg(y) - agg(n)
        thr = 5.0 if is_trade else 0.5
        mark = " ⭐" if diff > thr and len(y) >= MIN_SAMPLE else (
            " 🚫" if diff < -thr and len(y) >= MIN_SAMPLE else "")
        print(f"{f:<20}{len(y):>7}{agg(y):>10.2f}{unit}{len(n):>7}"
              f"{agg(n):>10.2f}{unit}{diff:>+10.2f}{unit}{mark}")


def filter_sim(trades: list[dict]) -> None:
    """신 로직 필터를 과거에 적용했다면? (D등급 차단 시뮬레이션)"""
    print("\n### 🔬 필터 시뮬레이션 = 「그때 이 로직이 있었다면?」")
    print(f"{'필터':<38}{'남는 거래':>9}{'차단':>7}{'총손익USDT':>14}{'승률':>9}")
    print("-" * 78)

    def run(name: str, keep) -> None:
        kept = [t for t in trades if keep(t)]
        if not kept:
            print(f"{name:<38}{'0':>9}{len(trades):>7}{'-':>14}{'-':>9}")
            return
        total = sum(t["pnl_usdt"] for t in kept)
        wins = sum(1 for t in kept if t["win"])
        print(f"{name:<38}{len(kept):>9}{len(trades)-len(kept):>7}"
              f"{total:>14.1f}{wins/len(kept)*100:>8.1f}%")

    base = sum(t["pnl_usdt"] for t in trades)
    bw = sum(1 for t in trades if t["win"])
    print(f"{'(현재 = 필터 없음)':<38}{len(trades):>9}{0:>7}{base:>14.1f}{bw/len(trades)*100:>8.1f}%")
    run("① EMA/VCP D등급 차단", lambda t: t["ema_grade"] != "D")
    run("② SAR/구름대 D등급 차단", lambda t: t["sar_grade"] != "D")
    run("③ 둘 중 하나라도 D면 차단", lambda t: t["ema_grade"] != "D" and t["sar_grade"] != "D")
    run("④ 둘 다 D일 때만 차단", lambda t: not (t["ema_grade"] == "D" and t["sar_grade"] == "D"))
    run("⑤ 합의(AGREE 이상)만 진입", lambda t: t["conf_level"] in ("STRONG_AGREE", "AGREE"))
    run("⑥ 4H 추세(EMA50) 일치만", lambda t: t["trend_ok"])
    run("⑦ 4H 구름 일치만", lambda t: t["cloud_4h_ok"])
    run("⑧ 4H 추세 AND 구름 일치", lambda t: t["trend_ok"] and t["cloud_4h_ok"])


def stored_vs_real(suggs: list[dict]) -> None:
    """저장된 outcome_change vs 캔들 재계산 = 데이터 신뢰도 검증."""
    pairs = [(s["stored_chg_4h"], s["chg_4h"]) for s in suggs
             if s.get("stored_chg_4h") is not None and s.get("chg_4h") is not None]
    if not pairs:
        return
    diffs = [abs(a - b) for a, b in pairs]
    big = sum(1 for d in diffs if d > 1.0)
    print("\n### 🔍 저장된 outcome_change_4h vs 캔들 재계산")
    print(f"  비교 가능 {len(pairs)}건 / 평균 절대오차 {_mean(diffs):.2f}%p / "
          f"1%p 초과 불일치 {big}건 ({big/len(pairs)*100:.0f}%)")

    # 저장값 1h == 4h 인 오염 케이스
    same = [s for s in suggs if s.get("stored_chg_1h") is not None
            and s.get("stored_chg_4h") is not None
            and s["stored_chg_1h"] == s["stored_chg_4h"]]
    print(f"  저장값 1h == 4h (같은 pass에 채워짐) = {len(same)}건")


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else "results.jsonl"
    trades, suggs = _load(path)
    trades = [t for t in trades if t.get("pnl_usdt") is not None]

    print("=" * 78)
    print(f"📊 소급 백테스트 결과 — 실매매 {len(trades)}건 / 추천 {len(suggs)}건")
    print("=" * 78)

    total = sum(t["pnl_usdt"] for t in trades)
    wins = sum(1 for t in trades if t["win"])
    print(f"\n실매매 전체: 총 {total:+.1f} USDT / 승률 {wins/len(trades)*100:.1f}% "
          f"({wins}승 {len(trades)-wins}패) / 평균 {total/len(trades):+.1f} USDT")

    trade_table(trades, "ema_grade", "📐 EMA/VCP 등급별 실매매 성과")
    trade_table(trades, "sar_grade", "☁️ SAR/구름대 등급별 실매매 성과")
    trade_table(trades, "conf_level", "🤝 합의 수준별 실매매 성과")
    trade_table(trades, "trend_4h_dir", "🧭 진입 시점 4H 추세 방향별")
    trade_table(trades, "cloud_4h", "☁️ 진입 시점 4H 구름 위치별")

    flag_table(trades, ["trend_ok", "aligned_1h", "vcp", "vol_dry", "first_rally_only",
                        "breakout", "vol_spike", "cloud_4h_ok", "cloud_1h_ok",
                        "cloud_15m_ok", "sar_aligned", "sar_fresh"],
               "pnl_usdt", "🔎 개별 조건별 실매매 손익 (중앙값 USDT)", is_trade=True)

    filter_sim(trades)

    print("\n" + "=" * 78)
    print("📢 추천 분석 (실제 매매 안 한 것 포함)")
    print("=" * 78)
    for h in ("ret_1h", "ret_4h", "ret_24h"):
        n = sum(1 for s in suggs if s.get(h) is not None)
        print(f"  {h}: {n}건 관측")

    sugg_table(suggs, "ema_grade", "📐 EMA/VCP 등급별 추천 이후 수익률")
    sugg_table(suggs, "sar_grade", "☁️ SAR/구름대 등급별 추천 이후 수익률")
    sugg_table(suggs, "conf_level", "🤝 합의 수준별 추천 이후 수익률")
    sugg_table(suggs, "side", "↕️ 방향별 추천 이후 수익률")
    sugg_table(suggs, "trend_4h_dir", "🧭 4H 추세 방향별 추천 이후 수익률")

    flag_table([s for s in suggs if s.get("ret_4h") is not None],
               ["trend_ok", "aligned_1h", "vcp", "vol_dry", "first_rally_only",
                "breakout", "vol_spike", "cloud_4h_ok", "cloud_1h_ok",
                "cloud_15m_ok", "sar_aligned", "sar_fresh"],
               "ret_4h", "🔎 개별 조건별 추천 4h 평균 수익%", is_trade=False)

    stored_vs_real(suggs)
    print()


if __name__ == "__main__":
    main()

"""🔬 진입 시점 지표 복원 분석 — 이긴 진입과 진 진입은 무엇이 달랐나 (Fix 242).

사장님 지시 (2026-08-31):
  "**수동관리의 손실 차트와 보조지표를 분석**해서 자동매매는 이것도 활용해서
   수익을 만들 전략을 만들어줘"

## 왜 이 도구가 필요한가

`entry_context`(진입 당시 지표)가 **12.1%** 밖에 안 채워져 있다.
그래서 「이긴 진입과 진 진입의 지표 차이」를 낼 수 없었다.
Fix 240 이 앞으로의 수집은 고쳤지만, **이미 끝난 1,000여 건은 영원히 빈 채**다.

→ 진입 시각을 알고 있으니 **그 시점까지의 캔들을 거래소에서 다시 받아**
  지표를 사후 복원한다. 수동 손실 557건이 가장 큰 학습 표본이다.

## 실행

    docker compose exec -T api python scripts/analyze_entry_patterns.py --manual-only
    docker compose exec -T api python scripts/analyze_entry_patterns.py --auto-only
    docker compose exec -T api python scripts/analyze_entry_patterns.py --top 60 --side LONG

기본은 **손실 상위 N + 이익 상위 N** 만 본다 (API weight 보호).
`--top 0` 이면 전건 (느리다 — 심볼당 2회 호출).

## 무엇을 복원하나

진입 시각 기준 **4H(확정된 흐름) + 15m(진입 타이밍)** 두 시간대:

    RSI / CCI / MACD 히스토그램 / 볼밴 내 위치 / OBV 방향 / 최근 변동률
    + 🎯 **되돌림 비율** = (고점 - 진입가) / (고점 - 상승시작가)     [사장님 사상 ⑤]

되돌림은 사장님 말씀을 그대로 숫자로 옮긴 것이다 —
「급등 중 조정」인지 「원점 회귀」인지를 가르는 값.

⚠️ 읽기 전용. 주문도 DB 쓰기도 하지 않는다.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

sys.path.insert(0, "/app")

from app.core.database import SessionLocal                        # noqa: E402
from app.models.strategy_instance import StrategyInstance         # noqa: E402
from app.models.strategy_template import StrategyTemplate         # noqa: E402
from app.services.chart_analyzer import ChartAnalyzer             # noqa: E402
from app.services.obv_metrics import obv_direction_ratio          # noqa: E402
from app.services.retracement import retracement_ratio            # noqa: E402

TERMINAL = ("STOPPED", "COMPLETED", "CLOSED", "LIQUIDATED", "FAILED")


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError, InvalidOperation):
        return None
    return v if v == v else None


def _hr(t: str) -> None:
    print()
    print("=" * 84)
    print(f"  {t}")
    print("=" * 84)


# ───────────────────────────────────────────── 지표 복원

def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, period + 1):
        d = closes[-i] - closes[-i - 1]
        (gains if d > 0 else losses).append(abs(d))
    ag = sum(gains) / period
    al = sum(losses) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return 100.0 - (100.0 / (1.0 + rs))


def _ema(vals: list[float], n: int) -> list[float]:
    if len(vals) < n:
        return []
    k = 2.0 / (n + 1)
    out = [sum(vals[:n]) / n]
    for v in vals[n:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def _macd_hist(closes: list[float]) -> float | None:
    e12, e26 = _ema(closes, 12), _ema(closes, 26)
    if not e12 or not e26:
        return None
    off = len(e12) - len(e26)
    macd = [a - b for a, b in zip(e12[off:], e26)]
    sig = _ema(macd, 9)
    if not sig:
        return None
    return macd[-1] - sig[-1]


def _bb_pos(closes: list[float], n: int = 20) -> float | None:
    """볼밴 내 위치: 0 = 하단, 0.5 = 중단, 1 = 상단. 밖이면 0 미만 / 1 초과."""
    if len(closes) < n:
        return None
    w = closes[-n:]
    mid = sum(w) / n
    sd = statistics.pstdev(w)
    if sd == 0:
        return None
    up, lo = mid + 2 * sd, mid - 2 * sd
    return (closes[-1] - lo) / (up - lo)


def _snapshot(bc, symbol: str, at_ms: int) -> dict[str, float | None]:
    """진입 시각까지의 캔들로 지표를 복원한다."""
    out: dict[str, float | None] = {}
    for iv, tag, lim in (("15m", "15m", 120), ("4h", "4h", 120)):
        try:
            kl = bc.get_klines(symbol=symbol, interval=iv, limit=lim, end_time=at_ms)
        except Exception:
            kl = None
        if not kl or len(kl) < 30:
            continue
        closes = [_f(k[4]) for k in kl]
        closes = [c for c in closes if c is not None]
        vols = [_f(k[5]) or 0.0 for k in kl]
        if len(closes) < 30:
            continue
        out[f"rsi_{tag}"] = _rsi(closes)
        out[f"macd_h_{tag}"] = _macd_hist(closes)
        out[f"bb_pos_{tag}"] = _bb_pos(closes)
        try:
            cci = ChartAnalyzer.compute_cci(kl)
            out[f"cci_{tag}"] = _f(cci[-1]) if cci else None
        except Exception:
            out[f"cci_{tag}"] = None
        try:
            obv = [float(x) for x in ChartAnalyzer.compute_obv(kl)]
            out[f"obv_dir_{tag}"] = obv_direction_ratio(obv, vols, 20)
        except Exception:
            out[f"obv_dir_{tag}"] = None
        if tag == "4h":
            # 사장님 사상 ⑤ — 되돌림 비율 (급등 중 조정인가 / 원점 회귀인가)
            r, _det = retracement_ratio(closes, 60)
            out["retrace_4h"] = r
            if len(closes) >= 19:
                out["chg_3d_pct"] = (closes[-1] - closes[-19]) / closes[-19] * 100
        else:
            if len(closes) >= 97:
                out["chg_24h_pct"] = (closes[-1] - closes[-97]) / closes[-97] * 100
    return out


# ───────────────────────────────────────────── 수집

def collect(db, days: int, mode: str, side: str | None, top: int) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    q = (
        db.query(StrategyInstance, StrategyTemplate)
        .outerjoin(StrategyTemplate,
                   StrategyInstance.strategy_template_id == StrategyTemplate.id)
        .filter(StrategyInstance.status.in_(TERMINAL))
        .filter(StrategyInstance.created_at >= since)
    )
    rows = []
    for si, tpl in q:
        name = (tpl.name if tpl else "") or ""
        manual = name.startswith("_quick_")
        if mode == "manual" and not manual:
            continue
        if mode == "auto" and manual:
            continue
        sd = (si.side or "").upper()
        if side and sd != side:
            continue
        at = si.started_at or si.created_at
        if at is None:
            continue
        rows.append({
            "id": si.id, "symbol": si.symbol, "side": sd,
            "pnl": _f(si.realized_pnl) or 0.0,
            "at_ms": int(at.timestamp() * 1000),
            "manual": manual,
        })
    if top > 0:
        rows.sort(key=lambda r: r["pnl"])
        rows = rows[:top] + rows[-top:]
        seen, uniq = set(), []
        for r in rows:
            if r["id"] not in seen:
                seen.add(r["id"])
                uniq.append(r)
        rows = uniq
    return rows


# ───────────────────────────────────────────── 출력

KEYS = [
    ("retrace_4h", "되돌림비율 4H", "🎯 사장님 사상 ⑤ — 0.3~0.6=추세중 조정 / 0.7↑=원점회귀"),
    ("chg_3d_pct", "3일 변동%", "급등 강도"),
    ("chg_24h_pct", "24h 변동%", "당일 급등락"),
    ("bb_pos_4h", "볼밴위치 4H", "1.0 초과 = 상단 밖 (사장님 ① 본격 진입 조건)"),
    ("bb_pos_15m", "볼밴위치 15m", ""),
    ("rsi_4h", "RSI 4H", ""),
    ("rsi_15m", "RSI 15m", "SHORT 게이트 65 / LONG 35"),
    ("cci_4h", "CCI 4H", ""),
    ("cci_15m", "CCI 15m", "게이트 ±80"),
    ("macd_h_4h", "MACD히스트 4H", ""),
    ("macd_h_15m", "MACD히스트 15m", ""),
    ("obv_dir_4h", "OBV방향 4H", "🎯 사장님 사상 ④ — -1~+1"),
    ("obv_dir_15m", "OBV방향 15m", ""),
]


def _med(vals: list[float]) -> float | None:
    return statistics.median(vals) if vals else None


def report(rows: list[dict], label: str) -> None:
    win = [r for r in rows if r["pnl"] > 0]
    los = [r for r in rows if r["pnl"] < 0]
    _hr(f"{label} — 이긴 진입 {len(win)}건 vs 진 진입 {len(los)}건")
    if not win or not los:
        print("  한쪽 표본이 없어 비교할 수 없습니다.")
        return
    print(f"{'지표':<16}{'승 n':>5}{'승 중앙값':>12}{'패 n':>6}{'패 중앙값':>12}"
          f"{'차이':>12}   설명")
    print("-" * 84)
    ranked = []
    for key, name, note in KEYS:
        wv = [v for r in win if (v := r["snap"].get(key)) is not None]
        lv = [v for r in los if (v := r["snap"].get(key)) is not None]
        if len(wv) < 3 or len(lv) < 3:
            continue
        wm, lm = _med(wv), _med(lv)
        diff = wm - lm
        ranked.append((abs(diff), key, name, len(wv), wm, len(lv), lm, diff, note))
    if not ranked:
        print("  복원된 표본이 너무 적습니다 (캔들 조회 실패 가능).")
        return
    for _a, _k, name, nw, wm, nl, lm, diff, note in sorted(ranked, reverse=True):
        print(f"{name:<16}{nw:>5}{wm:>12.3f}{nl:>6}{lm:>12.3f}{diff:>+12.3f}   {note}")
    print()
    print("  ※ 위쪽일수록 **승패를 가르는 힘이 큰 지표**다 (중앙값 차이 순).")
    print("     차이가 0 부근이면 그 지표를 게이트로 써도 효과가 없다.")


def report_retrace_buckets(rows: list[dict], label: str) -> None:
    """🎯 사장님 사상 ⑤ 를 직접 검증 — 되돌림 구간별로 성적이 갈리는가."""
    _hr(f"{label} — 되돌림 비율 구간별 성적 (사장님 사상 ⑤ 검증)")
    have = [r for r in rows if r["snap"].get("retrace_4h") is not None]
    if len(have) < 10:
        print(f"  되돌림이 복원된 건: {len(have)}건 — 표본 부족.")
        return
    buckets = [(-9.9, 0.30, "0.3 미만 (고점 부근)"),
               (0.30, 0.60, "0.30~0.60 (추세중 조정) ← 사장님 진입 자리"),
               (0.60, 0.70, "0.60~0.70 (깊은 조정)"),
               (0.70, 1.00, "0.70~1.00 (원점 회귀) ← 사장님 금지"),
               (1.00, 99.0, "1.00 초과 (원점 아래)")]
    print(f"{'되돌림 구간':<42}{'건수':>6}{'승률':>8}{'합계':>12}")
    print("-" * 70)
    for lo, hi, name in buckets:
        g = [r for r in have if lo <= r["snap"]["retrace_4h"] < hi]
        if not g:
            continue
        w = sum(1 for r in g if r["pnl"] > 0)
        tot = sum(r["pnl"] for r in g)
        print(f"{name:<42}{len(g):>6}{w / len(g) * 100:>7.1f}%{tot:>+12.2f}")
    print()
    print("  ※ 「추세중 조정」 줄이 「원점 회귀」 줄보다 좋으면 사장님 사상 ⑤ 가 실측으로 확인된 것이고,")
    print("     그대로 게이트로 넣으면 된다. 반대면 임계값을 데이터에 맞춰 다시 잡아야 한다.")


def _make_client(db):
    """mainnet Binance client — learning_sync_worker 와 같은 방식."""
    from sqlalchemy import select
    from app.core.crypto import decrypt_text
    from app.integrations.binance.client import BinanceClient
    from app.models.exchange_account import ExchangeAccount
    account = db.execute(
        select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
    ).scalar_one_or_none()
    if not account:
        raise RuntimeError("mainnet ExchangeAccount 가 없습니다")
    return BinanceClient(
        api_key=decrypt_text(account.api_key_enc),
        api_secret=decrypt_text(account.api_secret_enc),
        is_testnet=False,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--top", type=int, default=60,
                    help="손실 상위 N + 이익 상위 N 만 분석 (0=전건)")
    ap.add_argument("--manual-only", action="store_true")
    ap.add_argument("--auto-only", action="store_true")
    ap.add_argument("--side", type=str, default=None, choices=["LONG", "SHORT"])
    ap.add_argument("--sleep-ms", type=int, default=120,
                    help="호출 간 대기 (IP ban 방지)")
    args = ap.parse_args()

    mode = "manual" if args.manual_only else ("auto" if args.auto_only else "all")
    label = {"manual": "수동", "auto": "자동", "all": "전체"}[mode]
    if args.side:
        label += f" {args.side}"

    db = SessionLocal()
    try:
        rows = collect(db, args.days, mode, args.side, args.top)
        if not rows:
            print()
            print("  대상이 없습니다.")
            return
        print()
        print(f"  대상 {len(rows)}건 — 진입 시점 캔들을 다시 받아 지표를 복원합니다.")
        print(f"  (건당 2회 호출 · 대기 {args.sleep_ms}ms · 예상 {len(rows) * 2} 호출)")
        print()
        bc = _make_client(db)

        done = ok = 0
        for r in rows:
            r["snap"] = _snapshot(bc, r["symbol"], r["at_ms"])
            done += 1
            if r["snap"]:
                ok += 1
            if done % 20 == 0:
                print(f"    ... {done}/{len(rows)}  (복원 성공 {ok})")
            time.sleep(max(0, args.sleep_ms) / 1000.0)
        print(f"    복원 완료: {ok}/{len(rows)}")

        report(rows, label)
        report_retrace_buckets(rows, label)
        if not args.side:
            for sd in ("LONG", "SHORT"):
                sub = [r for r in rows if r["side"] == sd]
                if len(sub) >= 10:
                    report(sub, f"{label} {sd}")
                    report_retrace_buckets(sub, f"{label} {sd}")
        print()
    finally:
        db.close()


if __name__ == "__main__":
    main()

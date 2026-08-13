"""📊 과거 매매/추천에 신 전략 로직을 소급 적용하는 백테스트 (v139)

사장님 요청 2026-08-14:
  "지금까지 매매의 성공과 실패를 분석하고 지금 새로만들 로직에 비교해서
   다음 전략의 로직에 반영할수 있게 분석해주고, 실제 매매는 하지 않았지만
   추천 시점과 그후를 분석해서 로직에 반영해줘"

= 신 로직(v137 EMA/VCP + v138 SAR/구름대 + 합의)은 아직 배포 전이라
  entry_context에 등급이 안 쌓여 있습니다.
  → **과거 시점으로 되돌아가 그때 등급이 뭐였을지 재현**해서 실제 결과와 대조!

⚠️ lookahead(미래 참조) 금지:
  각 시점 T에서 open_time <= T 인 캔들만 사용합니다.
  마지막 캔들 = T 시점에 「진행 중」이던 봉 = 실거래와 동일한 상태!

사용:
    python scripts/backtest_setup_grades.py --dataset dataset.json --out results.jsonl
    python scripts/backtest_setup_grades.py --aggregate results.jsonl

읽기 전용 — 주문 X, DB 쓰기 X.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services import strategy_confluence  # noqa: E402
from app.services.ema_vcp_analyzer import EMAVCPAnalyzer  # noqa: E402
from app.services.sar_ichimoku_analyzer import SARIchimokuAnalyzer  # noqa: E402

FAPI = "https://fapi.binance.com/fapi/v1/klines"
INTERVAL_MS = {"15m": 15 * 60_000, "1h": 60 * 60_000, "4h": 4 * 60 * 60_000}

# 분석기가 요구하는 최소 캔들 수 + 여유
NEED_BARS = {"15m": 120, "1h": 120, "4h": 120}
# 각 시점 이전으로 확보해야 하는 여유 기간 (4h × 120 = 20일)
LOOKBACK_DAYS = 24
# 추천 이후 관찰 기간
FORWARD_HOURS = 24


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


# ----------------------------------------------------------------------
# 캔들 수집 (심볼 단위 = 메모리 절약!)
# ----------------------------------------------------------------------
def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int,
                 sleep: float = 0.12) -> list:
    """Binance 선물 캔들 (공개 엔드포인트, 인증 X). 페이지네이션 포함."""
    out: list = []
    cur = start_ms
    step = INTERVAL_MS[interval]
    while cur < end_ms:
        url = (f"{FAPI}?symbol={symbol}&interval={interval}"
               f"&startTime={cur}&endTime={end_ms}&limit=1500")
        for attempt in range(5):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    batch = json.load(r)
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 418):
                    time.sleep(5 * (attempt + 1))
                    continue
                if e.code == 400:
                    return out          # 상장 전 / 심볼 없음
                raise
            except Exception:
                time.sleep(1 + attempt)
        else:
            break
        if not batch:
            break
        out.extend(batch)
        last_open = int(batch[-1][0])
        if len(batch) < 1500:
            break
        cur = last_open + step
        time.sleep(sleep)
    return out


def slice_at(klines: list, ts_ms: int, need: int) -> list | None:
    """시점 ts_ms 기준 「그때 보였던」 캔들만 반환 (lookahead 차단!).

    마지막 원소 = ts_ms 를 포함하는 진행 중 봉 = 실거래와 동일.
    """
    idx = -1
    for i, k in enumerate(klines):
        if int(k[0]) <= ts_ms:
            idx = i
        else:
            break
    if idx < need - 1:
        return None
    return klines[idx - need + 1: idx + 1]


def price_at(klines_15m: list, ts_ms: int) -> float | None:
    """그 시점에 알 수 있었던 가격 = 직전 완료 15m 봉 종가."""
    prev = None
    for k in klines_15m:
        close_time = int(k[6])
        if close_time <= ts_ms:
            prev = k
        else:
            break
    return float(prev[4]) if prev else None


# ----------------------------------------------------------------------
# 평가
# ----------------------------------------------------------------------
def evaluate_point(kl: dict, ts: datetime, side: str) -> dict:
    """시점 ts 에서 두 분석기 + 합의를 재현."""
    ts_ms = _ms(ts)
    k4 = slice_at(kl["4h"], ts_ms, NEED_BARS["4h"])
    k1 = slice_at(kl["1h"], ts_ms, NEED_BARS["1h"])
    k15 = slice_at(kl["15m"], ts_ms, NEED_BARS["15m"])
    if not (k4 and k1 and k15):
        return {"ok": False, "reason": "캔들 부족"}

    ema = EMAVCPAnalyzer(None).analyze("X", side, klines_4h=k4, klines_1h=k1, klines_15m=k15)
    sar = SARIchimokuAnalyzer(None).analyze("X", side, klines_4h=k4, klines_1h=k1, klines_15m=k15)
    conf = strategy_confluence.evaluate(ema, sar, side)

    t1e, t1s = ema.get("tf_1h") or {}, sar.get("tf_1h") or {}
    t4e, t4s = ema.get("tf_4h") or {}, sar.get("tf_4h") or {}
    t15e, t15s = ema.get("tf_15m") or {}, sar.get("tf_15m") or {}
    return {
        "ok": True,
        "ema_grade": ema.get("grade"), "ema_score": ema.get("score"),
        "sar_grade": sar.get("grade"), "sar_score": sar.get("score"),
        "conf_level": conf.get("level"), "conf_score": conf.get("score"),
        # 개별 조건 = 어떤 조건이 실제로 유효했나?
        "trend_ok": bool(t4e.get("ok")),
        "trend_4h_dir": t4e.get("direction"),
        "aligned_1h": bool(t1e.get("aligned")),
        "vcp": bool(t1e.get("vcp_contracting")),
        "vol_dry": bool(t1e.get("volume_dry")),
        "first_rally_only": bool(t1e.get("first_rally_only")),
        "breakout": bool(t15e.get("breakout_closed") or t15e.get("breakout_intrabar")),
        "vol_spike": bool(t15e.get("volume_spike")),
        "cloud_4h": t4s.get("position"),
        "cloud_4h_ok": bool(t4s.get("ok")),
        "cloud_1h_ok": bool(t1s.get("ok")),
        "cloud_15m_ok": bool(t15s.get("ok")),
        "sar_aligned": bool(t15s.get("sar_aligned")),
        "sar_fresh": bool((t15s.get("sar") or {}).get("fresh_flip")),
    }


def run(dataset_path: str, out_path: str, cache_dir: str, limit_symbols: int = 0) -> None:
    data = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    trades = [t for t in data["trades"] if t.get("entry_time")]
    suggs = data["suggestions"]

    items: dict[str, list] = {}
    for t in trades:
        items.setdefault(t["symbol"], []).append(("trade", t))
    for s in suggs:
        items.setdefault(s["symbol"], []).append(("sugg", s))

    symbols = sorted(items)
    if limit_symbols:
        symbols = symbols[:limit_symbols]

    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    out = open(out_path, "w", encoding="utf-8")
    done = skipped = 0

    for n, symbol in enumerate(symbols, 1):
        rows = items[symbol]
        times = []
        for kind, r in rows:
            times.append(_parse(r["entry_time"] if kind == "trade" else r["created_at"]))
        start = min(times) - timedelta(days=LOOKBACK_DAYS)
        end = max(times) + timedelta(hours=FORWARD_HOURS + 2)

        cache_file = Path(cache_dir) / f"{symbol}.json"
        if cache_file.exists():
            kl = json.loads(cache_file.read_text())
        else:
            kl = {}
            for iv in ("4h", "1h", "15m"):
                kl[iv] = fetch_klines(symbol, iv, _ms(start), _ms(end))
            cache_file.write_text(json.dumps(kl), encoding="utf-8")

        if not kl.get("15m"):
            skipped += len(rows)
            print(f"[{n}/{len(symbols)}] {symbol}: 캔들 없음 — {len(rows)}건 skip", flush=True)
            continue

        for kind, r in rows:
            ts = _parse(r["entry_time"] if kind == "trade" else r["created_at"])
            side = (r["side"] or "LONG").upper()
            ev = evaluate_point(kl, ts, side)
            if not ev["ok"]:
                skipped += 1
                continue

            rec = {"kind": kind, "symbol": symbol, "side": side,
                   "ts": ts.isoformat(), **{k: v for k, v in ev.items() if k != "ok"}}

            if kind == "trade":
                cap = float(r["total_capital"] or 0)
                pnl = float(r["realized_pnl"] or 0)
                rec.update({
                    "id": r["id"],
                    "pnl_usdt": pnl,
                    "pnl_pct": round(pnl / cap * 100, 4) if cap > 0 else None,
                    "win": pnl > 0,
                    "max_profit_pct": float(r["max_profit_pct"]) if r.get("max_profit_pct") else None,
                    "max_loss_pct": float(r["max_loss_pct"]) if r.get("max_loss_pct") else None,
                    "entry_fills": r.get("entry_fills"),
                    "leverage": float(r["leverage"]) if r.get("leverage") else None,
                })
            else:
                p0 = price_at(kl["15m"], _ms(ts))
                fwd = {}
                for h in (1, 4, 24):
                    p = price_at(kl["15m"], _ms(ts + timedelta(hours=h)))
                    if p0 and p:
                        chg = (p - p0) / p0 * 100
                        # 방향 보정 = 「내 예측이 맞았는가」 기준!
                        fwd[f"ret_{h}h"] = round(chg if side == "LONG" else -chg, 4)
                        fwd[f"chg_{h}h"] = round(chg, 4)
                    else:
                        fwd[f"ret_{h}h"] = None
                        fwd[f"chg_{h}h"] = None
                rec.update({
                    "id": r["id"],
                    "price_at": p0,
                    "confidence": float(r["confidence_score"]) if r.get("confidence_score") else None,
                    "stored_outcome": r.get("outcome_status"),
                    "stored_chg_1h": float(r["outcome_change_1h"]) if r.get("outcome_change_1h") else None,
                    "stored_chg_4h": float(r["outcome_change_4h"]) if r.get("outcome_change_4h") else None,
                    "executed": bool(r.get("executed_at")),
                    **fwd,
                })

            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            done += 1

        print(f"[{n}/{len(symbols)}] {symbol}: {len(rows)}건 처리 (누적 {done}, skip {skipped})", flush=True)

    out.close()
    print(f"\n완료: {done}건 평가 / {skipped}건 skip → {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="dataset.json")
    ap.add_argument("--out", default="results.jsonl")
    ap.add_argument("--cache", default="klines_cache")
    ap.add_argument("--limit-symbols", type=int, default=0)
    args = ap.parse_args()
    run(args.dataset, args.out, args.cache, args.limit_symbols)


if __name__ == "__main__":
    main()

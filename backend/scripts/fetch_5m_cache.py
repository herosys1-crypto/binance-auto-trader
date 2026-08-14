"""📥 페이지네이션 캔들 캐시 수집 (v141/v146 급등락 연구용).

기존 klines_cache 의 심볼 목록을 그대로 써서 5m 캔들을 받아 별도 캐시에 저장합니다.
(Binance 공개 엔드포인트 = 인증 불필요, 읽기 전용)

사용:
    python scripts/fetch_5m_cache.py --cache <klines_cache> --out <cache_5m> --days 25
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

FAPI = "https://fapi.binance.com/fapi/v1/klines"
STEP_MS_BY_INTERVAL = {"1m": 60_000, "3m": 180_000, "5m": 300_000,
                       "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000}


def fetch(symbol: str, start_ms: int, end_ms: int, interval: str = "5m") -> list:
    out: list = []
    cur = start_ms
    step = STEP_MS_BY_INTERVAL[interval]
    while cur < end_ms:
        url = (f"{FAPI}?symbol={symbol}&interval={interval}"
               f"&startTime={cur}&endTime={end_ms}&limit=1500")
        batch = None
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
                    return out
                raise
            except Exception:
                time.sleep(1 + attempt)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 1500:
            break
        cur = int(batch[-1][0]) + step
        time.sleep(0.12)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True, help="기존 klines_cache (심볼 목록 소스)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--days", type=int, default=25)
    ap.add_argument("--interval", default="5m")
    args = ap.parse_args()

    symbols = [Path(f).stem for f in sorted(glob.glob(os.path.join(args.cache, "*.json")))]
    Path(args.out).mkdir(parents=True, exist_ok=True)

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    s_ms, e_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)

    done = 0
    for n, sym in enumerate(symbols, 1):
        dest = Path(args.out) / f"{sym}.json"
        if dest.exists():
            done += 1
            continue
        kl = fetch(sym, s_ms, e_ms, args.interval)
        dest.write_text(json.dumps(kl), encoding="utf-8")
        done += 1
        if n % 20 == 0:
            print(f"  ... {n}/{len(symbols)} ({sym}: {len(kl)}봉 {args.interval})", flush=True)
    print(f"완료: {done}개 심볼 → {args.out}")


if __name__ == "__main__":
    main()

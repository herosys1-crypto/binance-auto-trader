"""📥 범용 캔들 캐시 수집기 (연구용, 공개 엔드포인트 = 인증 X).

기존 캐시의 심볼 목록을 재사용해 원하는 interval 을 받아 저장합니다.

사용:
    python scripts/fetch_klines_cache.py --symbols-from <klines_cache> \
        --interval 4h --limit 1500 --out <cache_4h_deep>
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

FAPI = "https://fapi.binance.com/fapi/v1/klines"


def fetch(symbol: str, interval: str, limit: int) -> list:
    url = f"{FAPI}?symbol={symbol}&interval={interval}&limit={limit}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 400:
                return []
            time.sleep(3 * (attempt + 1))
        except Exception:
            time.sleep(1 + attempt)
    return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols-from", required=True)
    ap.add_argument("--interval", required=True)
    ap.add_argument("--limit", type=int, default=1500)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    symbols = [Path(f).stem for f in
               sorted(glob.glob(os.path.join(args.symbols_from, "*.json")))]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    got = 0
    for n, sym in enumerate(symbols, 1):
        dest = out / f"{sym}.json"
        if dest.exists():
            got += 1
            continue
        kl = fetch(sym, args.interval, args.limit)
        dest.write_text(json.dumps(kl), encoding="utf-8")
        if kl:
            got += 1
        if n % 40 == 0:
            print(f"  {n}/{len(symbols)} ({sym}: {len(kl)}봉)", flush=True)
        time.sleep(0.08)
    print(f"완료: {got}/{len(symbols)} 심볼 → {out}")


if __name__ == "__main__":
    main()

"""가상매매 진입 심볼의 봉을 바이낸스 공개 API 로 받아 캐시한다 (로컬 IP, 요청 무게 조절)."""
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
CACHE = HERE / "klines"
CACHE.mkdir(exist_ok=True)
d = pd.read_csv(HERE / "dumpall.csv", usecols=["symbol"], low_memory=False)
symbols = sorted(d.symbol.unique())

def ms(s):
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000)

PLAN = [  # (interval, startTime, limit)
    ("1d", ms("2026-05-20"), 150),
    ("4h", ms("2026-08-25"), 200),
    ("1h", ms("2026-09-05"), 350),
    ("5m", ms("2026-09-08T20:00:00"), 1500),
    ("5m", None, 1500),          # 이어받기
]

def get(url):
    for attempt in range(5):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                used = int(r.headers.get("X-MBP-USED-WEIGHT-1M", "0"))
                return json.loads(r.read()), used
        except urllib.error.HTTPError as e:
            if e.code in (418, 429):
                print("ban/limit", e.code, "— 90초 대기", flush=True)
                time.sleep(90)
            elif e.code == 400:
                return [], 0
            else:
                time.sleep(3)
        except Exception:
            time.sleep(3)
    return [], 0

t0 = time.time()
for i, sym in enumerate(symbols):
    out = CACHE / f"{sym}.json"
    if out.exists():
        continue
    data = {}
    last5 = None
    for iv, start, limit in PLAN:
        if iv == "5m" and start is None:
            if not last5:
                continue
            start = last5 + 1
        rows, used = get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval={iv}&startTime={start}&limit={limit}")
        if iv == "5m":
            data.setdefault("5m", []).extend(rows)
            last5 = rows[-1][0] if rows else None
        else:
            data[iv] = rows
        if used > 1500:
            time.sleep(20)
        else:
            time.sleep(0.12)
    out.write_text(json.dumps(data))
    if i % 25 == 0:
        print(f"{i}/{len(symbols)} {sym} used={used} {time.time()-t0:.0f}s", flush=True)
print("DONE", len(list(CACHE.glob('*.json'))), f"{time.time()-t0:.0f}s", flush=True)

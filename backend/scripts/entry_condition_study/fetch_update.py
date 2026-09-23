"""캐시에 최신 봉만 덧붙인다 (없는 심볼은 전체 받음). 로컬 IP · 요청 무게 조절."""
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent
CACHE = HERE / "klines"
CACHE.mkdir(exist_ok=True)
symbols = sorted(pd.read_csv(HERE / "dumpall.csv", usecols=["symbol"], low_memory=False).symbol.unique())

def ms(s):
    return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp() * 1000)

FULL = [("1d", ms("2026-05-20"), 150), ("4h", ms("2026-08-25"), 200), ("1h", ms("2026-09-05"), 350),
        ("5m", ms("2026-09-08T20:00:00"), 1500), ("5m", None, 1500), ("5m", None, 1500)]
TAIL = {"1d": 10, "4h": 30, "1h": 60, "5m": 900}      # 최근만 덧붙이기

def get(url):
    for _ in range(5):
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (418, 429):
                print("limit — 90초 대기", flush=True); time.sleep(90)
            elif e.code == 400:
                return []
            else:
                time.sleep(3)
        except Exception:
            time.sleep(3)
    return []

def merge(old, new):
    by = {int(k[0]): k for k in (old or [])}
    for k in new or []:
        by[int(k[0])] = k
    return [by[t] for t in sorted(by)]

t0, new_syms, updated = time.time(), 0, 0
for i, sym in enumerate(symbols):
    p = CACHE / f"{sym}.json"
    if not p.exists():
        data, last5 = {}, None
        for iv, start, limit in FULL:
            if iv == "5m" and start is None:
                if not last5:
                    continue
                start = last5 + 1
            rows = get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval={iv}&startTime={start}&limit={limit}")
            if iv == "5m":
                data["5m"] = merge(data.get("5m"), rows)
                last5 = rows[-1][0] if rows else None
            else:
                data[iv] = rows
            time.sleep(0.12)
        p.write_text(json.dumps(data))
        new_syms += 1
        continue
    data = json.loads(p.read_text())
    for iv, lim in TAIL.items():
        if iv == "5m":
            rows = get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=5m&limit=1000")
            rows += get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval=5m&startTime={ms('2026-09-14')}&limit=1000")
        else:
            rows = get(f"https://fapi.binance.com/fapi/v1/klines?symbol={sym}&interval={iv}&limit={lim}")
        data[iv] = merge(data.get(iv), rows)
        time.sleep(0.12)
    p.write_text(json.dumps(data))
    updated += 1
    if i % 50 == 0:
        print(f"{i}/{len(symbols)} {sym} {time.time()-t0:.0f}s", flush=True)
print(f"DONE 갱신 {updated} · 신규 {new_syms} · {time.time()-t0:.0f}s", flush=True)

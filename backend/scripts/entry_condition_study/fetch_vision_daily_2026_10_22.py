"""바이낸스 공개 데이터(data.binance.vision) USDT 무기한 일봉 전체 — 상장 폐지 종목 포함 (2026-10-22, 마틴게일 재측정용 · 생존 편향 제거) — 읽기 전용 · 로컬.

월별 zip(data/futures/um/monthly/klines/SYM/1d/) 을 받아 fapi 일봉과 같은 모양 [open_time, o, h, l, c, v, close_time, quote_vol, …] 으로
cache_daily_vision/SYM_1d.json 에 저장한다. 최근 몇 주(월 파일이 아직 없는 달)는 cache_daily_bb(fapi, 현재 상장 종목만) 로 이어 붙인다.
현재 상장 종목 목록 = cache_daily_bb 파일 이름 · 그 밖은 「폐지」로 표시(listed.json).
"""
from __future__ import annotations

import csv
import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "cache_daily_vision"
FAPI = HERE / "cache_daily_bb"
S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
DL = "https://data.binance.vision/"
PREFIX = "data/futures/um/monthly/klines/"


def _get(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read()
        except Exception:  # noqa: BLE001
            if i == tries - 1:
                raise
    return b""


def _list(prefix, delim=True):
    keys, marker = [], ""
    while True:
        url = f"{S3}?prefix={urllib.parse.quote(prefix)}&marker={urllib.parse.quote(marker)}" + ("&delimiter=/" if delim else "")
        x = _get(url).decode()
        tag = "Prefix" if delim else "Key"
        got = re.findall(rf"<{tag}>([^<]+)</{tag}>", x)
        keys += [g for g in got if g != prefix]
        if "<IsTruncated>true</IsTruncated>" not in x:
            return keys
        nm = re.search(r"<NextMarker>([^<]+)</NextMarker>", x)
        marker = nm.group(1) if nm else got[-1]


def fetch(sym):
    dst = OUT / f"{sym}_1d.json"
    if dst.exists():
        return sym, "cache"
    rows = {}
    for key in _list(f"{PREFIX}{sym}/1d/", delim=False):
        if not key.endswith(".zip"):
            continue
        z = zipfile.ZipFile(io.BytesIO(_get(DL + urllib.parse.quote(key))))
        for row in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
            if not row or not row[0].isdigit():
                continue                                          # 머리글 줄
            rows[int(row[0])] = [int(row[0]), *row[1:6], int(row[6]), row[7], *row[8:11]]
    fp = FAPI / f"{sym}_1d.json"
    if fp.exists():                                               # 월 파일 없는 최근 구간 = fapi 캐시로 채움
        for k in json.loads(fp.read_text()):
            rows.setdefault(int(k[0]), k)
    if not rows:
        return sym, "empty"
    dst.write_text(json.dumps([rows[t] for t in sorted(rows)]))
    return sym, len(rows)


def main():
    OUT.mkdir(exist_ok=True)
    syms = [p[len(PREFIX):-1] for p in _list(PREFIX)]
    syms = [s for s in syms if s.endswith("USDT") and "_" not in s]
    listed = sorted(p.name[:-8] for p in FAPI.glob("*_1d.json"))
    (OUT / "listed.json").write_text(json.dumps(listed))
    print(f"USDT 무기한 {len(syms)}종목 (현재 상장 {len(set(syms) & set(listed))} · 폐지 {len(set(syms) - set(listed))})")
    with ThreadPoolExecutor(12) as ex:
        for i, (s, r) in enumerate(ex.map(fetch, syms), 1):
            if i % 50 == 0 or r == "empty":
                print(i, s, r, flush=True)


if __name__ == "__main__":
    main()

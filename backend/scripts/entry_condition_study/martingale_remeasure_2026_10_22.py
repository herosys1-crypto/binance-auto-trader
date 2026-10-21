"""Fix 477 펌프·덤프 SHORT 마틴게일 재측정 (2026-10-22 인계 대기열 2 「2025 이전 데이터 · 다음 날 시가 체결 · 동시 3개 한도 · 상장 폐지 종목 포함」) — 읽기 전용 · 로컬.

신호 = app.services.pump_dump_short.detect 그대로(운영 그림자와 같은 함수) · 두 안 A·B = PLANS 그대로 · 레버 1 · 10일.
데이터 = fetch_vision_daily_2026_10_22.py (data.binance.vision 월 파일 · 폐지 종목 포함 · 2019~) .
조건을 하나씩 더해 어디서 숫자가 바뀌는지 본다:
  S0 옛 측정 재현 = 현재 상장 종목만 · 종가 체결 · 추가·손절은 문턱 가격 · 끝 안 난 건 버림 · 동시 한도 없음
  S1 + 폐지 종목 포함 (데이터가 끊기면 마지막 종가에 정리 = 「폐지」)
  S2 + 다음 날 시가 체결 · 갭 체결(시가가 문턱을 넘어 열리면 추가·손절·청산은 시가 · 익절은 문턱 그대로 = 보수적)
  S3 + 동시 3개 한도 (날짜 순 · 같은 날은 거래대금 배수 큰 순 — 「Claude가 정함」)
  S4 + 펀딩 (data.binance.vision fundingRate · SHORT 는 양수면 받고 음수면 냄 · 그날 종가 × 수량)
일봉 안 순서 모름 → 보수적: 추가 뒤 손절·청산 먼저, 익절은 그다음 (운영 simulate 와 같음).
"""
from __future__ import annotations

import csv
import io
import json
import sys
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from app.services import pump_dump_short as PDS  # noqa: E402

DATA = HERE / "cache_daily_vision"
FUND = HERE / "cache_funding_vision"
MM = PDS.MM
FEE = 0.0005
HOLD = 10
CAP = 3
DAY = 86400000


def load():
    listed = set(json.loads((DATA / "listed.json").read_text()))
    last_all = 0
    out = {}
    for p in sorted(DATA.glob("*_1d.json")):
        kl = json.loads(p.read_text())
        if len(kl) < 70:
            continue
        out[p.name[:-8]] = kl
        last_all = max(last_all, int(kl[-1][0]))
    return out, listed, last_all


def signals(kl, p):
    ev = []
    for n in range(62, len(kl)):
        sig = PDS.detect(kl[n - 61:n + 1], p)
        if sig:
            ev.append((n, sig))
    return ev


def _fund_get(sym):
    dst = FUND / f"{sym}.json"
    if dst.exists():
        return
    import re
    S3 = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
    pre = f"data/futures/um/monthly/fundingRate/{sym}/"
    keys, marker = [], ""
    while True:
        x = urllib.request.urlopen(f"{S3}?prefix={urllib.parse.quote(pre)}&marker={urllib.parse.quote(marker)}", timeout=30).read().decode()
        got = re.findall(r"<Key>([^<]+)</Key>", x)
        keys += got
        if "<IsTruncated>true</IsTruncated>" not in x or not got:
            break
        marker = got[-1]
    day = defaultdict(float)
    for k in keys:
        if not k.endswith(".zip"):
            continue
        z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen("https://data.binance.vision/" + urllib.parse.quote(k), timeout=30).read()))
        for row in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]))):
            if row and row[0].isdigit():
                day[int(row[0]) // DAY * DAY] += float(row[-1])
    dst.write_text(json.dumps(day))


def funding(syms):
    FUND.mkdir(exist_ok=True)
    with ThreadPoolExecutor(12) as ex:
        list(ex.map(_fund_get, syms))
    return {s: {int(k): v for k, v in json.loads((FUND / f"{s}.json").read_text()).items()} for s in syms}


def sim(kl, n, sig, plan, *, open_fill, gap, delisted, fund=None):
    t0 = [int(k[0]) for k in kl]
    o = [float(k[1]) for k in kl]
    h = [float(k[2]) for k in kl]
    lw = [float(k[3]) for k in kl]
    c = [float(k[4]) for k in kl]
    nums = plan.numbers(1.0)
    if open_fill:
        if n + 1 >= len(c):
            return None
        p0, j0 = o[n + 1], n + 1
    else:
        p0, j0 = c[n], n + 1
    legs = [(p0, nums["margins"][0])]
    trig = [(p0 * x, m) for m, x in zip(nums["margins"][1:], nums["mults"][1:])]
    stop = p0 * nums["stop"]
    half = sig["half"]
    exit_px = why = j_end = None
    fpnl = 0.0
    for j in range(j0, min(len(c), n + 1 + HOLD)):
        while trig and h[j] >= trig[0][0]:
            px, m = trig.pop(0)
            legs.append((max(px, o[j]) if gap else px, m))
        qty = sum(m / px for px, m in legs)
        avg = sum(m for _px, m in legs) / qty
        margin = sum(m for _px, m in legs)
        liq = avg + (margin - avg * qty * MM) / qty
        if not trig and stop < liq and h[j] >= stop:
            exit_px, why, j_end = (max(stop, o[j]) if gap else stop), "손절", j
            break
        if h[j] >= liq:
            exit_px, why, j_end = (max(liq, o[j]) if gap else liq), "청산", j
            break
        tp = min(half, avg * 0.995)
        if lw[j] <= tp:
            exit_px, why, j_end = tp, "익절", j          # 익절은 문턱 그대로(그날 추가로 평단이 바뀐 뒤 시가 체결은 불가능 → 유리한 가정 금지)
            break
        if fund is not None:
            fpnl += qty * c[j] * fund.get(t0[j] // DAY * DAY, 0.0)
    if exit_px is None:
        if n + HOLD > len(c) - 1:
            if not delisted:
                return None                       # 아직 안 끝남(상장 중)
            j_end = len(c) - 1
            exit_px, why = c[j_end], "폐지"
        else:
            j_end = n + HOLD
            exit_px, why = c[j_end], "시간"
    pnl = fe = 0.0
    for px, m in legs:
        q = m / px
        pnl += q * (px - exit_px)
        fe += (m + q * exit_px) * FEE
    return {"pnl": pnl - fe + fpnl, "fund": fpnl, "stages": len(legs), "why": why,
            "d": datetime.fromtimestamp(t0[n] / 1000, timezone.utc).date().isoformat(), "end_ms": t0[j_end], "start_ms": t0[n],
            "used": sum(m for _px, m in legs)}


def capped(rows, cap):
    out, open_until = [], []
    for r in sorted(rows, key=lambda r: (r["start_ms"], -r["vol"])):
        open_until = [x for x in open_until if x > r["start_ms"]]
        if len(open_until) >= cap:
            continue
        out.append(r)
        open_until.append(r["end_ms"])
    return out


def line(name, rs):
    if not rs:
        return f"| {name} | 0 |"
    p = [r["pnl"] for r in rs]
    cum = peak = mdd = 0.0
    for r in sorted(rs, key=lambda r: r["d"]):
        cum += r["pnl"]
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    pre = sum(r["pnl"] for r in rs if r["d"] < "2025")
    post = sum(r["pnl"] for r in rs if r["d"] >= "2025")
    npre = sum(r["d"] < "2025" for r in rs)
    yr = defaultdict(float)
    for r in rs:
        yr[r["d"][:4]] += r["pnl"]
    why = defaultdict(int)
    for r in rs:
        why[r["why"]] += 1
    st = defaultdict(int)
    for r in rs:
        st[r["stages"]] += 1
    fund = sum(r["fund"] for r in rs)
    return (f"| {name} | {len(rs)} | {sum(p):+,.0f} | {sum(p) / len(p):+.1f} | {sum(x > 0 for x in p) / len(p):.0%} | "
            f"{pre:+,.0f} ({npre}) → {post:+,.0f} ({len(rs) - npre}) | {mdd:+,.0f} | {min(p):+,.0f} | "
            + "/".join(str(st[k]) for k in sorted(st)) + " | "
            + " ".join(f"{k}{v}" for k, v in sorted(why.items())) + f" | {fund:+,.0f} | "
            + " ".join(f"{y}:{v:+,.0f}" for y, v in sorted(yr.items())) + " |")


def main():
    data, listed, last_all = load()
    p = PDS.params_from()
    evs = []
    for sym, kl in data.items():
        delisted = sym not in listed or int(kl[-1][0]) < last_all - 3 * DAY
        for n, sig in signals(kl, p):
            evs.append((sym, n, sig, delisted))
    syms = sorted({e[0] for e in evs})
    first = min(e[2]["entry_day"] for e in evs)
    print(f"# Fix 477 펌프·덤프 SHORT 마틴게일 재측정 — 종목 {len(data)} (상장 {len(listed & set(data))} · 폐지 {len(set(data) - listed)}) · "
          f"신호 {len(evs)} (폐지 종목 {sum(e[3] for e in evs)}) · 첫 신호 {datetime.fromtimestamp(first / 1000, timezone.utc).date()} · 레버 1 · {HOLD}일")
    fund = funding(syms)
    hdr = ("| 단계 | 거래 | 합 USDT | 건당 | 이긴 비율 | ~2024 (건) → 2025~ (건) | 누적 최대 낙폭 | 최악 1건 | 단계 분포 | 끝난 이유 | 펀딩 | 연도별 |\n"
           "|---|---|---|---|---|---|---|---|---|---|---|---|")
    for key, plan in PDS.PLANS.items():
        print(f"\n## {plan.label}\n")
        print(hdr)

        def rows(only_listed, **kw):
            out = []
            for sym, n, sig, dl in evs:
                if only_listed and dl:
                    continue
                r = sim(data[sym], n, sig, plan, delisted=dl, **kw)
                if r:
                    r["vol"] = sig["vol_mult"]
                    out.append(r)
            return out
        s0 = rows(True, open_fill=False, gap=False)
        s1 = rows(False, open_fill=False, gap=False)
        s2 = rows(False, open_fill=True, gap=True)
        print(line("S0 옛 측정 재현(상장만·종가·문턱 체결)", s0))
        print(line("S1 + 폐지 종목", s1))
        print(line("S2 + 다음 날 시가·갭 체결", s2))
        print(line("S3 + 동시 3개", capped(s2, CAP)))
        s4 = []
        for sym, n, sig, dl in evs:
            r = sim(data[sym], n, sig, plan, open_fill=True, gap=True, delisted=dl, fund=fund.get(sym, {}))
            if r:
                r["vol"] = sig["vol_mult"]
                s4.append(r)
        print(line("S4 + 펀딩 (= 동시 3개 · 최종)", capped(s4, CAP)))
        print(line("참고: S4 동시 한도 없음", s4))


if __name__ == "__main__":
    main()

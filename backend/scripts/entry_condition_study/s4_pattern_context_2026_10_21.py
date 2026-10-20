"""S4(실주문 급반등 꼭대기 SHORT) × 사장님 일봉 세 그림 (2026-10-21) — 읽기 전용 · 로컬 실행.

사장님: 「이것과 기존의 만들어져 있는 우리 로직으로 운영할 수 있게 수정·보완해서 손실은 줄이고 이익은 높이는 전략」
그림 이름(Claude가 붙임 — 사장님 설명 그대로):
  ① 정상 추세 (코인 자체 상승 이슈) — 일봉이 꾸준히 오르며 볼밴 중단(심하면 하단) 지지 뒤 다시 상승
  ② 세력 펌프·회귀 (며칠~몇 주)     — 급상승 → 중단·하단 조정 → 재상승 → 결국 원점
  ③ 세력 펌프·덤프 (당일~며칠)      — 시총 낮은 종목을 그날 이슈로 급등시킨 뒤 바로 하락
입력: 서버 가상 S4 행(source=live · CLOSED · zone_s4_spike_top_short · roi) JSON = [[symbol, opened_at, chg_24h, roi], …]
     (서버 읽기 전용 쿼리로 받음) + daily_bb_pullback_study 캐시(일봉) + CoinGecko 시총·유통 비율(받은 날 값)
진입 날의 그림 판정은 **진입 전날까지 마감한 일봉**만 쓴다(미래 참조 없음). 숫자는 모두 「Claude가 정함」.
  ③ 후보 = 진입 전 3일 안에 일봉 종가가 3일 최저가 대비 +30% 이상(급등 날이 있었다)
  ② 후보 = 직전 30일 고점이 60일 최저 대비 +30% 이상 · 랠리 하루 상승률 ≥ 3%
  ① 후보 = 같은 랠리 조건 · 하루 상승률 < 1% · 중단 위
  그 밖 = 랠리 없음(평범)
사용: python s4_pattern_context_2026_10_21.py <s4rows.json>
"""
from __future__ import annotations

import bisect
import importlib.util
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
_s = importlib.util.spec_from_file_location("dbb", HERE / "daily_bb_pullback_study_2026_10_21.py")
DBB = importlib.util.module_from_spec(_s)
_s.loader.exec_module(DBB)
_t = importlib.util.spec_from_file_location("d3", HERE / "daily_three_patterns_2026_10_21.py")
D3 = importlib.util.module_from_spec(_t)
_t.loader.exec_module(D3)
NET = 0.4


def context(kl, t):
    """t = 진입 전날까지 마감한 마지막 일봉 인덱스."""
    h = [float(k[2]) for k in kl[:t + 1]]
    lw = [float(k[3]) for k in kl[:t + 1]]
    c = [float(k[4]) for k in kl[:t + 1]]
    if t < 95:
        return "자료 부족"
    mid, _up, _lo = DBB.bands(c)
    for d in range(t - 2, t + 1):
        base = min(lw[d - 3:d + 1])
        if base > 0 and c[d] / base - 1 >= 0.30:
            return "③ 펌프·덤프 후보(3일 안 +30% 급등)"
    pk_i = max(range(t - 30, t + 1), key=lambda j: h[j])
    or_i = min(range(max(0, pk_i - 60), pk_i + 1), key=lambda j: lw[j])
    gain = h[pk_i] / lw[or_i] - 1 if lw[or_i] > 0 else 0
    if gain >= 0.30:
        speed = gain / max(1, pk_i - or_i)
        if speed >= 0.03:
            return "② 펌프·회귀 후보(급등 랠리)"
        if speed < 0.01 and c[t] >= mid[t]:
            return "① 정상 추세(완만 랠리 · 중단 위)"
        return "랠리 중간 속도"
    return "랠리 없음(평범)"


def main():
    rows = json.loads(Path(sys.argv[1]).read_text())
    info = D3.coin_info()
    kls = {}
    out = []
    for sym, at, chg, roi in rows:
        if sym not in kls:
            p = DBB.CACHE / f"{sym}_1d.json"
            kls[sym] = json.loads(p.read_text()) if p.exists() else None
        kl = kls[sym]
        if not kl:
            continue
        ts = datetime.fromisoformat(at).timestamp() * 1000
        opens = [int(k[0]) for k in kl]
        t = bisect.bisect_right(opens, ts) - 2          # 진입 봉(그날) 바로 앞 = 전날 마감 봉
        if t < 0:
            continue
        ci = info.get(D3.base_of(sym), {})
        out.append({"sym": sym, "at": at, "d": at[:10], "filt": chg is not None and chg >= 10, "net": roi - NET,
                    "ctx": context(kl, t), "mcap": ci.get("mcap"), "float": ci.get("float")})
    print(f"# S4 가상 {len(rows)}건 중 일봉 짝 {len(out)} · {out[0]['d']}~{out[-1]['d']} · 순수익 = roi − {NET} · 「필터 안」 = 실주문과 같은 24h +10%↑")

    def tab(title, key, groups):
        print(f"\n## {title}\n| 구간 | 필터 안 n (날) | 필터 안 순수익 | 이긴 비율 | 앞 → 뒤 | 전체 n | 전체 순수익 |\n|---|---|---|---|---|---|---|")
        for nm, f in groups:
            g = [x for x in out if f(key(x))]
            fi = [x for x in g if x["filt"]]
            if not g:
                continue
            ds = sorted({x["d"] for x in fi})
            mid = ds[len(ds) // 2] if ds else ""
            a = [x["net"] for x in fi if x["d"] < mid]
            b = [x["net"] for x in fi if x["d"] >= mid]
            m = lambda v: f"{sum(v) / len(v):+.2f}" if v else "—"   # noqa: E731
            print(f"| {nm} | {len(fi)} ({len(ds)}) | {m([x['net'] for x in fi])} | "
                  f"{(sum(x['net'] > 0 for x in fi) / len(fi)) if fi else 0:.0%} | {m(a)} → {m(b)} | {len(g)} | {m([x['net'] for x in g])} |")

    ctxs = sorted({x["ctx"] for x in out})
    tab("그림별", lambda x: x["ctx"], [(c, lambda v, c=c: v == c) for c in ctxs])
    tab("시총별", lambda x: x["mcap"], [(nm, lambda v, a=a, b=b: v is not None and a <= v < b) for nm, a, b in D3.MCAP]
        + [("시총 모름", lambda v: v is None)])
    tab("유통 비율별", lambda x: x["float"], [(nm, lambda v, a=a, b=b: v is not None and a <= v < b) for nm, a, b in D3.FLOAT])
    small = lambda x: (x["mcap"] or 9e99) < 2e8                                            # noqa: E731
    tab("그림 × 시총(2억$ 기준)", lambda x: x, [(f"{c} · {'소형' if s else '중대형'}", lambda v, c=c, s=s: v["ctx"] == c and small(v) == s)
                                             for c in ctxs for s in (True, False)])


if __name__ == "__main__":
    main()

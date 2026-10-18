"""🏁 Fix 471 (2026-10-18 사장님 「가상매매를 통해서 확실하게 성공하는 전략을 만들어줘」) — 일목 실험실 승격 관문 (순수 함수, 주문 없음).

100% 확실한 전략은 없다 → 「우연이 아니라는 증거가 충분히 쌓인 줄만」 검증 통과 후보로 올린다. 승격은 알림까지 — 실주문은 사장님 승인.
관문 G1~G7 (docs/spec/ICHIMOKU_KIJUN_COMBO_2026-10-18.md 11절, 숫자는 전부 「Claude가 정함」):
  G1 진입일 ≥ 60 · 건수 ≥ 100     G2 무작위 대비 날 차이 99.9% 아래 끝 > 0 (72줄 다중 비교 보정)
  G3 비용 뒤 평균 R > 0            G4 앞·뒤 절반 날 차이 둘 다 > 0      G5 최고 5일 빼도 날 차이 > 0
  G6 월별 일관성 — 진입일 ≥ 5 인 달이 3개 이상이고 그중 2/3 이상의 달에서 무작위 대비 날 차이 > 0
     (처음엔 「BTC 상승·하락 장세 둘 다 +」였으나 이 전략은 BTC 장세로 방향을 정해 한쪽 장세에서만 거래한다 → 구조적으로 통과 불가.
      과거 재생 72줄에서 확인 뒤 교체 — 10/18)                                                    G7 실주문 끝난 ≥ 10건이면 실주문 R − 실험실 R ≥ −0.3
상태: 검증 통과 · 관찰(G1 미달) · 탈락(G1 충족 뒤 다른 관문 실패).
"""
from __future__ import annotations

import math
import random
from typing import Any, Callable, Iterable

DAY = 86_400_000
PASS, WATCH, FAIL = "검증 통과", "관찰", "탈락"

SETTINGS: dict[str, tuple[str, float, float]] = {        # 키: (기본, 최소, 최대)
    "ichipromo_min_days": ("60", 1, 3650),
    "ichipromo_min_n": ("100", 1, 100000),
    "ichipromo_q": ("0.001", 0.0001, 0.05),
    "ichipromo_boot": ("5000", 200, 50000),
    "ichipromo_top_days": ("5", 0, 100),
    "ichipromo_month_min_days": ("5", 1, 31),
    "ichipromo_months_min": ("3", 1, 120),
    "ichipromo_month_share": ("0.667", 0.5, 1.0),
    "ichipromo_live_min": ("10", 1, 10000),
    "ichipromo_paired_share": ("0.8", 0.5, 1.0),
    "ichipromo_live_gap": ("-0.3", -10, 0),
}
SEED = 471


def params_from(get: Callable[[str], Any] | None = None) -> dict[str, float]:
    out = {}
    for k, (d, lo, hi) in SETTINGS.items():
        x = float(d)
        if get is not None:
            try:
                y = float(str(get(k)).strip())
                if math.isfinite(y) and lo <= y <= hi:
                    x = y
            except (TypeError, ValueError):
                pass
        out[k] = x
    return out


def _month(day_index: int) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(day_index * 86400, tz=_dt.timezone.utc).strftime("%Y-%m")


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _boot_q(vals: list[float], q: float, n_boot: int, seed: int) -> float:
    rng = random.Random(seed)
    n = len(vals)
    means = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return means[max(0, min(n_boot - 1, int(math.floor(q * n_boot))))]


def gate(sig_rows: list[dict], rand_r: dict[Any, float], applied_rows: list[dict], p: dict[str, float],
         seed: int = SEED) -> dict:
    """한 줄(변형×방향)의 관문 결과. sig_rows = 마감 신호 행 {entry_bar_ts, r_net, btc_up, pair_key}."""
    rows = sorted((r for r in sig_rows if r.get("r_net") is not None), key=lambda r: (r["entry_bar_ts"], r.get("symbol", "")))
    n = len(rows)
    days_all = {int(r["entry_bar_ts"]) // DAY for r in rows}
    byday: dict[int, list[float]] = {}
    for r in rows:
        pr = rand_r.get(r.get("pair_key"))
        if pr is not None:
            byday.setdefault(int(r["entry_bar_ts"]) // DAY, []).append(float(r["r_net"]) - pr)
    dv = [sum(byday[d]) / len(byday[d]) for d in sorted(byday)]
    g: dict[str, bool | None] = {}
    det: dict[str, Any] = {"n": n, "days": len(days_all), "paired_days": len(dv)}
    # 교차 감사: 짝(무작위) 없는 신호가 많으면 G2·G4·G5 가 소수의 짝 있는 날로만 판정된다 → 진입일의 80% 이상에 짝이 있어야 표본으로 친다
    g["G1"] = (len(days_all) >= p["ichipromo_min_days"] and n >= p["ichipromo_min_n"]
               and len(dv) >= p["ichipromo_paired_share"] * len(days_all))
    avg = _mean([float(r["r_net"]) for r in rows])
    det["avg_r"] = avg
    g["G3"] = avg is not None and avg > 0
    if len(dv) >= 2:
        h = len(dv) // 2
        det["first_half"], det["second_half"] = _mean(dv[:h]), _mean(dv[h:])
        g["G4"] = det["first_half"] > 0 and det["second_half"] > 0
        k = int(p["ichipromo_top_days"])
        rest = sorted(dv, reverse=True)[k:]
        det["edge_wo_top"] = _mean(rest)
        g["G5"] = det["edge_wo_top"] is not None and det["edge_wo_top"] > 0
        if g["G1"]:                                  # 부트스트랩은 표본 관문을 넘은 줄만 (비싸다)
            det["low_q"] = _boot_q(dv, p["ichipromo_q"], int(p["ichipromo_boot"]), seed)
            g["G2"] = det["low_q"] > 0
        else:
            g["G2"] = None
    else:
        g["G2"] = g["G4"] = g["G5"] = None
    bymon: dict[str, list[float]] = {}
    for d in sorted(byday):
        mon = _month(d)
        bymon.setdefault(mon, []).append(sum(byday[d]) / len(byday[d]))
    months = {m: _mean(v) for m, v in bymon.items() if len(v) >= p["ichipromo_month_min_days"]}
    good = sum(1 for v in months.values() if v is not None and v > 0)
    det["months"] = {"counted": len(months), "positive": good}
    for name, flag in (("up", True), ("down", False)):          # 참고 표시만 (관문 아님)
        rr = [r for r in rows if r.get("btc_up") is flag]
        det[f"regime_{name}"] = {"days": len({int(r["entry_bar_ts"]) // DAY for r in rr}),
                                 "avg_r": _mean([float(r["r_net"]) for r in rr])}
    g["G6"] = len(months) >= p["ichipromo_months_min"] and good >= p["ichipromo_month_share"] * len(months)
    live = [a for a in applied_rows if a.get("live_r") is not None and a.get("lab_r") is not None]
    if len(live) >= p["ichipromo_live_min"]:
        det["live_gap"] = _mean([a["live_r"] for a in live]) - _mean([a["lab_r"] for a in live])
        g["G7"] = det["live_gap"] >= p["ichipromo_live_gap"]
    else:
        g["G7"] = None                              # 실주문 표본 없음 = 이 관문은 아직 적용 안 함
    if not g["G1"]:
        status = WATCH
    elif all(g[x] is True for x in ("G2", "G3", "G4", "G5", "G6")) and g["G7"] in (True, None):
        status = PASS
    else:
        status = FAIL
    det["missing"] = [x for x in ("G1", "G2", "G3", "G4", "G5", "G6", "G7") if g[x] is False or (x != "G7" and g[x] is None)]
    return {"status": status, "gates": g, "detail": det}


def evaluate_all(rows: Iterable[dict], applied_rows: list[dict], p: dict[str, float]) -> dict[tuple[str, str], dict]:
    """rows = 실험실 마감 행 전부(sig + rand). → {(variant, side): gate 결과}."""
    sig: dict[tuple[str, str], list[dict]] = {}
    rand_r: dict[Any, float] = {}
    for r in rows:
        if r.get("r_net") is None:
            continue
        if r["kind"] == "sig":
            sig.setdefault((r["variant"], r["side"]), []).append(r)
        elif r["kind"] == "rand":
            rand_r[r["pair_key"]] = float(r["r_net"])
    out = {}
    for key, rs in sorted(sig.items()):
        ap = [a for a in applied_rows if (a.get("variant"), a.get("side")) == key]
        out[key] = gate(rs, rand_r, ap, p, seed=SEED + sum(map(ord, key[0] + key[1])))
    return out


def transitions(prev_pass: Iterable[str], now_pass: Iterable[str]) -> tuple[list[str], list[str]]:
    """→ (새로 통과, 통과 해제). 키 = "variant|side"."""
    a, b = set(prev_pass), set(now_pass)
    return sorted(b - a), sorted(a - b)

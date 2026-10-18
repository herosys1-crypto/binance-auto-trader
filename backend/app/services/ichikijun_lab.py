"""🗾 Fix 465 — 일목 기준선 변형 실험실 순위표·챔피언 (순수 함수, 주문 없음).

순위 = 같은 시각 무작위 짝 대비 **날 단위 차이의 날 묶음 부트스트랩 95% 아래 끝** (승률 순이 아님 — 승률은 열로 보여 준다).
  왜: 익절을 좁히면 승률은 얼마든지 오른다(1R 익절 53% 인데 본전) → 승률 1위를 고르면 돈 잃는 변형이 뽑힌다.
챔피언 교체 = 도전자 점수 > 챔피언 점수 + margin 이 streak 일 연속. 챔피언은 실주문을 켜지 않는다(사장님 승인 사항).
숫자 기본값은 전부 「Claude가 정함」 (docs/spec/ICHIMOKU_KIJUN_COMBO_2026-10-18.md 8절).
"""
from __future__ import annotations

import math
import random
from typing import Any, Callable, Iterable

SETTINGS: dict[str, tuple[str, str, float, float]] = {
    # 키: (기본, 설명, 최소, 최대)
    "ichilab_enabled": ("1", "실험실 워커 켜기 (0 = 끔)", 0, 1),
    "ichilab_top_n": ("40", "감시 종목 = 거래량 상위 N (+BTC + 열린 행 심볼)", 5, 100),
    "ichilab_cost_pct": ("0.1", "왕복 비용 % 가정 (수수료+슬리피지, 실측 아님)", 0, 1),
    "ichilab_min_days": ("20", "챔피언 자격: 진입일 수", 1, 365),
    "ichilab_min_n": ("30", "챔피언 자격: 건수", 1, 10000),
    "ichilab_switch_margin": ("0.02", "교체: 도전자 점수가 챔피언보다 이만큼(R) 높아야", 0, 1),
    "ichilab_switch_days": ("3", "교체: 위 조건이 이 일수 연속", 1, 30),
}
BOOT_N = 2000
BOOT_SEED = 465


def params_from(get: Callable[[str], Any] | None = None) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, (d, _desc, lo, hi) in SETTINGS.items():
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


def _boot_low(vals: list[float], seed: int) -> float:
    rng = random.Random(seed)
    n = len(vals)
    means = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(BOOT_N))
    return means[int(0.025 * BOOT_N)]


def build_board(rows: Iterable[dict], params: dict[str, float]) -> list[dict]:
    """rows = 마감 행 dict(kind, variant, side, symbol, entry_bar_ts, r_net, pair_key). pair_key = 신호 행과 짝을 잇는 값.
    반환 = 변형×방향 줄 목록 (score 내림차순 · 자격 미달은 score None, 뒤로)."""
    sig: dict[tuple[str, str], list[dict]] = {}
    rnd: dict[Any, float] = {}
    for r in rows:
        if r.get("r_net") is None:
            continue
        if r["kind"] == "sig":
            sig.setdefault((r["variant"], r["side"]), []).append(r)
        elif r["kind"] == "rand":
            rnd[r["pair_key"]] = float(r["r_net"])
    board = []
    for (var, side), rs in sig.items():
        rs.sort(key=lambda x: (x["entry_bar_ts"], x["symbol"]))
        n = len(rs)
        wins = sum(1 for x in rs if float(x["r_net"]) > 0)
        avg = sum(float(x["r_net"]) for x in rs) / n
        byday: dict[int, list[float]] = {}
        paired = []
        for x in rs:
            pr = rnd.get(x["pair_key"])
            if pr is None:
                continue
            paired.append(pr)
            byday.setdefault(int(x["entry_bar_ts"]) // 86_400_000, []).append(float(x["r_net"]) - pr)
        days = sorted(byday)
        dv = [sum(byday[d]) / len(byday[d]) for d in days]
        row: dict[str, Any] = {"variant": var, "side": side, "n": n, "days": len({int(x["entry_bar_ts"]) // 86_400_000 for x in rs}),
                               "win": wins / n, "avg_r": avg, "rand_r": (sum(paired) / len(paired)) if paired else None,
                               "edge": (sum(dv) / len(dv)) if dv else None, "low95": None, "first_half": None,
                               "second_half": None, "score": None}
        if len(dv) >= 2:
            h = len(dv) // 2
            row["first_half"], row["second_half"] = sum(dv[:h]) / h, sum(dv[h:]) / (len(dv) - h)
            row["low95"] = _boot_low(dv, BOOT_SEED + sum(map(ord, var + side)))
        if row["days"] >= params["ichilab_min_days"] and n >= params["ichilab_min_n"] and row["low95"] is not None:
            row["score"] = row["low95"]
        board.append(row)
    board.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0.0), -r["n"]))
    return board


def update_champion(prev: dict | None, board: list[dict], streak: dict | None, params: dict[str, float],
                    today: str) -> tuple[dict | None, dict, bool]:
    """→ (새 챔피언, 새 연속 기록, 바뀜). prev/streak 는 저장된 JSON(dict) 또는 None.
    같은 날 두 번 불러도 연속 일수는 한 번만 센다(streak["day"])."""
    best = next((r for r in board if r["score"] is not None), None)
    streak = dict(streak or {})
    if best is None:
        return prev, {}, False
    key = f'{best["variant"]}|{best["side"]}'
    snap = {k: best[k] for k in ("variant", "side", "score", "win", "avg_r", "edge", "n", "days")}
    if prev is None:
        return {**snap, "since": today}, {}, True
    pkey = f'{prev.get("variant")}|{prev.get("side")}'
    cur = next((r for r in board if f'{r["variant"]}|{r["side"]}' == pkey), None)
    cur_score = cur["score"] if cur is not None else None
    if key == pkey:
        return {**prev, **snap}, {}, False
    beats = cur_score is None or best["score"] > cur_score + params["ichilab_switch_margin"]
    if not beats:
        refreshed = {**prev, **({k: cur[k] for k in snap if k in cur} if cur else {})}
        return refreshed, {}, False
    if streak.get("key") == key:
        if streak.get("day") != today:
            streak = {"key": key, "count": int(streak.get("count", 0)) + 1, "day": today}
    else:
        streak = {"key": key, "count": 1, "day": today}
    if streak["count"] >= params["ichilab_switch_days"]:
        return {**snap, "since": today, "prev": pkey}, {}, True
    return prev, streak, False

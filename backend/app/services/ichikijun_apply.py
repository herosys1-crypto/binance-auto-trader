"""🗾 Fix 466 (2026-10-18 사장님 「시스템은 개발해 두고 가상매매로 업데이트 지속적으로 하고 시스템을 적용해서 나오는 결과도 검토해야해」)
— 일목 실험실 변형을 **사람이 만드는 예약 전략 인스턴스**에 적용 + 적용 결과 검토. 순수 함수(주문·DB 없음).

entry_signal (strategy_instances, alembic 0042):
  NULL                    = 기존 예약 경로 그대로 (check_stage_entry_signal)
  "ichikijun"             = 지금 실험실 챔피언 변형 (방향이 같을 때만)
  "ichikijun:<변형 키>"   = 72줄 중 그 변형 고정
판정 함수는 실험실과 같은 `ichimoku_kijun.entry_at` — 가상과 실주문이 같은 자리에서 들어간다.
숫자(신선도 30/90분 · 만료 30일)는 「Claude가 정함」 (docs/spec/ICHIMOKU_KIJUN_COMBO_2026-10-18.md 9절).
"""
from __future__ import annotations

import json
import math
from typing import Any

from app.services import ichimoku_kijun as IK

PREFIX = "ichikijun"
CHAMPION = "champion"
IV_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
FRESH_MIN = {"1h": 30, "4h": 30, "1d": 90}       # 봉 마감 뒤 이 분 안에만 진입 (Claude가 정함 — 늦은 진입 금지)
EXPIRE_DAYS_KEY = "ichikijun_sched_expire_days"
EXPIRE_DAYS_DEFAULT = 30                          # 일봉 신호가 드물어 기존 예약 7일보다 길게 (Claude가 정함)
ROI_CAP = 999.0                                   # Numeric(5,2) 상한


def parse_entry_signal(v: Any) -> tuple[bool, str | None]:
    """→ (허용, 변형 키 | "champion" | None). None 입력 = 기존 경로(허용, None)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return True, None
    if not isinstance(v, str):
        return False, None
    s = v.strip()
    if s == PREFIX:
        return True, CHAMPION
    if s.startswith(PREFIX + ":") and s[len(PREFIX) + 1:] in IK.BY_KEY:
        return True, s[len(PREFIX) + 1:]
    return False, None


def is_ichikijun(v: Any) -> bool:
    ok, key = parse_entry_signal(v)
    return ok and key is not None


def resolve_variant(entry_signal: Any, champion_json: str | dict | None, side: str) -> tuple[IK.Variant | None, str, dict]:
    """→ (변형, 이유, 챔피언 정보). 챔피언 따름인데 챔피언이 없거나 방향이 다르면 None + 대기 이유."""
    ok, key = parse_entry_signal(entry_signal)
    if not ok or key is None:
        return None, "일목 진입 신호 아님", {}
    if key != CHAMPION:
        return IK.BY_KEY[key], f"변형 지정 {key}", {}
    try:
        ch = json.loads(champion_json) if isinstance(champion_json, str) else (champion_json or None)
    except (TypeError, ValueError):
        ch = None
    if not isinstance(ch, dict) or ch.get("variant") not in IK.BY_KEY:
        return None, "대기: 실험실 챔피언 없음 (표본 쌓는 중)", {}
    if ch.get("side") != side:
        return None, f"대기: 챔피언 방향 {ch.get('side')} ≠ 이 전략 {side}", {}
    return IK.BY_KEY[ch["variant"]], f"챔피언 {ch['variant']} {ch['side']}", {
        "champion_score": ch.get("score"), "champion_since": ch.get("since")}


def last_closed_open(now_ms: int, iv: str, settle_ms: int = 60_000) -> int:
    ms = IV_MS[iv]
    return ((now_ms - settle_ms) // ms - 1) * ms


def decide(B: IK.Bars | None, btc: IK.Bars | None, side: str, var: IK.Variant, now_ms: int,
           fresh_min: float | None = None) -> tuple[bool, str, dict]:
    """마지막 완성봉 k 에서 이 변형이 진입인가 → (진입, 이유, meta). B·btc = 완성봉만(진행 중 봉 제외)."""
    if B is None or btc is None or len(B.c) <= IK.min_bars():
        return False, "봉 부족·조회 실패", {}
    k = len(B.c) - 1
    ms = IV_MS[var.iv]
    age_min = (now_ms - (B.ts[k] + ms)) / 60_000
    fresh = FRESH_MIN[var.iv] if fresh_min is None else fresh_min
    bs = IK.sma(btc.c, IK.BTC_SMA)
    up = {t: (btc.c[i] > bs[i]) if bs[i] is not None else None for i, t in enumerate(btc.ts)}
    ok, stop, j = IK.entry_at(B, k, side, var, lambda i: up.get(B.ts[i]))
    if not ok:
        return False, f"대기: {var.key} 신호 없음 ({var.iv} {B.ts[k]})", {}
    if age_min > fresh or age_min < 0:
        return False, f"늦음: 봉 마감 {age_min:.0f}분 지남 (> {fresh:.0f}분)", {}
    risk, clamped = IK.clamp_stop(B.c[k], stop)
    meta = {"variant": var.key, "iv": var.iv, "side": side, "signal_bar_ts": B.ts[j], "entry_bar_ts": B.ts[k],
            "entry_close": B.c[k], "stop_price": stop, "stop_pct": round(risk * 100, 4), "clamped": clamped,
            "rr": var.rr, "kj_exit_missing": var.kijun_exit, "btc_up": up.get(B.ts[k])}
    return True, f"🗾 {var.key} 진입 (손절폭 {risk * 100:.2f}% · 익절 {var.rr}R)", meta


def overrides(meta: dict, leverage: Any) -> tuple[float, float] | None:
    """→ (손절 ROI %, TP1 ROI %). 손절 = 가격 손절폭을 ROI 로 역산 · TP1 = 익절R × 손절폭 × 레버."""
    from app.services.surge_peak_ladder import sl_roi_for_price_pct
    try:
        sp, lev, rr = float(meta["stop_pct"]), float(leverage), float(meta["rr"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(sp) and math.isfinite(lev) and sp > 0 and lev > 0):
        return None
    sl = sl_roi_for_price_pct(sp, lev)
    if sl is None:
        return None
    return round(min(float(sl), ROI_CAP), 2), round(min(rr * sp * lev, ROI_CAP), 2)


# ───────── 9-3 적용 결과 검토 ─────────
from app.core.strategy_status import TERMINAL_STATUSES as FINISHED   # 끝난 상태 = 운영 단일 진실


def applied_report(instances: list[dict], lab_r: dict[tuple, float]) -> dict:
    """instances = [{id, symbol, side, status, leverage, realized_pnl, stage1_capital, stages, entry_signal, meta, started_at, stopped_at}]
    lab_r = {(variant, side, symbol, entry_bar_ts): r_net} (실험실 sig 행). → {"rows": [...], "summary": {...}}"""
    rows = []
    for it in instances:
        meta = it.get("meta") or {}
        entered = bool(meta.get("entry_bar_ts")) and bool(it.get("started_at"))   # 손절·익절을 박고도 진입 실패한 건 제외
        done = entered and str(it.get("status") or "").upper() in FINISHED
        live_r = None
        try:
            risk_usdt = float(it["stage1_capital"]) * float(it["leverage"]) * float(meta["stop_pct"]) / 100.0
            if done and risk_usdt > 0:
                live_r = float(it.get("realized_pnl") or 0) / risk_usdt
        except (KeyError, TypeError, ValueError):
            live_r = None
        key = (meta.get("variant"), it.get("side"), it.get("symbol"), meta.get("entry_bar_ts"))
        lab = lab_r.get(key) if entered else None
        flags = []
        if meta.get("kj_exit_missing"):
            flags.append("기준선 청산 없음")
        if int(it.get("stages") or 1) > 1:
            flags.append("단계 추가 계획")
        if meta.get("clamped"):
            flags.append("손절 15% 상한")
        rows.append({"id": it.get("id"), "symbol": it.get("symbol"), "side": it.get("side"),
                     "entry_signal": it.get("entry_signal"), "variant": meta.get("variant"),
                     "entered": entered, "done": done, "status": it.get("status"),
                     "started_at": it.get("started_at"), "stopped_at": it.get("stopped_at"),
                     "realized_pnl": float(it.get("realized_pnl") or 0), "live_r": live_r, "lab_r": lab,
                     "diff": (live_r - lab) if (live_r is not None and lab is not None) else None, "flags": flags})
    fin = [r for r in rows if r["live_r"] is not None]
    pair = [r for r in fin if r["lab_r"] is not None]
    avg = (lambda xs: sum(xs) / len(xs) if xs else None)
    summary = {"instances": len(rows), "entered": sum(1 for r in rows if r["entered"]), "finished": len(fin),
               "live_avg_r": avg([r["live_r"] for r in fin]),
               "paired": len(pair), "lab_avg_r": avg([r["lab_r"] for r in pair]),
               "diff_avg_r": avg([r["diff"] for r in pair]),
               "pnl_sum": sum(r["realized_pnl"] for r in rows if r["done"])}
    return {"rows": rows, "summary": summary}

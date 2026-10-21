"""🎰 Fix 477 (2026-10-21 사장님 「1·2위 두 안을 그림자(기록만) 하고 전략을 만들어서 언제든지 매매를 할수 있게 만들어줘」)
— 세력 펌프·덤프 SHORT 마틴게일 가족 (일봉 신호 · 기본 그림자).

신호(마감 일봉만 · 미래 참조 없음 — [[일봉 세 그림 연구 2026-10-21]] 「세 조건 함께」):
  급등 날 t : 종가 ≥ 전날 종가 +30% · 그날 거래대금 ≥ 직전 20일 중앙값 ×10 · 그날 고가 ≥ 60일 최저 ×2 (+100% 랠리 안)
  다음 날 n : 음봉(종가 < 급등 날 종가) → n 마감 직후 1단계 SHORT (가격 ≈ n 종가)
두 안 (사장님 1·2위, 백테스트 4년 레버 1 · 10일):
  A 「4단계」 10 → +15% 300 → +15% 600 → +15% 2000 (1단계가 대비 +15/+32.25/+52.09%) · 손절 = 다 들어간 뒤 총 증거금 −30%  (+19,689)
  B 「3단계」 100 → +20% 300 → +20% 1000 (+20/+44%) · 손절 = 다 들어간 뒤 총 증거금 −40%  (+11,447)
  익절 = min(급등분 절반 반납 가격, 평단 × 0.995) · 최대 보유 10일 뒤 정리 · 레버 1(사장님 [[feedback-leverage-safety]])
그림자 = 신호를 Redis 에 기록(pds:shadow:<날짜>:<심볼>) → 사후 채점 스크립트(scripts/entry_condition_study/pds_shadow_verdict.py)가 일봉으로 두 안을 같은 규칙으로 채점.
실주문 = pds_mode=on 일 때만 (Fix 477 실주문 경로 — pump_dump_short_live 참조). 숫자는 사장님 말씀 그대로, 신호 문턱은 연구 값(「Claude가 정함」).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Callable

FIX = "Fix477"
PREFIX = "PDS"
STYPE = "pump_dump_short"
SHADOW_KEY = "pds:shadow:{day}:{sym}"
SHADOW_TTL = 120 * 86400
MM = 0.01                                   # 유지 증거금률 가정(청산가 표시용)


@dataclass(frozen=True)
class Plan:
    key: str
    label: str
    margins: tuple[float, ...]              # 단계별 증거금 USDT
    gap_pct: float                          # 직전 단계가 대비 +% (이어서)
    loss_frac: float                        # 다 들어간 뒤 총 증거금 대비 손절 비율

    def mults(self) -> tuple[float, ...]:
        g = 1 + self.gap_pct / 100
        return tuple(g ** i for i in range(len(self.margins)))

    def numbers(self, scale: float = 1.0) -> dict:
        """1단계가 = 1 기준 — 단계 가격·평단·손절 가격·청산가·마지막 단계 진입 때 손실."""
        m = [x * scale for x in self.margins]
        mu = self.mults()
        qty = sum(a / b for a, b in zip(m, mu))
        tot = sum(m)
        avg = tot / qty
        stop = avg + self.loss_frac * tot / qty
        liq = avg + (tot - avg * qty * MM) / qty
        loss_last = sum(a / b * (mu[-1] - b) for a, b in zip(m[:-1], mu[:-1]))
        return {"margins": m, "mults": mu, "total": tot, "avg": avg, "stop": stop, "liq": liq, "loss_last": loss_last,
                "stop_loss_usdt": self.loss_frac * tot}


PLANS: dict[str, Plan] = {
    "a": Plan("a", "A 4단계 10/300/600/2000 · +15%씩 · 손절 −30%", (10.0, 300.0, 600.0, 2000.0), 15.0, 0.30),
    "b": Plan("b", "B 3단계 100/300/1000 · +20%씩 · 손절 −40%", (100.0, 300.0, 1000.0), 20.0, 0.40),
}

SETTINGS: dict[str, tuple[str, str, str]] = {
    "pds_mode": ("shadow", "off | shadow(신호 기록 + 사후 채점) | on(실주문 — 아래 pds_plan 한 안 · 실주문 경로 배포 전에는 on 이어도 기록·후보 로그만)", "Claude가 정함 — 실자금은 사장님이 켠다"),
    "pds_plan": ("a", "실주문에 쓸 안 (a = 4단계 10/300/600/2000 · b = 3단계 100/300/1000) — 그림자는 두 안 모두 채점", "사장님 1·2위"),
    "pds_scale": ("1", "단계 증거금 배수 (1 = 사장님 숫자 그대로 · 0.5 = 절반)", "Claude가 정함"),
    "pds_leverage": ("1", "레버리지 (1 권장 — 2 이상이면 1단계만 있을 때 청산이 2·3단계 지점보다 가까워질 수 있음)", "사장님 「숏은 1배속」"),
    "pds_max_concurrent": ("3", "동시 보유 상한(실주문)", "Claude가 정함 — 백테스트 동시 3 에도 결과 유지"),
    "pds_hold_days": ("10", "최대 보유 일수 뒤 정리", "연구 10일"),
    "pds_whale_only": ("0", "1 = 🐋 소형·큰손(시총<2억$·유통<60%)만", "Claude가 정함 — 기본 전체"),
    "pds_surge_pct": ("30", "급등 날 종가 ≥ 전날 +이 %", "사장님 「일 +30%」"),
    "pds_vol_mult": ("10", "급등 날 거래대금 ≥ 직전 20일 중앙값 × 이 값", "사장님 「거래대금 10배」"),
    "pds_rally_pct": ("100", "급등 날 고가 ≥ 60일 최저 × (1 + 이 %/100)", "사장님 「랠리 +100%」"),
}
_BOUNDS = {"pds_scale": (0.01, 10.0), "pds_leverage": (1.0, 5.0), "pds_max_concurrent": (0.0, 20.0), "pds_hold_days": (1.0, 60.0),
           "pds_surge_pct": (5.0, 500.0), "pds_vol_mult": (1.0, 1000.0), "pds_rally_pct": (10.0, 2000.0)}


def _f(get: Callable[[str], Any], key: str) -> float:
    d = float(SETTINGS[key][0])
    try:
        x = float(str(get(key)).strip())
    except Exception:  # noqa: BLE001
        return d
    lo, hi = _BOUNDS[key]
    return x if math.isfinite(x) and lo <= x <= hi else d


def params_from(get: Callable[[str], Any] | None = None) -> dict:
    g = get or (lambda k: SETTINGS[k][0])

    def s(k):
        try:
            return str(g(k)).strip().lower()
        except Exception:  # noqa: BLE001
            return SETTINGS[k][0]
    mode = s("pds_mode")
    plan = s("pds_plan")
    return {"mode": mode if mode in ("off", "shadow", "on") else "shadow", "plan": plan if plan in PLANS else "a",
            "scale": _f(g, "pds_scale"), "lev": int(_f(g, "pds_leverage")), "max_concurrent": int(_f(g, "pds_max_concurrent")),
            "hold_days": int(_f(g, "pds_hold_days")), "whale_only": s("pds_whale_only") in ("1", "true", "on", "yes"),
            "surge": _f(g, "pds_surge_pct") / 100, "vol": _f(g, "pds_vol_mult"), "rally": _f(g, "pds_rally_pct") / 100}


def detect(kl: list, p: dict | None = None) -> dict | None:
    """kl = **마감 일봉만** [[open_ms, o, h, l, c, v, close_ms, qv, ...], ...] — 마지막 봉 = 음봉 확인 날(n), 그 앞 = 급등 날(t).
    신호면 dict, 아니면 None. 예외 없음."""
    p = p or params_from()
    try:
        if len(kl) < 62:
            return None
        h = [float(k[2]) for k in kl[-62:]]
        lw = [float(k[3]) for k in kl[-62:]]
        c = [float(k[4]) for k in kl[-62:]]
        qv = [float(k[7]) for k in kl[-62:]]
    except (TypeError, ValueError, IndexError):
        return None
    if any(not math.isfinite(x) or x <= 0 for x in (*c, *lw, *h)) or any(not math.isfinite(x) or x < 0 for x in qv):
        return None
    n, t = len(c) - 1, len(c) - 2
    if not (c[t] / c[t - 1] - 1 >= p["surge"]):
        return None
    w = sorted(qv[t - 20:t])
    med = w[len(w) // 2]
    if not (med > 0 and qv[t] / med >= p["vol"]):
        return None
    lo60 = min(lw[max(0, t - 60):t + 1])
    if not (h[t] / lo60 - 1 >= p["rally"]):
        return None
    if not c[n] < c[t]:
        return None
    return {"surge_day": int(kl[-2][0]), "entry_day": int(kl[-1][0]), "entry_ref": c[n], "surge_close": c[t], "prev_close": c[t - 1],
            "half": c[t - 1] + 0.5 * (c[t] - c[t - 1]), "surge_pct": round((c[t] / c[t - 1] - 1) * 100, 1),
            "vol_mult": round(qv[t] / med, 1), "rally_pct": round((h[t] / lo60 - 1) * 100, 1)}


def record_shadow(redis, sym: str, sig: dict, extra: dict | None = None) -> bool:
    """그림자 기록 — 같은 날·심볼 한 번만(SET NX). True = 새로 기록."""
    from datetime import datetime, timezone
    day = datetime.fromtimestamp(sig["entry_day"] / 1000, timezone.utc).date().isoformat()
    payload = {"fix": FIX, "symbol": sym, "day": day, **sig, **(extra or {}),
               "plans": {k: {"label": v.label, **{kk: vv for kk, vv in v.numbers().items() if kk != "margins"}} for k, v in PLANS.items()}}
    return bool(redis.set(SHADOW_KEY.format(day=day, sym=sym), json.dumps(payload, ensure_ascii=False, default=float), nx=True, ex=SHADOW_TTL))


def simulate(h: list, lw: list, c: list, n: int, half: float, plan: Plan, hold: int = 10, lev: int = 1, fee: float = 0.0005,
             scale: float = 1.0) -> dict | None:
    """사후 채점(백테스트와 같은 규칙) — 1단계가 = c[n] · n+1 봉부터. 일봉 안 순서 모름 → 추가 뒤 손절·청산 먼저(보수적)."""
    nums = plan.numbers(scale)
    p0 = c[n]
    legs = [(p0, nums["margins"][0])]
    trig = [(p0 * x, m) for m, x in zip(nums["margins"][1:], nums["mults"][1:])]
    stop = p0 * nums["stop"]
    exit_px = why = None
    j_end = None
    for j in range(n + 1, min(len(c), n + 1 + hold)):
        while trig and h[j] >= trig[0][0]:
            legs.append(trig.pop(0))
        qty = sum(m * lev / px for px, m in legs)
        avg = sum(m * lev for _px, m in legs) / qty
        margin = sum(m for _px, m in legs)
        liq = avg + (margin - avg * qty * MM) / qty
        if not trig and stop < liq and h[j] >= stop:
            exit_px, why, j_end = stop, "손절", j
            break
        if h[j] >= liq:
            exit_px, why, j_end = liq, "청산", j
            break
        tp = min(half, avg * 0.995)
        if lw[j] <= tp:
            exit_px, why, j_end = tp, "익절", j
            break
    if exit_px is None:
        if n + hold > len(c) - 1:
            return None
        j_end = n + hold
        exit_px, why = c[j_end], "시간"
    pnl = fe = 0.0
    for px, m in legs:
        q = m * lev / px
        pnl += q * (px - exit_px)
        fe += (m * lev + q * exit_px) * fee
    return {"pnl": pnl - fe, "stages": len(legs), "why": why, "days": j_end - n}


def settings_get(db) -> Callable[[str], Any]:
    """system_settings 읽기(없으면 코드 기본값). 실패 = 기본값."""
    from app.models.system_setting import SystemSetting

    def g(key: str):
        try:
            row = db.get(SystemSetting, key)
            return row.value if row is not None and row.value is not None else SETTINGS[key][0]
        except Exception:  # noqa: BLE001
            return SETTINGS[key][0]
    return g


def make_daily_hook(redis, p: dict, stat: dict) -> Callable[[str, list, dict], None]:
    """pump_profile 일봉 갱신(KST 09:15)에 붙는 훅 — 같은 일봉으로 신호 판정 → 그림자 기록. 실주문 진입 후보는 stat["candidates"]."""
    stat.setdefault("signals", 0)
    stat.setdefault("recorded", 0)
    stat.setdefault("candidates", [])

    def hook(sym: str, kl: list, mi: dict) -> None:
        if p["mode"] == "off":
            return
        sig = detect(kl, p)
        if not sig:
            return
        mc, fl = (mi or {}).get("mcap"), (mi or {}).get("float")
        whale = bool(mc and fl and mc < 2e8 and fl < 0.6)
        stat["signals"] += 1
        new = record_shadow(redis, sym, sig, {"whale": whale, "mcap": mc, "float": fl, "mode": p["mode"]})
        if new:
            stat["recorded"] += 1
        # 실주문 후보 = 이 신호를 **처음** 본 때만(재시작 2분 뒤 재실행·같은 날 두 번째 실행이 다시 들어가지 않게)
        if new and p["mode"] == "on" and (whale or not p["whale_only"]):
            stat["candidates"].append({"symbol": sym, "whale": whale, **sig})
    return hook

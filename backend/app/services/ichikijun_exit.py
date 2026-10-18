"""🗾 Fix 467 (2026-10-18 사장님 「다음으로 진행해줘」 — 기획서 10절) — 일목 예약 인스턴스의 실주문 「기준선 재이탈 청산」 판정 (순수 함수).

출처 2차 손절 (verbatim 요지): 매수 진입 후 캔들 종가가 일목균형표 기준선을 다시 하향 이탈하면 즉시 시장가 청산 (매도는 상향 돌파 시).
실험실 `ichimoku_kijun.simulate` 의 KJ 청산과 같은 정의 — LONG 종가 < 기준선 · SHORT 종가 > 기준선 (같음 = 이탈 아님).
모드 `ichikijun_kijun_exit_mode` 기본 shadow (Claude가 정함 — 실주문 청산이라 켜기는 사장님).
"""
from __future__ import annotations

from typing import Any

from app.services import ichimoku_kijun as IK

MODE_KEY = "ichikijun_kijun_exit_mode"
MODE_DEFAULT = "shadow"


def mode_of(raw: Any) -> str:
    v = str(raw or "").strip().lower()
    return v if v in ("off", "shadow", "on") else MODE_DEFAULT


def is_target(entry_signal: Any, meta: Any) -> IK.Variant | None:
    """일목 예약이고 진입 근거 변형이 기준선 청산 변형(_r2kj)이면 그 변형."""
    if not isinstance(entry_signal, str) or not entry_signal.startswith("ichikijun"):
        return None
    if not isinstance(meta, dict):
        return None
    v = IK.BY_KEY.get(meta.get("variant"))
    if v is None or not v.kijun_exit or meta.get("entry_bar_ts") is None:
        return None
    return v


def kijun_break(B: IK.Bars, entry_bar_ts: int, last_judged_ts: int | None, side: str) -> tuple[bool, dict]:
    """진입 봉 **뒤**이면서 아직 판정 안 한(last_judged_ts 초과) 완성봉 중 첫 기준선 이탈 → (이탈, 그 봉 정보)."""
    up = side == "LONG"
    kj = B.ind["kj"]
    start = max(int(entry_bar_ts), int(last_judged_ts or 0))
    for k, t in enumerate(B.ts):
        if t <= start or kj[k] is None:
            continue
        if (B.c[k] < kj[k]) if up else (B.c[k] > kj[k]):
            return True, {"bar_ts": t, "close": B.c[k], "kijun": kj[k]}
    return False, {}

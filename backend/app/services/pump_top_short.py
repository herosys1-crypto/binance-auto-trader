"""🔺 Fix 438 (2026-10-11 사장님 「진행해줘」) — 「급등 정점 SHORT」: 24시간 크게 오른 종목에서 SHORT 규칙이 켜질 때.

근거 [[SHORT 수익 자리 2026-10-11]] (가상 30일, 봉당 1건, 80칸 중 통과):
  SHORT 규칙 + 24h ≥ +30%           : 1,419건 · live +1.76% · 같은 날 무작위 SHORT 대비 +4.13 · 앞 +2.46 / 뒤 +0.79 · 하루 1건 28일 +21.4 USDT(10U)
  SHORT 규칙 + 24h ≥ +10% · 시장폭 0.4~0.6 : 910+402건 · +2.48~+2.92% · 하루 3건 28일 +27.5 USDT · 이긴 날 22/28
  (시장이 빠진 날의 SHORT 는 −2.96 → 쓰지 않는다. LONG 합의(Fix 437)와 장세가 반대라 보완)
🚨 헌법 64 「급등 반대매매 금지」 · 8/21 급등 SHORT −849 사고: 맹목 SHORT 가 아니라 **정점 반전 SHORT 규칙이 이미 켜진 자리만**,
   실주문은 사장님이 켤 때만(기본 shadow) · 손절 −25 고정. 80칸을 시험해 찾은 것이라 2주 그림자 전진 확인이 먼저다.

동작: 가상매매 워커가 규칙 평가 직후 `apply()` → fired["pumptop_short_30"] · fired["pumptop_short_mid"] → 가상 행 → 규칙 가족(기본 shadow).
설정(「Claude가 정함」 — 측정 경계): pumptop_enabled 1 · pumptop_chg_hi 30 · pumptop_chg_lo 10 · pumptop_breadth_lo 0.4 · pumptop_breadth_hi 0.6.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Mapping

FIX = "Fix438"
KEY_30 = "pumptop_short_30"
KEY_MID = "pumptop_short_mid"
META_KEYS = frozenset({KEY_30, KEY_MID, "consensus_long"})     # 규칙 수를 셀 때 빼는 「규칙의 규칙」
SIDE = "SHORT"

SETTINGS: dict[str, tuple[str, str, str]] = {
    "pumptop_enabled": ("1", "급등 정점 SHORT 가상 판정 (1 켬 · 0 끔)", "Claude가 정함"),
    "pumptop_chg_hi": ("30", "24h 등락 % 이상 → pumptop_short_30", "Claude가 정함 — 가상 30일 실측 +30% 이상 칸"),
    "pumptop_chg_lo": ("10", "24h 등락 % 이상 + 시장폭 중간 → pumptop_short_mid", "Claude가 정함 — 실측 +10% 이상 칸 (Fix 328 과 같은 경계)"),
    "pumptop_breadth_lo": ("0.4", "시장폭 중간 하한 (이상)", "Claude가 정함 — 운영팀 성적표 구간과 같음"),
    "pumptop_breadth_hi": ("0.6", "시장폭 중간 상한 (이하)", "Claude가 정함 — 운영팀 성적표 구간과 같음"),
}
DEFAULTS = {"enabled": True, "chg_hi": 30.0, "chg_lo": 10.0, "b_lo": 0.4, "b_hi": 0.6}


def _num(raw: Any) -> float | None:
    if isinstance(raw, bool):                              # Gemini: True/False 를 1/0 측정값으로 읽지 않는다
        return None
    try:
        x = float(raw) if isinstance(raw, (int, float)) else float(str(raw).strip())
    except (TypeError, ValueError, OverflowError):
        return None
    return x if math.isfinite(x) else None


def params_from(get: Callable[[str], Any] | None = None) -> dict:
    g = get or (lambda k: SETTINGS[k][0])

    def v(k):
        try:
            return g(k)
        except Exception:  # noqa: BLE001
            return SETTINGS[k][0]
    p = dict(DEFAULTS)
    p["enabled"] = str(v("pumptop_enabled") or "1").strip() != "0"
    hi, lo = _num(v("pumptop_chg_hi")), _num(v("pumptop_chg_lo"))
    if hi is not None and 5 <= hi <= 200:
        p["chg_hi"] = hi
    if lo is not None and 3 <= lo <= 200:
        p["chg_lo"] = lo
    blo, bhi = _num(v("pumptop_breadth_lo")), _num(v("pumptop_breadth_hi"))
    if blo is not None and bhi is not None and 0.0 <= blo < bhi <= 1.0:
        p["b_lo"], p["b_hi"] = blo, bhi
    return p


PAPER_PARAMS: dict = params_from()


def set_paper_params(settings_get) -> None:
    global PAPER_PARAMS
    try:
        PAPER_PARAMS = params_from(settings_get)
    except Exception as e:  # noqa: BLE001 — 직전 값 유지, 원인은 남긴다 (Gemini)
        import logging
        logging.getLogger(__name__).warning("[Fix438] 설정 읽기 실패 → 직전 값 유지: %s", e)


def short_rule_count(fired: Mapping[str, bool], rule_side: Mapping[str, str]) -> int:
    """이 봉에 켜진 SHORT 규칙 수 (기준선·규칙의 규칙 제외)."""
    return sum(1 for k, hit in fired.items()
               if hit and k not in META_KEYS and not k.startswith("baseline_") and rule_side.get(k) == SIDE)


def judge(fired: Mapping[str, bool], rule_side: Mapping[str, str], chg_24h: Any, breadth: Any,
          p: dict | None = None) -> tuple[bool, bool, int]:
    """(pumptop_short_30, pumptop_short_mid, SHORT 규칙 수). 24h 등락을 모르면 둘 다 False. mid 는 시장폭도 알아야."""
    p = p or PAPER_PARAMS
    n = short_rule_count(fired, rule_side)
    c = _num(chg_24h)
    if not p.get("enabled", True) or n < 1 or c is None:
        return False, False, n
    hit30 = c >= p["chg_hi"]
    b = _num(breadth)
    hit_mid = c >= p["chg_lo"] and b is not None and p["b_lo"] <= b <= p["b_hi"]
    return hit30, hit_mid, n


def apply(fired: dict, rule_side: Mapping[str, str], chg_24h: Any, breadth: Any, p: dict | None = None) -> int:
    """가상매매 워커용 — 두 키를 세우고 SHORT 규칙 수를 돌려준다(스냅샷 기록용)."""
    h30, hmid, n = judge(fired, rule_side, chg_24h, breadth, p)
    fired[KEY_30] = h30
    fired[KEY_MID] = hmid
    return n


def _never(ctx: Any) -> bool:
    """규칙 목록 등록용 — 실제 판정은 워커가 apply() 로 한다."""
    return False


PAPER_RULES: tuple[tuple[str, str, str, Any], ...] = (
    (KEY_30, SIDE, "급등 정점 SHORT: SHORT 규칙 + 24h ≥ +30% (Fix 438, shadow)", _never),
    (KEY_MID, SIDE, "급등 정점 SHORT: SHORT 규칙 + 24h ≥ +10% · 시장폭 0.4~0.6 (Fix 438, shadow)", _never),
)

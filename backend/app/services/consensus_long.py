"""🤝 Fix 437 (2026-10-11 사장님 「진행해줘」) — 「합의 LONG」: 같은 15분봉에 LONG 규칙이 여럿 동시에 켜지고 시장폭이 낮을 때.

사장님 10/10: "지금부터 진행할 부분만 분석하고 자동매매를 통해서 큰 수익을 만들수 있게해줘"
근거 [[큰 수익 후보 — 합의 LONG 2026-10-10]] (가상 30일, 같은 종목·봉은 한 건):
  LONG 규칙 4개+ & 시장폭 < 0.4 : 봉 47/일 · roi +3.68% · 승률 65% · 같은 날 무작위 대비 +2.99 · 앞 15일 +6.48 / 뒤 +1.98
  LONG 4개+ & 시장폭 중간       : −0.55 (쓰지 않는다) · SHORT 합의는 겹칠수록 손실(−2.03) → LONG 만
  하루 진입을 제한하면 건당 약 +0.9% (평균은 시장 전체 반등 날에 몰림) → 그림자로 2주 전진 확인 뒤 실주문·자본은 사장님.

동작: 가상매매 워커가 규칙 평가 직후 `apply()` 로 fired["consensus_long"] 을 세운다 → 가상 행(rule = consensus_long)이 열리고
     규칙 가족 rf_consensus_long(기본 shadow)이 그 행을 받는다. 판정 재료는 이미 계산된 fired · 시장폭뿐 — 봉을 더 받지 않는다.
설정(「Claude가 정함」 — 측정값): consensus_min_rules 4 · consensus_breadth_max 0.4 · consensus_enabled 1.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Mapping

FIX = "Fix437"
RULE_KEY = "consensus_long"
SIDE = "LONG"

SETTINGS: dict[str, tuple[str, str, str]] = {
    "consensus_enabled": ("1", "합의 LONG 가상 판정 (1 켬 · 0 끔)", "Claude가 정함"),
    "consensus_min_rules": ("4", "같은 봉에 동시에 켜진 LONG 규칙 수 하한", "Claude가 정함 — 가상 30일 실측 4+ 부터 무작위 대비 +1.3"),
    "consensus_breadth_max": ("0.4", "시장폭(상승 종목 비율) 이 값 미만일 때만", "Claude가 정함 — 운영팀 성적표 「낮음」 구간과 같은 0.4"),
}
DEFAULTS = {"enabled": True, "min_rules": 4, "breadth_max": 0.4}


def _num(raw: Any) -> float | None:
    try:
        x = float(raw) if isinstance(raw, (int, float)) else float(str(raw).strip())
    except (TypeError, ValueError, OverflowError):        # 교차 감사: 아주 큰 정수 → OverflowError 도 「모름」
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
    p["enabled"] = str(v("consensus_enabled") or "1").strip() != "0"
    n = _num(v("consensus_min_rules"))
    if n is not None and n == int(n) and 2 <= n <= 20:
        p["min_rules"] = int(n)
    b = _num(v("consensus_breadth_max"))
    if b is not None and 0.05 <= b <= 0.95:
        p["breadth_max"] = b
    return p


PAPER_PARAMS: dict = params_from()


def set_paper_params(settings_get) -> None:
    global PAPER_PARAMS
    try:
        PAPER_PARAMS = params_from(settings_get)
    except Exception:  # noqa: BLE001
        pass


def long_rule_count(fired: Mapping[str, bool], rule_side: Mapping[str, str]) -> int:
    """이 봉에 켜진 LONG 규칙 수 (기준선·합의 자신 제외)."""
    return sum(1 for k, hit in fired.items()
               if hit and k != RULE_KEY and not k.startswith("baseline_") and rule_side.get(k) == SIDE)


def qualifies(fired: Mapping[str, bool], rule_side: Mapping[str, str], breadth: Any, p: dict | None = None) -> tuple[bool, int]:
    """(합의 LONG 인가, LONG 규칙 수). 시장폭을 모르면 판정하지 않는다(False) — 낮음일 때만 쓰는 규칙이라."""
    p = p or PAPER_PARAMS
    n = long_rule_count(fired, rule_side)
    if not p.get("enabled", True):
        return False, n
    b = _num(breadth)
    if b is None or not 0.0 <= b <= 1.0:
        return False, n
    return (n >= p["min_rules"] and b < p["breadth_max"]), n


def apply(fired: dict, rule_side: Mapping[str, str], breadth: Any, p: dict | None = None) -> int:
    """가상매매 워커용 — fired[consensus_long] 을 세우고 LONG 규칙 수를 돌려준다(스냅샷 기록용)."""
    ok, n = qualifies(fired, rule_side, breadth, p)
    fired[RULE_KEY] = ok
    return n


def _never(ctx: Any) -> bool:
    """규칙 목록 등록용 — 실제 판정은 워커가 apply() 로 한다(다른 규칙 결과가 있어야 판정 가능)."""
    return False


PAPER_RULES: tuple[tuple[str, str, str, Any], ...] = (
    (RULE_KEY, SIDE, "합의 LONG: 같은 봉 LONG 규칙 4개+ · 시장폭 < 0.4 (Fix 437, shadow)", _never),
)

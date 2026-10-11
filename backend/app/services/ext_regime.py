"""🧭 Fix 440 (2026-10-11 사장님 「1」) — 외부 전략(EMA 추세 눌림=아담쿠식 · 후지모토 · 마하세븐 · 볼린저 3종 · 3중 이평)에도 장세 필터.

Fix 439 의 「두 줄 법칙」을 외부 전략 워커에 그대로: LONG = 시장폭 < 0.4 · SHORT = 그 종목 24h ≥ +10%.
- 판정 숫자는 규칙 가족과 같은 설정(rf_long_breadth_max · rf_short_chg24_min)을 rule_families.regime_check 로 쓴다 (한 곳에서만 정한다).
- 시장폭 = 가상매매 워커가 15분마다 쓰는 system_settings.market_breadth_last {"at","breadth"} — 60분 넘게 오래되면 「모름」.
- 24h 등락 = 판정 봉 배열에서 하루 전 종가 대비 (일봉은 직전 일봉 대비) — 봉을 더 받지 않는다.
- 모드 ext_regime_filter: on(실주문 신규 진입만 막음) | shadow(기록만) | off. **그림자 기록은 막지 않고 판정을 같이 남긴다** — 10/23~25 판정에서
  필터 안/밖 성적을 나란히 보려고. 후지모토 2·3차 추가(이미 들어간 포지션)는 거르지 않는다.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any

FIX = "Fix440"
BREADTH_KEY = "market_breadth_last"
MAX_AGE = timedelta(minutes=60)          # Claude가 정함 — 15분 주기 4회분 (Fix 382 피라미딩 국면 게이트와 같은 값)
SETTINGS: dict[str, tuple[str, str, str]] = {
    "ext_regime_filter": ("on", "off | shadow(판정만 기록) | on(장세가 아니면 실주문 신규 진입 안 함) — 외부 전략",
                          "Claude가 정함 — Fix 439 두 줄 법칙과 같은 잣대 (그림자 기록은 막지 않고 판정을 남긴다)"),
}


def mode_of(get) -> str:
    try:
        m = str(get("ext_regime_filter") or "on").strip().lower()
    except Exception:  # noqa: BLE001
        return "on"
    return m if m in ("off", "shadow", "on") else "on"


def breadth_now(raw: Any, *, now: datetime | None = None) -> float | None:
    """system_settings 값(JSON 문자열) → 시장폭. 없음·형식 이상·60분 넘음 = None."""
    now = now or datetime.now(timezone.utc)
    try:
        d = json.loads(raw) if isinstance(raw, str) else raw
        b = d.get("breadth")
        at = datetime.fromisoformat(str(d.get("at")))
        at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        return None
    if isinstance(b, bool) or now - at > MAX_AGE or at - now > timedelta(minutes=5):   # 교차 감사: 미래 시각 = 시계 이상 → 모름
        return None
    try:
        b = float(b)
    except (TypeError, ValueError):
        return None
    return b if math.isfinite(b) and 0.0 <= b <= 1.0 else None


def chg24_from_bars(bars: list, interval_ms: int | None) -> float | None:
    """마지막 완성봉 종가 vs 하루 전 종가 (%). 봉이 모자라거나 값이 이상하면 None."""
    if not bars or not interval_ms or interval_ms <= 0:
        return None
    n = max(1, int(round(86_400_000 / interval_ms)))
    if len(bars) <= n:
        return None
    try:
        now_c, prev_c = float(bars[-1][4]), float(bars[-1 - n][4])
    except (TypeError, ValueError, IndexError):
        return None
    if not (math.isfinite(now_c) and math.isfinite(prev_c)) or prev_c <= 0:
        return None
    return (now_c / prev_c - 1.0) * 100.0


def judge(db: Any, side: str, breadth: float | None, chg24: float | None, mode: str) -> dict[str, Any]:
    """규칙 가족과 같은 regime_check 로 판정 + 모드. {"ok", "why", ..., "mode", "blocks"(on 이고 안 맞으면 True)}."""
    from app.services import rule_families as RF
    res = RF.regime_check(db, side, {"market_breadth": breadth}, chg24)
    res["mode"] = mode
    res["blocks"] = mode == "on" and not res["ok"]
    return res

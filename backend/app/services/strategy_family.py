"""🔀 Fix 369 (2026-09-13 사장님) — 전략 가족 판정 **단일 권한**.

사장님: "새 전략기존방식 과 새전략 obv 자동 둘을 완전 다르게 둘로 분리해서 개발을해줘 두개가 계속 겹치는것 같아"

감사(9/13, 워커·자본·화면 3렌즈)가 잡은 것: 두 가족을 가르는 기준이 코드에 없었다 — OBV 자동은 템플릿 trigger_mode 를
4곳에서 따로 비교하고, 기존 방식은 entry_profile 을 1곳에서만 봤다. 그래서 SHORT 반전 워커(Fix 41 peak_break · Fix 29 resistance)가
두 가족을 가리지 않고 단계 진입을 시도했고(#4496 LSKUSDT), 수익 추가 피라미딩이 손절 없는 기존 방식에 300×2 를 얹을 수 있었다.

판정 순서 (먼저 걸리는 것):
  split          capital_management_mode == split_entry (볼밴 분할)
  single         single_entry_guard (bb_mid_line · 급등 사다리 · 후지모토 · 마하세븐 · 규칙 가족 = 1회 진입)
  obv_auto       entry_profile == 'obv_auto' 또는 템플릿 trigger_mode == OBV_REVERSE (「새 전략 (OBV 자동)」 · 관리 재진입 복제)
  legacy_manual  entry_profile == 'legacy_manual' (「➕ 새 전략 (기존 방식)」, Fix 367 이후 생성)
  ladder         capital_management_mode == stage_ladder (v219 사다리)
  other          그 밖 (자동 워커 전략 · Fix 367 이전 수동 가격 전략 — 옛 동작 그대로)
판정 실패 = 'unknown' — 주문을 내는 워커는 fail-closed(제외)로 다룬다.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)

SPLIT = "split"
SINGLE = "single"
OBV_AUTO = "obv_auto"
LEGACY_MANUAL = "legacy_manual"
LADDER = "ladder"
OTHER = "other"
UNKNOWN = "unknown"
MANUAL_FAMILIES = frozenset({OBV_AUTO, LEGACY_MANUAL})
FAMILIES = (SPLIT, SINGLE, OBV_AUTO, LEGACY_MANUAL, LADDER, OTHER)


def _template_of(si: Any):
    tpl = getattr(si, "strategy_template", None)
    return tpl if tpl is not None else getattr(si, "template", None)


def family_of(si: Any) -> str:
    """인스턴스 한 건의 가족. 실패 = UNKNOWN."""
    try:
        from app.core.risk_constants import LEGACY_MANUAL_PROFILE, OBV_AUTO_PROFILE
        from app.core.strategy_status import SPLIT_ENTRY_MODE
        from app.services.single_entry_guard import is_single_entry
        mode = str(getattr(si, "capital_management_mode", "") or "").lower()
        if mode == str(SPLIT_ENTRY_MODE).lower():
            return SPLIT
        if is_single_entry(si):
            return SINGLE
        profile = str(getattr(si, "entry_profile", None) or "")
        tpl = _template_of(si)
        trig = str(getattr(tpl, "trigger_mode", "") or "").upper() if tpl is not None else ""
        if profile == OBV_AUTO_PROFILE or trig == "OBV_REVERSE":
            return OBV_AUTO
        if profile == LEGACY_MANUAL_PROFILE:
            return LEGACY_MANUAL
        if mode == "stage_ladder":
            return LADDER
        return OTHER
    except Exception as e:  # noqa: BLE001
        logger.warning("[Fix369] #%s 가족 판정 실패 → unknown: %s", getattr(si, "id", "?"), e)
        return UNKNOWN


def drop_families(rows: Iterable[Any], families: Iterable[str], *, tag: str = "") -> list:
    """후보에서 주어진 가족을 뺀다. 판정 실패(UNKNOWN)도 뺀다 — 주문을 내는 워커용 fail-closed."""
    fams = frozenset(families)
    kept: list = []
    dropped: dict[str, int] = {}
    for r in list(rows or []):
        f = family_of(r)
        if f in fams or f == UNKNOWN:
            dropped[f] = dropped.get(f, 0) + 1
        else:
            kept.append(r)
    if dropped:
        logger.debug("[Fix369]%s 가족 제외 %s", f" {tag}" if tag else "", dropped)
    return kept

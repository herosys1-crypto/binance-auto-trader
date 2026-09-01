"""🛡️ 「1회 진입 전략」에 남의 로직을 얹지 않는다 (Fix 283).

## 왜 필요한가 — 같은 사고가 **세 번** 반복됐다

    Fix 213  success_pyramiding_worker 가 볼밴 포지션에 300 USDT 를 얹어
             평단이 밀리고 손절선이 진입가보다 위로 올라갔다. 4건 **-252.18 USDT**.
    Fix 214  peak_break_reversal / resistance_reversal 이 같은 짓을 했다.
             → 그때마다 `capital_management_mode != SPLIT_ENTRY_MODE` 를 각 워커에
               **따로** 붙였다.
    Fix 282  새 전략(bb_mid_line)을 만들자 피라미딩이 또 집어갔다.
             볼밴만 예외였고 「1회 진입 전략」이라는 개념이 코드에 없었기 때문이다.

세 번째부터는 **한 곳**에 둔다. 새 전략이 생길 때 여기 한 줄만 추가하면 된다.

## 무엇을 막는가

이 전략들은 **자기 진입 계획과 자기 손절**을 갖는다:

    bb_mid_line       1회 진입 / TP +5% ROI / SL -10% ROI  (그 가정 위에서 성과를 측정했다)
    surge_peak_ladder 1회 진입 + **자기 추가 로직**(가격 2.5% 유리 시 50%, 최대 2회)

여기에 남의 워커가 단계를 얹거나 손절선을 덮어쓰면 **측정한 규칙과 다른 매매**가 된다.
실제로 peak_break_reversal / resistance_reversal 은 `force_sl_roi_override = 5` 를
**무조건** 덮어써서 ROI -10% 손절을 절반으로 줄이고, 존재하지도 않는 2단계를
1단계 plan 을 재사용해 시장가로 넣는다 (물량 2배 + 평단 이동).

## 원칙

- 판정 실패는 **제외로 간주**한다 (fail-closed). 자본을 늘리거나 손절을 바꾸는
  판정이므로, 모르면 손대지 않는 쪽이 안전하다.
- `strategy_type` 과 템플릿 **이름 접두사**를 둘 다 본다.
  strategy_type 에 접미사가 붙는 전략이 있다 (`auto_bb_break{suffix}`).
- ⚠️ 여기 등록되지 **않은** 전략의 동작은 하나도 바뀌지 않는다.
  사장님 「이익일때 추가 300씩」은 그대로다.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable

logger = logging.getLogger(__name__)

__all__ = [
    "SINGLE_ENTRY_STRATEGY_TYPES", "SINGLE_ENTRY_TEMPLATE_PREFIXES",
    "is_single_entry", "drop_single_entry",
]

# 새 「1회 진입」 전략이 생기면 **여기만** 추가한다.
SINGLE_ENTRY_STRATEGY_TYPES: frozenset[str] = frozenset({
    "bb_mid_line",        # Fix 278 볼밴 중단선 4종
    "surge_peak_ladder",  # Fix 267 급등 정점 사다리 (자기 추가 로직 보유)
})
SINGLE_ENTRY_TEMPLATE_PREFIXES: tuple[str, ...] = ("BB_MIDLINE", "SURGE_LADDER")


def _template_of(si: Any):
    tpl = getattr(si, "strategy_template", None)
    if tpl is None:
        tpl = getattr(si, "template", None)      # 혹시 모를 별칭 대비
    return tpl


def is_single_entry(si: Any) -> bool:
    """이 전략은 「1회 진입 전략」인가 = 남의 워커가 손대면 안 되는가.

    🚨 판정 실패는 **True**(=제외) 다. 자본/손절을 바꾸는 판정이므로 fail-closed.
    """
    try:
        tpl = _template_of(si)
        stype = (getattr(tpl, "strategy_type", "") or "") if tpl is not None else ""
        if stype in SINGLE_ENTRY_STRATEGY_TYPES:
            return True
        name = (getattr(tpl, "name", "") or "").upper() if tpl is not None else ""
        return any(name.startswith(p) for p in SINGLE_ENTRY_TEMPLATE_PREFIXES)
    except Exception as e:
        logger.warning("[single_entry_guard] 판정 실패 = 제외로 간주: %s", e)
        return True


def drop_single_entry(rows: Iterable[Any], *, tag: str = "") -> list:
    """후보 목록에서 1회 진입 전략을 걷어낸다. 걷어낸 수를 로그에 남긴다.

    쿼리 구조를 건드리지 않고 쓸 수 있게 **파이썬 쪽 필터**로 둔다
    (워커마다 조인 모양이 달라서 SQL 조건을 끼워 넣는 것보다 안전하다).
    후보 수가 작으므로 비용은 무시할 수 있다.
    """
    rows = list(rows or [])
    kept = [r for r in rows if not is_single_entry(r)]
    dropped = len(rows) - len(kept)
    if dropped:
        logger.info("[single_entry_guard]%s 1회 진입 전략 %d건 제외",
                    f" {tag}" if tag else "", dropped)
    return kept

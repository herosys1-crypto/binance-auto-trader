"""📊 당일 변동률 진입 게이트 — 사장님 2026-09-03 지시 (Fix 310 → 325).

## 사장님 원문

  (처음) "당분간 **당일 10% 이상 상승과 하락한 심볼만** 모니터링하고
          포지션에 진입하도록해줘"
  (확정) "당일 **상승 50위까지 50개 하락 50위까지 50개 100개**를 매일
          모니터링해서 포지션에 진입이 가능하면 진입해줘"

→ **순위 기준이 기본**이다. 절대값 |24h| >= 10% 는 시장이 조용한 날 대상이
  급격히 줄어든다 — 실측(2026-09-03) 거래대금 5M 이상 252심볼 중 **26개(10.3%)**.
  순위 방식은 **항상 100개**를 유지하고, 사장님 사상 ⑧(급등 50 / 급락 50
  모니터링)과 그대로 맞는다.

  `entry_chg24_gate_mode = "abs"` 로 두면 옛 절대값 방식으로 돌아간다.

전부 설정으로 뺀다 — 사장님이 언제든 끄고 값을 바꿀 수 있어야 한다.

## 🚨 어디에 거는가 — 「신규 진입」에만 건다

`execution_service.start_stage1` 한 곳에 건다. 이유:

- `start_stage1` 은 **새 전략의 1단계 진입**이다. 신규 진입 8개 경로가 전부
  여기를 지난다 (auto_bb_breakdown / pump_split / auto_reentry / ladder_restart /
  scheduled_entry / surge_ladder / API).
- **단계 진입(`trigger_next_stage`)에는 걸지 않는다.** 1단계 진입 때 12% 였다가
  2단계 트리거 시점에 8% 로 떨어지면 사다리가 그 자리에서 **영원히 멈춘다.**
  이미 자금이 들어간 전략의 사다리를 변동률로 끊으면 안 된다.

## ⚠️ 수동 진입은 제외한다

템플릿 이름이 `_quick_` 로 시작하면 통과시킨다. 사장님이 손으로 넣으신 것은
사장님 판단이고, 그걸 자동 규칙으로 막으면 안 된다.
(이 저장소는 「수동 진입에 자동 로직을 얹지 않는다」를 반복해서 확인했다 —
 realtime_reentry_worker 가 DYNAMIC_* 를 일부러 제외하는 것과 같은 이유다.)

## fail 방향

24h 조회에 실패하면 **통과**시킨다 (fail-open). 여기서 fail-closed 하면
거래소 API 가 한 번 흔들릴 때마다 모든 신규 진입이 멈춘다 — 이 저장소가
Fix 305 에서 겪은 「영구 정지」와 같은 함정이다. 대신 경고 로그를 남긴다.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

__all__ = [
    "SETTING_ENABLED", "SETTING_MIN_ABS", "SETTING_TOP_N", "SETTING_MODE",
    "MIN_ABS_DEFAULT", "TOP_N_DEFAULT", "MODE_DEFAULT",
    "gate_enabled", "min_abs_chg24", "top_n", "gate_mode", "passes",
]

SETTING_ENABLED = "entry_chg24_gate_enabled"    # 사장님 「당분간」 → 켜고 끌 수 있게
SETTING_MIN_ABS = "entry_min_abs_chg24"         # (구) 절대값 기준 — 순위 방식이 우선
SETTING_TOP_N = "entry_rank_top_n"              # 사장님 「상승 50 / 하락 50」
SETTING_MODE = "entry_chg24_gate_mode"          # "rank"(기본) | "abs"

MIN_ABS_DEFAULT: float = 10.0
TOP_N_DEFAULT: int = 50        # 상승 50 + 하락 50 = 100개
MODE_DEFAULT: str = "rank"


def _setting(db, key: str):
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        if row is None or row.value is None:
            return None
        v = str(row.value).strip()
        return v or None
    except Exception as e:
        logger.warning("[Fix310] %s 조회 실패: %s", key, e)
        return None


def gate_enabled(db) -> bool:
    v = _setting(db, SETTING_ENABLED)
    return bool(v) and v.lower() in ("1", "true", "on", "yes")


def min_abs_chg24(db) -> float:
    v = _setting(db, SETTING_MIN_ABS)
    if v is None:
        return MIN_ABS_DEFAULT
    try:
        f = float(v)
    except (TypeError, ValueError):
        logger.warning("[Fix310] %s=%r 파싱 실패 → 기본 %s", SETTING_MIN_ABS, v, MIN_ABS_DEFAULT)
        return MIN_ABS_DEFAULT
    if f < 0 or f > 100:
        logger.warning("[Fix310] %s=%s 범위밖(0~100) → 기본 %s", SETTING_MIN_ABS, f, MIN_ABS_DEFAULT)
        return MIN_ABS_DEFAULT
    return f


def top_n(db) -> int:
    """상승/하락 각각 몇 위까지 볼 것인가 (사장님 「50위까지」)."""
    v = _setting(db, SETTING_TOP_N)
    if v is None:
        return TOP_N_DEFAULT
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return TOP_N_DEFAULT
    if n < 1 or n > 500:
        logger.warning("[Fix325] %s=%s 범위밖(1~500) → 기본 %d", SETTING_TOP_N, v, TOP_N_DEFAULT)
        return TOP_N_DEFAULT
    return n


def gate_mode(db) -> str:
    """"rank"(순위) | "abs"(절대값). 사장님 지시는 순위다."""
    v = (_setting(db, SETTING_MODE) or MODE_DEFAULT).lower()
    return v if v in ("rank", "abs") else MODE_DEFAULT


def _is_manual(template_name: object) -> bool:
    """수동 진입(`_quick_`)인가. 사장님 판단이므로 이 게이트를 적용하지 않는다."""
    return str(template_name or "").startswith("_quick_")


def passes(db, bc, symbol: str, *, template_name: object = None) -> tuple[bool, str]:
    """이 심볼이 신규 진입 대상인가.

    Returns:
        (통과, 사유)

    사장님: "상승 50위까지 50개 하락 50위까지 50개 **100개**를 매일 모니터링"
    → 급등(+)과 급락(-) 양쪽 순위 각각 50위까지.
    """
    if not gate_enabled(db):
        return True, ""
    if _is_manual(template_name):
        return True, "수동 진입 (게이트 미적용)"

    # ═══════════════════════════════════════════════════════════════════
    # 🌟 Fix 325 (2026-09-03 사장님): **순위 기준**으로 바꾼다.
    #
    #   사장님: "당일 **상승 50위까지 50개 하락 50위까지 50개 100개**를 매일
    #            모니터링해서 포지션에 진입이 가능하면 진입해줘"
    #
    #   절대값 |24h| >= 10% 는 시장이 조용한 날 대상이 급격히 줄어든다 —
    #   실측(2026-09-03) 거래대금 5M 이상 252심볼 중 **26개(10.3%)** 만 남았다.
    #   순위 방식은 **항상 100개**를 유지한다. 사장님 사상 ⑧(급등 50 / 급락 50
    #   모니터링)과도 그대로 맞는다.
    #
    #   `entry_chg24_gate_mode = "abs"` 로 두면 옛 절대값 방식으로 돌아간다.
    # ═══════════════════════════════════════════════════════════════════
    mode = gate_mode(db)
    try:
        from app.services.market_movers import change_pct, top_movers
        rows = bc.get_24hr_ticker()
        if isinstance(rows, dict):
            rows = [rows]
    except Exception as e:
        logger.warning("[Fix325] %s 시세 조회 실패 → 통과 (fail-open): %s", symbol, e)
        return True, "시세 조회 실패 (fail-open)"

    me = next((t for t in rows if str(t.get("symbol") or "") == symbol), None)
    chg = change_pct(me) if me else 0.0

    if mode == "abs":
        floor = min_abs_chg24(db)
        if abs(chg) >= floor:
            return True, f"24h {chg:+.2f}% (|{chg:.2f}| >= {floor:g}%)"
        return False, f"24h {chg:+.2f}% — 「{floor:g}% 이상」 미충족"

    n = top_n(db)
    try:
        ups, downs = top_movers(rows, n)
    except Exception as e:
        logger.warning("[Fix325] %s 순위 산출 실패 → 통과 (fail-open): %s", symbol, e)
        return True, "순위 산출 실패 (fail-open)"

    for lab, group in (("상승", ups), ("하락", downs)):
        for i, t in enumerate(group, 1):
            if str(t.get("symbol") or "") == symbol:
                return True, f"{lab} {i}위 (24h {chg:+.2f}%) — 모니터링 {n}+{n}개 안"
    return False, (
        f"24h {chg:+.2f}% — 상승/하락 각 {n}위 밖 "
        f"(사장님 「상승 {n} + 하락 {n} = {n * 2}개」 대상 아님)"
    )

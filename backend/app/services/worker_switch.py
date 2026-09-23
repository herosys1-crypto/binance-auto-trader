"""🎛 Fix 374 (2026-09-16) — 개별 자동 워커 켜기/끄기 스위치.

2026-09-16 실측: 진입을 만드는 워커 6종은 **자기 스위치가 없어** 화면에서도 DB 에서도 개별로 끌 수 없었다.
끄는 방법이 「공용 한도 키를 0 으로」(다른 워커까지 멈춘다) 또는 「scheduler_runner 주석 처리 + 재배포」뿐이었다.
사장님 「모든 자동매매를 한곳으로 모아서 사용과 관리가 편리하게」를 만들려면 가족마다 스위치가 하나 있어야 한다.

설계 (기존 동작을 바꾸지 않는다):
  · 기본 **켜짐**. 행이 없거나 값이 이상하거나 읽기 실패 = 켜짐 = 이 스위치를 넣기 전과 똑같이 돈다 (fail-open).
  · 명시적으로 `0 / off / false / no` 일 때만 끈다. 끌 때는 반드시 로그를 남긴다 (헌법 80: 조용한 조기 return 금지).
  · 전면 정지는 이 스위치가 아니라 `auto_trading_halt`(Fix 371, fail-closed) 와 Kill-Switch 가 담당한다.
    이 스위치는 「이 워커만 쉬게 한다」는 용도다.

값은 `system_settings` 행이라 재시작이 필요 없다. 화면 = 🎛 자동매매 관제실 (`/static/auto-control.html`).
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

FIX = "Fix374"
OFF_WORDS = ("0", "off", "false", "no")

# key -> (사람이 읽는 이름, 워커 job id)
SWITCHES: dict[str, tuple[str, str]] = {
    "sajangnim_top_short_enabled": ("급등 정점 SHORT (v219)", "auto_short_at_top"),
    "sajangnim_bottom_long_enabled": ("저점 LONG (v226)", "auto_long_at_bottom"),
    "realtime_reentry_enabled": ("실시간 재진입 (마틴게일)", "realtime_reentry"),
    "resistance_reversal_enabled": ("저항 반전 SHORT", "resistance_reversal"),
    "peak_break_reversal_enabled": ("전고점 돌파 반전", "peak_break_reversal"),
    "ladder_restart_enabled": ("사다리 재시작", "ladder_restart"),
}


def is_on(db: Any, key: str) -> bool:
    """이 워커가 돌아야 하는가. 기본·손상·실패 = True (기존 동작 유지)."""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s 조회 실패 → 켜짐으로 진행: %s", FIX, key, e)
        return True
    if row is None or row.value is None:
        return True
    return str(row.value).strip().lower() not in OFF_WORDS


def off_note(key: str) -> dict:
    """꺼져 있을 때 워커가 돌려줄 결과 + 로그 (조용히 끝내지 않는다)."""
    label = SWITCHES.get(key, (key, ""))[0]
    logger.info("[%s] ⏹ %s 꺼짐 — %s=0 (관제실에서 켤 수 있음)", FIX, label, key)
    return {"note": f"{key}=0 (사장님 명시 OFF)", "entered": 0, "switch": key}

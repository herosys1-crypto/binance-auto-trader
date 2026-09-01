"""💰 잔액 부족을 **보이는 상태**로 만든다 (Fix 264).

## 왜 필요한가 — 실측 (2026-09-01)

가용 잔액이 바닥났는데 그 사실이 **어디에도 안 보였다.**

    balance             6,576.66 USDT   (활성 39건의 ISOLATED 마진 포함)
    availableBalance       46.73 USDT   <- 실제로 쓸 수 있는 돈
    계획자본 합            9,985.00 USDT

그 결과 재진입이 매 사이클 이렇게 죽었다:

    ValueError: 💰 잔액 부족 — 필요한 마진 150.00 USDT > 가용 잔액 76.52 USDT
      File "realtime_reentry_worker.py", line 1466, in run_realtime_reentry

문제는 세 가지였다:

  1. **사유가 뭉뚱그려졌다** — 워커 집계에는 `entry_exception` 으로만 잡혀서
     「왜 진입이 0건인가」를 로그만 보고는 알 수 없었다. 사이클 요약의
     `fail=0` 은 사실이 아니었다.
  2. **매 사이클 전체 스택트레이스**가 쌓였다. 원인은 하나인데 노이즈가 커서
     진짜 오류가 묻힌다.
  3. **낭비**: 잔액이 없는데도 남은 후보 전부에 대해 지표·캔들 API 를 계속 쳤다.

이 프로젝트의 대표적 실패 모드(「조용한 실패」)의 전형이다 — 시스템은
정확히 알고 있었는데 그 사실이 사람에게 도달하지 않았다.

## 무엇을 하는가

진입 생성이 잔액 부족으로 실패하면:
  - Redis 에 **짧은 TTL 플래그**를 남긴다 (숫자 포함)
  - 워커는 사이클 앞에서 그 플래그를 보고 **조기 종료**한다 (API 낭비 중단)
  - 사장님께 **1시간에 한 번만** 알린다 (같은 원인으로 도배하지 않는다)

⚠️ 플래그는 TTL 로 저절로 풀린다. 잔액이 회복되면 다음 사이클부터 정상 동작한다.
   수동 해제가 필요한 「잠금」이 아니다 — 그런 잠금은 이 프로젝트에서
   IP ban 사고(2026-08-26) 때 스스로 상황을 연장시킨 적이 있다.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "is_insufficient_balance_error",
    "mark_insufficient_balance",
    "check_balance_block",
    "clear_balance_block",
    "BLOCK_TTL_SEC",
]

_KEY = "entry_block:insufficient_balance"
_ALERT_KEY = "entry_block:insufficient_balance:alerted"

# 잔액이 회복되면 스스로 풀려야 한다. 사이클 주기(15~60초)보다 넉넉하되 짧게.
BLOCK_TTL_SEC = 300
_ALERT_TTL_SEC = 3600          # 같은 원인 알림은 1시간에 한 번


def is_insufficient_balance_error(exc: Any) -> bool:
    """이 예외가 「잔액/마진 부족」인가.

    strategy_service 가 던지는 두 문구를 모두 잡는다:
        "💰 잔액 부족 — 필요한 마진 ..."
        "💰 1단계 마진 부족 — 필요 ..."
    """
    m = str(exc or "")
    return ("잔액 부족" in m) or ("마진 부족" in m)


def _numbers_from(exc: Any) -> dict[str, float | None]:
    """예외 문구에서 필요/가용 숫자를 뽑는다 (실패해도 None 으로 넘어간다)."""
    import re
    m = str(exc or "")
    out: dict[str, float | None] = {"required": None, "available": None}
    try:
        nums = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*USDT", m)
        if len(nums) >= 2:
            out["required"], out["available"] = float(nums[0]), float(nums[1])
    except Exception:
        pass
    return out


def mark_insufficient_balance(redis_client, exc: Any, *, source: str, db=None) -> None:
    """잔액 부족을 기록하고(짧은 TTL) 사장님께 1시간에 한 번 알린다."""
    d = _numbers_from(exc)
    d["source"] = source
    try:
        redis_client.setex(_KEY, BLOCK_TTL_SEC, json.dumps(d, default=str))
    except Exception as e:
        logger.debug("[balance_guard] 플래그 기록 실패 (계속): %s", e)

    logger.warning(
        "[balance_guard] 💰 잔액 부족으로 진입 실패 (%s): 필요 %s / 가용 %s USDT "
        "— %d초간 진입 시도를 멈춘다",
        source, d.get("required"), d.get("available"), BLOCK_TTL_SEC,
    )

    # 알림은 1시간에 한 번만 — 같은 원인으로 화면을 도배하지 않는다.
    if db is None:
        return
    try:
        if redis_client.get(_ALERT_KEY):
            return
        redis_client.setex(_ALERT_KEY, _ALERT_TTL_SEC, "1")
    except Exception:
        return
    try:
        from app.services.notification_service import NotificationService
        NotificationService(db).send_system_alert(
            title="[진입 중단] 💰 가용 잔액 부족",
            body=(
                f"자동 진입이 잔액 부족으로 실패했습니다.\n"
                f"• 필요 마진: {d.get('required')} USDT\n"
                f"• 가용 잔액: {d.get('available')} USDT\n"
                f"• 발생 위치: {source}\n\n"
                f"활성 포지션이 증거금을 묶고 있으면 일부 정리하거나 "
                f"USDT 를 추가 입금해야 신규/재진입이 재개됩니다.\n"
                f"(이 알림은 1시간에 한 번만 옵니다)"
            ),
        )
    except Exception as e:
        logger.debug("[balance_guard] 알림 실패 (계속): %s", e)


def check_balance_block(redis_client) -> tuple[bool, dict[str, Any]]:
    """지금 잔액 부족으로 진입을 멈춰야 하는가.

    Returns:
        (막을 것인가, 상세)

    ⚠️ Redis 조회 실패는 **막지 않는다**(fail-open). 이 가드는 낭비를 줄이는
       최적화이지 안전장치가 아니다 — 실제 안전장치는 거래소의 잔액 검증이다.
       가드가 스스로 상황을 악화시키면 안 된다 (2026-08-26 IP ban 교훈).
    """
    try:
        raw = redis_client.get(_KEY)
        if not raw:
            return False, {}
        return True, json.loads(raw)
    except Exception:
        return False, {}


def clear_balance_block(redis_client) -> None:
    """수동 해제 (사장님이 입금한 직후 등)."""
    try:
        redis_client.delete(_KEY)
    except Exception:
        pass

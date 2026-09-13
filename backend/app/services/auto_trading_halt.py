"""⛔ Fix 371 (2026-09-14 사장님) — 자동매매 전면 중단 · 사람이 만든 전략과 사람이 누른 버튼만 실주문.

사장님 verbatim: "새전략 기본방식과 새전략 obv 자동만 가능하게 수동으로 전략을 만들수 있게 남기고 모든 자동매매 중단하고
가상으로만 매매하고 학습하고 손실이 발행하는 원일을 학습해서 수정할수 있게 기록해서 우리 자동매매에 적용할수 있게 자료를 만들어줘"

직전 상황: 9/13 KOMAUSDT #4500 · 哈基米USDT #4483 에서 자동 「수익 추가」(success_pyramiding) 300 USDT 가 급등 막바지에 들어가
미실현 −108 / −172 중 약 −91 / −134 가 추가분이었다 → 9/14 사장님 「모든 자동매매는 중단해줘」 → Kill-Switch MANUAL 로 전면 정지.
Kill-Switch 는 사람의 전략 생성·💉 추가까지 막으므로, 이 게이트로 「사람 것만 통과」를 만든다.

판정 (중단 중일 때):
  사람이 누른 버튼 (origin="manual")      💉 포지션 추가 · ▶ 다음 단계(시장가) · 「전략 시작」 → **출처와 무관하게 허용**
                                          (반박 검증 A/B: 배포 전에 만든 사람 전략·손절 없는 기존 방식 포지션을 사람이 방어할 길을 막지 않는다)
  자동 포지션 추가 · 자동 시장가 단계      항상 차단 (수익 추가 · 외부 전략 · 규칙 가족 · 급등 사다리 · 반전 워커)
  자동 1단계 · 자동 다음 단계              인스턴스 entry_origin == 'manual_modal' 만 (모달 설정대로 = 가격/OBV 단계 · 예약 시작)
  전략 생성                               entry_origin == 'manual_modal' 이고 가족이 legacy_manual · obv_auto 인 것만
청산 · TP · 손절은 이 게이트를 지나지 않는다 (진입 함수만 부른다).

🚨 왜 entry_profile 이 아니라 entry_origin 인가: `strategy_service` 는 템플릿이 OBV_REVERSE 면 **누가 만들든** entry_profile='obv_auto'
   를 찍는다 → 관리 재진입·자동 재진입 복제본도 'obv_auto' 라 사람 표식으로 쓸 수 없다. entry_origin 은 생성 요청의 출처(모달=manual_modal,
   워커=None) 를 그대로 저장한 값(alembic 0040). 소급은 entry_profile='legacy_manual' 행만(그 표식은 모달 생성에서만 찍힌다).

설정 (재시작 불필요):
  auto_trading_halt   행 없음 · 빈 값 · 읽기 실패 = **중단** (Claude가 정함 — 모르면 막는다, 헌법 118). "0"/"off"/"false"/"no" 일 때만 옛 동작.
차단 메시지에는 'kill-switch' 를 넣는다 — realtime_reentry 의 사유 분류가 Kill-Switch 와 같게 다룬다. 워커가 「중단」을 따로 알아볼 땐 is_halt_error.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

FIX = "Fix371"
HALT_KEY = "auto_trading_halt"
MANUAL_ORIGIN = "manual_modal"          # = strategy_service.ENTRY_ORIGIN_MANUAL (순환 import 를 피해 값으로 둔다 — 테스트가 같음을 고정)
MANUAL_ACTION = "manual"                # 진입 함수 origin=... 의 사람 버튼 값
CREATE_FAMILIES = frozenset({"legacy_manual", "obv_auto"})   # = risk_constants LEGACY_MANUAL_PROFILE / OBV_AUTO_PROFILE
_OFF_VALUES = ("0", "off", "false", "no")
BLOCK_TAG = "자동매매 중단 Fix371"
BLOCK_PREFIX = f"⛔ [{BLOCK_TAG}] (kill-switch 동급)"
FORCE_HALT: bool | None = None          # 테스트 전용 — None 이면 설정을 읽는다 (tests/conftest.py 가 False 로 둔다)


def halt_enabled(db) -> bool:
    """중단 중인가. 행 없음·빈 값·읽기 실패 = True (fail-closed)."""
    if FORCE_HALT is not None:
        return FORCE_HALT
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, HALT_KEY)
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s 조회 실패 = 중단 유지: %s", FIX, HALT_KEY, e)
        return True
    if row is None or row.value is None:
        return True
    return str(row.value).strip().lower() not in _OFF_VALUES


def is_manual_action(origin: Any) -> bool:
    return str(origin or "").strip().lower() == MANUAL_ACTION


def is_manual_strategy(strategy: Any) -> bool:
    return str(getattr(strategy, "entry_origin", None) or "") == MANUAL_ORIGIN


def is_halt_error(exc: BaseException | str) -> bool:
    return BLOCK_TAG in str(exc)


def check_order(db, strategy: Any, *, action: str, manual_action: bool = False, manual_only: bool = False) -> None:
    """진입 함수(1단계·다음 단계·시장가 단계·포지션 추가) 첫머리에서 부른다. 막히면 ValueError.
    manual_action = 사람이 누른 버튼, manual_only = 사람 버튼으로만 허용되는 동작(포지션 추가·시장가 단계)."""
    if not halt_enabled(db):
        return
    if manual_action:
        return
    sid = getattr(strategy, "id", "?")
    sym = getattr(strategy, "symbol", "?")
    if manual_only:
        logger.info("[%s] ⛔ #%s %s 자동 %s 차단", FIX, sid, sym, action)
        raise ValueError(
            f"{BLOCK_PREFIX} #{sid} {sym} 자동 {action} 차단 — 중단 중에는 사람이 누른 버튼만 허용 "
            f"(재개: system_settings {HALT_KEY}=0)"
        )
    if is_manual_strategy(strategy):
        return
    logger.info("[%s] ⛔ #%s %s %s 차단 — 사람이 모달로 만든 전략이 아님 (entry_origin=%s)",
                FIX, sid, sym, action, getattr(strategy, "entry_origin", None))
    raise ValueError(
        f"{BLOCK_PREFIX} #{sid} {sym} 자동 {action} 차단 — 중단 중에는 「➕ 새 전략 (기존 방식)」·「새 전략 (OBV 자동)」으로 "
        f"사람이 만든 전략만 자동 진행합니다 (재개: system_settings {HALT_KEY}=0)"
    )


def check_create(db, *, entry_origin: str | None, entry_profile: str | None) -> None:
    """전략 인스턴스 생성 직전에 부른다. 막히면 ValueError."""
    if not halt_enabled(db):
        return
    if str(entry_origin or "") == MANUAL_ORIGIN and str(entry_profile or "") in CREATE_FAMILIES:
        return
    logger.info("[%s] ⛔ 전략 생성 차단 (entry_origin=%s entry_profile=%s)", FIX, entry_origin, entry_profile)
    raise ValueError(
        f"{BLOCK_PREFIX} 전략 생성 차단 — 중단 중에는 화면 「➕ 새 전략 (기존 방식)」·「새 전략 (OBV 자동)」만 허용 "
        f"(요청 출처={entry_origin or '자동'}, 가족={entry_profile or '그 밖'} · 재개: system_settings {HALT_KEY}=0)"
    )

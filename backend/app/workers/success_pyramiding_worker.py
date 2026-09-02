"""🎯 사장님 사상 (2026-08-21): 성공 포지션 피라미딩!

사장님 verbatim:
"익절 시작하고 우리 로직으로 강력한 포지션 진입 일경우 초기 시작금액으로
 즉시 포지션 진입해서 수익을 더해가고 다시 하락하면 -5% 우리 로직에 맞게 청산"

= 매 30초 실행!
= 활성 심볼 (익절중!) = 강한 지속 신호 시 = 원 자본으로 즉시 추가 포지션!
= 신 strategy = 별도 관리 (자체 SL, TP, trailing = 우리 로직!)
= 다시 하락 = 강제 SL (-5%) = 우리 로직으로 청산!

realtime_reentry_worker와 대칭:
- realtime_reentry_worker = 청산 후 재진입 (TERMINAL_STATUSES!)
- success_pyramiding_worker = 활성 중 추가 진입 (ACTIVE_LIKE!)

안전:
- MAX_PYRAMID_COUNT=5 (헌법 47!)
- cooldown 5분 (심볼:side 단위 = 남발 방지!)
- daily_limit 공유 (auto_bb_break_daily_limit!)
- 급등/급락 필터 (헌법 64: >+15% SHORT 금지, <-15% LONG 금지!)
- 130% 자본 경고 = skip
- 이미 pyramid strategy 활성 = skip
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_WITH_POSITION   # Fix 196: ACTIVE_LIKE 미사용
from app.core.strategy_status import SPLIT_ENTRY_MODE as _SPLIT_ENTRY_MODE
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate

logger = logging.getLogger(__name__)

# 🚨 v220 사장님 (2026-08-22): 조건 완화 = 미발동 fix!
# 사장님 지적: "익절중인 심볼들의 추가 포지션에 들어가지 못한 원인 파악!"
# 🎯 Fix 134 (2026-08-26 사장님 지시): "수익일떄 10 +5% 마틴게일 300 진입"
#   손절이 -5% ROI(레버리지 반영) 이므로 익절 트리거도 「같은 자」로 재야 대칭이다.
#   옛 값 2.0 은 raw 가격 변동률이라 2x 레버리지에서 ROI 4% 를 뜻했다 = 기준 불일치.
MIN_UNREALIZED_ROI_PCT = 5.0       # ROI 기준 (= 가격변동 × 레버리지)
SETTING_TRIGGER_ROI = "sajangnim_pyramid_trigger_roi"   # Fix 300: 설정으로 덮는다
MIN_UNREALIZED_PNL_PCT = 2.0       # (레거시 상수 = 다른 곳 참조 방지 위해 유지)
MIN_SUSTAIN_PCT = 0.5              # v220: 1.0 → 0.5 (더 빨리 발동!)
PEAK_HOLD_TOLERANCE_PCT = 2.5      # v220: 1.5 → 2.5 (변동성 관대!)
COOLDOWN_SECONDS = 300             # 심볼:side 단위 5분 cooldown!
PYRAMID_COUNT_TTL_DAYS = 7         # 카운터 7일 후 리셋!

# 🌟 v241 Fix 68 사장님 신 verbatim (2026-08-25!):
# "이건 이미 있는 전략이야 TP1 실행후 지속적인 수익일때
#  포지션 초기진입 설정된 금액으로 포지션 추가야"
# = 마틴게일 배수 X! = 초기진입 설정 금액 그대로!
# = 예: 초기 300 USDT → TP1 실행 → 지속 수익 → 추가 300 → 추가 300!
# 이전 (v220 Fix 17): MARTINGALE_MULT = [1.0, 2.0, 6.0] (배수 도입 = 사장님 verbatim 위반!)
# 지금 (v241 Fix 68): 배수 완전 제거 = 초기진입 금액 그대로!
MAX_PYRAMID_COUNT = 2              # 🌟 Fix 98 (2026-08-25 사장님 verbatim!): "tp1 익절후 추가 진입은 최대 2번까지만" = 3 → 2!
# MARTINGALE_MULT 제거 = 배수 X = 초기진입 금액 그대로!

# 🚨 v220 사장님: 원본 필터 확장! (사장님 지적 root cause!)
# 이전: auto_bb_break* 만 → sajangnim_top_short/realtime_reentry = skip!
# 신: 모든 자동 진입 소스 = 익절중 pyramid 가능!
# 🚨 Fix 185 (2026-08-27): 한 사이클에 추가할 최대 건수.
#   동시보유 상한 게이트를 뺀 자리를 대신한다 (그 상한은 「새 종목 수」의 문제이지
#   「이기는 포지션을 키울까」의 문제가 아니다). 30초 주기라 소량이면 충분하다.
MAX_PYRAMID_PER_CYCLE = 3

# ═══════════════════════════════════════════════════════════════════════════
# 🚨 Fix 196 (2026-08-28): 후보를 ACTIVE_LIKE 로 고르면 안 된다.
#
# ACTIVE_LIKE 는 「신규 전략 진입을 **차단**해야 할 상태」 집합이지
# 「거래소에 포지션이 살아 있는 상태」 집합이 아니다 (strategy_status.py 주석이 그렇게 정의).
# 거기엔 포지션이 없는 상태가 셋 들어 있다:
#   LIQUIDATED_WAITING_RETRY  = 청산 완료, 잔량 0, 다음 단계 트리거 대기
#   STOPPING                  = 사장님이 정지를 눌러 청산 진행 중
#   MANUAL_CLEANUP_REQUIRED   = 사장님 확인 대기 (자동 정리에서 제외돼 무기한 지속)
#
# 그리고 청산 시 stream_service 는 qty/unrealized 만 0 으로 만들고
# **avg_entry_price 는 남긴다** → 옛 평단 + 살아있는 mark_price 로 ROI 가 계산돼
# 게이트를 통과할 수 있다. 통과하면 add_position_now(mode="reset") 가
#   ① 시장가로 **새 포지션을 연다** (= Fix 185 가 상한을 뺀 근거 「건수가 안 는다」가 깨진다)
#   ② execution_service 가 status 를 STAGE{n}_OPEN 으로 덮어쓴다
# → stage_trigger_worker 는 재진입을 status=="LIQUIDATED_WAITING_RETRY" 일 때만 진행하므로
#   **계획된 다음 단계가 영구히 차단된다** = 사장님이 원하신 「손실 구간 재반응」이 죽는다.
#   MANUAL_CLEANUP_REQUIRED 였다면 「확인 필요」 표식까지 조용히 지워진다.
#
# → 실제로 포지션을 들고 있는 상태만 고르고, **잔량으로 한 번 더** 확인한다.
#   (집합만 믿지 않는다 — 나중에 누가 상태를 추가하면 또 새는 자리다, 헌법 138)
# ═══════════════════════════════════════════════════════════════════════════
PYRAMID_ELIGIBLE_STATUSES = frozenset(
    ACTIVE_WITH_POSITION - {"STOPPING", "MANUAL_CLEANUP_REQUIRED"}
)

# 🚨 Fix 213/214: 볼밴 분할 마커 — 값은 app.core.strategy_status 하나에만 둔다.
#   (워커마다 문자열을 복사하면 한 곳만 오타나도 조용히 샌다 = -252 USDT 짜리 실패였다)
SPLIT_ENTRY_MODE = _SPLIT_ENTRY_MODE

# ═══════════════════════════════════════════════════════════════════════
# 🚨 Fix 282 (2026-09-02): 피라미딩에서 **제외**할 전략 타입.
#
#   위 -252.18 사고와 **정확히 같은 구조**가 새 전략들에도 있다:
#     • 발동선이 ROI +5% 인데, 이 전략들의 **TP1 도 +5%** 다.
#       → 익절해야 할 바로 그 지점에서 300 USDT 추가 매수가 나간다.
#     • 자본 100 짜리 포지션에 300 이 얹히면 물량이 4배가 되고 평단이 밀려
#       손절선이 진입가보다 불리한 쪽으로 올라온다.
#     • 두 전략 모두 **1회 진입**을 전제로 성과를 측정했다. 물량이 바뀌면
#       측정한 규칙과 다른 매매가 된다.
#
#   surge_peak_ladder 는 게다가 **자기 추가 로직**을 이미 갖고 있다
#   (add_to_surge_position: 가격 2.5% 유리하면 50% 추가, 최대 2회, 손실액 고정).
#   범용 피라미딩이 같이 들어오면 두 규칙이 서로 싸운다.
#
#   ⚠️ 다른 전략의 피라미딩은 **그대로 둔다** (사장님 "이익일때 추가 300씩").
# ═══════════════════════════════════════════════════════════════════════
# Fix 283: 목록을 services/single_entry_guard.py 한 곳으로 옮겼다 (여기서 재수출).
from app.services.single_entry_guard import (  # noqa: E402
    SINGLE_ENTRY_STRATEGY_TYPES as NO_PYRAMID_STRATEGY_TYPES,
    SINGLE_ENTRY_TEMPLATE_PREFIXES as NO_PYRAMID_TEMPLATE_PREFIXES,
    is_single_entry as _is_single_entry_shared,
)

# ⚠️ Fix 185 로 **더 이상 진입 필터로 쓰지 않는다** (사장님: "모든 전략").
#   로그/참조용으로만 남긴다.
AUTO_ENTRY_TYPES_PYRAMID = (
    "auto_bb_break",        # BB SUSTAINED / PENDING_HC / OBV_REVERSE / REENTRY_QUEUE
    "sajangnim_top",        # v219 정점 SHORT!
    "realtime_reentry",     # 실시간 재진입!
    "chart_pattern",        # 차트 패턴!
)


def _redis():
    from app.core.redis_client import get_redis_client
    return get_redis_client()


def _rget(key: str) -> str | None:
    try:
        v = _redis().get(key)
        return (v.decode() if isinstance(v, bytes) else v) if v else None
    except Exception:
        return None


def _get_pyramid_count(strategy_id: int) -> int:
    """🚨 Fix 196 (2026-08-28): 카운터를 **전략 단위**로 센다.

    옛 키는 `pyramid_count:{symbol}:{side}` + 7일 TTL 이고 **지우는 코드가 없었다.**
    이 시스템은 realtime_reentry / ladder_restart / pump_split 이 같은 심볼·방향으로
    반복 재진입하는 구조라, A 전략이 2회 쓰고 종료하면 몇 시간 뒤 만들어진 B 전략이
    **첫 진입부터 max_pyramid_count 로 조용히 탈락**했다.
    사장님 의도는 「이 포지션에 최대 2회」이지 「이 심볼에 7일간 2회」가 아니다.
    (반대로 7일이 지나면 카운터가 사라져 평생 상한도 아니었다.)

    TTL 은 남겨 둔다 — 종료된 전략의 키가 영원히 쌓이는 것을 막는 청소 용도다.
    """
    v = _rget(f"pyramid_count:sid:{strategy_id}")
    return int(v) if v else 0


def _increment_pyramid_count(strategy_id: int) -> int:
    try:
        new_count = _get_pyramid_count(strategy_id) + 1
        _redis().setex(
            f"pyramid_count:sid:{strategy_id}",
            PYRAMID_COUNT_TTL_DAYS * 86400, str(new_count),
        )
        return new_count
    except Exception:
        return 0


def _cooldown_active(symbol: str, side: str) -> bool:
    return bool(_rget(f"pyramid_cooldown:{symbol}:{side}"))


def _set_cooldown(symbol: str, side: str) -> None:
    try:
        _redis().setex(f"pyramid_cooldown:{symbol}:{side}", COOLDOWN_SECONDS, "1")
    except Exception:
        pass


def _update_peak_price(symbol: str, side: str, price: float) -> float:
    """LONG=max/SHORT=min 극값만 갱신. TTL 1h."""
    try:
        prev_v = _rget(f"pyramid_peak:{symbol}:{side}")
        prev = float(prev_v) if prev_v else None
        new_peak = price if prev is None else (
            max(prev, price) if side == "LONG" else min(prev, price)
        )
        _redis().setex(f"pyramid_peak:{symbol}:{side}", 3600, str(new_peak))
        return new_peak
    except Exception:
        return price


def _get_mark_price(symbol: str) -> float | None:
    v = _rget(f"mark_price:{symbol}")
    if not v:
        return None
    try:
        p = float(v)
        return p if p > 0 else None
    except (ValueError, TypeError):
        return None


def _is_no_pyramid(si) -> bool:
    """Fix 282 — 이 전략은 범용 피라미딩 대상이 아닌가.

    strategy_type 과 템플릿 **이름** 둘 다 본다. 이름 접두사까지 보는 이유는
    strategy_type 에 접미사가 붙는 전략이 있기 때문이다 (auto_bb_break{suffix}).
    판정 실패는 **제외로 간주**한다 (fail-closed) — 자본이 늘어나는 판정이다.
    """
    return _is_single_entry_shared(si)      # Fix 283: 공통 가드 (fail-closed)


def _strategy_type_of(si) -> str:
    """🚨 Fix 142 (2026-08-26): 관계명이 틀려 피라미딩이 100% 차단되고 있었다.

    옛 코드: `si.template if hasattr(si, "template") else None`
      StrategyInstance 의 관계명은 `strategy_template` 이다 (`template` 아님,
      models/strategy_instance.py:113). → hasattr False → tpl None → stype ""
      → AUTO_ENTRY_TYPES_PYRAMID 매칭 전멸 → 후보 전원 탈락.
      실 로그: "완료: entered=0 skipped=9 | 사유: not_auto_entry_type=9"
      strategy_type 실제 값은 auto_bb_break{suffix} 라 원래 통과했어야 한다.

    Fix 138(남의 스위치) 을 고쳐 워커가 돌기 시작하자 비로소 드러난 3번째 층이다.
    """
    tpl = getattr(si, "strategy_template", None)
    if tpl is None:
        tpl = getattr(si, "template", None)          # 혹시 모를 별칭 대비
    return getattr(tpl, "strategy_type", "") or "" if tpl is not None else ""


# 🚨 Fix 269 (2026-09-01): 포지션 추가 시 손절 **금액** 고정 스위치.
#   기본 **ON** — 손실을 줄이는 방향이고 실측 근거가 명확하다
#   (추가 없음 -13.28 / 1회 -42.92 / 2회 -64.27 건당).
#   끄려면 SystemSetting pyramid_cap_loss_enabled = 0.
CAP_LOSS_KEY = "pyramid_cap_loss_enabled"


def _cap_loss_enabled(db) -> bool:
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, CAP_LOSS_KEY)
        if row is None or row.value is None or str(row.value).strip() == "":
            return True                      # 기본 ON
        return str(row.value).strip().lower() in ("1", "true", "on", "yes")
    except Exception as e:
        logger.warning("[Fix269] %s 조회 실패 = ON 유지: %s", CAP_LOSS_KEY, e)
        return True                          # fail-safe = 손실을 묶는 쪽


# 💉 Fix 273: 피라미딩 보조지표 조건 스위치.
#   사장님이 **원래 요청하신 조건**이고 실측이 강하게 지지하므로 기본 **ON**.
#   (조건 없음 -5,832 / 4H+15m 상승 +1,359 — 과적합 검사도 양쪽 절반 통과)
#   끄려면 SystemSetting pyramid_indicator_gate_enabled = 0.
INDICATOR_GATE_KEY = "pyramid_indicator_gate_enabled"


def _indicator_gate_enabled(db) -> bool:
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, INDICATOR_GATE_KEY)
        if row is None or row.value is None or str(row.value).strip() == "":
            return True                      # 기본 ON
        return str(row.value).strip().lower() in ("1", "true", "on", "yes")
    except Exception as e:
        logger.warning("[Fix273] %s 조회 실패 = ON 유지: %s", INDICATOR_GATE_KEY, e)
        return True                          # fail-safe = 조건을 거는 쪽



def _trigger_roi(db) -> float:
    """🎯 Fix 300 (2026-09-03 사장님 지시) — 추가 진입 트리거 ROI 를 설정으로 뺀다.

    사장님: "추가 트리거가 ROI +5% 인데 안정 종목 TP1 이 3% 면 추가 전에 익절됩니다.
             이것도 그러면 **+2%부터 진행**하면 될것 같아"

    ## 실측 (상승50 ∪ 하락50, 15m 1000봉, Fix 299 적응TP 적용, 전체 흐름 시뮬)

        트리거      총 손익      전반      후반    과적합   추가횟수  1차승률
        +2.0%     +556.27  +171.86  +309.60     OK      168     54%
        +2.5%     +610.28  +167.58  +345.74     OK      142      -
        +3.0%     +578.31  +187.49  +409.81     OK      101      -
        +5.0%     +656.95  +113.47  +512.66     OK       63     61%

    두 가지가 동시에 사실이다:

    1. **사장님이 지적한 「추가 전에 익절」은 일어나지 않는다.** TP1 은 물량의 25%만
       닫으므로 나머지 75%가 그대로 ROI 5% 까지 간다. 실측 63회 붙었다.
    2. **그래도 낮추면 추가가 2.7배(63→168회) 붙는다.** 사장님 사상
       「잘되면 추가 2번 진입해서 수익을 올린다」에 더 부합한다.

    다만 총 손익은 -100.68 낮고 1차 승률이 61%→54% 로 떨어진다. 덜 확실한 자리에
    물량을 키우면 되돌림에서 **커진 물량**이 손절을 맞기 때문이다.
    2% 도 과적합 검사(표본 절반 양쪽 양수)는 통과하므로 위험한 값은 아니다.

    그래서 **코드 기본값은 측정 최선인 5.0 을 유지**하고, 사장님 지시값 2.0 은
    설정 행으로 넣는다. 되돌리기 = 설정 행 삭제 한 줄.
    """
    from app.models.system_setting import SystemSetting
    try:
        row = db.get(SystemSetting, SETTING_TRIGGER_ROI)
        if row is None or row.value is None or not str(row.value).strip():
            return MIN_UNREALIZED_ROI_PCT
        v = float(str(row.value).strip())
        if v < 0.5 or v > 50.0:
            logger.warning(
                "[Fix300] %s=%s 범위밖(0.5~50) → 기본 %.1f",
                SETTING_TRIGGER_ROI, v, MIN_UNREALIZED_ROI_PCT,
            )
            return MIN_UNREALIZED_ROI_PCT
        return v
    except Exception as e:
        logger.warning("[Fix300] %s 조회 실패 → 기본 %.1f: %s",
                       SETTING_TRIGGER_ROI, MIN_UNREALIZED_ROI_PCT, e)
        return MIN_UNREALIZED_ROI_PCT


def run_success_pyramiding() -> dict:
    """매 30초 = 익절중 심볼 = 강한 지속 신호 시 = 원 자본으로 추가 진입!"""
    db: Session = SessionLocal()
    entered = 0
    skipped = 0
    results: list[dict] = []
    # 🎯 Fix 140: skip 사유 집계 — "왜 0건이지?" 에 로그만 보고 답할 수 있게.
    #   (realtime_reentry 의 _bump 와 같은 패턴 = 헌법 93 차단 사유 기록)
    _reasons: dict[str, int] = {}

    def _bump(reason: str) -> None:
        _reasons[reason] = _reasons.get(reason, 0) + 1
    try:
        # ═══════════════════════════════════════════════════════════════════
        # 🚨 Fix 138 (2026-08-26): 피라미딩이 남의 스위치에 물려 꺼져 있었다
        #
        # 사장님 질문: "이익일때 추가 300씩 두번 진입도 하는거지?"
        # 확인 결과 = 아니오. 이 워커 첫 줄이 auto_bb_break_daily_limit 을 보는데
        # 사장님이 「BB 이탈 자동진입」을 끄려고 그 값을 0 으로 두셨기 때문에
        # 별개 기능인 수익 피라미딩까지 통째로 꺼져 있었다.
        #   (두 기능이 스위치를 공유한 것 자체가 설계 실수 = 헌법 83 정신 위반)
        #
        # 또한 Fix 112 로 실질 상한이 「동시 보유 수」가 되었으므로,
        # 하루 카운터는 더 이상 이 워커의 예산이 아니다 (아래 check_position_slot 이 담당).
        #
        # 신: 전용 스위치 sajangnim_pyramid_enabled (기본 ON = 사장님이 원하는 기능).
        #     0 을 넣으면 피라미딩만 정확히 꺼진다.
        # ═══════════════════════════════════════════════════════════════════
        from app.models.system_setting import SystemSetting
        _pyr_row = db.get(SystemSetting, "sajangnim_pyramid_enabled")
        if _pyr_row is not None and str(_pyr_row.value).strip() not in ("", None):
            try:
                if int(str(_pyr_row.value).strip()) <= 0:
                    logger.warning(
                        "[success_pyramiding+Fix138] SKIP: sajangnim_pyramid_enabled=0 "
                        "= 사장님 명시 OFF"
                    )
                    return {"note": "pyramid_enabled=0 (사장님 명시 OFF)", "entered": 0}
            except (TypeError, ValueError):
                pass    # 손상값이면 켜진 것으로 본다 (사장님이 원하는 기본 동작)

        # 🎯 Fix 300: 추가 트리거 ROI (런당 1회 조회 — 후보마다 DB 를 때리지 않는다)
        _trig = _trigger_roi(db)

        from app.workers.auto_bb_breakdown_worker import (
            _count_used_slots, _create_auto_bb_strategy,
        )
        # ══════════════════════════════════════════════════════════════════
        # 🚨 Fix 185 (2026-08-27): 동시보유 상한 게이트를 **제거**한다 — 내 판단 착오.
        #
        # Fix 112b 는 "이 워커도 _create_auto_bb_strategy 로 새 StrategyInstance 를
        # 만든다" 는 전제로 상한을 걸었다. 그런데 **Fix 156 에서 그 전제가 바뀌었다** —
        # 지금은 `add_position_now` 로 **기존 포지션에 증거금을 추가**한다.
        #   → 동시 보유 **건수가 늘지 않는다.** 포지션 수 상한으로 막을 이유가 없다.
        #
        # 실제 피해 (사장님 #1581 BTRUSDT, 2026-08-27):
        #   동시보유가 10/10 으로 꽉 차 있어 이 워커가 **통째로 return** 했다.
        #   → 18분간 ROI +22% 까지 올라갔는데 수익 피라미딩이 한 번도 안 들어갔다.
        #   상한은 「새 종목을 몇 개까지 잡을까」의 문제이지,
        #   「이기고 있는 포지션을 키울까」의 문제가 아니다.
        #
        # 남는 안전장치: pyramid_enabled 스위치 / MAX_PYRAMID_COUNT(2) /
        #   ROI >= +5% / 쿨다운 / peak 되돌림 검사 — 자본 폭주는 이쪽이 막는다.
        # ══════════════════════════════════════════════════════════════════
        used = _count_used_slots(db)     # 참고 로그용
        # ⚠️ 상한 게이트를 없앤 자리에 **한 사이클 예산**을 둔다.
        #   `remaining` 은 아래 루프(:243, :559)가 그대로 쓰므로 반드시 정의해야 한다.
        #   (정의만 지우면 NameError 로 워커가 통째로 죽는다 — Fix 129 와 같은 사고)
        #   30초마다 도는 워커라 한 번에 몰아 넣지 않도록 소량으로 제한한다.
        remaining = MAX_PYRAMID_PER_CYCLE
        logger.info(
            "[success_pyramiding] 시작 (Fix185: 동시보유 상한 미적용 — 기존 포지션 "
            "추가라 건수가 늘지 않음 | 이번 사이클 예산 %d건, 오늘 신규 %d)",
            remaining, used,
        )

        # 2. 활성 심볼 조회 (익절중 후보!)
        active = db.execute(
            select(StrategyInstance)
            .join(StrategyTemplate,
                  StrategyInstance.strategy_template_id == StrategyTemplate.id)
            # 🚨 Fix 196: 포지션을 실제로 들고 있는 상태 + 잔량 확인 (위 상수 주석 참조)
            .where(StrategyInstance.status.in_(list(PYRAMID_ELIGIBLE_STATUSES)))
            .where(StrategyInstance.current_position_qty.isnot(None))
            .where(StrategyInstance.current_position_qty != 0)
            .where(StrategyInstance.is_archived.is_(False))   # Fix 158
            .where(StrategyInstance.current_stage >= 1)
            # ═══════════════════════════════════════════════════════════
            # 🚨 Fix 213 (2026-08-30): 볼밴 분할(split_entry)은 **제외**한다.
            #   두 전략은 방향이 정반대다:
            #     볼밴   = 내려갈수록 더 산다 (평단 개선이 목적)
            #     피라미딩 = 올라갈수록 더 산다 (평단 악화를 감수한 추세 추종)
            #   한 포지션에 둘 다 걸면 평단이 **불리한 쪽으로** 밀린다.
            #
            #   실측 2026-08-29 (볼밴 4건이 이걸로 죽었다):
            #     #1711 볼밴1차 399개 @0.50110  → 피라미딩 300씩 2회
            #                    1146개 @0.52345 + 1119개 @0.53621 (물량 5.7배)
            #           → 평단 0.50110 → 0.52546. 손절선이 **1차 진입가보다 위**로 올라와
            #             가격이 진입가로 되돌아오기만 해도 -10% 손절.
            #     #1721 / #1699(SHORT) / #1629 동일 패턴. 4건 합계 실현 -252.18 USDT.
            #
            #   게다가 mode=reset 이라 max_profit_pct 가 지워진다
            #   (#1629 는 +6.83% 기록이 None 이 됐다) = 트레일링 익절도 리셋.
            #   결정타: 볼밴 TP1 은 **+5% 부터 익절**인데 피라미딩 발동선도 ROI +5% 다.
            #   익절해야 할 바로 그 지점에서 추가 매수가 나간다 = 사장님 설계와 정면 충돌.
            #
            #   ⚠️ 다른 전략의 피라미딩은 **그대로 둔다** (사장님 "이익일때 추가 300씩").
            #      이 예외는 split_entry 뿐이다 — Fix 203 과 같은 성격.
            # ═══════════════════════════════════════════════════════════
            .where(StrategyInstance.capital_management_mode != SPLIT_ENTRY_MODE)
            # 🚨 Fix 282: 1회 진입 전략 제외 (TP1 과 발동선이 둘 다 ROI +5% 라 충돌)
            .where(~StrategyTemplate.strategy_type.in_(tuple(NO_PYRAMID_STRATEGY_TYPES)))
        ).scalars().all()

        # 🚨 Fix 282 이중 방어: strategy_type 에 접미사가 붙는 전략이 있어서
        #   (auto_bb_break{suffix} 처럼) DB 필터만 믿지 않는다. 템플릿 **이름**으로도 거른다.
        _before = len(active)
        active = [si for si in active if not _is_no_pyramid(si)]
        if len(active) != _before:
            logger.info("[pyramid] Fix282 제외 %d건 (1회 진입 전략)", _before - len(active))

        # 3. 심볼별 이미 pyramid 활성 = skip 집합!
        pyramid_active_syms: set[tuple[str, str]] = set()
        for si in active:
            stype = _strategy_type_of(si)      # Fix 142
            if "_pyramid" in stype:
                pyramid_active_syms.add((si.symbol, si.side))

        # 4. 원본 활성 심볼 = pyramid 후보 판정!
        seen: set[tuple[str, str]] = set()
        for si in active:
            if remaining <= 0:
                break
            key = (si.symbol, si.side)
            if key in seen:
                continue
            seen.add(key)

            # 🚨 Fix 213: 쿼리 필터를 한 번 더 확인한다 (헌법 138 — 집합만 믿지 않는다).
            #   이 자리가 새면 볼밴 평단이 조용히 망가지고, 그건 -252 USDT 짜리 실패였다.
            if str(getattr(si, "capital_management_mode", "") or "").lower() == SPLIT_ENTRY_MODE:
                logger.info(
                    "[success_pyramiding] SKIP #%s %s %s = 볼밴 분할(split_entry) — "
                    "내려가며 사는 전략에 올라가며 사는 피라미딩을 얹지 않는다 (Fix 213)",
                    si.id, si.symbol, si.side,
                )
                _bump("split_entry_excluded")
                continue

            # 이미 pyramid 활성 = skip
            if key in pyramid_active_syms:
                skipped += 1
                _bump("already_pyramid_active")
                continue

            # pyramid strategy 자체 = 재 pyramid 금지!
            stype = _strategy_type_of(si)      # Fix 142
            if "_pyramid" in stype:
                skipped += 1
                _bump("is_pyramid_strategy")
                continue

            # ══════════════════════════════════════════════════════════════
            # 🚨 Fix 185 (2026-08-27 사장님): strategy_type 필터 **제거** — 「모든 전략」.
            #
            # 사장님 verbatim: "모든 전략 — 수동/모달 전략도 수익 나면 추가 진입"
            #                 "수익구간에서 추가하는건 좋은 전략같아"
            #
            # 옛 코드는 AUTO_ENTRY_TYPES_PYRAMID(auto_bb_break / sajangnim_top /
            # realtime_reentry / chart_pattern) 4종만 허용했다.
            #   → 모달로 만든 전략(`_quick_*`)과 볼밴 분할(`pump_split`)은 전부 탈락.
            #   → 사장님 #1581 BTRUSDT 가 ROI +22% 까지 갔는데 피라미딩 0회.
            # 이 필터는 v220 에서 "소스 확장" 하며 넓혔지만 여전히 화이트리스트였고,
            # 그 뒤에 생긴 전략 종류가 자동으로 빠지는 구조였다 (헌법 121 패턴).
            #
            # 이제 종류를 가리지 않는다. 위 `_pyramid` 자기 자신 제외는 그대로 둔다
            # (피라미딩으로 만든 것에 또 피라미딩하면 무한 증식).
            # 자본 폭주는 MAX_PYRAMID_COUNT(2) + ROI>=5% + 쿨다운이 막는다.
            # ══════════════════════════════════════════════════════════════
            _ = AUTO_ENTRY_TYPES_PYRAMID   # 상수는 로그/참조용으로 남겨둔다

            # cooldown 체크
            if _cooldown_active(si.symbol, si.side):
                skipped += 1
                _bump("cooldown")
                continue

            # pyramid count 체크
            pyr_count = _get_pyramid_count(si.id)          # Fix 196: 전략 단위
            if pyr_count >= MAX_PYRAMID_COUNT:
                skipped += 1
                _bump("max_pyramid_count")
                continue

            # unrealized ROI 판정 (익절중?)
            # 🚨 Fix 160: 여기에는 사유 기록이 없어 「평단/마크 결손」이
            #   집계되지 않았다. 정작 no_avg_or_mark 라벨은 ROI 조건에 붙어 있었다
            #   (Fix 140 이 줄 번호로 삽입했는데 이후 수정으로 줄이 밀린 탓).
            #   = 진단 도구가 거짓 라벨을 보고하고 있었다.
            avg = float(si.avg_entry_price or 0)
            if avg <= 0:
                skipped += 1
                _bump("no_avg_entry")
                continue
            mp = _get_mark_price(si.symbol)
            if mp is None:
                skipped += 1
                _bump("no_mark_price")
                continue

            # 🎯 Fix 134: ROI = 가격변동률 × 레버리지 (손절 -5% 와 동일한 자!)
            if si.side == "LONG":
                price_pct = (mp - avg) / avg * 100
            else:
                price_pct = (avg - mp) / avg * 100
            try:
                _lev = float(si.leverage or 1) or 1.0
            except Exception:
                _lev = 1.0
            roi_pct = price_pct * _lev

            if roi_pct < _trig:
                skipped += 1
                _bump("roi_below_trigger")
                continue

            # peak 갱신 + 지속 판정
            peak = _update_peak_price(si.symbol, si.side, mp)
            if si.side == "LONG":
                retrace_pct = (peak - mp) / peak * 100 if peak > 0 else 100
            else:
                retrace_pct = (mp - peak) / peak * 100 if peak > 0 else 100
            if retrace_pct > PEAK_HOLD_TOLERANCE_PCT:
                # peak 대비 되돌림 크다 = 지속 약함 = skip
                skipped += 1
                _bump("peak_retraced")
                continue

            # 시작가 대비 방향 지속 검증
            start = float(si.start_price or 0)
            if start > 0:
                if si.side == "LONG":
                    sustain_pct = (mp - start) / start * 100
                else:
                    sustain_pct = (start - mp) / start * 100
                if sustain_pct < MIN_SUSTAIN_PCT:
                    skipped += 1
                    _bump("peak_not_sustained")
                    continue

            # 급등/급락 필터 (헌법 64!)
            try:
                from app.integrations.binance.client import BinanceClient
                from app.models.exchange_account import ExchangeAccount
                from app.core.crypto import decrypt_text
                acct = db.execute(
                    select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
                ).scalar_one_or_none()
                if acct:
                    bc = BinanceClient(
                        api_key=decrypt_text(acct.api_key_enc),
                        api_secret=decrypt_text(acct.api_secret_enc),
                        is_testnet=False,
                    )
                    tk = bc.get_24hr_ticker(symbol=si.symbol)
                    if isinstance(tk, dict):
                        ch = float(tk.get("priceChangePercent") or 0)
                        # ═══════════════════════════════════════════════
                        # 🚨 Fix 155 (2026-08-26 사장님 실측): 이 게이트가
                        #   v219 정점 SHORT 의 피라미딩을 100% 차단하고 있었다.
                        #
                        # 사장님 스크린샷: #1493 ZESTUSDT 1단계 10U SHORT +6.23%
                        #   "다음단계 진입이 되어야 하는데"
                        # v219 정점 SHORT 는 「24h >= +15% 급등 종목」만 진입한다.
                        #   → ch > 15 조건에 언제나 걸린다 = 구조적 100% 차단.
                        #
                        # 헌법 64 = 급등에 SHORT 「신규 진입」 금지
                        # 헌법 68 = 그 예외가 사장님 v219 정점 SHORT
                        #   여기는 헌법 68 을 무시하고 64 만 적용하고 있었다.
                        #   (Fix 114 / Fix 141 에 이어 같은 실수 세 번째)
                        #
                        # 더 근본적으로: 이미 수익 중인 포지션에 추가하는 것은
                        # 「반대매매」가 아니다. 방향이 맞다는 게 이미 증명된 상태다
                        # (이 워커는 ROI >= +5% 일 때만 여기 도달한다).
                        # 사장님 지시도 "수익일떄 10 +5% 마틴게일 300 진입" 이다.
                        #
                        # → 24h 극단 필터는 「기록만」 하고 차단하지 않는다.
                        #   안전은 이미 있는 장치가 맡는다:
                        #   ROI>=5% / peak 지속 / cooldown 5분 /
                        #   MAX_PYRAMID_COUNT=2 / 동시보유 상한 / 자체 SL -5%
                        # ═══════════════════════════════════════════════
                        if si.side == "SHORT" and ch > 15.0:
                            logger.info(
                                "[Fix155/헌법68] %s SHORT 24h=%+.1f%% 이지만 "
                                "수익 중(ROI>=%.1f%%) 포지션 추가 = 반대매매 아님 → 허용",
                                si.symbol, ch, _trig,
                            )
                            _bump("chg24_extreme_allowed")
                        if si.side == "LONG" and ch < -15.0:
                            logger.info(
                                "[Fix155/대칭] %s LONG 24h=%+.1f%% 이지만 "
                                "수익 중 포지션 추가 = 반대매매 아님 → 허용",
                                si.symbol, ch,
                            )
                            _bump("chg24_extreme_allowed")
            except Exception:
                pass  # ticker 실패 = 조용히 통과 (Redis mark_price는 이미 확보!)

            # 🌟 v241 Fix 68 사장님 신 verbatim (2026-08-25!):
            # "TP1 실행후 지속적인 수익일때 포지션 초기진입 설정된 금액으로 포지션 추가"
            # = 마틴게일 배수 X! = 초기진입 설정 금액 그대로!
            # = 예: 300 USDT → 추가 300 USDT → 추가 300 USDT (누적 900, 각 300!)
            # 이전 (v220 Fix 17): 부모 자본 × [1.0, 2.0, 6.0] = 마틴게일 배수 (사장님 verbatim 위반!)
            # 지금 (v241 Fix 68): 최초 진입 금액 (template capitals[0]) 그대로!
            _initial_capital = 0.0
            try:
                # Fix 155b: 관계명은 strategy_template (Fix 142 와 같은 버그 3번째 위치)
                _parent_tpl = getattr(si, "strategy_template", None) or getattr(si, "template", None)
                _tpl_config = getattr(_parent_tpl, "config", None) if _parent_tpl else None
                if isinstance(_tpl_config, dict):
                    _caps = _tpl_config.get("capitals") or []
                    if _caps and float(_caps[0] or 0) > 0:
                        _initial_capital = float(_caps[0])  # 🌟 최초 진입 금액!
            except Exception:
                _initial_capital = 0.0
            # fallback: si.total_capital (template 없을 때만!)
            if _initial_capital <= 0:
                _initial_capital = float(si.total_capital or 0)
            # 🚨 Fix 155b: 무로그 continue 제거 (헌법 80).
            #   게다가 Fix 134 이후 추가 자본의 진실은 get_pyramid_capital(사다리) 이므로
            #   최초 진입금을 못 구했다고 진입을 막을 이유가 없다 (fallback 일 뿐).
            if _initial_capital <= 0:
                logger.info(
                    "[Fix155b] %s 최초 진입금 미확보 → 사다리 자본으로 진행", si.symbol,
                )
                _bump("initial_capital_unknown_using_ladder")
            _seq = pyr_count + 1  # 1, 2, 3
            if _seq > MAX_PYRAMID_COUNT:
                skipped += 1
                _bump("seq_over_max")
                continue
            # 🎯 Fix 134 (사장님 지시): 추가 금액은 「사다리 2번째 칸」 = 300
            #   사장님 verbatim: "10 +5% 마틴게일 300 진입 ... 300한번더 포지션 진입"
            #   옛 로직은 capitals[0](= 최초 진입금)을 그대로 추가했는데,
            #   Fix 133 으로 1단계가 10 USDT(탐색 진입)가 되어 그대로 두면 10 만 추가된다.
            try:
                from app.services.sajangnim_capital import get_pyramid_capital
                base_capital = float(get_pyramid_capital(db))
            except Exception as _pe:
                logger.warning("[Fix134] 피라미딩 자본 조회 실패 → 최초 진입금 사용: %s", _pe)
                base_capital = _initial_capital
            logger.info(
                "[SUCCESS_PYRAMID] 🌟 v241 Fix 68 초기금액 재사용 #%d: %s %s = %.0f USDT (배수 X!)",
                _seq, si.symbol, si.side, base_capital,
            )

            # ═══════════════════════════════════════════════════════════════
            # 🚨 Fix 156 (2026-08-26 사장님 실측): 「포지션 추가」를
            #   「새 전략 생성」으로 구현한 것이 설계 오류였다.
            #
            # 사장님 실 로그:
            #   🌟 초기금액 재사용 #1: ZESTUSDT SHORT = 300 USDT
            #   진입 실패: ⚠️ ZESTUSDT SHORT 전략이 이미 진행 중입니다 (#1493).
            #             Binance 는 한 종목/방향에 하나의 통합 포지션만 허용합니다.
            #
            # 자본 계산까지 정상이었는데 발주 직전 중복 방지 가드에 막혔다.
            # 그 가드는 옳다 — Binance 는 한 종목/방향에 통합 포지션 하나뿐이고,
            # 전략을 둘로 만들면 익절/손절이 서로 충돌한다.
            #
            # 사장님 지시는 "300한번더 「포지션 진입」" =
            #   같은 포지션에 물량을 더하는 것이지 별도 전략이 아니다.
            # → add_position_now (=「💉 포지션 추가」 와 같은 경로) 를 쓴다.
            #   · 같은 전략에 MARKET 추가, 평단/qty/total_capital 자동 갱신
            #   · mode="reset" = 신 평단 기준으로 TP1 부터 다시
            #     (사장님 "+15% 익절시작" = 새 평단 기준이어야 맞다)
            #   · 새 StrategyInstance 를 만들지 않으므로 동시보유 상한도 소비하지 않는다
            #     (추가는 「새 포지션」이 아니다)
            # ═══════════════════════════════════════════════════════════════
            try:
                from app.services.execution_service import ExecutionService
                from app.core.crypto import decrypt_text as _dt
                from app.models.exchange_account import ExchangeAccount as _EA
                _acc = db.execute(
                    select(_EA).where(_EA.is_testnet.is_(False)).where(_EA.is_active.is_(True))
                ).scalars().first()
                if _acc is None:
                    skipped += 1
                    _bump("no_mainnet_account")
                    logger.warning("[Fix156] %s mainnet 계정 없음 = 포지션 추가 불가", si.symbol)
                    continue
                _exec = ExecutionService(
                    db,
                    api_key=_dt(_acc.api_key_enc),
                    api_secret=_dt(_acc.api_secret_enc),
                    is_testnet=False,
                )
                # 🚨 Fix 269 (2026-09-01): 추가가 **손절 금액**을 키우지 않게 한다.
                #
                # 실측 (최근 3일, 종료 151건):
                #     추가 없음 97건 건당 **-13.28**
                #     추가 1회  34건 건당 **-42.92**  (3.2배)
                #     추가 2회  15건 건당 **-64.27**  (4.8배)
                #
                # 손절은 ROI 기준인데 추가로 자본이 커지면 같은 ROI 라도 손실
                # **금액**이 그만큼 커진다. #1890 SNXXUSDT 는 1단계 10 에
                # 300 을 두 번 얹어 610 이 됐고 -65.75 를 잃었다 (추가가 없었다면 -0.5).
                # cap_loss=True 면 추가 직후 손절 ROI 를 낮춰 손실 금액을 유지한다.
                _cap_loss = _cap_loss_enabled(db)

                # ══════════════════════════════════════════════════════
                # 💉 Fix 273 (2026-09-01 사장님): 「계속 상승하는 차트와 **보조지표**」
                #
                # 사장님 원 요청은 「차트 **와 보조지표**」였는데 코드에는 **차트만**
                # 있었다(peak 되돌림 2.5% / 시작가 대비 지속 0.5%). RSI·CCI·OBV 는
                # 학습 기록에 None 으로 저장만 하고 판정에 안 썼다 = 요청의 절반.
                #
                # 실측 (추가 시점 88건, 그 전략의 최종 손익):
                #   조건 없음(현행)           88건 승률 20.5%  **-5,832.19** 건당 -66.27
                #   4H AND 15m 둘 다 상승     45건      33.3%  **+1,359.23**     +30.21
                #   4H hist 상승 **아님**     34건       2.9%    -7,049.40    -207.34
                #   과적합 검사: 최근 -871->+234 / 이전 -4,961->+1,125 (양쪽 다 양수)
                #
                # 🚨 진입 게이트(Fix 270)와 조건이 **다르다** — 거기선 `hist>0` 을
                #    더하는 게 최고였지만 여기선 +22.54 -> +0.31 로 무너진다.
                #    용도가 다르면 반드시 그 용도로 다시 잰다.
                # ══════════════════════════════════════════════════════
                if _indicator_gate_enabled(db):
                    try:
                        from app.integrations.binance.client import BinanceClient as _BC273
                        from app.services.trend_4h_gate import check_pyramid_trend as _pt273
                        _bc273 = _BC273(
                            api_key=_dt(_acc.api_key_enc),
                            api_secret=_dt(_acc.api_secret_enc),
                            is_testnet=False,
                        )
                        _ok273, _why273, _det273 = _pt273(_bc273, si.symbol, si.side)
                        if not _ok273:
                            skipped += 1
                            _bump("indicator_not_rising")
                            logger.info(
                                "[Fix273] ⛔ %s %s 추가 차단 — %s | %s",
                                si.symbol, si.side, _why273, _det273,
                            )
                            continue
                        logger.info("[Fix273] ✅ %s %s — %s", si.symbol, si.side, _why273)
                    except Exception as _e273:
                        # fail-open — 판정 하나가 피라미딩을 통째로 멈추면 안 된다 (Fix 252)
                        logger.warning("[Fix273] 지표 판정 오류 (fail-open): %s", _e273)

                # 🚨 Fix 273: mode="reset" -> **"preserve"**
                #   사장님 요청: "300usdt 씩 최대 2번 진입을 하고 **tp1 단계 익절**"
                #   reset 은 추가할 때마다 TP/SL 을 초기화해 TP1 을 처음부터 다시 노리게
                #   만든다. 실제로 #1930 XPLUSDT 에서 max_profit_pct 가 4.04 -> None,
                #   3.08 -> None 로 두 번 지워졌다 = 익절 목표가 매번 리셋.
                #   preserve = 평단·qty·total_capital 은 갱신하되 TP/SL 진행은 유지한다.
                _add_order = _exec.add_position_now(
                    si.id,
                    amount_usdt=Decimal(str(base_capital)),
                    order_type="MARKET",
                    mode="preserve",
                    cap_loss=_cap_loss,
                )
                if not _add_order:
                    skipped += 1
                    _bump("add_position_failed")
                    continue
                new_strategy = si          # 이후 기록은 부모 전략 기준
                logger.info(
                    "[Fix156] ✅ %s %s 포지션 추가 #%d: %.0f USDT MARKET "
                    "(전략 #%d 에 물량 추가, 평단 갱신)",
                    si.symbol, si.side, _seq, base_capital, si.id,
                )

                # StrategySuggestion 기록!
                from app.models.strategy_suggestion import StrategySuggestion
                # 🎓 v218 fix (2026-08-22 사장님!): entry_snapshot 저장 = 학습 데이터!
                _kst_hour = (datetime.now(timezone.utc).hour + 9) % 24
                _pyr_entry_snapshot = {
                    "rsi": None,
                    "cci": None,
                    "obv_slope_pct": None,
                    "regime": "NEUTRAL",
                    "source": "SUCCESS_PYRAMID",
                    "kst_hour": _kst_hour,
                    "parent_strategy_id": si.id,
                    "pyramid_seq": pyr_count + 1,
                    "roi_pct_at_entry": roi_pct,
                    "entry_price": mp,
                    "entered_at": datetime.now(timezone.utc).isoformat(),
                }
                sugg = StrategySuggestion(
                    symbol=si.symbol, side=si.side,
                    suggestion_type="bb4h_auto_entry",
                    strategy_config={
                        "capitals": [base_capital],
                        "symbol": si.symbol, "side": si.side,
                        "pyramid": True,
                        "pyramid_seq": pyr_count + 1,
                        "parent_strategy_id": si.id,
                        "entry_price": mp,
                        "roi_pct_at_entry": roi_pct,
                        "entry_snapshot": _pyr_entry_snapshot,  # 🎓 v218!
                    },
                    confidence_score=Decimal("0.7"),
                    reason=f"SUCCESS_PYRAMID#{pyr_count + 1}: {si.side} ROI+{roi_pct:.2f}% peak-retrace {retrace_pct:.2f}%!",
                    status="EXECUTED",
                    execution_mode="AUTO",
                    executed_at=datetime.now(timezone.utc),
                    executed_strategy_id=new_strategy.id,
                    outcome_status="PENDING",
                )
                db.add(sugg)
                db.commit()

                _increment_pyramid_count(si.id)            # Fix 196: 전략 단위
                _set_cooldown(si.symbol, si.side)
                entered += 1
                remaining -= 1
                results.append({
                    "symbol": si.symbol, "side": si.side,
                    "parent_id": si.id, "new_id": new_strategy.id,
                    "pyramid_seq": pyr_count + 1,
                    "roi_pct": round(roi_pct, 2),
                })
                logger.info(
                    "[SUCCESS_PYRAMID] ✅ %s %s #%d parent=%d new=%d ROI+%.2f%%",
                    si.symbol, si.side, pyr_count + 1, si.id, new_strategy.id, roi_pct,
                )
            except Exception as e:
                logger.warning(
                    "[SUCCESS_PYRAMID] %s %s 진입 실패: %s", si.symbol, si.side, e,
                )
                skipped += 1
                _bump("exception")
                db.rollback()

        _reason_str = " ".join(
            f"{k}={v}" for k, v in sorted(_reasons.items(), key=lambda x: -x[1])
        ) or "-"
        logger.info(
            "[SUCCESS_PYRAMID] 완료: entered=%d skipped=%d | 사유: %s "
            "(트리거 ROI>=%.1f%% 추가자본=사다리2칸 최대%d회)",
            entered, skipped, _reason_str, _trig, MAX_PYRAMID_COUNT,
        )
        return {"entered": entered, "skipped": skipped, "results": results}
    except Exception as e:
        logger.exception("[SUCCESS_PYRAMID] 실행 실패: %s", e)
        return {"error": str(e), "entered": 0}
    finally:
        db.close()

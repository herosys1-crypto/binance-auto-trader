"""🎯 사장님 실 성공 로직 = 자본 관리 헬퍼 (v219 = 2026-08-22!).

사장님 verbatim (초기 사상, 2026-08-22):
"전체자산에 1-2% 진입 후 지속적인 손실이면 다시 처음 진입금액의 2배를
 하락 시작하는 보조지표가 나올때 포지션 진입"

🌟 사장님 신 명확 규정 (2026-08-22 저녁!):
"전체자산에 대해서는 시스템에서 고려 대상이 아니야
 초기 금액과 다음 2배 그리고 다음은 투자금 전체의 2배야"
"300 600 이거네"

🚨 사장님 최종 명확 (2026-08-22 저녁 v219 최종!):
"3단계까지 갈수 있다야 가능하면 가지않는 관리가 필요하다는거야"

= 시스템 = 전체 자산 무관! (사장님 판단!)
= 마틴게일 (3단계까지! but 3단계 = 매우 신중!):
  - 1단계 = 초기 금액 (default 300 USDT!)
  - 2단계 = 이전 진입금액 × 2 (예: 300 × 2 = 600)
  - 3단계 = 투자금 전체 × 2 (예: (300+600) × 2 = 1800) ⚠️ 매우 신중!
  - 4단계+ = 금지! (사장님 상한!)

= MAX_REENTRY_STAGE = 3! (3단계까지!)
= MAX_REENTRY_COUNT = 2! (재진입 최대 2회!)
= 3단계 관리:
  - 가급적 = 2단계에서 익절!
  - 3단계 = 매우 강한 확신 시만!
  - 손실 폭발 위험 = 사장님 자본 보호!
"""
from __future__ import annotations

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# 🎯 Fix 133 (2026-08-26 사장님 지시): 자본 「사다리」 방식으로 전환
#
# 사장님 verbatim:
#   "10 300 600으로 마틴게일 설정"
#   "손실일때 10 -5% 마틴게일 진입대기 조건에 맞으면 300 진입 그리고 -5%면 청산하고
#    다시 마틴게일 600 대기 조건 맞으면 진입"
#   "수익일떄 10 +5% 마틴게일 300 진입 ... 300한번더 포지션 진입 이렇게 두번만 진입하고
#    +15%(설정된 옵션 tp1 25%) 익절시작"
#   "손실일때 -10%정도되면 청산하고 마틴게일 1단계 모니터링 대기하고 조건에 맞으면 1단계 진입"
#
# 왜 배수(base × [1,2,6])로는 안 되는가:
#   10 → 300 은 30배, 300 → 600 은 2배 = 단일 배수열로 표현 불가.
#   → 명시적 사다리(리스트)로 바꾼다. SystemSetting 하나로 운영 중 조정 가능.
#
# 설계 의도 (사장님 사상):
#   1단계 10 USDT = 「탐색(probe)」. 방향이 틀리면 -5% 손절해도 -0.5 USDT 만 잃는다.
#   방향이 맞으면(+5%) 그때 300 으로 키운다 = 이긴 거래에만 큰 자본이 들어간다.
#   (실측 승률 3.7% 상황에서 첫 진입 300 은 매번 -15 USDT 씩 잃는 구조였다)
# ═══════════════════════════════════════════════════════════════════════════
CAPITAL_LADDER_KEY = "sajangnim_capital_ladder"
DEFAULT_CAPITAL_LADDER = [Decimal("10"), Decimal("300"), Decimal("600")]

# 🎯 사장님 1단계 = 사다리 첫 칸 (10 USDT = 탐색 진입!)
DEFAULT_STAGE1_CAPITAL = DEFAULT_CAPITAL_LADDER[0]
FALLBACK_CAPITAL = DEFAULT_CAPITAL_LADDER[0]   # 실패 시!


def get_capital_ladder(db) -> list:
    """🎯 자본 사다리 조회 (단일 진실 = 헌법 6).

    SystemSetting `sajangnim_capital_ladder` = "10,300,600" 형식.
    없거나 손상되면 DEFAULT_CAPITAL_LADDER.
    """
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, CAPITAL_LADDER_KEY)
        if row and row.value:
            vals = []
            for part in str(row.value).replace(" ", "").split(","):
                if not part:
                    continue
                d = Decimal(part)
                if d > 0:
                    vals.append(d)
            if vals:
                return vals
    except Exception as e:
        logger.warning("[sajangnim_capital] 사다리 조회 실패 → default: %s", e)
    return list(DEFAULT_CAPITAL_LADDER)


def get_pyramid_capital(db) -> Decimal:
    """🎯 수익 피라미딩 1회당 자본 = 사다리 2번째 칸 (사장님: 10 → +5% → 300 추가).

    ⚠️ 1단계(10)를 그대로 추가하면 사장님 의도와 다르다.
    사장님 verbatim: "10 +5% 마틴게일 300 진입" = 추가 금액은 300 이다.
    """
    ladder = get_capital_ladder(db)
    return ladder[1] if len(ladder) >= 2 else ladder[0]


def _get_default_capital(db) -> Decimal:
    """🎯 사장님 초기 금액 조회 (default 300 USDT, 운영 중 조정 가능!)"""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, "sajangnim_default_capital")
        if row and row.value:
            val = Decimal(str(row.value))
            if val > 0:
                return val
    except Exception:
        pass
    return DEFAULT_STAGE1_CAPITAL


def compute_stage1_capital(bc, db) -> Decimal:
    """🎯 사장님 1단계 = 초기 금액 (300 USDT default!)

    사장님 규정: 전체 자산 = 시스템 고려 X! 초기 금액만!

    Args:
        bc: BinanceClient (호환성 유지, 미사용!)
        db: SQLAlchemy Session

    Returns:
        Decimal: 초기 진입 자본 USDT
    """
    default_cap = _get_default_capital(db)
    logger.info(
        "[sajangnim_capital] 🎯 1단계 초기 자본: %.2f USDT",
        float(default_cap),
    )
    return default_cap.quantize(Decimal("0.01"))


MAX_REENTRY_STAGE = 3  # 🎯 사장님 최종 (2026-08-22): 3단계까지! (관리 필요!)


def compute_reentry_capital(stage: int, previous_capitals: list[Decimal] | list[float]) -> Decimal | None:
    """🎯 사장님 신 마틴게일 (v219 최종 확정!)

    사장님 최종 규정 (2026-08-22 저녁!):
    "3단계까지 갈수 있다야 가능하면 가지않는 관리가 필요하다는거야"

    - stage=1 (초기!): 이 함수 호출 X = compute_stage1_capital 사용!
    - stage=2: 이전 진입 × 2 (예: 300 × 2 = 600)
    - stage=3: 투자금 전체 × 2 (예: (300+600) × 2 = 1800) ⚠️ 매우 신중!
    - stage>=4: None 반환! (사장님 상한!)

    관리 사상:
      - 가급적 2단계에서 익절!
      - 3단계 = 매우 강한 확신 시만!
      - 손실 폭발 위험 = 자본 보호!

    Args:
        stage: 다음 진입 단계 번호 (2 or 3!)
        previous_capitals: 이전까지 실 진입한 자본 리스트

    Returns:
        Decimal: stage 2/3 시 자본
        None: stage>=4 = STOP!
    """
    if stage <= 1:
        raise ValueError(f"compute_reentry_capital = stage >= 2! (got {stage})")
    if not previous_capitals:
        raise ValueError("compute_reentry_capital = previous_capitals 필수!")

    if stage > MAX_REENTRY_STAGE:
        logger.info(
            "[sajangnim_capital] 🚨 사장님 상한! stage=%d > MAX=%d (3단계까지!)",
            stage, MAX_REENTRY_STAGE,
        )
        return None

    # ═══════════════════════════════════════════════════════════════════
    # 🎯 Fix 133 (2026-08-26 사장님 지시): 배수 → 「사다리」
    #
    # 옛: 2단계 = 이전 × 2 / 3단계 = 투자금 전체 × 2 (= 300 → 600 → 1800)
    # 신: 사장님 verbatim "10 300 600으로 마틴게일 설정"
    #     "10 진입 → -5% → 조건 충족 대기 → 300 진입
    #      300진입후 손실이 -5%면 청산하고 다음단계 600 모니터링 600진입대기"
    #     = 각 단계는 「청산 후 대체」이므로 이전 자본을 누적할 이유가 없다.
    #       사다리에서 그 단계의 금액을 그대로 쓴다.
    # ═══════════════════════════════════════════════════════════════════
    _prev = [Decimal(str(c)) for c in previous_capitals]   # 로그용 (하위 호환)
    _db = None
    try:
        from app.core.database import SessionLocal
        _db = SessionLocal()
        result = get_stage_capital(_db, stage)
    except Exception as _le:
        logger.warning("[sajangnim_capital] 사다리 조회 실패 → 기본 사다리 사용: %s", _le)
        result = (
            DEFAULT_CAPITAL_LADDER[stage - 1]
            if 1 <= stage <= len(DEFAULT_CAPITAL_LADDER) else None
        )
    finally:
        if _db is not None:
            try:
                _db.close()          # 세션 누수 방지 (매 재진입마다 열리는 경로!)
            except Exception:
                pass
    if result is None:
        logger.info(
            "[sajangnim_capital] 사다리 상한 도달: stage=%d (이전=%s)",
            stage, [float(x) for x in _prev],
        )
        return None
    logger.info(
        "[sajangnim_capital] 🎯 %d단계 자본(사다리) = %.2f USDT (이전 %s)",
        stage, float(result), [float(x) for x in _prev],
    )
    return result.quantize(Decimal("0.01"))



# ============================================================
# Fix 31 v230 (2026-08-23): 마틴게일 max_stage 통합!
# 사장님 verbatim: "마틴게일도 지금 3단계인데 조정가능하게, 지금은 2단계로"
# SystemSetting = "sajangnim_max_stage" (range [1, 2, 3], default=2)
# ============================================================

DEFAULT_MAX_STAGE = 2  # 사장님 신 default (2026-08-23!)


def get_max_stage(db) -> int:
    """사장님 max_stage (default 2, range [1, 2, 3])"""
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, "sajangnim_max_stage")
        if row and row.value is not None:
            val = int(str(row.value))
            # 🎯 Fix 133: 상한은 「사다리 길이」 (사장님이 10/300/600 = 3칸을 지정하면 3)
            _ceil = min(MAX_REENTRY_STAGE, max(1, len(get_capital_ladder(db))))
            if val < 1: val = 1
            elif val > _ceil: val = _ceil
            return val
    except Exception as e:
        logger.warning(f"[sajangnim_capital] get_max_stage 실패 (default={DEFAULT_MAX_STAGE}): {e}")
    # 🎯 Fix 133: 설정이 없으면 사다리 길이를 그대로 쓴다
    #   (사장님이 10/300/600 을 지정했는데 설정 부재로 2 에서 잘리면 600 이 영영 안 나온다)
    try:
        return min(MAX_REENTRY_STAGE, max(1, len(get_capital_ladder(db))))
    except Exception:
        return DEFAULT_MAX_STAGE


def get_stage_capital(db, stage: int):
    """단계별 자본 (v219: base × [1, 2, 6])"""
    if stage < 1: return None
    max_stage = get_max_stage(db)
    if stage > max_stage:
        logger.info(f"[sajangnim_capital] max_stage 상한! stage={stage} > max={max_stage}")
        return None
    # 🎯 Fix 133: 배수(base×[1,2,6]) → 명시적 사다리(10/300/600)
    ladder = get_capital_ladder(db)
    if stage > len(ladder):
        logger.info(
            "[sajangnim_capital] 사다리 초과! stage=%d > 사다리 길이 %d %s",
            stage, len(ladder), [str(x) for x in ladder],
        )
        return None
    return ladder[stage - 1].quantize(Decimal("0.01"))


def get_martingale_multipliers(db) -> list:
    """마틴게일 배수 — 사다리에서 1단계 대비 비율로 산출 (하위 호환용).

    Fix 133 이후 자본의 진실은 사다리이며, 이 함수는 화면/로그 표시용이다.
    """
    ladder = get_capital_ladder(db)
    if not ladder:
        return [1.0]
    base = ladder[0]
    if base <= 0:
        return [1.0]
    return [float(c / base) for c in ladder[:get_max_stage(db)]]

"""🎯 Fix 112 (2026-08-26): 최대 「동시 보유」 포지션 상한 (사장님 요구!)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 verbatim (2026-08-26):
  "일 20개로 하지말고 일 20개 최대 20개 수정해줘"
  = 「하루 신규 20건」이 아니라 「동시 보유 최대 20건」!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

왜 필요한가 (사장님 실측):
  UI 「활성 전략 44건」 + 「일 자동 진입 한도 20」
  → 옛 로직 = 「하루 신규 진입 20건」 = KST 자정마다 카운터 리셋!
  → 포지션이 청산되지 않으면 매일 20건씩 계속 누적!
  → 20 → 40 → 60 ... 무한 증가 = 자본 노출 폭증!
  신 로직 = 「지금 열려 있는 포지션 20건」 상한
  → 20건 차 있으면 하나 닫히기 전까지 신규 진입 X = 노출 고정!

설정 키 = 기존 것을 그대로 재사용 (사장님이 UI 에서 이미 쓰던 값!):
  sajangnim_top_short_daily_limit → auto_bb_break_daily_limit → DEFAULT
  ※ 값의 「의미」만 바뀜: 하루 건수 → 동시 보유 건수
  ※ 0 = 완전 OFF (Fix 108 규칙 유지!)

fail-safe 원칙:
  조회 실패 시 = 「막는 쪽」 (진입 차단!)
  이유: 자본 노출 상한은 안전장치이므로 불확실하면 보수적으로!
  (다른 게이트들의 fail-open 과 반대 = 의도된 비대칭!)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MAX_CONCURRENT_DEFAULT = 20        # 사장님 default (설정 없을 때만!)

# 🚨 Fix 191 (2026-08-28): sajangnim_max_concurrent_positions 를 **퇴역**시켰다.
#
# 이 키는 「최우선」으로 읽히면서 **쓰는 코드가 어디에도 없었다.**
# 실측(2026-08-28)에서도 행 자체가 존재하지 않았다 = 한 번도 쓰인 적 없는 키가
# UI 값을 언제든 덮을 수 있는 자리에 앉아 있었다는 뜻이다.
# 화면은 2순위 키를 보여주는데 워커는 1순위를 보므로, 그 행이 어떤 경로로든
# 한 번 생기면 사장님 수정이 **영구히 조용히 무시된다.**
# 실제로 이번 조사에서 내가 이 키를 원인으로 오진했고, 고친다며 넣은 코드가
# 오히려 그 행을 생성하고 있었다 (Fix 188 → 철회).
# → 상한 키를 하나로 못 박는다 (헌법 102: 모순 가능한 설정 2개 금지).
RETIRED_LIMIT_KEY = "sajangnim_max_concurrent_positions"
_retired_warned = False            # 퇴역 키 경고는 프로세스당 1회

LIMIT_KEYS = (
    "sajangnim_top_short_daily_limit",      # UI 「최대 동시 포지션」이 읽고 쓰는 단 하나의 키
    "auto_bb_break_daily_limit",            # 옛 카드 (UI 「BB 이탈 자동 진입」)
)


def get_max_concurrent(db) -> tuple[int, str]:
    """동시 보유 상한 조회. 0 = 완전 OFF (Fix 108 규칙!).

    Returns: (limit, source_key)
    """
    from app.models.system_setting import SystemSetting

    # Fix 191: 퇴역 키가 DB 에 남아 있으면 「무시되고 있다」는 사실을 반드시 알린다.
    #   조용히 무시하면 이 키를 설정한 사람은 적용된 줄 안다 (헌법 80).
    #   더는 읽지 않으므로 동작에는 영향이 없다. 프로세스당 1회만 확인 (hot path).
    global _retired_warned
    if not _retired_warned:
        _retired_warned = True
        try:
            if db.get(SystemSetting, RETIRED_LIMIT_KEY) is not None:
                logger.warning(
                    "[Fix191] 설정 '%s' 이 DB 에 남아 있지만 **더는 사용되지 않습니다**. "
                    "동시 상한은 '%s' 로만 결정됩니다. 이 행은 지우셔도 됩니다.",
                    RETIRED_LIMIT_KEY, LIMIT_KEYS[0],
                )
        except Exception:
            pass          # 알림 실패가 진입을 막아서는 안 된다

    for key in LIMIT_KEYS:
        try:
            row = db.get(SystemSetting, key)
        except Exception as e:
            # 🚨 Fix 112b: DB 조회 실패를 삼키고 다음 키로 넘어가면
            #   결국 default 20 이 나온다 = fail-OPEN! (사장님이 0 으로 꺼놔도 20!)
            #   → 상한 함수는 fail-SAFE 여야 하므로 예외를 올려서 차단시킨다.
            raise RuntimeError(f"SystemSetting '{key}' 조회 실패: {e}") from e

        if row is None or row.value is None or str(row.value).strip() == "":
            continue                                  # 값 없음 = 다음 키로

        raw = str(row.value).strip()
        try:
            v = int(raw)
        except (TypeError, ValueError) as e:
            # 🚨 값이 「있는데 숫자가 아님」 = 설정 손상! 이것도 삼키면 20 으로 둔갑!
            raise RuntimeError(f"SystemSetting '{key}' 값 파싱 실패: {raw!r}") from e

        return (v if v > 0 else 0), key               # 0 도 그대로 존중! (헌법 83)

    return MAX_CONCURRENT_DEFAULT, "default"


def count_active_positions(db, side: str | None = None) -> int:
    """지금 열려 있는 전략 인스턴스 수 (ACTIVE_LIKE).

    side 를 주면 해당 방향만, 없으면 전체 (SHORT+LONG 합산).
    사장님 사상: 자본 노출은 방향 무관 = 기본은 전체 합산!
    """
    from sqlalchemy import select, func
    from app.core.strategy_status import ACTIVE_LIKE
    from app.models.strategy_instance import StrategyInstance

    q = select(func.count(StrategyInstance.id)).where(
        StrategyInstance.status.in_(list(ACTIVE_LIKE)),
        StrategyInstance.is_archived.is_(False),
    )
    if side:
        q = q.where(StrategyInstance.side == side)
    return int(db.execute(q).scalar() or 0)


def check_position_slot(db, tag: str = "") -> tuple[bool, str, int, int]:
    """🎯 신규 진입 가능한가? (모든 진입 워커 공통 게이트!)

    Returns: (allowed, reason, active, limit)

    fail-safe = 조회 실패 시 차단! (자본 노출 상한이므로 보수적으로!)
    """
    try:
        limit, src = get_max_concurrent(db)
        if limit <= 0:
            return False, f"동시보유 상한=0 = 자동 진입 완전 OFF (src={src})", 0, 0

        active = count_active_positions(db)
        if active >= limit:
            return (
                False,
                f"동시보유 상한 도달 {active}/{limit} (src={src}) "
                f"= 포지션 하나 청산 전까지 신규 진입 X!",
                active, limit,
            )
        return True, f"슬롯 여유 {active}/{limit} (src={src})", active, limit

    except Exception as e:
        # 🚨 fail-SAFE (다른 게이트와 반대!): 자본 노출 상한은 불확실하면 막는다!
        logger.warning(
            "[Fix112/%s] 동시보유 상한 조회 실패 = 안전상 진입 차단! : %s", tag or "slot", e,
        )
        return False, f"상한 조회 실패 = 안전 차단 ({e})", -1, -1

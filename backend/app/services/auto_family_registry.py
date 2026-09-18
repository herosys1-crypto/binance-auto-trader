"""🗓 자동매매 전략 가족 레지스트리 + 가족별 하루 최대 진입 (2026-09-15 사장님).

사장님 verbatim (2026-09-15):
  "1 2 3 모두 분석해서 적당한 포지션 진입방법을 정해줘 그리고 포지션에 들어가면 구분할수있게 확실하게 만들어줘
   10 100 200 이렇게 진입하는 전략을 고려해서 만들어주고 모두 일최대 1개로 설정해주고
   각각 일 최대 제한수를 정할수 있게 만들어줘 언제든지 자동매매 할수 있게 준비해줘"

한 곳에서 판정한다 — 새 진입을 만드는 워커가 13개라 워커마다 넣으면 빠진다. 적용 지점 2곳:
  ① StrategyService.create_strategy_instance (Fix 371 생성 게이트 바로 뒤) — 한도가 찼으면 인스턴스를 만들지 않는다
     (같은 가족 동시 생성은 Postgres advisory xact lock 으로 한 번에 하나 — 못 잡으면 이번엔 막고 다음 사이클)
  ② ExecutionService.start_stage1 (Fix 371 주문 게이트 바로 뒤) — 실제 1차 주문 직전, 자기 자신을 빼고 다시 센다
사람 판정 = **생성 출처 entry_origin == manual_modal 하나** (모달 · 빠른 진입 · 터미널 계획 모두 POST /strategies 로 이 값을 찍는다).
  사람이 만든 템플릿(_quick_ · DYNAMIC_)을 자동 워커(사다리 재시작 · 자동 재진입)가 다시 열면 **자동**으로 센다 (반박 검증 9/15 #3).
  alembic 0040(entry_origin) 이전 행은 값이 없으므로 옛 표식(_quick_ 템플릿 · DYNAMIC_ 종류)을 사람으로 믿는다 (ORIGIN_CUTOFF 이전 생성분만).
사람이 누른 「전략 시작」 버튼(origin=manual)은 ② 에서 막지 않는다.

설정 (system_settings, 재시작 불필요):
  auto_daily_limit_enabled   "1"(기본) | "0" = 이 한도 끔
  daily_max_<가족키>          기본 "1" (사장님 「모두 일최대 1개」) · "0" = 그 가족 새 진입 없음 · 손상 = 기본 1
하루 = KST 자정. 센다 = 오늘 만든 그 가족 인스턴스 중
  · 보관 안 된 것: 1단계 이상 진입 · 진행 중(ACTIVE_LIKE) · 대기(WAITING — 곧 진입할 행, 동시 생성 경쟁 방지)
  · 보관된 것: 1단계 이상 진입했던 것만 (사람이 청산 뒤 「삭제(보관)」해도 그날 건수가 줄지 않게 — 반박 검증 #6)
워커 자체 한도(sajangnim_top_short_daily_limit 등)는 그대로 둔다 — 실효 한도 = 둘 중 작은 값.
"""
from __future__ import annotations

import logging
import zlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

FIX = "DAILY"
KST = timezone(timedelta(hours=9))
ENABLED_KEY = "auto_daily_limit_enabled"
DEFAULT_DAILY_MAX = 1                    # 사장님 「모두 일최대 1개」
BLOCK_TAG = "가족별 일 최대 진입"
MANUAL_ORIGIN = "manual_modal"
ORIGIN_CUTOFF = datetime(2026, 9, 15, 0, 0, tzinfo=timezone.utc)   # 이 시각 이전 생성 + entry_origin 없음 = 옛 표식으로 판정 (Claude가 정함)
COUNT_FAILED = 10**6


@dataclass(frozen=True)
class AutoFamily:
    key: str        # daily_max_<key>
    label: str      # 사람이 읽는 이름 (화면 배지 · 로그)
    short: str      # 배지용 짧은 이름


# auto_bb_break 계열은 여러 워커가 같은 접두사를 쓴다 (_create_auto_bb_strategy → f"auto_bb_break{suffix}") —
# 종류·템플릿 이름의 **꼬리**로 가른다 (반박 검증 9/15 #1). 위에서부터 먼저 맞는 것.
_BB_BREAK_BY_MARK: tuple[tuple[str, AutoFamily], ...] = (
    ("SAJANGNIM_TOP", AutoFamily("top_short", "급등 정점 SHORT", "정점SHORT")),
    ("SAJANGNIM_BOTTOM", AutoFamily("bottom_long", "저점 LONG", "저점LONG")),
    ("UNIFIED_15M", AutoFamily("unified_15m", "통합 15분", "통합15m")),
    ("PENDING_HC_FAST", AutoFamily("pending_hc", "HC 속행", "HC속행")),
    ("_lastchance", AutoFamily("rt_lastchance", "라스트 찬스 재진입", "라스트찬스")),
    ("_success", AutoFamily("success_reentry", "익절 뒤 재진입", "익절재진입")),
    ("_reentry", AutoFamily("bb_reentry", "손절 뒤 재진입", "재진입")),
    ("OBV_HOLD", AutoFamily("obv_hold", "OBV 보류 진입", "OBV보류")),
)
BB_BREAK = AutoFamily("bb_break", "BB 이탈 자동", "BB이탈")

# 그 밖의 strategy_type 접두사 → 가족.
_BY_PREFIX: tuple[tuple[str, AutoFamily], ...] = (
    ("realtime_reentry", AutoFamily("rt_reentry", "실시간 재진입", "실시간재진입")),
    ("pump_split", AutoFamily("pump_split", "볼밴 분할", "볼밴분할")),
    ("bb_swing", AutoFamily("bb_swing", "볼밴 스윙", "볼밴스윙")),
    ("bb_mid_line", AutoFamily("bb_mid_line", "볼밴 중단선", "중단선")),
    ("surge_peak_ladder", AutoFamily("surge_ladder", "급등 사다리", "급등사다리")),
    ("sajangnim_top", AutoFamily("sajangnim_top", "정점 SHORT v219", "정점v219")),
    ("chart_pattern", AutoFamily("chart_pattern", "차트 패턴", "차트패턴")),
    ("fujimoto", AutoFamily("fujimoto", "후지모토 3역 호전", "후지모토")),
    ("mach7", AutoFamily("mach7", "마하세븐 속임수 돌파", "마하세븐")),
)
MANAGED = AutoFamily("managed_reentry", "심볼 관리 재진입", "관리재진입")
HUMAN_TEMPLATE_AUTO = AutoFamily("human_template_auto", "사람 전략 자동 재시작·재진입", "자동재시작")
OTHER = AutoFamily("auto_other", "기타 자동", "기타자동")


def _rule_family(strategy_type: str) -> AutoFamily | None:
    """규칙 가족(rf_*) — 이름은 rule_families 레지스트리가 단일 진실."""
    try:
        from app.services.rule_families import FAMILIES
        for f in FAMILIES:
            if f.stype == strategy_type:
                return AutoFamily(f.key, f.label, f.short or f.label)
    except Exception as e:  # noqa: BLE001
        logger.debug("[%s] 규칙 가족 조회 실패: %s", FIX, e)
    return None


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def is_manual(*, strategy_type: str | None, template_name: str | None, entry_origin: str | None,
              created_at: datetime | None = None) -> bool:
    """사람이 만든 전략인가. 생성 출처가 단일 진실 — 출처 기록 이전(ORIGIN_CUTOFF) 행만 옛 표식을 믿는다."""
    if str(entry_origin or "") == MANUAL_ORIGIN:
        return True
    if entry_origin:
        return False
    created = _aware(created_at)
    if created is None or created >= ORIGIN_CUTOFF:
        return False                                  # 지금 만드는 행·새 행에 출처가 없으면 = 워커가 만든 것
    name = str(template_name or "")
    if name.startswith("_quick_m"):
        return False
    st = str(strategy_type or "")
    return name.startswith("_quick_") or st.startswith("DYNAMIC_") or st.startswith("terminal_manual") or st == "manual"


def family_for(*, strategy_type: str | None, template_name: str | None, entry_origin: str | None,
               created_at: datetime | None = None) -> AutoFamily | None:
    """자동 전략의 가족. 사람이 만든 것 = None."""
    if is_manual(strategy_type=strategy_type, template_name=template_name, entry_origin=entry_origin, created_at=created_at):
        return None
    name = str(template_name or "")
    if name.startswith("_quick_m"):
        return MANAGED
    st = str(strategy_type or "")
    if st.startswith("rf_"):
        return _rule_family(st) or AutoFamily(st, f"규칙 가족 {st[3:]}", st[3:])
    if st.startswith("auto_bb_break"):
        hay = f"{st}|{name}"
        for mark, fam in _BB_BREAK_BY_MARK:
            if mark in hay:
                return fam
        return BB_BREAK
    for prefix, fam in _BY_PREFIX:
        if st.startswith(prefix):
            return fam
    if st.startswith("DYNAMIC_") or name.startswith("_quick_"):
        return HUMAN_TEMPLATE_AUTO
    if st:                                         # 분류 안 되는 자동 전략은 종류마다 따로 센다 (한 칸에 몰아 서로 막지 않게 — 반박 검증 9/15 M2)
        safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in st)[:40]
        return AutoFamily(f"other_{safe}", f"기타 자동 ({st})", "기타자동")
    return OTHER


def family_of_template(tpl: Any) -> AutoFamily | None:
    """워커가 **자동으로** 이 템플릿으로 전략을 만들 때 붙을 가족 (Fix 376 — 워커의 사전 확인용, 생성 출처 없음)."""
    return family_for(strategy_type=getattr(tpl, "strategy_type", None), template_name=getattr(tpl, "name", None),
                      entry_origin=None)


def _template_of(si: Any):
    tpl = getattr(si, "strategy_template", None)
    return tpl if tpl is not None else getattr(si, "template", None)


def family_of_instance(si: Any) -> AutoFamily | None:
    tpl = _template_of(si)
    return family_for(strategy_type=getattr(tpl, "strategy_type", None), template_name=getattr(tpl, "name", None),
                      entry_origin=getattr(si, "entry_origin", None), created_at=getattr(si, "created_at", None))


def _setting(db, key: str) -> str | None:
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        return None if row is None or row.value is None or not str(row.value).strip() else str(row.value).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s 조회 실패: %s", FIX, key, e)
        return None


def enabled(db) -> bool:
    v = _setting(db, ENABLED_KEY)
    return v is None or v.lower() not in ("0", "off", "false", "no")


def daily_max(db, key: str) -> int:
    v = _setting(db, f"daily_max_{key}")
    if v is None:
        return DEFAULT_DAILY_MAX
    try:
        n = int(float(v))
        return n if 0 <= n <= 1000 else DEFAULT_DAILY_MAX
    except (TypeError, ValueError):
        return DEFAULT_DAILY_MAX


def kst_day_start(now: datetime | None = None) -> datetime:
    k = (now or datetime.now(timezone.utc)).astimezone(KST)
    return datetime(k.year, k.month, k.day, tzinfo=KST).astimezone(timezone.utc)


def counts_toward_today(*, stage: int | None, status: str | None, archived: bool) -> bool:
    from app.core.strategy_status import ACTIVE_LIKE
    entered = (stage or 0) >= 1
    if archived:
        return entered
    return entered or status in ACTIVE_LIKE or status == "WAITING"


def count_today(db, key: str, *, exclude_id: int | None = None, now: datetime | None = None) -> int:
    """오늘(KST) 그 가족의 진입 수. 조회 실패 = COUNT_FAILED (fail-closed — 자본이 나가는 판정)."""
    try:
        from sqlalchemy import select
        from app.models.strategy_instance import StrategyInstance as SI
        from app.models.strategy_template import StrategyTemplate as T
        rows = db.execute(
            select(SI.id, SI.entry_origin, SI.current_stage, SI.status, SI.is_archived, SI.created_at, T.strategy_type, T.name)
            .join(T, T.id == SI.strategy_template_id, isouter=True)
            .where(SI.created_at >= kst_day_start(now))
        ).all()
        n = 0
        for sid, origin, stage, status, archived, created, stype, tname in rows:
            if exclude_id is not None and sid == exclude_id:
                continue
            if not counts_toward_today(stage=stage, status=status, archived=bool(archived)):
                continue
            fam = family_for(strategy_type=stype, template_name=tname, entry_origin=origin, created_at=created)
            if fam is not None and fam.key == key:
                n += 1
        return n
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s 오늘 진입 수 조회 실패 = 막음: %s", FIX, key, e)
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return COUNT_FAILED


def _try_family_lock(db, key: str) -> bool:
    """같은 가족 동시 생성 방지 — 트랜잭션 끝까지 유지되는 Postgres advisory lock. Postgres 가 아니면(테스트) True."""
    try:
        from sqlalchemy import text
        bind = db.get_bind()
        if getattr(getattr(bind, "dialect", None), "name", "") != "postgresql":
            return True
        return bool(db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"),
                               {"k": zlib.crc32(f"daily_family:{key}".encode()) & 0x7FFFFFFF}).scalar())
    except Exception as e:  # noqa: BLE001
        logger.debug("[%s] %s advisory lock 불가 → 잠금 없이 진행: %s", FIX, key, e)
        return True


def check(db, *, strategy_type: str | None, template_name: str | None, entry_origin: str | None,
          exclude_id: int | None = None, created_at: datetime | None = None, where: str = "생성",
          lock: bool = False) -> AutoFamily | None:
    """한도가 찼으면 ValueError. 통과하면 가족(사람 전략 = None)을 돌려준다."""
    fam = family_for(strategy_type=strategy_type, template_name=template_name, entry_origin=entry_origin, created_at=created_at)
    if fam is None or not enabled(db):
        return fam
    cap = daily_max(db, fam.key)
    if lock and not _try_family_lock(db, fam.key):
        raise ValueError(f"⛔ [{BLOCK_TAG}] {fam.label} 같은 가족 전략을 다른 작업이 만드는 중 — 이번 {where}은 건너뜀 (다음 사이클)")
    used = count_today(db, fam.key, exclude_id=exclude_id)
    if used >= cap:
        why = "오늘 건수 조회 실패 = 안전하게 막음" if used >= COUNT_FAILED else f"오늘(KST) {used}/{cap}건"
        logger.info("[%s] ⛔ %s %s 차단 — %s (daily_max_%s)", FIX, fam.label, where, why, fam.key)
        raise ValueError(f"⛔ [{BLOCK_TAG}] {fam.label} {why} — {where} 차단 (조정: system_settings daily_max_{fam.key})")
    return fam


def check_instance(db, si: Any, *, where: str = "1차 주문") -> AutoFamily | None:
    tpl = _template_of(si)
    return check(db, strategy_type=getattr(tpl, "strategy_type", None), template_name=getattr(tpl, "name", None),
                 entry_origin=getattr(si, "entry_origin", None), exclude_id=getattr(si, "id", None),
                 created_at=getattr(si, "created_at", None), where=where)


def is_limit_error(exc: BaseException | str) -> bool:
    """하루 최대 · 🎯 Fix 376 차트 자리 게이트 · 📊 Fix 380 세력 CCI 게이트 — 모두 「영구 실패」가 아니라 「다음에 다시」다."""
    s = str(exc)
    return BLOCK_TAG in s or "차트 자리 게이트" in s or "세력 CCI 게이트" in s


def known_families() -> list[AutoFamily]:
    """검사기·화면용 — 규칙 가족 포함 전체 목록."""
    out = [f for _m, f in _BB_BREAK_BY_MARK] + [BB_BREAK] + [f for _p, f in _BY_PREFIX] + [MANAGED, HUMAN_TEMPLATE_AUTO]
    try:
        from app.services.rule_families import FAMILIES
        out += [family_for(strategy_type=f.stype, template_name=None, entry_origin=None) for f in FAMILIES]
    except Exception:  # noqa: BLE001
        pass
    return out + [OTHER]

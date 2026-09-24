"""⛔ Fix 384 (2026-09-19 사장님) — 자동매매 가족별 손실 차단기.

사장님: "자동 합계(−1,858) 이게 문제야 … 자동은 적게벌어도 벌어야 하는데 그래야 자동으로 지속적으로 하지
        아니면 내가 왜 시스템을 개발하나? 그리고 시스템 개발 때문에 관리를 실시간으로 하지 못해서 …"
        → 선택 「차단기만 개발」

근거 (45일 실거래 861건 · 자동 합 −1,858):
  · 저점 LONG 이 3주 연속 졌다(−52 → −577 → −758) — 아무도 끄지 않았다. 이 한 가족이 −1,387.
  · 모의(그 시점까지 끝난 거래만 봄): 「가족 최근 7일 실현 합 < −30 → 사람이 풀 때까지 막음」 = 자동 합 −672
    (저점 LONG +1,297 · 심볼 관리 재진입 +194 를 막았고, 급등 정점 SHORT 의 좋은 주 −429 를 같이 잘랐다).
  → 흑자를 만드는 장치가 아니라 **사람이 안 볼 때 한 가족이 몇 주씩 잃는 것을 막는 안전망**이다.

동작 (자동 전략이 만들어지는 유일한 곳 = `StrategyService.create_strategy_instance`, 세력 CCI 게이트 바로 뒤):
  1. 사람 전략(family_for = None)은 보지 않는다. 자동매매 전면 중단 중이면 보지 않는다(어차피 만들지 않는다).
  2. `<가족>_loss_breaker` = "1" 이면 막는다 (ValueError 「손실 차단기」 = is_limit_error → 「다음에 다시」).
  3. 아니면 그 가족의 최근 N일(= 마지막 해제 시각 이후만) **끝난** 전략 실현 합을 본다 → −X 미만이면
     `<가족>_loss_breaker` = "1" 로 **따로 저장**(생성 트랜잭션이 롤백돼도 남게) + 알림 + 막는다.
  4. 사장님이 관제실에서 「허용」(0)으로 바꾸면 풀린다. 그 시각 이전 손실은 다시 세지 않는다(행의 updated_at).
설정 (모두 「Claude가 정함」): family_loss_breaker_enabled 1 · family_loss_breaker_days 7 · family_loss_breaker_usdt 30.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

FIX = "Fix384"
BLOCK_TAG = "손실 차단기"
S_ENABLED = "family_loss_breaker_enabled"
S_DAYS = "family_loss_breaker_days"
S_USDT = "family_loss_breaker_usdt"
DEFAULT_DAYS = 7
DEFAULT_USDT = 30.0
FORCE_OFF: bool | None = None            # 테스트 전용 (tests/conftest.py 가 True — DB 조회 금지)


def key_for(fam_key: str) -> str:
    return f"{fam_key}_loss_breaker"


def _row(db: Any, key: str):
    try:
        from app.models.system_setting import SystemSetting
        return db.get(SystemSetting, key)
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s 조회 실패: %s", FIX, key, e)
        return None


def _num(db: Any, key: str, default: float, lo: float, hi: float) -> float:
    r = _row(db, key)
    try:
        v = float(str(r.value).strip()) if r is not None and str(r.value).strip() else default
    except (TypeError, ValueError):
        return default
    return v if lo <= v <= hi else default


def enabled(db: Any) -> bool:
    if FORCE_OFF:
        return False
    r = _row(db, S_ENABLED)
    return r is None or str(r.value).strip().lower() not in ("0", "off", "false", "no")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _closed_rows(db: Any, since: datetime) -> list:
    """since 이후 **끝난** 전략 행. 🚨 종료 판정은 status(TERMINAL) 로 한다 —
    `stopped_at` 만 보면 **COMPLETED(익절 완료) 101건이 그 값이 비어 있어**(2026-09-20 운영 실측, 실현 +3,097)
    이긴 거래가 통째로 빠지고 손실만 세어 차단기가 잘못 발동한다. 시각은 stopped_at 없으면 updated_at."""
    from sqlalchemy import func, select
    from app.core.strategy_status import TERMINAL_STATUSES
    from app.models.strategy_instance import StrategyInstance as SI
    from app.models.strategy_template import StrategyTemplate as ST
    closed_at = func.coalesce(SI.stopped_at, SI.updated_at)
    # 🚨 Fix 400: 자본 두 개를 같이 읽는다 — 사람이 키운 몫을 가려내기 위해서다 (아래 family_share 참조).
    return db.execute(select(SI.realized_pnl, SI.created_at, closed_at.label("closed_at"), SI.entry_origin,
                             ST.strategy_type, ST.name,
                             SI.total_capital.label("actual_capital"),
                             ST.total_capital.label("designed_capital"),
                             SI.id.label("sid"), SI.symbol.label("symbol"))
                      .join(ST, ST.id == SI.strategy_template_id)
                      .where(SI.status.in_(tuple(TERMINAL_STATUSES)), closed_at >= since)).all()


def _cap_pair(row: Any) -> tuple[Any, Any]:
    """(설계 자본, 실제 자본) — 칸이 없는 행(옛 호출·테스트 가짜)이면 (None, None)."""
    try:
        return row.designed_capital, row.actual_capital
    except (AttributeError, IndexError, KeyError, TypeError):
        return None, None


def family_share(designed: Any, actual: Any) -> float:
    """🚨 Fix 400 (2026-09-25): 그 거래에서 **자동 가족이 설계한 자본의 비중**.

    사장님 실측 #4548 PLAYUSDT (S4, 설계 10 USDT):
      09-21 S4 자동 진입 692개(증거금 10) → 09-23 **사장님이 「💉 포지션 추가」로 6,357개(증거금 100)**
      → 09-24 손절. ROI −26% 로 **정상 작동**했는데 절대 손실은 −28.74 였다 (11배 커진 물량).
    그 −28.74 가 S4 가족의 손실 차단기(최근 7일 −30)를 90% 소진시켰다 — 즉 **사람의 결정이**
    **자동 가족을 멈추게 한다.** 차단기의 목적은 「그 가족의 자동 판정이 지고 있는지」이므로,
    사람이 키운 몫은 비율로 덜어내고 센다 (원시 합계는 따로 보고한다 — 감추지 않는다).

    share = min(1, 설계 자본 / 실제 자본). 값이 없거나 이상하면 1 (덜어내지 않는다 = 보수적).
    """
    try:
        d = float(designed or 0)
        a = float(actual or 0)
    except (TypeError, ValueError):
        return 1.0
    if d <= 0 or a <= 0 or a <= d:
        return 1.0
    return d / a


def family_realized(db: Any, fam_key: str, since: datetime) -> tuple[float, int]:
    """그 가족의 since 이후 끝난 전략 실현 손익 합 · 건수. 사람 전략 제외.

    🚨 Fix 400: 합계는 **가족 몫**(사람이 키운 비율만큼 덜어낸 값)이다. 원시 합계가 필요하면
    `family_realized_detail` 을 쓴다 (화면·보고는 둘 다 보여 준다).
    """
    d = family_realized_detail(db, fam_key, since)
    return d["pnl"], d["n"]


def family_realized_detail(db: Any, fam_key: str, since: datetime) -> dict[str, Any]:
    """{"pnl"(가족 몫), "pnl_raw"(원시), "n", "human_pnl"(사람이 키운 몫), "human_n"(개입 건수)}."""
    from app.services import auto_family_registry as AF
    counted, raw, n, human_n = 0.0, 0.0, 0, 0
    for row in _closed_rows(db, since):
        rp, ca, _sa, origin, stype, name = row[0], row[1], row[2], row[3], row[4], row[5]
        fam = AF.family_for(strategy_type=stype, template_name=name, entry_origin=origin, created_at=ca)
        if fam is None or fam.key != fam_key:
            continue
        pnl = float(rp or 0)
        share = family_share(*_cap_pair(row))
        counted += pnl * share
        raw += pnl
        n += 1
        if share < 1.0:
            human_n += 1
    return {"pnl": round(counted, 2), "pnl_raw": round(raw, 2), "n": n,
            "human_pnl": round(raw - counted, 2), "human_n": human_n}


def state(db: Any, fam_key: str, *, now: datetime | None = None) -> dict[str, Any]:
    """화면·판정 공용. {"tripped", "pnl", "n", "since", "limit", "days"}."""
    now = now or datetime.now(timezone.utc)
    days = int(_num(db, S_DAYS, DEFAULT_DAYS, 1, 30))
    limit = _num(db, S_USDT, DEFAULT_USDT, 1, 100000)
    row = _row(db, key_for(fam_key))
    tripped = row is not None and str(row.value).strip() == "1"
    since = now - timedelta(days=days)
    reset_at = _aware(getattr(row, "updated_at", None)) if row is not None and not tripped else None
    if reset_at is not None and reset_at > since:
        since = reset_at                      # 사장님이 푼 뒤의 손익만 센다
    d = family_realized_detail(db, fam_key, since)
    # 🚨 Fix 400: 판정은 「가족 몫」(pnl), 보고는 원시(pnl_raw)·사람 몫(human_pnl)까지 같이 준다.
    return {"tripped": tripped, "pnl": d["pnl"], "n": d["n"], "since": since.isoformat(),
            "limit": limit, "days": days,
            "pnl_raw": d["pnl_raw"], "human_pnl": d["human_pnl"], "human_n": d["human_n"]}


def all_states(db: Any, fam_keys: list[str], *, now: datetime | None = None) -> dict[str, dict[str, Any]]:
    """관제실 화면용 — 모든 가족을 **쿼리 한 번**으로. 가족마다 해제 시각이 다르므로 최대 창으로 읽고 가족별로 자른다."""
    from app.services import auto_family_registry as AF
    now = now or datetime.now(timezone.utc)
    days = int(_num(db, S_DAYS, DEFAULT_DAYS, 1, 30))
    limit = _num(db, S_USDT, DEFAULT_USDT, 1, 100000)
    base = now - timedelta(days=days)
    out: dict[str, dict[str, Any]] = {}
    for k in fam_keys:
        row = _row(db, key_for(k))
        tripped = row is not None and str(row.value).strip() == "1"
        reset_at = _aware(getattr(row, "updated_at", None)) if row is not None and not tripped else None
        since = reset_at if reset_at is not None and reset_at > base else base
        out[k] = {"tripped": tripped, "pnl": 0.0, "n": 0, "since": since, "limit": limit, "days": days,
                  "pnl_raw": 0.0, "human_pnl": 0.0, "human_n": 0}
    rows = _closed_rows(db, base)
    for row in rows:
        rp, ca, sa, origin, stype, name = row[0], row[1], row[2], row[3], row[4], row[5]
        fam = AF.family_for(strategy_type=stype, template_name=name, entry_origin=origin, created_at=ca)
        if fam is None or fam.key not in out or _aware(sa) < out[fam.key]["since"]:
            continue
        pnl = float(rp or 0)
        share = family_share(*_cap_pair(row))            # 🚨 Fix 400
        out[fam.key]["pnl"] += pnl * share
        out[fam.key]["pnl_raw"] += pnl
        out[fam.key]["human_pnl"] += pnl - pnl * share
        out[fam.key]["n"] += 1
        if share < 1.0:
            out[fam.key]["human_n"] += 1
    for v in out.values():
        v["pnl"] = round(v["pnl"], 2)
        v["pnl_raw"] = round(v["pnl_raw"], 2)
        v["human_pnl"] = round(v["human_pnl"], 2)
        v["since"] = v["since"].isoformat()
    return out


def _trip(fam_key: str, label: str, st: dict[str, Any]) -> None:
    """차단 상태를 **별도 세션**으로 저장 + 알림 (생성 트랜잭션이 롤백돼도 남는다)."""
    from app.core.database import SessionLocal
    from app.services.system_settings_service import SystemSettingsService
    s = SessionLocal()
    try:
        SystemSettingsService(s).set(
            key_for(fam_key), "1",
            description=f"⛔ {FIX} 손실 차단 {datetime.now(timezone.utc):%m-%d %H:%M} UTC — 최근 {st['days']}일 실현 "
                        f"{st['pnl']:+.1f} USDT ({st['n']}건) < −{st['limit']:g}. 관제실에서 「허용」으로 풀 때까지 막음")
        s.commit()
        try:
            from app.services.notification_service import NotificationService
            NotificationService(s).send_system_alert(
                title=f"⛔ 자동매매 손실 차단 — {label}",
                body=(f"{label} 가족의 최근 {st['days']}일 실현 손익 {st['pnl']:+.1f} USDT ({st['n']}건)가 "
                      f"−{st['limit']:g} 밑이라 새 전략을 막았습니다. 다시 허용하려면 관제실에서 「손실 차단」을 「허용」으로."
                      # 🚨 Fix 400: 사람이 키운 몫은 판정에서 뺐다는 사실을 숨기지 않는다.
                      + (f"\n\n(원시 합 {st.get('pnl_raw', st['pnl']):+.1f} 중 "
                         f"사람이 「포지션 추가」로 키운 몫 {st.get('human_pnl', 0):+.1f} "
                         f"{st.get('human_n', 0)}건은 가족 판정에서 제외했습니다)"
                         if st.get("human_n") else "")))
            s.commit()
        except Exception as e:  # noqa: BLE001
            s.rollback()
            logger.warning("[%s] 알림 실패 (차단은 저장됨): %s", FIX, e)
    except Exception as e:  # noqa: BLE001
        s.rollback()
        logger.error("[%s] %s 차단 저장 실패 (이번 생성은 막는다): %s", FIX, fam_key, e)
    finally:
        s.close()


def check(db: Any, *, strategy_type: str | None, template_name: str | None, entry_origin: str | None,
          symbol: str, side: str, where: str = "전략 생성") -> dict | None:
    """자동 전략 생성 직전. 막히면 ValueError(「손실 차단기」). 사람 전략·꺼짐·중단 중 = None."""
    from app.services import auto_family_registry as AF
    fam = AF.family_for(strategy_type=strategy_type, template_name=template_name, entry_origin=entry_origin)
    if fam is None or not enabled(db):
        return None
    try:
        from app.services.auto_trading_halt import halt_enabled
        if halt_enabled(db):
            return None
    except Exception:  # noqa: BLE001
        pass
    try:
        st = state(db, fam.key)
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s 손익 조회 실패 → 이번엔 통과 (차단기는 안전망): %s", FIX, fam.key, e)
        return None
    if not st["tripped"] and st["pnl"] < -st["limit"]:
        _trip(fam.key, fam.label, st)
        st["tripped"] = True
        logger.warning("[%s] ⛔ %s 손실 차단 발동 — 최근 %d일 %+.1f USDT (%d건)", FIX, fam.label, st["days"], st["pnl"], st["n"])
    if st["tripped"]:
        raise ValueError(f"⛔ [{BLOCK_TAG}] {fam.label} {symbol} {side} {where} 막음 — 최근 {st['days']}일 실현 "
                         f"{st['pnl']:+.1f} USDT (조정: 관제실 「손실 차단」 → 허용 · system_settings {key_for(fam.key)}=0)")
    return {"family": fam.key, **st}


def is_breaker_error(exc: BaseException | str) -> bool:
    return BLOCK_TAG in str(exc)

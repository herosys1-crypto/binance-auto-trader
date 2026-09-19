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


def family_realized(db: Any, fam_key: str, since: datetime) -> tuple[float, int]:
    """그 가족의 since 이후 **끝난**(stopped_at) 전략 실현 손익 합 · 건수. 사람 전략 제외."""
    from sqlalchemy import select
    from app.models.strategy_instance import StrategyInstance as SI
    from app.models.strategy_template import StrategyTemplate as ST
    from app.services import auto_family_registry as AF
    rows = db.execute(select(SI.realized_pnl, SI.created_at, SI.entry_origin, ST.strategy_type, ST.name)
                      .join(ST, ST.id == SI.strategy_template_id)
                      .where(SI.stopped_at.is_not(None), SI.stopped_at >= since)).all()
    total, n = 0.0, 0
    for rp, ca, origin, stype, name in rows:
        fam = AF.family_for(strategy_type=stype, template_name=name, entry_origin=origin, created_at=ca)
        if fam is not None and fam.key == fam_key:
            total += float(rp or 0)
            n += 1
    return total, n


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
    pnl, n = family_realized(db, fam_key, since)
    return {"tripped": tripped, "pnl": round(pnl, 2), "n": n, "since": since.isoformat(), "limit": limit, "days": days}


def all_states(db: Any, fam_keys: list[str], *, now: datetime | None = None) -> dict[str, dict[str, Any]]:
    """관제실 화면용 — 모든 가족을 **쿼리 한 번**으로. 가족마다 해제 시각이 다르므로 최대 창으로 읽고 가족별로 자른다."""
    from sqlalchemy import select
    from app.models.strategy_instance import StrategyInstance as SI
    from app.models.strategy_template import StrategyTemplate as ST
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
        out[k] = {"tripped": tripped, "pnl": 0.0, "n": 0, "since": since, "limit": limit, "days": days}
    rows = db.execute(select(SI.realized_pnl, SI.created_at, SI.stopped_at, SI.entry_origin, ST.strategy_type, ST.name)
                      .join(ST, ST.id == SI.strategy_template_id)
                      .where(SI.stopped_at.is_not(None), SI.stopped_at >= base)).all()
    for rp, ca, sa, origin, stype, name in rows:
        fam = AF.family_for(strategy_type=stype, template_name=name, entry_origin=origin, created_at=ca)
        if fam is None or fam.key not in out or _aware(sa) < out[fam.key]["since"]:
            continue
        out[fam.key]["pnl"] += float(rp or 0)
        out[fam.key]["n"] += 1
    for v in out.values():
        v["pnl"] = round(v["pnl"], 2)
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
                      f"−{st['limit']:g} 밑이라 새 전략을 막았습니다. 다시 허용하려면 관제실에서 「손실 차단」을 「허용」으로."))
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

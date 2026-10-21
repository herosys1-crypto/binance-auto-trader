"""🎰 Fix 477 실주문 경로 — 세력 펌프·덤프 SHORT 마틴게일 (pds_mode=on 일 때만 진입 · 열린 포지션 익절·기한 정리는 모드와 관계없이).

진입: 일봉 잡(KST 09:15)의 후보 → 기존 엔진 사다리(stage_ladder)로 인스턴스 생성
  · 단계 = Plan.margins × pds_scale · 추가 = 직전 단계가 +gap%(계산기 복리 = 사장님 「이어서 +g%」) · 마지막 단계도 PRICE_UP_PCT
  · 손절 = force_sl_roi_override(평단 ROI %, 레버 1 이면 총 증거금 대비 손실 %) = loss_frac × 100 — 엔진이 처리(단계 게이트 면제 = 사다리 마커)
  · 엔진 익절 끔(tp1_pct_override = 0, v115 「TP 완전 끔」) — 익절은 아래 전용 정리
정리(5분마다): 현재가 ≤ min(급등분 절반 반납 가격, 평단 × 0.995) → 전량 시장가 · 보유 hold_days 일 지나면 전량 시장가 (백테스트와 같은 규칙)
생성 게이트(가족 하루 최대 · 차트 자리 · 손실 차단기 · 자동매매 중단)는 공용 create_strategy_instance 가 그대로 건다 — 막히면 건너뜀.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Iterable

from app.services import pump_dump_short as P

logger = logging.getLogger(__name__)

FIX = P.FIX
SIGNAL = "pds"
TP_FACTOR = 0.995
ENTRY_WINDOW_H = 6                  # 일봉 마감 뒤 이 시간 안에만 진입 (Claude가 정함 — 백테스트는 마감가 진입)


def order_candidates(cands: Iterable[dict]) -> list[dict]:
    """🐋 먼저 · 급등폭 큰 순 · 심볼 이름 순(같을 때 늘 같게)."""
    return sorted(cands, key=lambda c: (not c.get("whale"), -float(c.get("surge_pct") or 0), str(c.get("symbol"))))


def stages_config(plan: P.Plan, scale: float) -> dict:
    caps = [round(m * scale, 4) for m in plan.margins]
    g = plan.gap_pct
    return {"capitals": caps, "trigger_percents": [None] + [g] * (len(caps) - 1), "stages_count": len(caps),
            "last_stage_trigger_mode": "PRICE_UP_PCT", "last_stage_trigger_percent": g}


def template_kwargs(plan: P.Plan, p: dict, symbol: str, now: datetime) -> dict:
    sc = stages_config(plan, p["scale"])
    caps = sc["capitals"] + [None] * (4 - len(sc["capitals"]))
    trig = [None] + [plan.gap_pct] * (len(sc["capitals"]) - 1) + [None] * (4 - len(sc["capitals"]))
    D = lambda v: None if v is None else Decimal(str(v))      # noqa: E731
    return {
        "name": f"PDS_{plan.key.upper()}_{symbol}_{now:%Y%m%d_%H%M%S}", "strategy_type": P.STYPE, "side": "SHORT",
        "leverage": int(p["lev"]), "total_capital": D(sum(sc["capitals"])), "stages_config": sc,
        "stage1_capital": D(caps[0]), "stage2_capital": D(caps[1]), "stage3_capital": D(caps[2]), "stage4_capital": D(caps[3]),
        "stage2_trigger_percent": D(trig[1]), "stage3_trigger_percent": D(trig[2]), "stage4_trigger_percent": D(trig[3]),
        # 엔진 익절은 인스턴스 tp1_pct_override=0 으로 끈다 — 칸은 필수라 닿지 않는 값(ROI 95%)으로 둔다
        "tp1_percent": D(95), "tp2_percent": D(96), "tp3_percent": D(97), "tp4_percent": D(98),
        "tp1_qty_ratio": D(25), "tp2_qty_ratio": D(25), "tp3_qty_ratio": D(25), "tp4_qty_ratio": D(25),
        "stop_loss_percent_of_capital": D(90), "is_active": True,
    }


def _tag(db, si, tags: dict) -> bool:
    for attempt in (1, 2):
        try:
            if attempt == 2:
                db.rollback()
                db.refresh(si)
            for k, v in tags.items():
                setattr(si, k, v)
            db.commit()
            return True
        except Exception as e:  # noqa: BLE001
            logger.error("[%s] #%s 표식 저장 실패(%d번째): %s", FIX, getattr(si, "id", "?"), attempt, e)
    try:
        db.rollback()
    except Exception:  # noqa: BLE001
        pass
    return False


def _stop_untagged(si) -> None:
    """표식 없는 인스턴스가 기본 손절·익절로 돌지 않게 — 새 세션으로 1단계 전에 멈춘다(포지션 없을 때)."""
    try:
        from app.core.database import SessionLocal
        from app.models.strategy_instance import StrategyInstance as SI
        s2 = SessionLocal()
        try:
            row = s2.get(SI, si.id)
            if row is not None and not row.current_position_qty:
                row.status = "STOPPED"
                row.last_error_message = f"[{FIX}] 표식 저장 실패 — 1단계 전에 멈춤"
                s2.commit()
            logger.critical("[%s] #%s %s 표식 저장 실패 → %s", FIX, si.id, getattr(si, "symbol", "?"),
                            "멈춤" if row is not None and not row.current_position_qty else "⚠️ 포지션 있음 — 사람 확인 필요")
        finally:
            s2.close()
    except Exception as e:  # noqa: BLE001
        logger.critical("[%s] #%s 표식 실패 뒤 멈춤도 실패 — 사람 확인 필요: %s", FIX, getattr(si, "id", "?"), e)


def no_position_error(e: Exception) -> bool:
    """emergency_close_position 의 「거래소에 포지션 없음」 메시지만 (교차 감사: "does not" 등 다른 오류를 포지션 없음으로 보면 안 됨)."""
    m = str(e).lower()
    return "exchange has no" in m and "position" in m


def _active(db) -> list:
    from sqlalchemy import select
    from app.core.strategy_status import ACTIVE_LIKE
    from app.models.strategy_instance import StrategyInstance as SI
    rows = db.execute(select(SI).where(SI.entry_signal == SIGNAL, SI.status.in_(tuple(ACTIVE_LIKE)))).scalars().all()
    return [si for si in rows if not (si.entry_signal_meta or {}).get("exit_done")]


def open_positions(db, candidates: list[dict], p: dict, *, svc_factory: Callable[[Any], Any] | None = None,
                   active_fn: Callable[[Any], list] | None = None, price_of: Callable[[str], Any] | None = None,
                   now: datetime | None = None) -> dict:
    """후보 → 인스턴스 생성. 반환 stat."""
    stat: dict[str, Any] = {"mode": p["mode"], "candidates": len(candidates), "opened": [], "skipped": {}}
    if p["mode"] != "on" or not candidates:
        return stat
    now = now or datetime.now(timezone.utc)
    plan = P.PLANS[p["plan"]]
    active = (active_fn or _active)(db)
    busy = {str(getattr(si, "symbol", "")) for si in active}
    slots = int(p["max_concurrent"]) - len(active)

    def skip(why: str) -> None:
        stat["skipped"][why] = stat["skipped"].get(why, 0) + 1
    if svc_factory is None:
        from app.services.strategy_service import StrategyService
        svc_factory = StrategyService
    from app.models.strategy_template import StrategyTemplate
    from app.services.auto_family_registry import is_limit_error
    from app.services.sajangnim_capital import STAGE_LADDER_MODE
    for c in order_candidates(candidates):
        sym = str(c["symbol"])
        if slots <= 0:
            skip("동시 상한")
            continue
        if sym in busy:
            skip("이미 보유")
            continue
        try:                                                     # 일봉 마감(= 음봉 확인 날 끝) 뒤 ENTRY_WINDOW_H 시간 안에만 — 늦은 진입 금지
            close_at = datetime.fromtimestamp(int(c["entry_day"]) / 1000 + 86400, timezone.utc)
            late = not (close_at <= now <= close_at + timedelta(hours=ENTRY_WINDOW_H))
        except (KeyError, TypeError, ValueError):
            late = True
        if late:
            skip("진입 창 밖")
            continue
        try:
            px = price_of(sym) if price_of else None
            start = Decimal(str(px if px and float(px) > 0 else c["entry_ref"]))
            tpl = StrategyTemplate(**template_kwargs(plan, p, sym, now))
            db.add(tpl)
            db.flush()
            si = svc_factory(db).create_strategy_instance(
                user_id=1, exchange_account_id=1, strategy_template_id=tpl.id, symbol=sym, side="SHORT",
                start_price=start, leverage_override=int(p["lev"]), capital_management_mode=STAGE_LADDER_MODE,
                entry_origin="auto_pds")
            # ⚠️ 생성 함수는 안에서 커밋한다(기본 손절 −25%·기본 익절이 붙은 채) — 1단계 주문은 그 뒤 엔진 주기에 나간다.
            #   표식(손절 −30/−40 · 엔진 익절 끔 · pds)을 붙이는 커밋이 실패하면 한 번 더, 그래도 실패면 1단계 전에 멈춘다(교차 감사).
            tags = {"force_sl_roi_override": Decimal(str(round(plan.loss_frac * 100, 4))), "tp1_pct_override": Decimal("0"),
                    "entry_signal": SIGNAL,
                    "entry_signal_meta": {"fix": FIX, "plan": plan.key, "half": float(c["half"]), "entry_ref": float(c["entry_ref"]),
                                          "surge_day": c.get("surge_day"), "entry_day": c.get("entry_day"), "hold_days": int(p["hold_days"]),
                                          "whale": bool(c.get("whale")), "scale": p["scale"], "opened_at": now.isoformat()}}
            if not _tag(db, si, tags):
                _stop_untagged(si)
                skip("표식 실패 → 멈춤")
                continue
            busy.add(sym)
            slots -= 1
            stat["opened"].append({"symbol": sym, "id": getattr(si, "id", None), "plan": plan.key})
            logger.warning("[%s] 🎰 세력 펌프·덤프 SHORT 진입 #%s %s · %s · 1단계가 ≈ %s", FIX, getattr(si, "id", "?"), sym, plan.label, start)
        except ValueError as e:
            db.rollback()
            if is_limit_error(e):
                skip("생성 게이트")
            else:
                try:
                    from app.services.balance_guard import is_insufficient_balance_error
                    skip("잔고 부족" if is_insufficient_balance_error(e) else "생성 거절")
                except Exception:  # noqa: BLE001
                    skip("생성 거절")
            logger.info("[%s] %s 진입 건너뜀: %s", FIX, sym, str(e)[:200])
        except Exception as e:  # noqa: BLE001 — 한 건 실패가 나머지를 막지 않게
            db.rollback()
            skip("오류")
            logger.warning("[%s] %s 진입 실패: %s", FIX, sym, e)
    if stat["opened"] or stat["skipped"]:
        logger.info("[%s] 진입 결과 %s", FIX, stat)
    return stat


def exit_decision(meta: dict, avg: float | None, mark: float | None, now: datetime) -> tuple[bool, str, float | None]:
    """(청산?, 사유, 익절가). 현재가·평단 모름 = (False, "모름", None)."""
    try:
        opened = datetime.fromisoformat(str(meta.get("opened_at")))
        if opened.tzinfo is None:
            opened = opened.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        opened = None
    hold = int(meta.get("hold_days") or 10)
    tp = None
    if avg and avg > 0:
        half = meta.get("half")
        tp = min(float(half), avg * TP_FACTOR) if half else avg * TP_FACTOR
    if mark and mark > 0 and tp is not None and mark <= tp:
        return True, "익절", tp
    if opened is not None and now - opened >= timedelta(days=hold):
        return True, "기한", tp
    if not (mark and mark > 0) or tp is None:
        return False, "모름", tp
    return False, "유지", tp


def run_exit_once(db=None, *, now: datetime | None = None, mark_price_of: Callable[[Any, str], Any] | None = None,
                  closer: Callable[[Any, Any], None] | None = None, rows: list | None = None) -> dict:
    """열린 pds 포지션 익절·기한 정리. 모드와 관계없이 돈다(켰다 끈 경우에도 열린 건은 끝까지)."""
    own = db is None
    if own:
        from app.core.database import SessionLocal
        db = SessionLocal()
    stat: dict[str, Any] = {"targets": 0, "closed": 0, "errors": 0, "unknown": 0}
    now = now or datetime.now(timezone.utc)
    try:
        if rows is None:
            rows = [si for si in _active(db) if si.current_position_qty not in (None, 0)]
        clients: dict = {}
        for si in rows:
            meta = dict(si.entry_signal_meta or {})
            if meta.get("exit_done"):
                continue
            stat["targets"] += 1
            try:
                avg = float(si.avg_entry_price) if si.avg_entry_price else None
                mark = None
                try:
                    mark = float((mark_price_of or _mark_price)(si, clients) or 0) or None
                except Exception as e:  # noqa: BLE001 — 현재가 실패 = 이번엔 청산 안 함(기한도 다음에)
                    logger.info("[%s] #%s 현재가 실패: %s", FIX, si.id, e)
                go, why, tp = exit_decision(meta, avg, mark, now)
                if not go:
                    if why == "모름":
                        stat["unknown"] += 1
                    continue
                done = {"why": why, "price": mark, "tp": tp, "at": now.isoformat()}
                try:
                    (closer or _close)(db, si)
                except ValueError as ve:
                    if not no_position_error(ve):
                        raise
                    db.rollback()
                    done["no_position"] = True
                try:
                    db.refresh(si, attribute_names=["entry_signal_meta"])
                except Exception:  # noqa: BLE001
                    pass
                fresh = dict(si.entry_signal_meta or {})
                fresh["exit_done"] = done
                si.entry_signal_meta = fresh
                si.last_error_message = f"[{FIX}] {why} 정리 — 현재가 {mark if mark is None else format(mark, '.6g')} · 익절가 {tp if tp is None else format(tp, '.6g')}"
                db.commit()
                stat["closed"] += 1
                logger.warning("[%s] 🎰 #%s %s %s 전량 시장가 정리 %s", FIX, si.id, si.symbol, why, done)
            except Exception as e:  # noqa: BLE001 — 표식 없음 = 다음 사이클 재시도
                db.rollback()
                stat["errors"] += 1
                logger.warning("[%s] #%s 정리 실패 (다음 사이클 재시도): %s", FIX, getattr(si, "id", "?"), e)
        return stat
    finally:
        if own:
            db.close()


def _keys(db, account_id: int, cache: dict):
    if account_id in cache:
        return cache[account_id]
    from app.core.crypto import decrypt_text
    from app.models.exchange_account import ExchangeAccount
    acc = db.get(ExchangeAccount, account_id)
    cache[account_id] = None if acc is None else {"api_key": decrypt_text(acc.api_key_enc), "api_secret": decrypt_text(acc.api_secret_enc),
                                                  "is_testnet": acc.is_testnet}
    return cache[account_id]


def _mark_price(si, cache: dict):
    from app.integrations.binance.client import BinanceClient
    bc = cache.get("_public")
    if bc is None:
        bc = cache["_public"] = BinanceClient(api_key="", api_secret="")
    t = bc.get_24hr_ticker(symbol=si.symbol)
    if isinstance(t, list):
        t = t[0] if t else None
    return float((t or {}).get("lastPrice") or 0) or None


def _close(db, si) -> None:
    from app.services.execution_service import ExecutionService
    keys = _keys(db, si.exchange_account_id, {})
    if keys is None:
        raise RuntimeError("거래소 계정 없음")
    qty = Decimal(str(si.current_position_qty or 0)).copy_abs()
    ExecutionService(db, **keys).emergency_close_position(si.id, quantity=qty)

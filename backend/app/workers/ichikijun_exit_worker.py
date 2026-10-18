"""🗾 Fix 467 워커 — 일목 예약 인스턴스(기준선 청산 변형 `_r2kj`)의 실주문 「기준선 재이탈 청산」.

15분마다(분 4·19·34·49). 대상 = 포지션 있는 ACTIVE_LIKE 인스턴스 중 entry_signal=ichikijun* 이고 meta.variant 가 `_r2kj` 인 것만
(다른 전략·가족은 손대지 않는다). 그 변형 봉의 새 완성봉이 생겼을 때만 klines 1회 — Redis ichiexit:last:{sid}:{iv}.
모드 ichikijun_kijun_exit_mode: off · shadow(기본 — 기록만) · on(전량 시장가 청산 = 기존 emergency_close_position).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.services import ichikijun_apply as IA
from app.services import ichikijun_exit as EX
from app.services import ichimoku_kijun as IK

logger = logging.getLogger(__name__)

FIX = "Fix467"
KLINE_LIMIT = 300
K_LAST = "ichiexit:last:{sid}:{iv}"
LAST_TTL = 7 * 86400


def _setting(db, key: str) -> str | None:
    from app.models.system_setting import SystemSetting
    row = db.get(SystemSetting, key)
    return None if row is None or row.value is None else str(row.value)


def _closed(bc, sym: str, iv: str, target: int) -> IK.Bars | None:
    kl = bc.get_klines(symbol=sym, interval=iv, limit=KLINE_LIMIT) or []
    kl = [b for b in kl if isinstance(b, (list, tuple)) and b and int(b[0]) <= target]
    if not kl or int(kl[-1][0]) != target:
        return None
    return IK.bars_from(kl)


def _client(db, account_id: int, cache: dict):
    """계정별 (BinanceClient, ExecutionService 생성 인자). 계정 없음 = None."""
    if account_id in cache:
        return cache[account_id]
    from app.core.crypto import decrypt_text
    from app.integrations.binance.client import BinanceClient
    from app.models.exchange_account import ExchangeAccount
    acc = db.get(ExchangeAccount, account_id)
    if acc is None:
        cache[account_id] = None
        return None
    keys = {"api_key": decrypt_text(acc.api_key_enc), "api_secret": decrypt_text(acc.api_secret_enc),
            "is_testnet": acc.is_testnet}
    cache[account_id] = (BinanceClient(**keys), keys)
    return cache[account_id]


def _close(db, si, keys: dict) -> None:
    from app.services.execution_service import ExecutionService
    qty = Decimal(str(si.current_position_qty or 0)).copy_abs()
    ExecutionService(db, **keys).emergency_close_position(si.id, quantity=qty)


def run_ichikijun_exit_once(decrypt_text=None) -> dict[str, Any]:  # decrypt_text: 스케줄러 공용 시그니처(계정 키는 _client 가 푼다)
    from app.core.database import SessionLocal
    from app.core.redis_client import get_redis_client
    from app.core.strategy_status import ACTIVE_LIKE
    from app.models.strategy_instance import StrategyInstance as SI

    stat: dict[str, Any] = {"targets": 0, "judged": 0, "signals": 0, "closed": 0, "errors": 0}
    db = SessionLocal()
    try:
        mode = EX.mode_of(_setting(db, EX.MODE_KEY))
        stat["mode"] = mode
        if mode == "off":
            return stat
        rows = db.execute(
            select(SI).where(SI.entry_signal.like("ichikijun%"), SI.status.in_(tuple(ACTIVE_LIKE)),
                             SI.current_position_qty.isnot(None), SI.current_position_qty != 0)
        ).scalars().all()
        r = get_redis_client()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        clients: dict = {}
        for si in rows:
            meta = dict(si.entry_signal_meta or {})
            var = EX.is_target(si.entry_signal, meta)
            if var is None or meta.get("kj_exit_done"):
                continue
            stat["targets"] += 1
            target = IA.last_closed_open(now_ms, var.iv)
            key = K_LAST.format(sid=si.id, iv=var.iv)
            try:
                raw = r.get(key)
                seen_r = int(raw) if raw else None
            except Exception:  # noqa: BLE001
                seen_r = None
            # Gemini 심판: Redis 가 비면 진입 뒤 **지난** 이탈까지 다시 보고 지금 청산할 수 있다 → 판정한 마지막 봉을 DB(meta)에도
            #   남기고 둘 중 늦은 쪽부터만 본다(Redis 는 조회 절약용 캐시).
            seen_m = meta.get("kj_judged_ts")
            seen_vals = [int(x) for x in (seen_r, seen_m) if x is not None]
            seen = max(seen_vals) if seen_vals else None
            if seen is not None and seen >= target:
                continue
            try:
                cl = _client(db, si.exchange_account_id, clients)
                if cl is None:
                    stat["errors"] += 1
                    continue
                bc, keys = cl
                B = _closed(bc, si.symbol, var.iv, target)
                if B is None:
                    continue                                   # 봉 정착 전 = 다음 사이클
                stat["judged"] += 1
                if seen is not None and B.ts[0] > seen + IA.IV_MS[var.iv]:
                    logger.warning("[%s] #%s 판정 공백 — 마지막 판정 봉 %s 뒤가 창(%d봉) 밖이라 그 사이 봉은 못 본다",
                                   FIX, si.id, seen, KLINE_LIMIT)
                hit, info = EX.kijun_break(B, int(meta["entry_bar_ts"]), seen, si.side)
                if hit:
                    stat["signals"] += 1
                    if mode == "on":
                        try:
                            _close(db, si, keys)
                            meta["kj_exit_done"] = {**info, "at": datetime.now(timezone.utc).isoformat()}
                        except ValueError as ve:
                            # 교차 감사: 거래소엔 이미 포지션이 없는데 DB 수량만 남은 경우(손절 먼저 체결 등) — 15분마다
                            #   영원히 재시도하지 않게 「포지션 없음」으로 끝낸다 (기존 정지 API 와 같은 판별).
                            if not ("no" in str(ve).lower() and "position" in str(ve).lower()):
                                raise
                            db.rollback()
                            meta["kj_exit_done"] = {**info, "at": datetime.now(timezone.utc).isoformat(), "no_position": True}
                        si.last_error_message = (f"[{FIX}] 기준선 재이탈 청산 — 종가 {info['close']:.6g} vs 기준선 "
                                                 f"{info['kijun']:.6g} ({var.key})")
                        stat["closed"] += 1
                        logger.warning("[%s] 🗾 #%s %s %s 기준선 재이탈 → 전량 시장가 청산 %s", FIX, si.id, si.symbol,
                                       si.side, info)
                    elif not meta.get("kj_exit_signal"):
                        meta["kj_exit_signal"] = {**info, "at": datetime.now(timezone.utc).isoformat()}
                        logger.info("[%s] 🗾 (그림자) #%s %s %s 기준선 재이탈 신호 — 청산 안 함 %s", FIX, si.id,
                                    si.symbol, si.side, info)
                meta["kj_judged_ts"] = target                     # DB 커서 (위 Gemini 지적) — 신호 기록과 같은 커밋
                # Gemini 3차(오탐이지만 보강): 저장 직전 DB 값을 다시 읽어 이 워커가 쓰는 키만 덮는다(다른 키 보존).
                try:
                    db.refresh(si, attribute_names=["entry_signal_meta"])
                except Exception:  # noqa: BLE001 — 다시 읽기 실패면 들고 있던 값 그대로
                    pass
                fresh = dict(si.entry_signal_meta or {})
                fresh.update({k: meta[k] for k in ("kj_judged_ts", "kj_exit_signal", "kj_exit_done") if k in meta})
                si.entry_signal_meta = fresh
                db.commit()
                try:
                    r.setex(key, LAST_TTL, str(target))
                except Exception:  # noqa: BLE001 — 캐시 실패는 DB 커서가 막는다
                    pass
            except Exception as e:  # noqa: BLE001 — 한 건 실패가 다른 건을 막지 않게 · 표식 안 남김 = 다음 사이클 재시도
                db.rollback()
                stat["errors"] += 1
                logger.warning("[%s] #%s 기준선 청산 판정·청산 실패 (다음 사이클 재시도): %s", FIX, si.id, e)
        if stat["targets"]:
            logger.info("[%s] 일목 기준선 청산 %s", FIX, stat)
        return stat
    finally:
        db.close()

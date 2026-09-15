"""🌊 볼밴 스윙 워커 (2026-09-14 사장님) — 판정: app/services/bb_swing_rules.py (사장님 원문·규칙은 그 파일 머리말).

60초마다 돌지만 **15분 완성봉당 1회**만 스캔한다 (Redis SET NX bbswing:scan:{봉} — 리더가 둘이어도 한 번).
모드 bb_swing_mode:
  off    = 아무것도 안 함
  shadow = 신호만 Redis bbswing:shadow:{sym}:{side}:{봉시각} (7일) + 사이클 요약. **주문 없음** (기본)
  on     = 실주문. 진입은 공용 분할 실행기 app/services/split_entry_executor.open_split_position (규칙 가족과 같은 코드) —
           capital_management_mode=split_entry 라서 손절(risk_service) · 2·3차 실체결가 재앵커(stage_trigger_worker) ·
           피라미딩 제외 · 단계 정리 제외 · 반전 워커 제외가 그대로 붙는다.
           진입 전 가드 = surge_ladder_entry._guards_ok (킬스위치 · ban · 잔액 · 같은 심볼·방향 · 전용 슬롯).
           strategy_type=bb_swing 은 재진입 워커 화이트리스트(pump_split% 등)에 걸리지 않는다 = 손절 뒤 자동 재진입 없음.
           하루 최대 진입 = auto_family_registry (daily_max_bb_swing, 기본 1) — 생성·1차 주문 두 곳에서 막는다.

반박 검증 (2026-09-14, 렌즈 3) 반영:
  · 전환 = **새 방향 1차 주문이 성공한 뒤에만** 반대 포지션을 닫는다 (먼저 닫으면 24h 순위 게이트·슬롯에 막혀 「닫고 안 엶」).
    청산 수량 0 = 거래소 실수량 전량 (DB 수량 지연·부분 잔량 방지). 상태는 청산 함수·체결 스트림이 쓴다 (워커가 덮어쓰지 않음).
  · 1차 주문 실패 = 그 인스턴스 보관 처리(실행기) + 6시간 재시도 금지.
  · 같은 봉에 SHORT·LONG 이 둘 다 참이면 둘 다 건너뛴다 (방금 연 포지션을 스스로 전환 청산하는 왕복 방지).
  · 기준선 = 1차 **예상 체결가**(판정봉 종가) ÷ (1 ∓ 1차 심도) — 저장 트리거·주문 전 검산이 실제 체결가와 맞게 (실행기).
  · 캔들 = 다른 워커와 캐시 키가 겹치지 않는 limit + 「방금 마감한 봉」인지 확인 (옛 스냅샷으로 판정 금지).
  · 감시 종목에서 비영문 심볼 제외 (백테스트와 같은 표본).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core.redis_client import get_redis_client
from app.services import bb_swing_rules as R

logger = logging.getLogger(__name__)

BAR_MS = 900_000
SETTLE_MS = 5_000                     # 봉 마감 직후 5초는 거래소 확정 대기 (Claude가 정함)
K15_LIMIT = 121                       # 121 = bb_mid_line(120) 등과 kline 캐시 키가 겹치지 않게
K4H_LIMIT = 301                       # EMA50 수렴 (백테스트 4H 300봉과 같은 창)
SHADOW_TTL = 7 * 86400
START_FAIL_COOLDOWN_S = 6 * 3600      # 1차 주문 실패 뒤 같은 심볼·방향 재시도 금지 (Claude가 정함)
CYCLE_KEY = "bbswing:last_cycle"
LABEL = "볼밴 스윙"
_MISS_BY_CODE = {"create_blocked": "생성 게이트(중단·하루 최대 등)", "dead_stage": "죽은 단계 취소", "start_failed": "1차 주문 실패",
                 "start_unconfirmed": "1차 주문 뒤 후처리 실패(보관 안 함)"}


def _k_shadow(sym: str, side: str, ts: int) -> str:
    return f"bbswing:shadow:{sym}:{side}:{ts}"


def _k_scan(bucket: int) -> str:
    return f"bbswing:scan:{bucket}"


def _k_cool(sym: str, side: str) -> str:
    return f"bbswing:cool:{sym}:{side}"


def _completed(kl, now_ms: int) -> list:
    """진행 중 봉(close_time ≥ 지금)을 뺀다 — 가짜 신호에 자본이 물리지 않게 (Fix 216 교훈)."""
    rows = list(kl or [])
    if rows and int(rows[-1][6]) >= now_ms:
        rows = rows[:-1]
    return rows


def _is_fresh_15m(rows: list, bucket: int) -> bool:
    """마지막 완성봉이 **방금 마감한 봉**(시작 = 이번 봉 시작 − 15분)인가. 캐시의 옛 스냅샷이면 False."""
    return bool(rows) and int(rows[-1][0]) == bucket * BAR_MS - BAR_MS


def _resolve_same_bar(sigs: list) -> list:
    """같은 봉에 SHORT·LONG 이 둘 다 참이면 둘 다 버린다 (좁은 밴드·긴 꼬리 봉 — 방향 판단 불가)."""
    return [] if len({s[0] for s in sigs}) > 1 else sigs


def _load_split_config(db) -> tuple[list[Decimal], list[Decimal], Decimal, str]:
    """자본·단계·손절 — 공용 실행기 파서(볼밴 분할 검증 규칙). 손상·정합성 실패 = 기본값."""
    from app.services.split_entry_executor import parse_config
    return parse_config(R.setting(db, "bb_swing_capitals"), R.setting(db, "bb_swing_steps"), R.setting(db, "bb_swing_sl_roi"))


def _active_family(db, symbol: str | None = None, side: str | None = None) -> list:
    from app.core.strategy_status import ACTIVE_LIKE
    from app.models.strategy_instance import StrategyInstance
    from app.models.strategy_template import StrategyTemplate
    q = (
        select(StrategyInstance)
        .join(StrategyTemplate, StrategyTemplate.id == StrategyInstance.strategy_template_id)
        .where(StrategyTemplate.strategy_type == R.STRATEGY_TYPE)
        .where(StrategyInstance.status.in_(tuple(ACTIVE_LIKE)))
        .where(StrategyInstance.is_archived.is_(False))
    )
    if symbol:
        q = q.where(StrategyInstance.symbol == symbol)
    if side:
        q = q.where(StrategyInstance.side == side)
    return list(db.execute(q).scalars().all())


def _cycles_24h(db, symbol: str, side: str) -> int:
    """24h 안에 **실제로 진입한** 이 가족 사이클 수. 실패 = 큰 수(fail-closed, 자본이 나가는 판정)."""
    from app.models.strategy_instance import StrategyInstance
    from app.models.strategy_template import StrategyTemplate
    try:
        return int(db.execute(
            select(func.count()).select_from(StrategyInstance)
            .join(StrategyTemplate, StrategyTemplate.id == StrategyInstance.strategy_template_id)
            .where(StrategyTemplate.strategy_type == R.STRATEGY_TYPE)
            .where(StrategyInstance.symbol == symbol, StrategyInstance.side == side)
            .where(StrategyInstance.created_at >= datetime.now(timezone.utc) - timedelta(hours=24))
            .where(StrategyInstance.is_archived.is_(False), StrategyInstance.current_stage >= 1)
        ).scalar() or 0)
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] 24h 사이클 조회 실패 = 상한으로 간주: %s", R.FIX, e)
        return 10**6


def _exec(db, account):
    from app.core.crypto import decrypt_text
    from app.services.execution_service import ExecutionService
    return ExecutionService(
        db,
        api_key=decrypt_text(account.api_key_enc),
        api_secret=decrypt_text(account.api_secret_enc),
        is_testnet=account.is_testnet,
    )


def _flip_close(db, account, opp) -> str:
    """스윙 전환 — 같은 가족 반대 포지션 **전량** 시장가 청산. 새 방향 1차 주문이 성공한 뒤에만 부른다.

    quantity=0 = 거래소 실수량 전량 (execution_service._emergency_close_position_locked). 포지션이 이미 없으면
    그 함수가 미체결 취소 + STOPPED 를 찍고 ValueError 를 던진다 = 정상. 상태값은 워커가 쓰지 않는다
    (체결 스트림이 STOPPED 로 확정한 행을 옛 객체로 STOPPING 으로 덮어 좀비를 만들지 않게).
    """
    ex = _exec(db, account)
    try:
        ex.client.cancel_all_orders(symbol=opp.symbol)
        ex.emergency_close_position(opp.id, quantity=Decimal("0"))
        logger.warning("[%s] 🔄 전환 청산 #%s %s %s (거래소 실수량 전량)", R.FIX, opp.id, opp.symbol, opp.side)
        return "closed"
    except ValueError as ve:
        logger.info("[%s] 🔄 전환 대상 #%s 이미 포지션 없음: %s", R.FIX, opp.id, ve)
        return "already_flat"


def _enter(db, r, stat: dict, miss, account, *, sym: str, side: str, close: float, why: str, opp: list,
           caps, steps, sl_roi, tp1: float, trail: float, flip: bool, cap_n: int) -> None:
    from app.services.split_entry_executor import open_split_position
    from app.services.surge_ladder_entry import _guards_ok

    if cap_n <= 0:
        miss("전용 상한 0")
        return
    try:
        if r.get(_k_cool(sym, side)):
            miss("1차 실패 뒤 대기")
            return
    except Exception:  # noqa: BLE001
        miss("Redis 실패 = 보류")
        return
    if _cycles_24h(db, sym, side) >= R.setting_int(db, "bb_swing_cycles_per_day", 1, 20):
        miss("24h 진입 상한")
        return
    g_ok, g_why = _guards_ok(db, account, sym, side, prefix=R.TEMPLATE_PREFIX,
                             cap_key="bb_swing_max_concurrent",
                             cap_default=int(R.SETTINGS["bb_swing_max_concurrent"][0]))
    # 슬롯 소진이 **반대 포지션 때문**이고 전환이 켜져 있으면만 통과 — 새 방향이 열린 직후 반대를 닫으므로 초과는 잠깐 1건.
    # 킬스위치·ban·잔액·같은 방향 중복은 절대 우회하지 않는다.
    if not g_ok and not (flip and opp and g_why.startswith("전용 동시 슬롯")):
        miss(f"가드: {g_why.split(' (')[0]}")
        logger.info("[%s] ⛔ %s %s 진입 보류 — %s", R.FIX, sym, side, g_why)
        return
    if opp and not flip:
        miss("반대 포지션 보유 (전환 끔)")
        return

    from app.services.split_entry_executor import split_total_full
    t_full, t_why = split_total_full(db)       # 분할 예약이 다른 가족 2단계를 막지 않게 (반박 검증 9/15 H1)
    if t_full:
        miss("분할 자동 전략 전체 상한")
        logger.info("[%s] ⏸ %s %s 진입 보류 — %s", R.FIX, sym, side, t_why)
        return

    si, code, reason = open_split_position(
        db, account, symbol=sym, side=side, price=close, strategy_type=R.STRATEGY_TYPE, name_prefix=R.TEMPLATE_PREFIX,
        label=LABEL, caps=caps, steps=steps, sl_roi=sl_roi, tp1=tp1, trail=trail,
    )
    if si is None:
        miss(_MISS_BY_CODE.get(code, code))
        if code in ("start_failed", "start_unconfirmed"):
            try:
                r.setex(_k_cool(sym, side), START_FAIL_COOLDOWN_S, "1")
            except Exception:  # noqa: BLE001
                pass
        logger.warning("[%s] ⛔ %s %s 진입 안 됨 (%s, 반대 포지션 그대로): %s", R.FIX, sym, side, code, reason)
        return
    stat["entered"] += 1
    logger.warning("[%s] ✅ 진입 #%s %s %s | %s", R.FIX, si.id, sym, side, why)

    for o in (opp if flip else []):            # 새 방향이 열린 **뒤에만** 반대 포지션을 닫는다
        try:
            _flip_close(db, account, o)
            stat["flipped"] += 1
        except Exception as e:  # noqa: BLE001 — 반대 포지션은 자기 손절·익절 경로가 계속 관리한다
            db.rollback()
            miss("전환 청산 실패")
            logger.error("[%s] 🔄 #%s 전환 청산 실패 (새 방향 #%s 은 진입됨, 반대 포지션은 기존 손절·익절이 관리): %s",
                         R.FIX, o.id, si.id, e)


def run_bb_swing_once() -> dict:
    stat: dict = {"at": None, "mode": None, "symbols": 0, "sig": 0, "shadow": 0,
                  "entered": 0, "flipped": 0, "err": 0, "miss": {}}

    def miss(k: str) -> None:
        stat["miss"][k] = stat["miss"].get(k, 0) + 1

    db = SessionLocal()
    scanned = False
    r = None
    try:
        mode = R.mode_of(db)
        stat["mode"] = mode
        if mode == "off":
            return {"note": "off", **stat}
        r = get_redis_client()
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        bucket = now_ms // BAR_MS
        if now_ms - bucket * BAR_MS < SETTLE_MS:
            return {"note": "봉 마감 확정 대기", **stat}
        try:
            if r.exists(_k_scan(bucket)):
                return {"note": "같은 봉 = 이미 스캔", **stat}
        except Exception:  # noqa: BLE001
            return {"note": "Redis 실패 = 스캔 보류", **stat}

        from app.models.exchange_account import ExchangeAccount
        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            logger.warning("[%s] mainnet 계정 없음", R.FIX)
            return stat
        from app.core.api_backoff import is_account_banned
        if is_account_banned(account.id):
            logger.info("[%s] API ban 중 = 이번 분 건너뜀 (다음 분 재시도)", R.FIX)
            return stat

        caps, steps, sl_roi, cfg = _load_split_config(db)
        if cfg != "설정 OK":                    # 사장님 설정과 다른 값(기본값)으로 거래하지 않는다 — 스캔 중단 (반박 검증 9/15 L2)
            logger.error("[%s] ⛔ 자본·단계·손절 설정 손상/정합성 실패 → 스캔 중단: %s", R.FIX, cfg)
            return {"note": f"설정 오류: {cfg}", **stat}
        try:
            if not r.set(_k_scan(bucket), "1", nx=True, ex=3600):   # 원자적 — 리더가 둘이어도 한 번만
                return {"note": "같은 봉 = 다른 실행이 스캔 중", **stat}
        except Exception:  # noqa: BLE001
            return {"note": "Redis 실패 = 스캔 보류", **stat}
        scanned = True

        from app.core.crypto import decrypt_text
        from app.integrations.binance.client import BinanceClient
        from app.workers.external_strategies_worker import _universe
        bc = BinanceClient(api_key=decrypt_text(account.api_key_enc),
                           api_secret=decrypt_text(account.api_secret_enc), is_testnet=False)
        syms = [s for s in _universe(bc, db, R.setting_int(db, "bb_swing_top_n", 5, 200), 0.0) if s.isascii()]
        stat["symbols"] = len(syms)
        sides = R.sides_of(db)
        trend_mode = R.setting(db, "bb_swing_trend").lower()
        persist = R.setting_int(db, "bb_swing_short_persist", 2, 20)
        s_ind = R.indicator_of(db, "bb_swing_short_indicator")
        l_ind = R.indicator_of(db, "bb_swing_long_indicator")
        rsi_hi = R.setting_float(db, "bb_swing_rsi_high", 50, 95)
        rsi_lo = R.setting_float(db, "bb_swing_rsi_low", 5, 50)
        tol = R.setting_float(db, "bb_swing_support_tol_pct", 0, 2)
        tp1 = R.setting_float(db, "bb_swing_tp1_pct", 1, 50)
        trail = R.setting_float(db, "bb_swing_trailing_pct", 0.5, 20)
        flip = R.setting(db, "bb_swing_flip_close") == "1"
        cap_n = R.setting_int(db, "bb_swing_max_concurrent", 0, 1000)   # 가드(get_surge_max_concurrent)와 같은 원값 범위
        # ⛔ Fix 371 (2026-09-14 사장님 「모든 자동매매 중단하고 가상으로만 매매하고 학습」): 중단 중이면 on 이어도 그림자로만 기록한다.
        #   생성 게이트(strategy_service.check_create)가 어차피 막지만, 막힐 때마다 템플릿 생성→롤백·오류 로그가 쌓이고 신호 기록이 사라진다.
        from app.services.auto_trading_halt import halt_enabled
        halted = mode == "on" and halt_enabled(db)
        stat["halted"] = halted

        for sym in syms:
            try:
                kl = _completed(bc.get_klines(symbol=sym, interval="15m", limit=K15_LIMIT), now_ms)
                if len(kl) < R.MIN_15M_BARS:
                    miss("15m 봉 부족")
                    continue
                if not _is_fresh_15m(kl, bucket):
                    miss("15m 방금 마감한 봉 아님")
                    continue
                closes = [float(k[4]) for k in kl]
                lows = [float(k[3]) for k in kl]
                bar_ts = int(kl[-1][0])
                sigs = []
                if "SHORT" in sides:
                    b, why, _d = R.short_signal(closes, persist=persist, indicator=s_ind, rsi_high=rsi_hi)
                    if b is not None:
                        sigs.append(("SHORT", b, why))
                if "LONG" in sides:
                    b, why, _d = R.long_signal(closes, lows, tol_pct=tol, indicator=l_ind, rsi_low=rsi_lo)
                    if b is not None:
                        sigs.append(("LONG", b, why))
                if not sigs:
                    continue
                if not _resolve_same_bar(sigs):
                    miss("같은 봉 양방향 신호")
                    logger.info("[%s] ⏸ %s 같은 봉에 SHORT·LONG 동시 신호 = 둘 다 건너뜀", R.FIX, sym)
                    continue
                if trend_mode == "ema":        # 15m 신호가 있을 때만 4H 를 받는다 (weight 절약)
                    k4 = _completed(bc.get_klines(symbol=sym, interval="4h", limit=K4H_LIMIT), now_ms)
                    up_ok, twhy = R.uptrend_4h([float(k[4]) for k in k4])
                    if not up_ok:
                        miss("상승중 아님")
                        logger.info("[%s] ⏸ %s 15m 신호 %s — 상승중 아님 (%s)", R.FIX, sym, [s[0] for s in sigs], twhy)
                        continue
                else:
                    twhy = "추세 조건 끔"
                for side, band, why in sigs:
                    stat["sig"] += 1
                    opp = _active_family(db, sym, "LONG" if side == "SHORT" else "SHORT")
                    if mode != "on" or halted:
                        stat["shadow"] += 1
                        if halted:
                            miss("자동매매 중단 Fix371 = 그림자 기록")
                        payload = {"symbol": sym, "side": side, "bar_ts": bar_ts, "band": float(band),
                                   "close": closes[-1], "why": why, "trend": twhy,
                                   "would_flip": [o.id for o in opp],
                                   "at": datetime.now(timezone.utc).isoformat()}
                        try:
                            r.setex(_k_shadow(sym, side, bar_ts), SHADOW_TTL, json.dumps(payload, default=str))
                        except Exception:  # noqa: BLE001
                            pass
                        logger.info("[%s] 👻 shadow %s %s | %s | %s%s", R.FIX, sym, side, why, twhy,
                                    f" | 전환 대상 {[o.id for o in opp]}" if opp else "")
                        continue
                    _enter(db, r, stat, miss, account, sym=sym, side=side, close=closes[-1], why=why, opp=opp,
                           caps=caps, steps=steps, sl_roi=sl_roi, tp1=tp1, trail=trail, flip=flip, cap_n=cap_n)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                stat["err"] += 1
                logger.warning("[%s] %s 처리 실패: %s", R.FIX, sym, e)
        logger.info("[%s] 사이클 완료 mode=%s 심볼 %d 신호 %d 그림자 %d 진입 %d 전환 %d 오류 %d 사유 %s",
                    R.FIX, mode, stat["symbols"], stat["sig"], stat["shadow"], stat["entered"],
                    stat["flipped"], stat["err"], stat["miss"])
        return stat
    except Exception as e:  # noqa: BLE001
        logger.exception("[%s] 실패: %s", R.FIX, e)
        return stat
    finally:
        if scanned and r is not None:
            try:
                stat["at"] = datetime.now(timezone.utc).isoformat()
                r.setex(CYCLE_KEY, 86400, json.dumps(stat, default=str))
            except Exception:  # noqa: BLE001
                pass
        db.close()

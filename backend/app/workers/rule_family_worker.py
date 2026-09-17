"""🎯 대기열 3A·3B·3D 규칙 가족 러너 (2026-09-15 가상매매 규칙 12개로 확장) — 판정·설정·근거는 app/services/rule_families.py.

60초마다 가상매매가 새로 연 실시간 진입 행(paper_trades, source=live)을 읽는다. 가족 모드(설정 {가족}_mode):
  off    = 무시
  shadow = on 과 **같은 검사**(자리·신선도·쿨다운·전체 자동진입 OFF·반대 방향·가격 이동·하루 최대·가드)를 돌리고 결과만 Redis 에 기록
           (rf:shadow:{가족}:{심볼}:{행id}, 7일 — would_enter / blocks). **주문 없음** (기본). 쿨다운은 그림자 전용 키.
  on     = 위 검사 통과 뒤 진입 — {가족}_entry:
             split  (기본) 분할 10/100/200 = split_entry_executor.open_split_position (가드는 여기서 먼저 본다)
             single        1회 진입 = surge_ladder_entry.create_surge_position (가드 내장)
⛔ Fix 371 자동매매 중단 중이면 on 가족도 그림자로만 기록한다 (생성 게이트가 어차피 막는다 — 기록이라도 남긴다).
🗓 하루 최대 = auto_family_registry (daily_max_<가족키>, 기본 1). 여기서 먼저 보고, 생성·1차 주문에서 한 번 더 막는다.
처리한 행은 rf:seen:{행id}(2일, SET NX)로 한 번만 본다 — 막힌 주문을 다음 사이클에 다시 내지 않는다 (신호는 시간에 민감하다).
모든 가족이 피라미딩 워커 대상이 아니다 (분할 = split_entry 모드 · 단일 = single_entry_guard 등록). 재진입 워커는 strategy_type 화이트리스트,
심볼 관리 명부(Fix 365)는 OBV_REVERSE 템플릿만 등록하므로 둘 다 집어가지 않는다.

반박 검증(2026-09-13, 렌즈 1) 반영: 같은 심볼 반대 방향 차단(헤지 계정) · 전체 동시보유 상한 0(자동 진입 완전 OFF) 존중 ·
그림자도 가격 이동 검사 + 전용 쿨다운 · swing8 봉 조회 전 ban 확인 · 행 처리 표시 원자화.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.core.redis_client import get_redis_client
from app.services import rule_families as RF
from app.services import entry_conditions as EC

logger = logging.getLogger(__name__)

FIX = RF.FIX
LOOKBACK_MIN = 90                 # DB 조회 창(분). 주문 여부는 rf_max_signal_age_min 이 정한다 (Claude가 정함)
SEEN_TTL = 2 * 86400
SHADOW_TTL = 7 * 86400
START_FAIL_COOLDOWN_S = 6 * 3600  # 분할 1차 주문 실패 뒤 같은 가족·심볼 재시도 금지 (Claude가 정함)
CYCLE_KEY = "rf:last_cycle"


def _k_seen(row_id: int) -> str: return f"rf:seen:{row_id}"
def _k_shadow(fam: str, sym: str, row_id: int) -> str: return f"rf:shadow:{fam}:{sym}:{row_id}"


def _k_cool(fam: str, sym: str, shadow: bool = False) -> str:
    return f"rf:cooldown:{'shadow:' if shadow else ''}{fam}:{sym}"      # 그림자 쿨다운이 on 진입을 막지 않게 분리


def _bump(stat: dict, fam: str, what: str) -> None:
    d = stat["fam"].setdefault(fam, {})
    d[what] = d.get(what, 0) + 1


def _new_rows(db, rules: list[str], since: datetime) -> list:
    from app.models.paper_trade import PaperTrade
    return list(db.execute(
        select(PaperTrade)
        .where(PaperTrade.source == "live", PaperTrade.rule.in_(rules), PaperTrade.opened_at >= since)
        .order_by(PaperTrade.opened_at, PaperTrade.id)
    ).scalars().all())


def _last_paper_open(db) -> str | None:
    try:
        from app.models.paper_trade import PaperTrade
        v = db.execute(select(func.max(PaperTrade.opened_at)).where(PaperTrade.source == "live")).scalar()
        return v.isoformat() if v else None
    except Exception:  # noqa: BLE001
        return None


def _account(db):
    from app.models.exchange_account import ExchangeAccount
    return db.execute(select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))).scalars().first()


def _price(sym: str) -> float:
    """지금 가격 — create_surge_position 이 쓰는 것과 같은 출처. 모르면 0."""
    try:
        from app.workers.auto_bb_breakdown_worker import _get_current_price
        return float(_get_current_price(sym) or 0)
    except Exception:  # noqa: BLE001
        return 0.0


def _global_auto_off(db) -> bool:
    """전체 동시보유 상한 0 = 자동 진입 완전 OFF (position_limit Fix 108 규칙). 조회 실패 = OFF 로 본다 (fail-closed)."""
    try:
        from app.services.position_limit import get_max_concurrent
        limit, _src = get_max_concurrent(db)
        return int(limit) <= 0
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] 전체 상한 조회 실패 = 진입 안 함: %s", FIX, e)
        return True


def _halted(db) -> bool:
    """Fix 371 자동매매 중단 중인가 (행 없음 = 중단, 조회 실패 = 중단)."""
    try:
        from app.services.auto_trading_halt import halt_enabled
        return bool(halt_enabled(db))
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] 자동매매 중단 여부 조회 실패 = 중단으로 간주: %s", FIX, e)
        return True


def _daily_full(db, fam: RF.Family) -> tuple[bool, str]:
    """이 가족 오늘(KST) 하루 최대를 채웠는가. 조회 실패 = 찼다고 본다 (registry.count_today 가 fail-closed)."""
    from app.services import auto_family_registry as AF
    af = AF.family_for(strategy_type=fam.stype, template_name=None, entry_origin=None)
    if af is None or not AF.enabled(db):
        return False, "한도 끔"
    cap, used = AF.daily_max(db, af.key), AF.count_today(db, af.key)
    return used >= cap, f"오늘 {used}/{cap} (daily_max_{af.key})"


def _opposite_active(db, sym: str, side: str) -> bool:
    """같은 심볼 반대 방향에 살아 있는 전략이 있는가 (종류 무관). 조회 실패 = 있다고 본다 (fail-closed)."""
    try:
        from app.core.strategy_status import ACTIVE_LIKE
        from app.models.strategy_instance import StrategyInstance
        opp = "SHORT" if str(side).upper() == "LONG" else "LONG"
        return db.execute(
            select(StrategyInstance.id)
            .where(StrategyInstance.symbol == sym, StrategyInstance.side == opp,
                   StrategyInstance.status.in_(tuple(ACTIVE_LIKE)))
            .limit(1)
        ).scalar_one_or_none() is not None
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s 반대 방향 조회 실패 = 있다고 간주: %s", FIX, sym, e)
        return True


def _cap_default(fam: RF.Family) -> int:
    return int(float(RF.SETTINGS[f"{fam.key}_max_concurrent"][0]))


def _guards(db, acc, fam: RF.Family, sym: str) -> tuple[bool, str]:
    from app.services.surge_ladder_entry import _guards_ok
    return _guards_ok(db, acc, sym, fam.side, prefix=fam.prefix,
                      cap_key=f"{fam.key}_max_concurrent", cap_default=_cap_default(fam))


def _stop_price_pct(db, acc, fam: RF.Family, sym: str, price: float, lev: int) -> tuple[float | None, str]:
    base = RF.sl_price_pct(db, fam, lev)
    if fam.key != "rf_s2_short" or RF.setting(db, "rf_s2_short_stop_mode").lower() != "swing8":
        return base, "roi"
    try:
        from app.core.api_backoff import is_account_banned
        if is_account_banned(acc.id):                                  # 418 전력: ban 중엔 봉을 받지 않는다
            return base, "roi(ban 중)"
        from app.core.crypto import decrypt_text
        from app.integrations.binance.client import BinanceClient
        bc = BinanceClient(api_key=decrypt_text(acc.api_key_enc), api_secret=decrypt_text(acc.api_secret_enc),
                           is_testnet=acc.is_testnet)
        bars = (bc.get_klines(symbol=sym, interval="15m", limit=RF.SWING_BARS + 2) or [])[:-1]   # 진행 중 봉 제외
        sp = RF.swing8_stop_pct([float(b[2]) for b in bars], price,
                                lo=RF.setting_float(db, "rf_stop_pct_min"), hi=RF.setting_float(db, "rf_stop_pct_max"))
        if sp is not None:
            return sp, "swing8"
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s swing8 손절 계산 실패 → ROI 손절: %s", FIX, sym, e)
    return base, "roi(swing8 불가)"


def _enter_split(db, r, stat: dict, acc, fam: RF.Family, sym: str, px: float, cool_key: str, cool_s: int, row_id: int, det: dict) -> None:
    """분할 10/100/200 진입 — 가드 먼저, 실행은 공용 실행기."""
    ok, why = _guards(db, acc, fam, sym)
    if not ok:
        _bump(stat, fam.key, "guards")
        logger.info("[%s] ⏸ %s %s %s 분할 진입 보류 — %s", FIX, fam.key, sym, fam.side, why)
        return
    from app.services.split_entry_executor import open_split_position, split_total_full
    caps, steps, sl, tp1, trail, note = RF.split_config(db)
    if note != "설정 OK":                                   # 사장님 설정과 다른 값(기본값)으로 거래하지 않는다 (반박 검증 9/15 L2)
        _bump(stat, fam.key, "split_config_invalid")
        logger.error("[%s] ⛔ %s 분할 설정 손상/정합성 실패 → 진입 안 함: %s", FIX, fam.key, note)
        return
    full, twhy = split_total_full(db)                       # 분할 예약이 다른 가족 2단계를 막지 않게 (반박 검증 9/15 H1)
    if full:
        _bump(stat, fam.key, "split_total_full")
        logger.info("[%s] ⏸ %s %s %s 분할 진입 보류 — %s", FIX, fam.key, sym, fam.side, twhy)
        return
    si, code, reason = open_split_position(
        db, acc, symbol=sym, side=fam.side, price=px, strategy_type=fam.stype, name_prefix=f"{fam.prefix}_",
        label=fam.label, caps=caps, steps=steps, sl_roi=sl, tp1=tp1, trail=trail,
    )
    if si is None:
        _bump(stat, fam.key, code)
        if code in ("start_failed", "start_unconfirmed"):
            r.setex(cool_key, START_FAIL_COOLDOWN_S, "1")
        logger.warning("[%s] ⛔ %s %s %s 분할 진입 안 됨 (%s): %s", FIX, fam.label, sym, fam.side, code, reason)
        return
    if cool_s > 0:
        r.setex(cool_key, cool_s, "1")
    stat["entered"] += 1
    _bump(stat, fam.key, "entered")
    logger.warning("[%s] 🎯 %s 분할 진입 #%s %s %s 자본 %s · 가상행 #%s 자리 %s", FIX, fam.label, si.id, sym, fam.side,
                   "/".join(str(c) for c in caps), row_id, det.get("groups"))


def run_rule_families_once() -> dict:
    db = SessionLocal()
    stat: dict = {"modes": {}, "rows": 0, "shadow": 0, "entered": 0, "err": 0, "fam": {}, "last_paper_open": None, "halted": None}
    try:
        modes = {f.key: RF.mode_of(db, f.key) for f in RF.FAMILIES}
        stat["modes"] = modes
        active = {f.rule: f for f in RF.FAMILIES if modes[f.key] != "off"}
        if not active:
            return stat
        r = get_redis_client()
        now = datetime.now(timezone.utc)
        since = now - timedelta(minutes=max(LOOKBACK_MIN, RF.setting_float(db, "rf_max_signal_age_min")))
        stat["last_paper_open"] = _last_paper_open(db)
        lev = int(RF.setting_float(db, "rf_leverage")) or 2
        allow_hedge = RF.setting(db, "rf_allow_hedge").lower() in ("1", "true", "on", "yes")
        max_drift = RF.setting_float(db, "rf_max_drift_pct")
        gate_params = EC.params(db)
        halted = any(m == "on" for m in modes.values()) and _halted(db)
        stat["halted"] = halted
        acc = None
        for row in _new_rows(db, sorted(active), since):
            fam = active.get(row.rule)
            if fam is None:
                continue
            sym = row.symbol
            try:
                if not r.set(_k_seen(row.id), "1", nx=True, ex=SEEN_TTL):      # 원자적 — 한 행은 많아야 한 번
                    continue
                stat["rows"] += 1
                is_shadow = modes[fam.key] == "shadow" or halted
                dec, det = RF.decide(db, fam, {"side": row.side, "tags": row.tags, "opened_at": row.opened_at}, now=now)
                if dec != "go":
                    _bump(stat, fam.key, dec)
                    continue
                cool_key = _k_cool(fam.key, sym, is_shadow)
                if r.get(cool_key):
                    _bump(stat, fam.key, "cooldown")
                    continue
                acc = acc or _account(db)
                if acc is None:
                    _bump(stat, fam.key, "no_account")
                    continue
                cool_s = int(RF.setting_float(db, f"{fam.key}_cooldown_hours") * 3600)
                entry = float(row.entry_price)
                entry_mode = RF.entry_of(db, fam.key)

                # ── on 과 그림자가 같이 쓰는 검사 ──
                blocks: list[str] = []
                if _global_auto_off(db):
                    blocks.append("global_auto_off")
                if not allow_hedge and _opposite_active(db, sym, fam.side):
                    blocks.append("opposite_side_active")
                px = _price(sym)
                mv = RF.price_move_pct(entry, px)
                if mv is None:
                    blocks.append("no_price")
                elif mv > max_drift:
                    blocks.append("drift")
                full, dwhy = _daily_full(db, fam)
                if full:
                    blocks.append("daily_max")
                # 🎯 Fix 375: 차트 자리 게이트 — 가상행 snapshot(chart_state)만 본다 (봉을 새로 받지 않는다)
                gate_mode = RF.chart_gate_of(db, fam.key)
                gate = {"mode": gate_mode}
                if gate_mode != "off":
                    gate.update(EC.evaluate(fam.side, getattr(row, "snapshot", None), chg_24h=getattr(row, "chg_24h", None),
                                           p=gate_params))
                    if EC.blocks(gate_mode, gate):
                        blocks.append("chart_gate")

                if is_shadow:
                    ok, why = _guards(db, acc, fam, sym)
                    if not ok:
                        blocks.append("guards")
                    would = not blocks
                    payload = {"at": now.isoformat(), "family": fam.key, "rule": fam.rule, "symbol": sym, "side": fam.side,
                               "paper_trade_id": row.id, "entry": entry, "price_now": px, "entry_mode": entry_mode,
                               "drift_pct": None if mv is None else round(mv, 3), "opened_at": row.opened_at.isoformat(),
                               "tags": list(row.tags or []), **det, "would_enter": would, "blocks": blocks, "guards_why": why,
                               "daily": dwhy, "halted": halted, "chart_gate": gate}
                    r.setex(_k_shadow(fam.key, sym, row.id), SHADOW_TTL, json.dumps(payload, default=str))
                    if would and cool_s > 0:
                        r.setex(cool_key, cool_s, "1")
                    stat["shadow"] += 1
                    _bump(stat, fam.key, "shadow_would_enter" if would else f"shadow_{blocks[0]}")
                    continue

                # ── on: 실주문 ──
                if blocks:
                    _bump(stat, fam.key, blocks[0])
                    logger.info("[%s] ⏸ %s %s %s 진입 안 함 — %s (진입 봉 종가 %s · 지금 %s · %s · 차트 %s)", FIX, fam.key, sym,
                                fam.side, ",".join(blocks), entry, px, dwhy, gate.get("why"))
                    continue
                if entry_mode == "split":
                    _enter_split(db, r, stat, acc, fam, sym, px, cool_key, cool_s, row.id, det)
                    continue
                sp, stop_src = _stop_price_pct(db, acc, fam, sym, px, lev)
                cap = RF.setting_float(db, f"{fam.key}_capital_usdt")
                if sp is None or sp <= 0 or cap <= 0:
                    _bump(stat, fam.key, "bad_stop_or_capital")
                    continue
                from app.services.surge_ladder_entry import create_surge_position
                si = create_surge_position(
                    db, symbol=sym, capital=cap, sl_price_pct=sp, attempt_no=1, leverage=lev, side=fam.side,
                    template_prefix=fam.prefix, strategy_type=fam.stype, cap_key=f"{fam.key}_max_concurrent",
                    cap_default=_cap_default(fam), tp_percents=RF.tp_percents(db),
                )
                if si is None:
                    _bump(stat, fam.key, "entry_blocked")
                    continue
                if cool_s > 0:
                    r.setex(cool_key, cool_s, "1")
                stat["entered"] += 1
                _bump(stat, fam.key, "entered")
                logger.warning("[%s] 🎯 %s 진입 #%s %s %s 증거금 %.1f 손절 가격 %.2f%%(%s) · 가상행 #%s 자리 %s", FIX, fam.label,
                               si.id, sym, fam.side, cap, sp, stop_src, row.id, det.get("groups"))
            except Exception as e:  # noqa: BLE001
                stat["err"] += 1
                logger.warning("[%s] %s %s 처리 실패: %s", FIX, fam.key, sym, e)
                try:
                    db.rollback()
                except Exception:  # noqa: BLE001
                    pass
        try:
            r.setex(CYCLE_KEY, 3600, json.dumps({"at": now.isoformat(), **stat}, default=str))
        except Exception:  # noqa: BLE001
            pass
        if stat["rows"] or stat["err"]:
            logger.info("[%s] 규칙 가족: 모드=%s 새 가상행=%d 그림자=%d 진입=%d 오류=%d 중단=%s 가족별=%s 마지막 가상진입=%s", FIX, modes,
                        stat["rows"], stat["shadow"], stat["entered"], stat["err"], halted, stat["fam"], stat["last_paper_open"])
        return stat
    finally:
        db.close()

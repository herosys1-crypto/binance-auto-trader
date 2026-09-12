"""🎯 Fix 368 워커 — 후지모토 「3역 호전」 + 마하세븐 「속임수 돌파」 (판정: app/services/external_strategies.py).

60초마다 돈다. 심볼마다 **완성된 15분봉** 하나에 한 번만 판정한다 (Redis ext:last:{sym} = 마지막 판정 봉).
모드(설정 fujimoto_mode / mach7_mode):
  off    = 아무것도 안 함
  shadow = 신호만 Redis 에 기록 (ext:shadow:{family}:{sym}:{ts}, 7일) + 사이클 요약 로그. **주문 없음** (기본)
  on     = 실주문. 1차/단일 진입은 surge_ladder_entry.create_surge_position (킬스위치·ban·잔액·중복·전용 슬롯 가드 포함),
           후지모토 2·3차는 같은 인스턴스에 ExecutionService.add_position_now(mode="preserve") 로 얹고 손절 ROI 를 다시 잡는다.
두 가족 모두 우리 피라미딩 워커의 대상이 아니다 (single_entry_guard 에 등록) — 후지모토는 자기 2·3차가 곧 추가다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.redis_client import get_redis_client
from app.services import external_strategies as ES

logger = logging.getLogger(__name__)

FIX = ES.FIX
KLINE_LIMIT = 300                     # 완성봉 299 → MA200 + 여유 (Claude가 정함)
MIN_BARS = ES.MACH7_MA_LONG + ES.MACH7_TREND_LOOKBACK + 5
MIN_MARGIN_USDT = 5.0                 # 2% 룰로 깎인 뒤 이보다 작으면 진입하지 않는다 (Claude가 정함 — 거래소 최소 명목 5 의 여유)
LAST_TTL = 3 * 3600
SHADOW_TTL = 7 * 86400
STATE_TTL = 30 * 86400
CYCLE_KEY = "ext:last_cycle"


def _k_last(sym: str) -> str: return f"ext:last:{sym}"
def _k_shadow(fam: str, sym: str, ts: int) -> str: return f"ext:shadow:{fam}:{sym}:{ts}"
def _k_cool(fam: str, sym: str) -> str: return f"ext:cooldown:{fam}:{sym}"
def _k_stage(sid: int) -> str: return f"ext:fujimoto:stage:{sid}"
def _k_stop(sid: int) -> str: return f"ext:fujimoto:stop:{sid}"


def _rget(r, key: str) -> str | None:
    try:
        v = r.get(key)
        return v.decode() if isinstance(v, bytes) else v
    except Exception:  # noqa: BLE001
        return None


def _universe(bc, db, top_n: int, min_qv: float) -> list[str]:
    """거래대금 상위 N (USDT 무기한) ∩ DB 심볼 테이블."""
    from app.models.symbol import Symbol
    known = set(db.execute(select(Symbol.symbol)).scalars().all())
    rows = []
    for t in bc.get_24hr_ticker() or []:
        sym = str(t.get("symbol") or "")
        if not sym.endswith("USDT") or sym not in known:
            continue
        try:
            qv = float(t.get("quoteVolume") or 0)
        except (TypeError, ValueError):
            continue
        if qv >= min_qv:
            rows.append((qv, sym))
    rows.sort(reverse=True)
    return [s for _, s in rows[:top_n]]


def _active_by_prefix(db, prefix: str) -> dict[str, object]:
    from app.core.strategy_status import ACTIVE_LIKE
    from app.models.strategy_instance import StrategyInstance
    from app.models.strategy_template import StrategyTemplate
    rows = db.execute(
        select(StrategyInstance)
        .join(StrategyTemplate, StrategyTemplate.id == StrategyInstance.strategy_template_id)
        .where(StrategyInstance.status.in_(tuple(ACTIVE_LIKE)))
        .where(StrategyTemplate.name.ilike(f"{prefix}%"))
    ).scalars().all()
    return {si.symbol: si for si in rows}


def _equity(bc) -> float | None:
    try:
        acct = bc.get_account() or {}
        v = float(acct.get("totalWalletBalance") or acct.get("totalMarginBalance") or 0)
        return v if v > 0 else None
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] 총자산 조회 실패 (2%% 룰 상한 생략): %s", FIX, e)
        return None


def _shadow(r, stat: dict, fam: str, sym: str, ts: int, payload: dict) -> None:
    stat["shadow"] += 1
    try:
        r.setex(_k_shadow(fam, sym, ts), SHADOW_TTL, json.dumps(payload, default=str))
    except Exception:  # noqa: BLE001
        pass


def _size(db, bc_equity: float | None, *, risk_key: str, wanted: float, sp: float, lev: float) -> tuple[float, bool]:
    risk = ES.setting_float(db, risk_key)
    if bc_equity is None:
        return wanted, False
    return ES.risk_capped_margin(equity=bc_equity, risk_pct=risk, stop_price_pct=sp, leverage=lev, wanted_margin=wanted)


def _enter(db, r, stat: dict, *, fam: str, sym: str, side: str, margin: float, sp: float, lev: int,
           prefix: str, stype: str, cap_key: str, stop_price: float, cooldown_h: float, stage: int | None) -> bool:
    from app.services.surge_ladder_entry import create_surge_position
    if margin < MIN_MARGIN_USDT:
        stat["miss"]["증거금<5"] = stat["miss"].get("증거금<5", 0) + 1
        return False
    si = create_surge_position(
        db, symbol=sym, capital=margin, sl_price_pct=sp, attempt_no=1, leverage=lev, side=side,
        template_prefix=prefix, strategy_type=stype, cap_key=cap_key, cap_default=int(ES.SETTINGS[cap_key][0]),
    )
    if si is None:
        stat["miss"]["진입 차단"] = stat["miss"].get("진입 차단", 0) + 1
        return False
    stat["entered"] += 1
    try:
        r.setex(_k_cool(fam, sym), int(cooldown_h * 3600), "1")
        if stage is not None:
            r.setex(_k_stage(si.id), STATE_TTL, str(stage))
            r.setex(_k_stop(si.id), STATE_TTL, repr(float(stop_price)))
    except Exception:  # noqa: BLE001
        pass
    logger.warning("[%s] 🎯 %s 진입 #%s %s %s 증거금 %.1f 손절폭 %.2f%% (가격 %s)", FIX, fam, si.id, sym, side, margin, sp, stop_price)
    return True


def _add_stage(db, r, stat: dict, si, *, nxt: int, margin: float, stop_price: float, side: str, lev: int, sym: str) -> bool:
    """후지모토 2·3차: 같은 인스턴스에 preserve 추가 → 평단 갱신 뒤 손절 ROI 를 저장된 손절가 기준으로 다시 잡는다."""
    from app.core.crypto import decrypt_text
    from app.models.exchange_account import ExchangeAccount
    from app.services.execution_service import ExecutionService
    from app.services.surge_ladder_entry import _guards_ok
    if margin < MIN_MARGIN_USDT:
        stat["miss"]["추가 증거금<5"] = stat["miss"].get("추가 증거금<5", 0) + 1
        return False
    acc = db.get(ExchangeAccount, si.exchange_account_id)
    if acc is None:
        return False
    ok, why = _guards_ok(db, acc, sym, side, prefix=ES.FUJIMOTO_PREFIX, cap_key="fujimoto_max_concurrent",
                         cap_default=int(ES.SETTINGS["fujimoto_max_concurrent"][0]))
    if not ok and ("킬스위치" in why or "ban" in why or "잔액" in why):          # 중복·슬롯은 기존 포지션 추가엔 해당 없음
        stat["miss"]["추가 차단"] = stat["miss"].get("추가 차단", 0) + 1
        return False
    try:
        order = ExecutionService(
            db, api_key=decrypt_text(acc.api_key_enc), api_secret=decrypt_text(acc.api_secret_enc), is_testnet=acc.is_testnet,
        ).add_position_now(si.id, amount_usdt=Decimal(str(round(margin, 2))), order_type="MARKET", mode="preserve")
        if not order:
            return False
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] #%s %d차 추가 실패: %s", FIX, si.id, nxt, e)
        return False
    try:
        db.refresh(si)
        avg = float(si.avg_entry_price or 0)
        new_roi = ES.roi_for_stop(avg, stop_price, side, lev) if avg > 0 else None
        if new_roi is not None and new_roi > 0:
            si.force_sl_enabled_override = True
            si.force_sl_roi_override = Decimal(str(round(new_roi, 4)))
            db.commit()
        r.setex(_k_stage(si.id), STATE_TTL, str(nxt))
    except Exception as e:  # noqa: BLE001
        logger.error("[%s] 🚨 #%s %d차 추가는 됐는데 손절 재설정 실패 — 손절가 %s 기준이 깨졌을 수 있다: %s", FIX, si.id, nxt, stop_price, e)
        db.rollback()
    stat["added"] += 1
    logger.warning("[%s] ➕ 후지모토 #%s %s %d차 추가 %.1f USDT (손절가 %s)", FIX, si.id, sym, nxt, margin, stop_price)
    return True


def run_external_strategies_once() -> dict:
    db = SessionLocal()
    stat: dict = {"fujimoto": "off", "mach7": "off", "symbols": 0, "eval": 0, "shadow": 0, "entered": 0, "added": 0,
                  "err": 0, "sig": {"fj_L1": 0, "fj_L2": 0, "fj_L3": 0, "fj_S1": 0, "fj_S2": 0, "fj_S3": 0, "m7_L": 0, "m7_S": 0},
                  "miss": {}}
    try:
        fm, mm = ES.mode_of(db, "fujimoto_mode"), ES.mode_of(db, "mach7_mode")
        stat["fujimoto"], stat["mach7"] = fm, mm
        if fm == "off" and mm == "off":
            return stat
        from app.core.crypto import decrypt_text
        from app.integrations.binance.client import BinanceClient
        from app.models.exchange_account import ExchangeAccount
        acc = db.execute(select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))).scalar_one_or_none()
        if acc is None:
            return stat
        bc = BinanceClient(api_key=decrypt_text(acc.api_key_enc), api_secret=decrypt_text(acc.api_secret_enc), is_testnet=acc.is_testnet)
        r = get_redis_client()
        now = datetime.now(timezone.utc)
        interval = ES.setting(db, "ext_interval")
        lev = int(ES.setting_float(db, "ext_leverage")) or 2
        sp_lo, sp_hi = ES.setting_float(db, "ext_stop_pct_min"), ES.setting_float(db, "ext_stop_pct_max")
        fj_sides, m7_sides = ES.sides_of(db, "fujimoto_sides"), ES.sides_of(db, "mach7_sides")
        div_lb = int(ES.setting_float(db, "fujimoto_div_lookback"))
        swing_lb = int(ES.setting_float(db, "fujimoto_swing_lookback"))
        ratios = ES.stage_ratios(db)
        alloc = ES.setting_float(db, "fujimoto_total_alloc_usdt")
        m7_cap = ES.setting_float(db, "mach7_capital_usdt")
        m7_slope = ES.setting_float(db, "mach7_min_slope_pct")
        fj_cool, m7_cool = ES.setting_float(db, "fujimoto_cooldown_hours"), ES.setting_float(db, "mach7_cooldown_hours")
        universe = _universe(bc, db, int(ES.setting_float(db, "ext_universe_top_n")), ES.setting_float(db, "ext_min_quote_volume"))
        stat["symbols"] = len(universe)
        act_fj = _active_by_prefix(db, ES.FUJIMOTO_PREFIX) if fm != "off" else {}
        act_m7 = _active_by_prefix(db, ES.MACH7_PREFIX) if mm != "off" else {}
        equity = _equity(bc) if (fm == "on" or mm == "on") else None

        for sym in universe:
            try:
                kl = bc.get_klines(symbol=sym, interval=interval, limit=KLINE_LIMIT) or []
                bars = kl[:-1]                                   # 마지막 = 진행 중 봉 → 버린다
                if len(bars) < MIN_BARS:
                    stat["miss"]["봉 부족"] = stat["miss"].get("봉 부족", 0) + 1
                    continue
                j = len(bars) - 1
                ts = int(bars[j][0])
                if _rget(r, _k_last(sym)) == str(ts):
                    continue                                     # 이 봉은 이미 판정했다
                r.setex(_k_last(sym), LAST_TTL, str(ts))
                c = [float(b[4]) for b in bars]
                h = [float(b[2]) for b in bars]
                lo = [float(b[3]) for b in bars]
                ind = ES.compute(c, h, lo)
                stat["eval"] += 1
                price = c[j]

                # ── 후지모토 ──
                if fm != "off":
                    for side in sorted(fj_sides):
                        st = ES.fujimoto_stages(ind, j, side, div_lookback=div_lb)
                        for n in (1, 2, 3):
                            if st[n]:
                                stat["sig"][f"fj_{'L' if side == 'LONG' else 'S'}{n}"] += 1
                        si = act_fj.get(sym)
                        if si is not None:
                            if str(si.side).upper() != side:
                                continue
                            cur = int(_rget(r, _k_stage(si.id)) or 1)
                            nxt = cur + 1
                            if nxt > 3 or not st[nxt]:
                                continue
                            stop_s = _rget(r, _k_stop(si.id))
                            stop_price = float(stop_s) if stop_s else ES.swing_stop(ind, j, side, swing_lb)
                            avg = float(si.avg_entry_price or 0) or price
                            sp = ES.clamp_stop_pct(ES.stop_pct(avg, stop_price, side), sp_lo, sp_hi)
                            wanted = alloc * ratios[nxt - 1] / 100.0
                            margin, capped = _size(db, equity, risk_key="fujimoto_risk_pct", wanted=wanted, sp=sp, lev=lev)
                            payload = {"at": now.isoformat(), "family": "fujimoto", "symbol": sym, "side": side, "stage": nxt,
                                       "price": price, "stop": stop_price, "stop_pct": sp, "margin": margin, "capped": capped,
                                       "strategy_id": si.id}
                            if fm == "shadow":
                                _shadow(r, stat, "fujimoto", sym, ts, payload)
                            else:
                                _add_stage(db, r, stat, si, nxt=nxt, margin=margin, stop_price=stop_price, side=side, lev=lev, sym=sym)
                            continue
                        if not st[1] or _rget(r, _k_cool("fujimoto", sym)):
                            continue
                        stop_price = ES.swing_stop(ind, j, side, swing_lb)
                        sp = ES.clamp_stop_pct(ES.stop_pct(price, stop_price, side), sp_lo, sp_hi)
                        wanted = alloc * ratios[0] / 100.0
                        margin, capped = _size(db, equity, risk_key="fujimoto_risk_pct", wanted=wanted, sp=sp, lev=lev)
                        payload = {"at": now.isoformat(), "family": "fujimoto", "symbol": sym, "side": side, "stage": 1,
                                   "price": price, "stop": stop_price, "stop_pct": sp, "margin": margin, "capped": capped,
                                   "rsi": ind.rsi[j], "rsi_prev": ind.rsi[j - 1]}
                        if fm == "shadow":
                            _shadow(r, stat, "fujimoto", sym, ts, payload)
                            r.setex(_k_cool("fujimoto", sym), int(fj_cool * 3600), "1")
                        else:
                            _enter(db, r, stat, fam="fujimoto", sym=sym, side=side, margin=margin, sp=sp, lev=lev,
                                   prefix=ES.FUJIMOTO_PREFIX, stype=ES.FUJIMOTO_TYPE, cap_key="fujimoto_max_concurrent",
                                   stop_price=stop_price, cooldown_h=fj_cool, stage=1)

                # ── 마하세븐 ──
                if mm != "off" and sym not in act_m7:
                    for side in sorted(m7_sides):
                        ok, d = ES.mach7_signal(ind, j, side, min_slope_pct=m7_slope)
                        if not ok:
                            continue
                        stat["sig"][f"m7_{'L' if side == 'LONG' else 'S'}"] += 1
                        if _rget(r, _k_cool("mach7", sym)):
                            continue
                        stop_price = float(d["stop"])
                        sp = ES.clamp_stop_pct(ES.stop_pct(price, stop_price, side), sp_lo, sp_hi)
                        margin, capped = _size(db, equity, risk_key="mach7_risk_pct", wanted=m7_cap, sp=sp, lev=lev)
                        payload = {"at": now.isoformat(), "family": "mach7", "symbol": sym, "side": side, "price": price,
                                   "stop": stop_price, "stop_pct": sp, "margin": margin, "capped": capped,
                                   "slope_pct": d.get("slope_pct")}
                        if mm == "shadow":
                            _shadow(r, stat, "mach7", sym, ts, payload)
                            r.setex(_k_cool("mach7", sym), int(m7_cool * 3600), "1")
                        else:
                            _enter(db, r, stat, fam="mach7", sym=sym, side=side, margin=margin, sp=sp, lev=lev,
                                   prefix=ES.MACH7_PREFIX, stype=ES.MACH7_TYPE, cap_key="mach7_max_concurrent",
                                   stop_price=stop_price, cooldown_h=m7_cool, stage=None)
                        break
            except Exception as e:  # noqa: BLE001
                stat["err"] += 1
                logger.warning("[%s] %s 판정 실패: %s", FIX, sym, e)
                try:
                    db.rollback()
                except Exception:  # noqa: BLE001
                    pass
        try:
            r.setex(CYCLE_KEY, 3600, json.dumps({"at": now.isoformat(), **stat}, default=str))
        except Exception:  # noqa: BLE001
            pass
        logger.info("[%s] 완료: fujimoto=%s mach7=%s 심볼=%d 평가=%d 신호=%s 그림자=%d 진입=%d 추가=%d 오류=%d 미충족=%s",
                    FIX, fm, mm, stat["symbols"], stat["eval"], stat["sig"], stat["shadow"], stat["entered"], stat["added"],
                    stat["err"], stat["miss"])
        return stat
    finally:
        db.close()

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
from app.services import bar_gate as BG
from app.services import external_strategies as ES
from app.services import ema_pullback as EP          # 📈 Fix 423
from app.services.kline_incremental import INTERVAL_MS, IncrementalKlines
from app.services.universe_cache import cached_universe

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
def _k_last_iv(sym: str, interval: str) -> str:
    """후지모토·마하세븐 판정 봉 기록 — 15m 은 옛 키 그대로, 다른 봉은 봉별 키 (Fix 427: 15m 기록이 일봉 첫 판정을 막지 않게)."""
    return _k_last(sym) if interval == "15m" else f"ext:last:{interval}:{sym}"


def _k_last_ep(sym: str, interval: str) -> str: return f"ext:last:emapb:{interval}:{sym}"   # 🗓 Fix 424: EMA 눌림 전용 판정 봉 기록


# ⚖️ Fix 406 (2026-10-02, Duel ext-bar-gate): 60초마다 60종목 × 300봉(무게 2)을 받던 것(실측 147 weight/분 = 전체 1위) →
#   판정할 새 완성봉이 있을 때만 받고(봉 마감 게이트), 받을 때도 완료봉 증분 캐시(Fix 405 모듈). 판정 코드는 그대로.
class _CycleFetch:
    """IncrementalKlines 의 fetch — 사이클마다 그 사이클의 bc·판정 시각으로 바꿔 낀다. 응답은 check_rows 통과분만 캐시로."""

    def __init__(self) -> None:
        self.bc = None
        self.judge_ms: int | None = None
        self.stat: dict | None = None

    def __call__(self, symbol: str, interval: str, limit: int) -> list:
        if self.bc is None or self.judge_ms is None:
            raise RuntimeError("사이클 밖 kline fetch")
        if self.stat is not None:
            self.stat["kl_weight"] = self.stat.get("kl_weight", 0) + BG.kline_weight(limit)
        rows = self.bc.get_klines(symbol=symbol, interval=interval, limit=limit) or []
        return BG.check_rows(rows, INTERVAL_MS[interval], self.judge_ms)


_KFETCH = _CycleFetch()
_KC = IncrementalKlines(_KFETCH)          # 프로세스 전역 하나 — 재시작하면 첫 사이클만 전체 조회


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _closed_bars(bc, r, sym: str, interval: str, *, settle_ms: int, incremental: bool, stat: dict,
                 now_ms: int | None = None, last_key: str | None = None) -> tuple[list | None, str | None]:
    """판정할 완성봉 목록과 직전 기록값. 받을 필요가 없거나 아직 확정이 아니면 (None, None).

    ① 게이트: 기록된 마지막 판정 봉 ≥ 정착 지연 뒤 마지막 완성봉 → fetch 없음
    ② 조회: 증분 캐시 get_closed(판정 시각) 또는 기존 kl[:-1] — 둘 다 응답 마지막 행이 이미 닫혔으면(다음 봉 미개시) 보류
    ③ 기존 경로는 정착 지연 안쪽 봉을 판정하지 않는다(시간 안전). 모르는 interval 은 게이트·캐시 없이 기존 그대로.
    """
    iv = INTERVAL_MS.get(interval)
    now_ms = _now_ms() if now_ms is None else now_ms
    seen = _rget(r, last_key or _k_last(sym))           # Redis 실패 = None → 게이트 열림(기존처럼 진행) · Fix 424: 가족별 봉 키
    if iv is None:
        stat["kl_weight"] = stat.get("kl_weight", 0) + BG.kline_weight(KLINE_LIMIT)
        kl = bc.get_klines(symbol=sym, interval=interval, limit=KLINE_LIMIT) or []
        return kl[:-1], seen
    if not BG.should_fetch(seen, now_ms, iv, settle_ms):
        stat["gate_skip"] = stat.get("gate_skip", 0) + 1
        return None, None
    judge = now_ms - settle_ms
    try:
        if incremental:
            _KFETCH.bc, _KFETCH.judge_ms, _KFETCH.stat = bc, judge, stat
            # 한 행 더 받아 마지막 완성봉 299개로 자른다 — 우리 시계가 거래소보다 늦어 최신 완성봉이 아직 「미완」으로 보일 때도
            #   판정 입력이 기존 kl[:-1] 과 같은 개수(EMA200 시작점 불변). 무게는 그대로(limit ≤ 500 = 2).
            bars = _KC.get_closed(sym, interval, KLINE_LIMIT + 1, judge)[-(KLINE_LIMIT - 1):]
        else:
            stat["kl_weight"] = stat.get("kl_weight", 0) + BG.kline_weight(KLINE_LIMIT)
            kl = BG.check_rows(bc.get_klines(symbol=sym, interval=interval, limit=KLINE_LIMIT) or [], iv, judge)
            bars = kl[:-1]                               # 마지막 = 진행 중 봉 → 버린다 (기존과 같음)
            if bars and int(bars[-1][0]) > BG.last_closed_open(now_ms, iv, settle_ms):
                stat["miss"]["봉 정착 대기"] = stat["miss"].get("봉 정착 대기", 0) + 1
                return None, None                        # 정착 지연 안쪽 봉 = 다음 사이클에 판정
    except BG.BarNotSettled:
        stat["miss"]["봉 미정착"] = stat["miss"].get("봉 미정착", 0) + 1
        return None, None
    finally:
        _KFETCH.bc = _KFETCH.judge_ms = _KFETCH.stat = None
    return bars, seen


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
    stat: dict = {"fujimoto": "off", "mach7": "off", "emapb": "off", "symbols": 0, "eval": 0, "shadow": 0, "entered": 0, "added": 0,
                  "err": 0, "sig": {"fj_L1": 0, "fj_L2": 0, "fj_L3": 0, "fj_S1": 0, "fj_S2": 0, "fj_S3": 0, "m7_L": 0, "m7_S": 0, "ep_L": 0, "ep_S": 0},
                  "miss": {}}
    try:
        fm, mm = ES.mode_of(db, "fujimoto_mode"), ES.mode_of(db, "mach7_mode")
        em = ES.mode_of(db, "emapb_mode")                     # 📈 Fix 423 EMA 추세 눌림
        stat["fujimoto"], stat["mach7"], stat["emapb"] = fm, mm, em
        if fm == "off" and mm == "off" and em == "off":
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
        settle_ms = BG.parse_settle_ms(ES.setting(db, "ext_bar_settle_ms"))
        cycle_now = _now_ms()        # Fix 408: 감시 종목 스냅샷과 봉 판정이 같은 시각을 본다 (정착 경계에서 어긋나지 않게)
        top_n, min_qv = int(ES.setting_float(db, "ext_universe_top_n")), ES.setting_float(db, "ext_min_quote_volume")
        universe, stat["universe"] = cached_universe(
            r, interval=interval, interval_ms=INTERVAL_MS.get(interval), settle_ms=settle_ms, top_n=top_n, min_qv=min_qv,
            enabled=ES.setting(db, "ext_universe_per_bar"), now_ms=cycle_now,
            compute=lambda: _universe(bc, db, top_n, min_qv))   # 24h 티커(무게 40) — 새 완성봉에서만
        stat["symbols"] = len(universe)
        act_fj = _active_by_prefix(db, ES.FUJIMOTO_PREFIX) if fm != "off" else {}
        act_m7 = _active_by_prefix(db, ES.MACH7_PREFIX) if mm != "off" else {}
        act_ep = _active_by_prefix(db, EP.PREFIX) if em != "off" else {}
        ep_sides = ES.sides_of(db, "emapb_sides")
        ep_p = EP.params_from(lambda k: ES.setting(db, k))
        ep_cap, ep_cool = ES.setting_float(db, "emapb_capital_usdt"), ES.setting_float(db, "emapb_cooldown_hours")
        equity = _equity(bc) if (fm == "on" or mm == "on" or em == "on") else None
        incremental = BG.parse_flag(ES.setting(db, "ext_kline_incremental"), default=True)
        last_ttl = max(LAST_TTL, 2 * INTERVAL_MS.get(interval, 0) // 1000)   # 4h·1d 간격에서도 같은 봉 재판정 없게
        stat["gate_skip"] = stat["kl_weight"] = 0

        for sym in (universe if (fm != "off" or mm != "off") else []):   # Fix 424: 15분 가족이 모두 꺼졌으면 15분봉을 받지 않는다
            try:
                bars, seen = _closed_bars(bc, r, sym, interval, settle_ms=settle_ms, incremental=incremental, stat=stat,
                                          now_ms=cycle_now, last_key=_k_last_iv(sym, interval))
                if bars is None:
                    continue                                     # 새 완성봉 없음 · 아직 확정 아님 (Fix 406)
                if len(bars) < MIN_BARS:
                    stat["miss"]["봉 부족"] = stat["miss"].get("봉 부족", 0) + 1
                    continue
                j = len(bars) - 1
                ts = int(bars[j][0])
                if BG.already_judged(seen, ts):
                    continue                                     # 이 봉(또는 더 새 봉)은 이미 판정했다 — 단조 비교
                r.setex(_k_last_iv(sym, interval), last_ttl, str(ts))
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
        # ── 📈 EMA 추세 눌림 (Fix 423) · 🗓 Fix 424 사장님 「전부 일봉」: 자기 봉(emapb_interval)으로 따로 판정 ──
        #   봉 마감 게이트·증분 캐시는 같은 것을 쓰고, 판정 기록 키만 가족 전용(15분 가족과 섞이지 않게). 1회 진입.
        if em != "off":
            ep_iv = ES.setting(db, "emapb_interval")
            ep_iv = ep_iv if ep_iv in INTERVAL_MS else "1d"
            ep_ttl = max(LAST_TTL, 2 * INTERVAL_MS[ep_iv] // 1000)
            stat["ep_interval"] = ep_iv
            ep_universe = EP.coin_symbols(None, universe) if EP.coin_only_on(lambda k: ES.setting(db, k)) else list(universe)
            stat["ep_symbols"] = len(ep_universe)          # Fix 425: 코인 무기한만 (주식·금·원유 제외)
            for sym in ep_universe:
                if sym in act_ep:
                    continue
                try:
                    lk = _k_last_ep(sym, ep_iv)
                    bars, seen = _closed_bars(bc, r, sym, ep_iv, settle_ms=settle_ms, incremental=incremental, stat=stat,
                                              now_ms=cycle_now, last_key=lk)
                    if bars is None:
                        continue
                    if len(bars) < EP.min_bars(ep_p):
                        stat["miss"]["EMA눌림 봉 부족"] = stat["miss"].get("EMA눌림 봉 부족", 0) + 1
                        continue
                    j = len(bars) - 1
                    ts = int(bars[j][0])
                    if BG.already_judged(seen, ts):
                        continue
                    c = [float(b[4]) for b in bars]
                    h = [float(b[2]) for b in bars]
                    lo = [float(b[3]) for b in bars]
                    v = [float(b[5]) for b in bars]
                    e_ = EP.emas(c)
                    price = c[j]
                    stat["ep_eval"] = stat.get("ep_eval", 0) + 1
                    for side in sorted(ep_sides):
                        ok, d = EP.signal(c, h, lo, v, j, side, ep_p, e_)
                        if not ok:
                            continue
                        stat["sig"][f"ep_{'L' if side == 'LONG' else 'S'}"] += 1
                        if _rget(r, _k_cool("emapb", sym)):
                            continue
                        stop_price = float(d["stop"])
                        sp = ES.clamp_stop_pct(ES.stop_pct(price, stop_price, side), sp_lo, sp_hi)
                        margin, capped = _size(db, equity, risk_key="emapb_risk_pct", wanted=ep_cap, sp=sp, lev=lev)
                        payload = {"at": now.isoformat(), "family": "emapb", "interval": ep_iv, "symbol": sym, "side": side,
                                   "price": price, "stop": stop_price, "stop_pct": sp, "margin": margin, "capped": capped,
                                   "vol_ratio": d.get("vol_ratio"), "fib": d.get("fib"), "confluence": d.get("confluence"),
                                   "macro": d.get("macro"), "ema200": d.get("ema200")}
                        if em == "shadow":
                            _shadow(r, stat, "emapb", sym, ts, payload)
                            r.setex(_k_cool("emapb", sym), int(ep_cool * 3600), "1")
                        else:
                            _enter(db, r, stat, fam="emapb", sym=sym, side=side, margin=margin, sp=sp, lev=lev,
                                   prefix=EP.PREFIX, stype=EP.STYPE, cap_key="emapb_max_concurrent",
                                   stop_price=stop_price, cooldown_h=ep_cool, stage=None)
                        break
                    r.setex(lk, ep_ttl, str(ts))         # 교차 감사: 처리를 마친 뒤 기록 — 일시 오류면 다음 주기(1분)에 다시 판정
                except Exception as e:  # noqa: BLE001
                    stat["err"] += 1
                    logger.warning("[%s] EMA눌림 %s 판정 실패: %s", FIX, sym, e)
                    try:
                        db.rollback()
                    except Exception:  # noqa: BLE001
                        pass
        try:
            r.setex(CYCLE_KEY, 3600, json.dumps({"at": now.isoformat(), **stat}, default=str))
        except Exception:  # noqa: BLE001
            pass
        logger.info("[%s] 완료: fujimoto=%s mach7=%s emapb=%s 심볼=%d 평가=%d 신호=%s 그림자=%d 진입=%d 추가=%d 오류=%d 미충족=%s",
                    FIX, fm, mm, em, stat["symbols"], stat["eval"], stat["sig"], stat["shadow"], stat["entered"], stat["added"],
                    stat["err"], stat["miss"])
        return stat
    finally:
        db.close()

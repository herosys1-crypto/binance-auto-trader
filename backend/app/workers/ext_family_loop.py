"""🧩 Fix 431·432 — 외부 전략 「단순 가족」 공용 판정 루프 (새 전략을 계속 붙이기 위한 틀).

가족 모듈이 아래만 갖추면 external_strategies_worker 가 같은 루프로 돌린다 (봉 마감 게이트·증분 캐시·그림자·실주문 경로 공용):
  PREFIX · STYPE · SETTINGS · params_from(get) · min_bars(p) · evaluate(bars, j, side, p, cache) -> (ok, d{stop, ...})
  설정 키: <key>_mode · <key>_sides · <key>_interval · <key>_capital_usdt · <key>_cooldown_hours · <key>_risk_pct · <key>_max_concurrent
판정 기록 키 = ext:last:<key>:<interval>:<sym> (가족 전용) — 처리를 마친 뒤 기록(일시 오류면 다음 주기 재판정).
`force_shadow` = 실주문 청산이 출처 청산과 달라 on 이어도 shadow 로 돌리는 가족 (Fix 429 선례).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from types import ModuleType
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Family:
    key: str                     # 설정·Redis 접두 (bbwave, trima)
    mod: ModuleType              # 판정 모듈
    label: str                   # 로그·미충족 이름
    intervals: tuple[str, ...]   # 허용 판정 봉 (첫 값 = 기본)
    force_shadow: str = ""       # 비어 있지 않으면 on → shadow + 이 이유를 경고


def k_last(key: str, interval: str, sym: str) -> str:
    return f"ext:last:{key}:{interval}:{sym}"


def mode(ES, db, fam: Family) -> str:
    m = ES.mode_of(db, f"{fam.key}_mode")
    if m == "on" and fam.force_shadow:
        logger.warning("[%s] %s_mode=on 이지만 %s → shadow 로 동작", fam.mod.FIX, fam.key, fam.force_shadow)
        return "shadow"
    return m


def run(ext: Any, fam: Family, m: str, *, db, r, bc, stat: dict, universe: list[str], cycle_now: int, settle_ms: int,
        incremental: bool, equity, lev: int, sp_lo: float, sp_hi: float, now) -> None:
    """ext = external_strategies_worker 모듈 (공용 도우미: _closed_bars · _shadow · _enter · _size · _k_cool · _rget · BG · ES)."""
    if m == "off":
        return
    ES, BG = ext.ES, ext.BG
    iv = ES.setting(db, f"{fam.key}_interval")
    if iv not in fam.intervals:
        logger.warning("[%s] %s_interval=%r 는 지원 안 함 → %s", fam.mod.FIX, fam.key, iv, fam.intervals[0])
        iv = fam.intervals[0]
    ttl = max(ext.LAST_TTL, 2 * ext.INTERVAL_MS[iv] // 1000)
    p = fam.mod.params_from(lambda k: ES.setting(db, k))
    sides = ES.sides_of(db, f"{fam.key}_sides")
    cap, cool = ES.setting_float(db, f"{fam.key}_capital_usdt"), ES.setting_float(db, f"{fam.key}_cooldown_hours")
    active = ext._active_by_prefix(db, fam.mod.PREFIX)
    stat[f"{fam.key}_interval"] = iv
    for side in ("LONG", "SHORT"):
        stat["sig"].setdefault(f"{fam.key}_{side[0]}", 0)
    for sym in universe:
        if sym in active:
            continue
        try:
            lk = k_last(fam.key, iv, sym)
            bars, seen = ext._closed_bars(bc, r, sym, iv, settle_ms=settle_ms, incremental=incremental, stat=stat,
                                          now_ms=cycle_now, last_key=lk)
            if bars is None:
                continue
            if len(bars) < fam.mod.min_bars(p):
                stat["miss"][f"{fam.label} 봉 부족"] = stat["miss"].get(f"{fam.label} 봉 부족", 0) + 1
                continue
            j = len(bars) - 1
            ts = int(bars[j][0])
            if BG.already_judged(seen, ts):
                continue
            price = float(bars[j][4])
            stat[f"{fam.key}_eval"] = stat.get(f"{fam.key}_eval", 0) + 1
            cache: dict = {}
            for side in sorted(sides):
                ok, d = fam.mod.evaluate(bars, j, side, p, cache)
                if not ok:
                    continue
                stat["sig"][f"{fam.key}_{side[0]}"] += 1
                if ext._rget(r, ext._k_cool(fam.key, sym)):
                    continue
                stop_price = float(d["stop"])
                sp = ES.clamp_stop_pct(ES.stop_pct(price, stop_price, side), sp_lo, sp_hi)
                margin, capped = ext._size(db, equity, risk_key=f"{fam.key}_risk_pct", wanted=cap, sp=sp, lev=lev)
                payload = {"at": now.isoformat(), "family": fam.key, "interval": iv, "symbol": sym, "side": side,
                           "price": price, "stop": stop_price, "stop_pct": sp, "margin": margin, "capped": capped,
                           "detail": {k: v for k, v in d.items() if isinstance(v, (int, float, bool, str)) and k != "stop"}}
                if m == "shadow":
                    ext._shadow(r, stat, fam.key, sym, ts, payload)
                    r.setex(ext._k_cool(fam.key, sym), int(cool * 3600), "1")
                else:
                    ext._enter(db, r, stat, fam=fam.key, sym=sym, side=side, margin=margin, sp=sp, lev=lev,
                               prefix=fam.mod.PREFIX, stype=fam.mod.STYPE, cap_key=f"{fam.key}_max_concurrent",
                               stop_price=stop_price, cooldown_h=cool, stage=None)
                break
            r.setex(lk, ttl, str(ts))
        except Exception as e:  # noqa: BLE001
            stat["err"] += 1
            logger.warning("[%s] %s %s 판정 실패: %s", fam.mod.FIX, fam.label, sym, e)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass

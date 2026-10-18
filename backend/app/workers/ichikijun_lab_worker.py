"""🗾 Fix 465 워커 — 일목 기준선 변형 실험실 (가상 전용 · 주문 0).

사장님 2026-10-18: 「가상매매로 이 전략을 수정해서 승률이 제일 높은 방법을 지속적으로 찾아서 업데이트하는 방법으로 개선」.

run_ichikijun_lab_once  (15분마다) — 1h·4h·1d 중 **새 완성봉이 생긴 봉만** (Redis ichilab:last:{iv}):
  ① 그 봉 열린 행 정산 (진입 뒤 완성봉을 처음부터 다시 걷는다 = 상태 없음)
  ② 변형 24줄(봉당) × 2방향 신호 판정 → 신호 행 + 같은 시각 무작위 짝 행 (같은 손절폭·같은 청산)
     같은 변형·방향·심볼에 열린 신호 행이 있으면 건너뜀(겹침 없음)
run_ichikijun_board_once (매일 KST 10:30) — 순위표(Redis ichilab:board) · 챔피언 갱신(system_settings) · 바뀌면 텔레그램 1통.
klines·24h 티커 읽기만. 실패한 봉은 기록하지 않고 다음 사이클에 다시.
"""
from __future__ import annotations

import json
import logging
import random
import zlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.services import bar_gate as BG
from app.services import ichikijun_lab as LAB
from app.services import ichimoku_kijun as IK

logger = logging.getLogger(__name__)

FIX = IK.FIX
IV_MS = {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
KLINE_LIMIT = 300                 # 무게 2 · 지표 최소봉 + 최대 보유 60 + 여유 (Claude가 정함)
SETTLE_MS = 60_000                # 봉 마감 뒤 1분 기다린다 (Claude가 정함)
K_LAST = "ichilab:last:{iv}"
K_BOARD = "ichilab:board"
K_UNIV = "ichilab:universe"
UNIV_TTL = 3600
S_STARTED = "ichilab_started_at"
S_CHAMP = "ichikijun_champion"
S_HIST = "ichikijun_champion_history"
S_STREAK = "ichikijun_champion_streak"
LAST_TTL = 3 * 86400
GONE_GRACE_BARS = 10          # 진입 봉을 못 받는 열린 행: 최대 보유 + 이 봉 수 뒤 GONE (Claude가 정함)


def _setting(db, key: str) -> str | None:
    from app.models.system_setting import SystemSetting
    row = db.get(SystemSetting, key)
    v = None if row is None or row.value is None else str(row.value).strip()
    return v or None


def _set_setting(db, key: str, value: str) -> None:
    from app.models.system_setting import SystemSetting
    row = db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=value))
    else:
        row.value = value


def _params(db) -> dict[str, float]:
    return LAB.params_from(lambda k: _setting(db, k))


def _universe(bc, r, top_n: int) -> list[str]:
    try:
        raw = r.get(K_UNIV)
        if raw:
            snap = json.loads(raw)
            if snap.get("top_n") == top_n and isinstance(snap.get("symbols"), list):
                return list(snap["symbols"])
    except Exception:  # noqa: BLE001 — 캐시 문제 = 새로 계산
        pass
    tick = bc.get_24hr_ticker() or []
    rows = []
    for t in tick:
        s = str(t.get("symbol", ""))
        if not s.endswith("USDT") or not s.isascii() or "_" in s:
            continue
        try:
            rows.append((float(t.get("quoteVolume") or 0), s))
        except (TypeError, ValueError):
            continue
    syms = [s for _, s in sorted(rows, reverse=True)[:top_n]]
    try:
        r.setex(K_UNIV, UNIV_TTL, json.dumps({"top_n": top_n, "symbols": syms}))
    except Exception:  # noqa: BLE001
        pass
    return syms


def _closed(bc, sym: str, iv: str, target: int) -> IK.Bars | None:
    """target(마지막 완성봉 open) 까지의 완성봉. target 봉이 아직 응답에 없으면 None(다음 사이클)."""
    kl = bc.get_klines(symbol=sym, interval=iv, limit=KLINE_LIMIT) or []
    kl = [b for b in kl if isinstance(b, (list, tuple)) and b and int(b[0]) <= target]
    if not kl or int(kl[-1][0]) != target:
        return None
    return IK.bars_from(kl)


def _pair_pick(var: str, side: str, sym: str, ts: int, cands: list[str], taken: set[str]) -> str | None:
    pool = sorted(c for c in cands if c != sym and c not in taken)
    if not pool:
        return None
    return random.Random(zlib.crc32(f"{var}|{side}|{sym}|{ts}".encode())).choice(pool)


def _close_row(row, res: dict, risk: float, cost: float) -> None:
    row.status = "CLOSED"
    row.exit_reason = res["exit"]
    row.r_gross = Decimal(f'{res["r"]:.4f}')
    row.r_net = Decimal(f"{IK.net_r(res['r'], risk, cost):.4f}")
    row.bars_held = int(res["bars"])
    row.closed_at = datetime.fromtimestamp(res["exit_ts"] / 1000, tz=timezone.utc)


def process_interval(db, bc, r, iv: str, now_ms: int, params: dict[str, float], stat: dict) -> bool:
    """한 봉(iv)의 새 완성봉 처리. 처리했으면 True (Redis 기록은 호출 측이 commit 뒤에)."""
    from app.models.ichikijun_lab_trade import IchikijunLabTrade as T

    ms = IV_MS[iv]
    target = BG.last_closed_open(now_ms, ms, SETTLE_MS)
    seen = BG.parse_open(r.get(K_LAST.format(iv=iv)))
    if seen is not None and seen >= target:
        return False
    open_rows = db.execute(select(T).where(T.interval == iv, T.status == "OPEN")).scalars().all()
    univ = _universe(bc, r, int(params["ichilab_top_n"]))
    syms = sorted(set(univ) | {"BTCUSDT"} | {x.symbol for x in open_rows})
    bars: dict[str, IK.Bars] = {}
    for s in syms:
        try:
            B = _closed(bc, s, iv, target)
        except Exception as e:  # noqa: BLE001
            stat["fetch_err"] = stat.get("fetch_err", 0) + 1
            logger.debug("[%s] %s %s 봉 실패: %s", FIX, s, iv, e)
            B = None
        if B is not None:
            bars[s] = B
        stat["fetched"] = stat.get("fetched", 0) + 1
    btc = bars.get("BTCUSDT")
    if btc is None:
        stat["skip"] = f"{iv}: BTC 봉 없음"
        return False                                     # BTC 장세를 모르면 이 봉 전체를 다음 사이클로
    bs = IK.sma(btc.c, IK.BTC_SMA)
    btc_up = {t: (btc.c[i] > bs[i]) if bs[i] is not None else None for i, t in enumerate(btc.ts)}
    cost = params["ichilab_cost_pct"]
    # ① 정산
    for row in open_rows:
        B = bars.get(row.symbol)
        j = None
        if B is not None:
            try:
                j = B.ts.index(int(row.entry_bar_ts))
            except ValueError:
                j = None
        if j is None:
            # 교차 감사: 상장폐지·거래정지·긴 장애로 진입 봉을 더는 못 받는 행은 영원히 OPEN 으로 남는다
            #   → 최대 보유 + 여유를 넘기면 GONE(결과 없음, 순위표 제외)으로 닫는다.
            if target - int(row.entry_bar_ts) > (IK.MAX_HOLD + GONE_GRACE_BARS) * ms:
                row.status, row.exit_reason = "CLOSED", "GONE"
                row.closed_at = datetime.fromtimestamp(target / 1000, tz=timezone.utc)
                stat["gone"] = stat.get("gone", 0) + 1
            continue
        v = IK.BY_KEY.get(row.variant)
        if v is None:
            continue
        risk = float(row.stop_pct) / 100.0
        res = IK.simulate(B, j, row.side, risk, v.rr, v.kijun_exit)
        row.bars_held = int(res["bars"])
        if res["status"] == "CLOSED":
            _close_row(row, res, risk, cost)
            stat["closed"] = stat.get("closed", 0) + 1
    # ② 새 신호 (마지막 완성봉 = target)
    open_sig = {(x.variant, x.side, x.symbol) for x in open_rows if x.kind == "sig" and x.status == "OPEN"}
    ready = [s for s in univ if s in bars and bars[s].ts[-1] == target and len(bars[s].c) > IK.min_bars()]
    opened_at = datetime.fromtimestamp((target + ms) / 1000, tz=timezone.utc)
    for v in (x for x in IK.VARIANTS if x.iv == iv):
        for side in ("LONG", "SHORT"):
            taken: set[str] = set()
            for s in ready:
                if (v.key, side, s) in open_sig:
                    continue
                B = bars[s]
                k = len(B.c) - 1
                ok, stop, j_sig = IK.entry_at(B, k, side, v, lambda i, B=B: btc_up.get(B.ts[i]))
                if not ok:
                    continue
                risk, clamped = IK.clamp_stop(B.c[k], stop)
                common = {"variant": v.key, "side": side, "interval": iv, "signal_bar_ts": B.ts[j_sig],
                          "entry_bar_ts": target, "stop_pct": Decimal(f"{risk * 100:.4f}"), "clamped": clamped,
                          "btc_up": btc_up.get(target), "status": "OPEN", "opened_at": opened_at}
                db.add(T(kind="sig", symbol=s, entry_price=Decimal(str(B.c[k])), **common))
                stat["signals"] = stat.get("signals", 0) + 1
                p = _pair_pick(v.key, side, s, target, ready, taken)
                if p is not None:
                    taken.add(p)
                    db.add(T(kind="rand", symbol=p, pair_symbol=s, entry_price=Decimal(str(bars[p].c[-1])), **common))
    return True


def run_ichikijun_lab_once(decrypt_text) -> dict[str, Any]:
    from app.core.redis_client import get_redis_client
    from app.workers.chart_learning_worker import _open

    stat: dict[str, Any] = {}
    db, bc = _open(decrypt_text)
    if db is None:
        return {"error": "no account"}
    try:
        if str(_setting(db, "ichilab_enabled") or "1") in ("0", "false", "off"):
            return {"skipped": "disabled"}
        if not _setting(db, S_STARTED):
            _set_setting(db, S_STARTED, datetime.now(timezone.utc).isoformat())   # 최초 1회 · 이후 덮지 않음(판정 창 시작)
            db.commit()
        r = get_redis_client()
        params = _params(db)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        for iv in IK.INTERVALS:
            try:
                if process_interval(db, bc, r, iv, now_ms, params, stat):
                    db.commit()
                    r.setex(K_LAST.format(iv=iv), LAST_TTL, str(BG.last_closed_open(now_ms, IV_MS[iv], SETTLE_MS)))
                    stat.setdefault("done", []).append(iv)
            except Exception as e:  # noqa: BLE001 — 한 봉 실패가 다른 봉을 막지 않게
                db.rollback()
                stat.setdefault("err", []).append(f"{iv}: {e!r:.120}")
                logger.warning("[%s] 실험실 %s 처리 실패 (다음 사이클 재시도): %s", FIX, iv, e)
        if stat.get("done"):
            logger.info("[%s] 일목 실험실 %s", FIX, stat)
        return stat
    finally:
        db.close()


def _rows_for_board(db, since: datetime) -> list[dict]:
    from app.models.ichikijun_lab_trade import IchikijunLabTrade as T
    q = select(T.kind, T.variant, T.side, T.symbol, T.pair_symbol, T.entry_bar_ts, T.r_net).where(
        T.status == "CLOSED", T.opened_at >= since)
    out = []
    for kind, var, side, sym, pair, ts, rn in db.execute(q):
        key_sym = sym if kind == "sig" else pair
        out.append({"kind": kind, "variant": var, "side": side, "symbol": sym, "entry_bar_ts": int(ts),
                    "r_net": None if rn is None else float(rn), "pair_key": f"{var}|{side}|{key_sym}|{ts}"})
    return out


def _applied(db) -> dict:
    """🗾 Fix 466 — 일목 진입 신호 예약 인스턴스의 실주문 결과 vs 같은 진입의 실험실 결과."""
    from app.models.ichikijun_lab_trade import IchikijunLabTrade as T
    from app.models.strategy_instance import StrategyInstance as SI
    from app.models.strategy_stage_plan import StrategyStagePlan as SP
    from app.services import ichikijun_apply as IA

    sis = db.execute(select(SI).where(SI.entry_signal.like("ichikijun%"))).scalars().all()
    items, keys = [], set()
    for si in sis:
        plans = db.execute(select(SP).where(SP.strategy_instance_id == si.id)).scalars().all()
        p1 = next((p for p in plans if p.stage_no == 1), None)
        meta = si.entry_signal_meta or {}
        items.append({"id": si.id, "symbol": si.symbol, "side": si.side, "status": si.status, "leverage": si.leverage,
                      "realized_pnl": float(si.realized_pnl or 0),
                      "stage1_capital": float(p1.planned_capital) if p1 is not None else None,
                      "stages": sum(1 for p in plans if p.is_enabled), "entry_signal": si.entry_signal, "meta": meta,
                      "started_at": si.started_at.isoformat() if si.started_at else None,
                      "stopped_at": si.stopped_at.isoformat() if si.stopped_at else None})
        if meta.get("variant") and meta.get("entry_bar_ts"):
            keys.add((meta["variant"], si.side, si.symbol, int(meta["entry_bar_ts"])))
    lab: dict[tuple, float] = {}
    for var, side, sym, ts in keys:
        rn = db.execute(select(T.r_net).where(T.kind == "sig", T.variant == var, T.side == side, T.symbol == sym,
                                              T.entry_bar_ts == ts, T.status == "CLOSED")).scalar()
        if rn is not None:
            lab[(var, side, sym, ts)] = float(rn)
    return IA.applied_report(items, lab)


S_APPLIED_N = "ichikijun_applied_finished_n"


def run_ichikijun_board_once() -> dict[str, Any]:
    from app.core.database import SessionLocal
    from app.core.redis_client import get_redis_client

    db = SessionLocal()
    try:
        started = _setting(db, S_STARTED)
        if not started:
            return {"skipped": "not started"}
        params = _params(db)
        since = datetime.fromisoformat(started)
        board = LAB.build_board(_rows_for_board(db, since), params)
        today = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")
        prev = json.loads(_setting(db, S_CHAMP) or "null")
        streak = json.loads(_setting(db, S_STREAK) or "null")
        champ, streak, changed = LAB.update_champion(prev, board, streak, params, today)
        _set_setting(db, S_STREAK, json.dumps(streak))
        if champ is not None:
            _set_setting(db, S_CHAMP, json.dumps(champ, ensure_ascii=False))
        if changed and champ is not None:
            hist = json.loads(_setting(db, S_HIST) or "[]")[-49:]
            hist.append(champ)
            _set_setting(db, S_HIST, json.dumps(hist, ensure_ascii=False))
        db.commit()
        try:
            applied = _applied(db)
        except Exception as e:  # noqa: BLE001 — 결과 검토 실패가 순위표를 막지 않게
            db.rollback()
            logger.warning("[%s] 적용 결과 검토 실패: %s", FIX, e)
            applied = {"rows": [], "summary": {}, "error": f"{e!r:.120}"}
        fin_n = int((applied.get("summary") or {}).get("finished") or 0)
        prev_fin = int(_setting(db, S_APPLIED_N) or 0)
        if fin_n != prev_fin:
            _set_setting(db, S_APPLIED_N, str(fin_n))
            db.commit()
        payload = {"at": datetime.now(timezone.utc).isoformat(), "since": started, "champion": champ,
                   "streak": streak, "board": board, "applied": applied}
        try:
            get_redis_client().setex(K_BOARD, 3 * 86400, json.dumps(payload, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] 순위표 Redis 기록 실패: %s", FIX, e)
        if changed and champ is not None:
            try:
                from app.services.notification_service import NotificationService
                NotificationService(db).send_system_alert(
                    title="🗾 일목 실험실 챔피언 바뀜",
                    body=(f'{champ["variant"]} {champ["side"]} · 점수(무작위 대비 95% 아래 끝) {champ["score"]:+.3f}R · '
                          f'승률 {champ["win"]:.0%} · {champ["n"]}건/{champ["days"]}일\n(가상 전용 — 실주문은 사장님 승인)'))
            except Exception as e:  # noqa: BLE001
                logger.warning("[%s] 텔레그램 실패: %s", FIX, e)
        sm = applied.get("summary") or {}
        if fin_n > prev_fin:
            try:
                from app.services.notification_service import NotificationService
                f = (lambda x: "—" if x is None else f"{x:+.2f}R")
                NotificationService(db).send_system_alert(
                    title="🗾 일목 신호 예약 — 실주문 결과",
                    body=(f'끝난 {sm.get("finished")}건 · 실주문 평균 {f(sm.get("live_avg_r"))} · '
                          f'같은 진입 실험실 {f(sm.get("lab_avg_r"))} (짝 {sm.get("paired")}건) · 차이 {f(sm.get("diff_avg_r"))} · '
                          f'실현 합계 {sm.get("pnl_sum", 0):+.2f} USDT'))
            except Exception as e:  # noqa: BLE001
                logger.warning("[%s] 적용 결과 텔레그램 실패: %s", FIX, e)
        return {"rows": len(board), "champion": champ, "changed": changed, "applied": sm}
    finally:
        db.close()

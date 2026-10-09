"""🗓 Fix 424 (2026-10-09 사장님) — EMA 추세 눌림 「진입 준비」·「진입 신호」 알림 (텔레그램 + 화면).

사장님: "내가 이 전략을 할꺼야 — 롱이든 숏 진입 준비 단계일 때 알려줘" · 판정 봉 = 일봉(「전부 일봉」).

- 진입 준비: 어제까지 일봉으로 추세(가격 vs EMA20·기울기)와 정배열(10/20/50)이 맞고, **오늘 현재가**가 EMA20 근처까지 눌려 옴
             (LONG: EMA20 −허용오차 ~ +emapb_ready_near_pct%, EMA50 위 / SHORT 반대). 같은 심볼·방향은 하루 한 번만 알림.
- 진입 신호: 방금 닫힌 일봉이 전략 조건 전부 충족(눌림 + 거래량 + 마감 확정) — 자동매매·가상매매와 같은 판정 함수.
- 주문은 내지 않는다(알림·화면 전용). 15분마다 · 감시 종목 = 외부 전략과 같은 거래대금 상위 목록 · 일봉 300개(무게 2).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.redis_client import get_redis_client
from app.services import ema_pullback as EP
from app.services import external_strategies as ES
from app.services.kline_incremental import INTERVAL_MS

logger = logging.getLogger(__name__)
FIX = "Fix424"
BOARD_KEY = "emapb:board"
BOARD_TTL = 3 * 3600
LIMIT = 300


def _k_sent(kind: str, sym: str, side: str, tag: str) -> str:
    return f"emapb:alert:{kind}:{sym}:{side}:{tag}"


def _fmt(x: float | None) -> str:
    if x is None:
        return "-"
    return f"{x:.6g}"


def scan_symbol(rows: list, side: str, *, p: dict, near_pct: float, now_ms: int, iv_ms: int) -> list[dict]:
    """한 심볼·한 방향의 상태 목록 — 진입 신호와 진입 준비를 **따로** 본다(교차 감사). rows = 거래소 kline 행(진행 중 봉 포함 가능).

    교차 감사: 마지막 완성봉이 「방금 닫힌 봉」(지금 기준 직전 봉)이 아니면 묵은 응답 → 아무것도 내지 않는다.
    진입 준비의 현재가는 **지금 진행 중인 봉**의 종가만 쓴다(없으면 준비 판정 안 함).
    """
    closed = [b for b in rows if int(b[0]) + iv_ms <= now_ms]
    if len(closed) < EP.min_bars(p):
        return []
    cur_open = now_ms // iv_ms * iv_ms
    if int(closed[-1][0]) != cur_open - iv_ms:
        return []
    live_row = rows[-1] if rows and int(rows[-1][0]) == cur_open else None
    c = [float(b[4]) for b in closed]
    h = [float(b[2]) for b in closed]
    lo = [float(b[3]) for b in closed]
    v = [float(b[5]) for b in closed]
    e = EP.emas(c)
    j = len(c) - 1
    out: list[dict] = []
    sig, sd = EP.signal(c, h, lo, v, j, side, p, e)
    if sig:
        out.append({"kind": "signal", "side": side, "price": c[j], "bar": int(closed[j][0]), "stop": sd["stop"],
                    "ema20": e[EP.EMA_MID][j], "vol_ratio": sd.get("vol_ratio"), "confluence": sd.get("confluence")})
    if live_row is not None:
        live = float(live_row[4])
        ready, rd = EP.ready_state(c, h, lo, v, live, side, p, e, near_pct=near_pct)
        if ready:
            out.append({"kind": "ready", "side": side, "price": live, "bar": int(closed[j][0]), "stop": rd["stop"],
                        "ema20": rd["ema20"], "ema50": rd["ema50"], "dist_pct": rd["dist_pct"]})
    return out


def _line(it: dict) -> str:
    arrow = "🟢 LONG" if it["side"] == "LONG" else "🔴 SHORT"
    if it["kind"] == "signal":
        return (f"{arrow} {it['symbol']} ✅ 진입 신호(일봉 마감 확정) 종가 {_fmt(it['price'])} · EMA20 {_fmt(it['ema20'])} "
                f"· 손절 {_fmt(it['stop'])} · 거래량 ×{(it.get('vol_ratio') or 0):.2f}{' · 지표 겹침' if it.get('confluence') else ''}")
    return (f"{arrow} {it['symbol']} ⏳ 진입 준비 현재가 {_fmt(it['price'])} · EMA20 {_fmt(it['ema20'])} "
            f"({(it.get('dist_pct') or 0):+.2f}%) · 손절 후보 {_fmt(it['stop'])}")


MSG_LIMIT = 3500        # 텔레그램 4096자 제한 아래로 나눠 보낸다 (교차 감사)


def chunks(lines: list[str], limit: int = MSG_LIMIT) -> list[list[str]]:
    out: list[list[str]] = [[]]
    size = 0
    for ln in lines:
        if out[-1] and size + len(ln) + 1 > limit:
            out.append([])
            size = 0
        out[-1].append(ln)
        size += len(ln) + 1
    return [c for c in out if c]


def _send(db, r, fresh: list[dict], iv: str) -> int:
    """묶어서(나눠서) 보낸다. 실패한 묶음의 중복 키는 지워 다음 주기에 다시 보낸다(교차 감사). 보낸 건수."""
    from app.services.notification_service import NotificationService
    fresh = sorted(fresh, key=lambda x: (x["kind"] != "signal", x["symbol"]))
    n_sig = sum(1 for x in fresh if x["kind"] == "signal")
    groups = chunks([_line(x) for x in fresh])
    sent, idx = 0, 0
    for gi, g in enumerate(groups, start=1):
        items = fresh[idx:idx + len(g)]
        idx += len(g)
        title = f"📈 EMA 추세 눌림({iv}) — 진입 신호 {n_sig} · 진입 준비 {len(fresh) - n_sig}" + (f" ({gi}/{len(groups)})" if len(groups) > 1 else "")
        body = "\n".join(g) + "\n\n※ 알림 전용 — 주문은 내지 않습니다. 자동매매 모드는 관제실 ⑥ (기본 그림자)."
        ok = False
        try:
            ok = NotificationService(db).send_system_alert(title=title, body=body) is not None
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s] 텔레그램 알림 실패: %s", FIX, e)
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        if ok:
            sent += len(items)
        else:
            for it in items:
                try:
                    r.delete(it["_key"])
                except Exception:  # noqa: BLE001
                    pass
    return sent


def run_emapb_watch_once() -> dict:
    db = SessionLocal()
    stat: dict = {"symbols": 0, "ready": 0, "signal": 0, "new_alerts": 0, "err": 0}
    try:
        from app.core.crypto import decrypt_text
        from app.integrations.binance.client import BinanceClient
        from app.models.exchange_account import ExchangeAccount
        from app.services.universe_cache import cached_universe
        from app.services import bar_gate as BG
        from app.workers.external_strategies_worker import _universe

        acc = db.execute(select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))).scalar_one_or_none()
        if acc is None:
            return stat
        bc = BinanceClient(api_key=decrypt_text(acc.api_key_enc), api_secret=decrypt_text(acc.api_secret_enc), is_testnet=acc.is_testnet)
        r = get_redis_client()
        now = datetime.now(timezone.utc)
        now_ms = int(now.timestamp() * 1000)
        iv = ES.setting(db, "emapb_interval")
        iv = iv if iv in INTERVAL_MS else "1d"
        iv_ms = INTERVAL_MS[iv]
        p = EP.params_from(lambda k: ES.setting(db, k))
        near = ES.setting_float(db, "emapb_ready_near_pct")
        sides = ES.sides_of(db, "emapb_sides") or {"LONG", "SHORT"}
        alert_on = BG.parse_flag(ES.setting(db, "emapb_alert_enabled"), default=True)
        ext_iv = ES.setting(db, "ext_interval")
        top_n, min_qv = int(ES.setting_float(db, "ext_universe_top_n")), ES.setting_float(db, "ext_min_quote_volume")
        universe, _src = cached_universe(
            r, interval=ext_iv, interval_ms=INTERVAL_MS.get(ext_iv), settle_ms=BG.parse_settle_ms(ES.setting(db, "ext_bar_settle_ms")),
            top_n=top_n, min_qv=min_qv, enabled=ES.setting(db, "ext_universe_per_bar"), now_ms=now_ms,
            compute=lambda: _universe(bc, db, top_n, min_qv))
        stat["symbols"] = len(universe)
        day = now.strftime("%Y%m%d")
        board: list[dict] = []
        fresh: list[dict] = []
        for sym in universe:
            try:
                rows = bc.get_klines(symbol=sym, interval=iv, limit=LIMIT) or []
                for side in sorted(sides):
                    for it in scan_symbol(rows, side, p=p, near_pct=near, now_ms=now_ms, iv_ms=iv_ms):
                        it["symbol"] = sym
                        board.append(it)
                        stat[it["kind"]] += 1
                        if not alert_on:
                            continue                     # 알림 꺼짐 = 중복 키도 안 박는다 (다시 켜면 그날 것부터 받음)
                        tag = str(it["bar"]) if it["kind"] == "signal" else day
                        it["_key"] = _k_sent(it["kind"], sym, side, tag)
                        try:
                            if r.set(it["_key"], "1", nx=True, ex=2 * 86400):
                                fresh.append(it)
                        except Exception:  # noqa: BLE001 — Redis 실패면 알림 생략(반복 폭주 방지), 화면은 그대로
                            pass
            except Exception as e:  # noqa: BLE001
                stat["err"] += 1
                logger.warning("[%s] %s 감시 실패: %s", FIX, sym, e)
        board.sort(key=lambda x: (x["kind"] != "signal", x["symbol"]))
        board = [{k: v for k, v in x.items() if k != "_key"} for x in board]
        try:
            r.setex(BOARD_KEY, BOARD_TTL, json.dumps({"at": now.isoformat(), "interval": iv, "near_pct": near,
                                                       "items": board}, default=str))
        except Exception:  # noqa: BLE001
            pass
        if fresh and alert_on:
            stat["new_alerts"] = _send(db, r, fresh, iv)
        logger.info("[%s] EMA 눌림 감시: 심볼 %d · 준비 %d · 신호 %d · 새 알림 %d · 오류 %d (%.0fs)",
                    FIX, stat["symbols"], stat["ready"], stat["signal"], stat["new_alerts"], stat["err"],
                    time.time() - now.timestamp())
        return stat
    finally:
        db.close()

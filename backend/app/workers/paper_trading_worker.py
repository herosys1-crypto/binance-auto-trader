"""🧪 가상 매매 학습 워커 (Fix 361, 2026-09-08) — 매 15분 감시 대상을 훑어 가상 진입·관리·기록, 학습 일지로 부트스트랩.

사장님 (2026-09-08 verbatim): "지금부터 실시간 자동은 종료했어 가상으로 포지션 진입해서 성공과 실패를 기록저장 학습해서
다시 실시간 운영시작 하면 그때 적용할 수 있게 학습해줘 꼭 성리할수 있는 롱과숏 포지션 진입하고 익절중에 포지션 추가해서
수익을 만들 자리를 찾아줘"

🚨 주문 0건 — 이 워커는 `bc.get_24hr_ticker()` / `bc.get_klines()` 로 **읽기만** 한다. 실주문 경로와 무관.

  once     : 15분마다(cron 1,16,31,46). 감시 대상(당일 상승/하락 top N ∪ 열린 가상 포지션의 심볼)을 훑어
             ① 열린 가상 포지션을 진입 이후 완성봉으로 재관리(`paper_trading.manage_trade`, 미래참조 없음 — 상태 없이 매번 처음부터)
             ② `chart_learning.RULES` 12종 + 기준선 2종이 그 봉에서 발동했으면 가상 진입(`paper_trading.open_trade`).
             사이클 끝에 학습 일지 백필을 이어서(설정 ON 이고 미완이면) 진행한다.
  backfill : `chart_learning_days`(라벨링 완료 행)을 오래된 것부터 같은 엔진으로 되돌려 첫 표본을 만든다. API 호출 없음.
  report   : `paper_trading.build_report` → markdown/JSON.
  status   : source×status 건수, 백필 커서, 마지막 사이클 요약(Redis).

3·5일 태그·변동률은 자체 계산하지 않고 오늘/어제 `chart_learning_days` 스냅샷에서 병합한다 —
같은 정보를 두 워커가 각자 API 로 다시 재는 낭비를 없앤다(스냅샷이 없으면 3·5일 태그 없이 진행 = fail-open).

CLI (컨테이너 안):
  python -m app.workers.paper_trading_worker once
  python -m app.workers.paper_trading_worker backfill --limit 300
  python -m app.workers.paper_trading_worker report --days 60 [--json]
  python -m app.workers.paper_trading_worker status
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.models.chart_learning_day import ChartLearningDay
from app.services import chart_learning as CL
from app.services import paper_trading as PT
from app.services.market_movers import MIN_QUOTE_VOLUME, change_pct, quote_volume
from app.workers.chart_learning_worker import MAX_CONSEC_FAIL, SLEEP, _klines, _now_ms, _open

logger = logging.getLogger(__name__)

FIX = "Fix361"
MIN_LIVE_BARS = 30          # Series.build 에 최소 필요한 15m 완성봉 (부족하면 그 심볼만 건너뜀 = fail-open)
CURSOR_KEY = "paper_backfill_last_id"     # system_settings — 백필 진행 커서(마지막 처리 chart_learning_days.id)
DONE_KEY = "paper_backfill_done"          # system_settings — "1" 이면 부트스트랩 완료
REDIS_KEY = "paper_trading:last_cycle"
REDIS_TTL = 172800           # 2일


# ══════════════════════════════════════════════════════════════════════
# 설정 (system_settings)
# ══════════════════════════════════════════════════════════════════════

def _setting(db: Any, key: str) -> str | None:
    if db is None:
        return None
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        if row is None or row.value is None:
            return None
        v = str(row.value).strip()
        return v or None
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s 조회 실패 → 기본값: %s", FIX, key, e)
        return None


def _set_setting(db: Any, key: str, value: str) -> None:
    from app.models.system_setting import SystemSetting
    row = db.get(SystemSetting, key)
    if row is None:
        db.add(SystemSetting(key=key, value=str(value)))
    else:
        row.value = str(value)
    db.commit()


def _bool_setting(db: Any, key: str, default: bool) -> bool:
    v = _setting(db, key)
    return default if v is None else v.lower() in ("1", "true", "on", "yes")


def _int_setting(db: Any, key: str, default: int, lo: int, hi: int) -> int:
    v = _setting(db, key)
    try:
        return max(lo, min(hi, int(float(v)))) if v is not None else default
    except (TypeError, ValueError):
        return default


# ══════════════════════════════════════════════════════════════════════
# 1) 실시간 사이클 — 15분마다
# ══════════════════════════════════════════════════════════════════════

def _daily_tags(db: Any) -> dict[str, dict[str, Any]]:
    """오늘/어제 chart_learning_days 스냅샷에서 심볼별 (tags, chg_3d, chg_5d) — 같은 심볼이 둘 다 있으면 최신(오늘)."""
    today = datetime.now(timezone.utc).date()
    out: dict[str, dict[str, Any]] = {}
    rows = db.execute(
        select(ChartLearningDay.symbol, ChartLearningDay.tags, ChartLearningDay.chg_3d, ChartLearningDay.chg_5d)
        .where(ChartLearningDay.snap_date >= today - timedelta(days=1))
        .order_by(ChartLearningDay.snap_date.desc())
    ).all()
    for sym, tags, c3, c5 in rows:
        if sym in out:      # 정렬이 최신 먼저라 이미 있으면 더 옛 행 = 건너뜀
            continue
        out[sym] = {"tags": list(tags or []),
                    "chg_3d": float(c3) if c3 is not None else None,
                    "chg_5d": float(c5) if c5 is not None else None}
    return out


def _store_cycle_summary(summary: dict[str, Any]) -> None:
    try:
        from app.core.redis_client import get_redis_client
        get_redis_client().setex(REDIS_KEY, REDIS_TTL, json.dumps(summary, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        logger.debug("[%s] redis 저장 실패 (무시): %s", FIX, e)


def run_paper_trading_once(decrypt_text, *, limit_symbols: int | None = None) -> dict[str, Any]:
    db, bc = _open(decrypt_text)
    if db is None:
        return {"error": "no account"}
    try:
        from app.models.paper_trade import PaperTrade

        if not _bool_setting(db, PT.S_ENABLED, True):
            return {"skipped": "disabled"}
        t0 = time.time()
        n = _int_setting(db, PT.S_TOP_N, 50, 5, 200)

        tickers = bc.get_24hr_ticker()
        if not isinstance(tickers, list) or not tickers:
            logger.warning("[%s] 티커 없음 → 사이클 건너뜀", FIX)
            return {"error": "no tickers"}
        usdt = [t for t in tickers if str(t.get("symbol") or "").endswith("USDT")]
        chg = {str(t["symbol"]): change_pct(t) for t in usdt}
        qv = {str(t["symbol"]): quote_volume(t) for t in usdt}
        # rets={} — 다일 순위는 자체 계산하지 않는다(속도 우선). 3·5일 태그는 아래서 학습 일지로 병합.
        uni = CL.tag_universe(chg, qv, {}, n=n, min_quote_volume=MIN_QUOTE_VOLUME)
        daily = _daily_tags(db)

        open_syms = set(db.execute(select(PaperTrade.symbol).where(PaperTrade.status == "OPEN")).scalars())
        process_symbols = sorted(set(uni) | open_syms)
        if limit_symbols:
            process_symbols = process_symbols[:limit_symbols]

        rule_side = {r.key: r.side for r in CL.RULES}
        now = datetime.now(timezone.utc)
        now_ms = _now_ms()
        opened = managed = closed = processed = 0
        fails = 0
        for sym in process_symbols:
            try:
                k15 = CL.compact(_klines(bc, symbol=sym, interval="15m", limit=262), now_ms=now_ms)
                k4 = CL.compact(_klines(bc, symbol=sym, interval="4h", limit=62), now_ms=now_ms, interval_ms=CL.MS_4H)
                fails = 0
            except Exception as e:  # noqa: BLE001
                if sym not in uni:
                    # Fix 361b: 감시 밖(열린 가상 포지션만 있는 심볼)의 조회 실패는 연속 실패로 세지 않는다 —
                    #   상장폐지·거래정지 심볼 3개가 나란히 있으면 사이클 전체가 죽는 것을 막는다. 3사이클 연속이면
                    #   그 심볼의 열린 가상 포지션을 SYMBOL_UNAVAILABLE 로 닫아 좀비를 없앤다.
                    n_fail = _bump_fetch_fail(sym)
                    logger.warning("[%s] %s 봉 조회 실패 (감시 밖, %d회): %s", FIX, sym, n_fail, e)
                    if n_fail >= 3:
                        closed += _close_unavailable(db, sym, now, str(e)[:120])
                    time.sleep(SLEEP)
                    continue
                fails += 1
                logger.warning("[%s] %s 봉 조회 실패 (%d/%d): %s", FIX, sym, fails, MAX_CONSEC_FAIL, e)
                if fails >= MAX_CONSEC_FAIL:
                    logger.error("[%s] 연속 실패 → 사이클 중단 (ban 보호). 처리 %d", FIX, processed)
                    break
                continue
            _clear_fetch_fail(sym)
            if len(k15) < MIN_LIVE_BARS:
                logger.debug("[%s] %s 15m 봉 부족(%d) → 건너뜀", FIX, sym, len(k15))
                time.sleep(SLEEP)
                continue
            try:
                series = PT.Series.build(k15, k4)
            except Exception as e:  # noqa: BLE001
                logger.warning("[%s] %s 지표 계산 실패 → 건너뜀: %s", FIX, sym, e)     # Fix 361b: 한 심볼이 사이클을 죽이지 않게
                time.sleep(SLEEP)
                continue
            j = len(k15) - 1

            open_rows = db.execute(
                select(PaperTrade).where(PaperTrade.symbol == sym, PaperTrade.status == "OPEN")
            ).scalars().all()
            open_rule_set: set[str] = set()
            for row in open_rows:
                trade_map = {"side": row.side, "entry_price": float(row.entry_price),
                            "entry_bar_ts": int(row.entry_bar_ts),
                            "tp1_pct": float(row.tp1_pct) if row.tp1_pct is not None else None,
                            "chg_24h": float(row.chg_24h) if row.chg_24h is not None else None}
                try:
                    res = PT.manage_trade(trade_map, series)
                except Exception as e:  # noqa: BLE001
                    logger.warning("[%s] %s/%s 관리 실패 (열림 유지): %s", FIX, sym, row.rule, e)
                    open_rule_set.add(row.rule)
                    continue
                if res.get("engines") is None:                 # Fix 361b: 진입 봉이 조회 창 밖 = gap → 닫지 않고 유지
                    logger.info("[%s] %s/%s 진입 봉이 창 밖 (gap %s봉) → 열림 유지", FIX, sym, row.rule, res.get("gap_bars"))
                    open_rule_set.add(row.rule)
                    continue
                row.engines = res["engines"]
                row.adds = res["adds"]
                row.bars_seen = res["bars_seen"]
                row.mfe = round(float(res["mfe"]), 4)
                row.mae = round(float(res["mae"]), 4)
                managed += 1
                if res["status"] == "CLOSED":
                    row.status = "CLOSED"
                    row.close_reason = res["close_reason"]
                    _xb = int(res.get("exit_bars") or 0)      # Fix 361b: closed_at = 마지막 엔진이 끝난 봉의 마감 시각
                    row.closed_at = (row.opened_at + timedelta(minutes=15 * _xb)) if _xb > 0 else now
                    closed += 1
                else:
                    open_rule_set.add(row.rule)

            try:
                fired = PT.evaluate_rules(series, j)
            except Exception as e:  # noqa: BLE001
                logger.warning("[%s] %s 규칙 평가 실패 → 신규 진입 없음: %s", FIX, sym, e)
                fired = {}
            tags = sorted(set(uni.get(sym, {}).get("tags") or []) | set(daily.get(sym, {}).get("tags") or []))
            chg24 = chg.get(sym)
            chg3 = daily.get(sym, {}).get("chg_3d")
            chg5 = daily.get(sym, {}).get("chg_5d")
            for key, hit in fired.items():
                if not hit or key in open_rule_set:      # 이미 열린 같은 (심볼, 규칙) = 한 번에 하나만
                    continue
                side = PT.BASELINE_KEYS.get(key) or rule_side.get(key)
                if side is None:
                    continue
                try:
                    t = PT.open_trade(symbol=sym, side=side, rule=key, series=series, j=j, tags=tags,
                                      chg_24h=chg24, chg_3d=chg3, chg_5d=chg5, source="live", fired=fired)
                except Exception as e:  # noqa: BLE001
                    logger.warning("[%s] %s/%s 가상 진입 기록 실패 → 건너뜀: %s", FIX, sym, key, e)
                    continue
                opened_at = datetime.fromtimestamp(t["entry_bar_ts"] / 1000, tz=timezone.utc) + timedelta(minutes=15)
                row = PaperTrade(source=t["source"], symbol=t["symbol"], side=t["side"], rule=t["rule"],
                                 entry_bar_ts=t["entry_bar_ts"], entry_price=t["entry_price"], tp1_pct=t["tp1_pct"],
                                 opened_at=opened_at, status="OPEN", tags=t["tags"], chg_24h=t["chg_24h"],
                                 chg_3d=t["chg_3d"], chg_5d=t["chg_5d"], snapshot=t["snapshot"], version=t["version"])
                try:
                    with db.begin_nested():
                        db.add(row)
                        db.flush()
                    opened += 1
                    open_rule_set.add(key)
                except IntegrityError as e:
                    logger.debug("[%s] %s/%s 같은 진입봉 중복 → 건너뜀: %s", FIX, sym, key, e)

            processed += 1
            if processed % 25 == 0:
                db.commit()
            time.sleep(SLEEP)
        db.commit()

        backfill_res: dict[str, Any] | None = None
        if _bool_setting(db, PT.S_BACKFILL, True):     # Fix 361b: done 은 정보용 — 늦게 라벨된 행을 위해 매 사이클 확인
            try:
                backfill_res = backfill_from_journal(db, limit_rows=300)
            except Exception as e:  # noqa: BLE001
                logger.warning("[%s] 백필 실패 (무시): %s", FIX, e)

        res: dict[str, Any] = {"at": now.isoformat(), "symbols": len(process_symbols), "opened": opened,
                               "managed": managed, "closed": closed, "seconds": round(time.time() - t0, 1)}
        if backfill_res is not None:
            res["backfill"] = backfill_res
        _store_cycle_summary(res)
        # 🚨 할 일이 0건이어도 한 줄 남긴다 — 침묵을 고장으로 착각하지 않게 (Fix 353 교훈).
        logger.info("[%s] 가상매매: 감시 %d · 열림 %d · 관리 %d · 마감 %d · %.0fs",
                    FIX, res["symbols"], opened, managed, closed, res["seconds"])
        return res
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
# 2) 백필 — chart_learning_days 를 오래된 것부터 재구성 (API 호출 없음)
# ══════════════════════════════════════════════════════════════════════

def _bump_fetch_fail(sym: str) -> int:
    """감시 밖 심볼의 연속 조회 실패 횟수 (Redis, 1일 TTL). Redis 실패 = 1 (정리하지 않음)."""
    try:
        from app.core.redis_client import get_redis_client
        r = get_redis_client()
        n = int(r.incr(f"paper_trading:fetch_fail:{sym}"))
        r.expire(f"paper_trading:fetch_fail:{sym}", 86400)
        return n
    except Exception:  # noqa: BLE001
        return 1


def _clear_fetch_fail(sym: str) -> None:
    try:
        from app.core.redis_client import get_redis_client
        get_redis_client().delete(f"paper_trading:fetch_fail:{sym}")
    except Exception:  # noqa: BLE001
        pass


def _close_unavailable(db: Any, sym: str, now: datetime, why: str) -> int:
    """상장폐지·거래정지 등으로 봉을 못 받는 심볼의 열린 가상 포지션을 닫는다 (좀비 방지). 기록은 그대로, 사유만 남긴다."""
    from app.models.paper_trade import PaperTrade
    rows = db.execute(select(PaperTrade).where(PaperTrade.symbol == sym, PaperTrade.status == "OPEN")).scalars().all()
    for row in rows:
        row.status = "CLOSED"
        row.close_reason = f"SYMBOL_UNAVAILABLE: {why}"[:60]
        row.closed_at = now
    if rows:
        logger.warning("[%s] %s 열린 가상 포지션 %d건 SYMBOL_UNAVAILABLE 로 정리", FIX, sym, len(rows))
    return len(rows)


def backfill_from_journal(db: Any, *, limit_rows: int = 300) -> dict[str, Any]:
    from app.models.paper_trade import PaperTrade

    last_id = int(_setting(db, CURSOR_KEY) or "0")
    rows = db.execute(
        select(ChartLearningDay)
        .where(ChartLearningDay.id > last_id, ChartLearningDay.outcome_status == "DONE")
        .order_by(ChartLearningDay.id)
        .limit(limit_rows)
    ).scalars().all()
    if not rows:
        if (_setting(db, DONE_KEY) or "") != "1":
            _set_setting(db, DONE_KEY, "1")
            logger.info("[%s] 백필 부트스트랩 완료 (cursor=%d) — 이후 새로 라벨된 행만", FIX, last_id)
        return {"done": True, "last_id": last_id}

    t0 = time.time()
    inserted = skipped_short = skipped_dup = failed = 0
    max_id = last_id
    for i, row in enumerate(rows, start=1):
        max_id = row.id
        kl = row.klines or {}
        pre15, pre4, fwd15 = kl.get("15m") or [], kl.get("4h") or [], kl.get("15m_fwd") or []
        if not pre15 or not fwd15:
            skipped_short += 1
            continue
        try:
            trades = PT.backfill_row(
                symbol=row.symbol, pre15=pre15, pre4h=pre4, fwd15=fwd15, tags=row.tags or [],
                chg_24h=float(row.chg_24h) if row.chg_24h is not None else None,
                chg_3d=float(row.chg_3d) if row.chg_3d is not None else None,
                chg_5d=float(row.chg_5d) if row.chg_5d is not None else None,
            )
        except Exception as e:  # noqa: BLE001
            failed += 1
            logger.warning("[%s] 백필 %s(id=%d) 실패 (건너뜀): %s", FIX, row.symbol, row.id, e)
            continue
        for t in trades:
            opened_at = datetime.fromtimestamp(t["entry_bar_ts"] / 1000, tz=timezone.utc) + timedelta(minutes=15)
            _xb = int(t.get("exit_bars") or 0) or int(t.get("bars_seen") or 0)
            closed_at = opened_at + timedelta(minutes=15 * _xb)      # Fix 361b: 마지막 엔진이 끝난 봉 (미완이면 자료 끝)
            stmt = pg_insert(PaperTrade).values(
                source=t["source"], symbol=t["symbol"], side=t["side"], rule=t["rule"],
                entry_bar_ts=t["entry_bar_ts"], entry_price=t["entry_price"], tp1_pct=t.get("tp1_pct"),
                opened_at=opened_at, closed_at=closed_at, status=t["status"], close_reason=t.get("close_reason"),
                tags=t.get("tags") or [], chg_24h=t.get("chg_24h"), chg_3d=t.get("chg_3d"), chg_5d=t.get("chg_5d"),
                snapshot=t.get("snapshot"), engines=t.get("engines"), adds=t.get("adds"),
                bars_seen=t.get("bars_seen") or 0, mfe=t.get("mfe"), mae=t.get("mae"),
                version=t.get("version", PT.VERSION),
            ).on_conflict_do_nothing(index_elements=["symbol", "rule", "entry_bar_ts"])
            result = db.execute(stmt)
            if result.rowcount:
                inserted += 1
            else:
                skipped_dup += 1
        if i % 25 == 0:
            db.commit()
    # Fix 361b: 커서 = 워터마크. 처리한 최대 id 보다 아래에 아직 PENDING(미라벨) 행이 있으면 그 앞으로 물러난다 —
    #   라벨링 잡이 나중에 DONE 으로 바꾼 행을 놓치지 않게 (중복 삽입은 on_conflict 로 무해, 행당 0.04s).
    from sqlalchemy import func as _func
    _min_pending = db.execute(
        select(_func.min(ChartLearningDay.id)).where(ChartLearningDay.outcome_status == "PENDING",
                                                    ChartLearningDay.id <= max_id)).scalar()
    cursor = max_id if _min_pending is None else min(max_id, int(_min_pending) - 1)
    _set_setting(db, CURSOR_KEY, str(cursor))
    if (_setting(db, DONE_KEY) or "") == "1":
        _set_setting(db, DONE_KEY, "0")
    db.commit()
    res = {"rows": len(rows), "inserted": inserted, "skipped_short": skipped_short, "skipped_dup": skipped_dup,
           "failed": failed, "last_id": max_id, "seconds": round(time.time() - t0, 1)}
    logger.info("[%s] 백필: 행 %d · 저장 %d · 짧음 %d · 중복 %d · 실패 %d · cursor=%d · %.0fs",
                FIX, len(rows), inserted, skipped_short, skipped_dup, failed, max_id, res["seconds"])
    return res


# ══════════════════════════════════════════════════════════════════════
# 3) 보고서 / 상태
# ══════════════════════════════════════════════════════════════════════

def build_report_from_db(db: Any, days: int = 60) -> dict[str, Any]:
    from app.models.paper_trade import PaperTrade
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(PaperTrade).where(PaperTrade.status == "CLOSED", PaperTrade.opened_at >= cutoff)
    ).scalars().all()
    trades = [{"status": r.status, "engines": r.engines, "adds": r.adds, "rule": r.rule, "side": r.side,
              "symbol": r.symbol, "tags": r.tags, "source": r.source,
              "opened_at": r.opened_at.isoformat() if r.opened_at else None} for r in rows]
    return PT.build_report(trades)


def status(db: Any) -> dict[str, Any]:
    from app.models.paper_trade import PaperTrade
    counts: dict[str, dict[str, int]] = {}
    for src, st, cnt in db.execute(
        select(PaperTrade.source, PaperTrade.status, func.count()).group_by(PaperTrade.source, PaperTrade.status)
    ).all():
        counts.setdefault(src, {})[st] = int(cnt)
    last_cycle = None
    try:
        from app.core.redis_client import get_redis_client
        raw = get_redis_client().get(REDIS_KEY)
        if raw:
            last_cycle = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        logger.debug("[%s] redis 조회 실패 (무시): %s", FIX, e)
    return {"counts": counts, "backfill_last_id": _setting(db, CURSOR_KEY),
            "backfill_done": _setting(db, DONE_KEY) == "1", "last_cycle": last_cycle}


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> int:
    import app.core.logging  # noqa: F401
    from app.core.crypto import decrypt_text

    p = argparse.ArgumentParser(description="가상 매매 학습 (Fix 361)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once")
    bf = sub.add_parser("backfill")
    bf.add_argument("--limit", type=int, default=300)
    r = sub.add_parser("report")
    r.add_argument("--days", type=int, default=60)
    r.add_argument("--json", action="store_true")
    sub.add_parser("status")
    a = p.parse_args(argv)
    try:
        os.nice(10)     # 실매매 워커보다 낮은 우선순위
    except (AttributeError, OSError):
        pass

    if a.cmd == "once":
        print(json.dumps(run_paper_trading_once(decrypt_text), ensure_ascii=False))
    elif a.cmd == "backfill":
        with SessionLocal() as db:
            print(json.dumps(backfill_from_journal(db, limit_rows=a.limit), ensure_ascii=False))
    elif a.cmd == "report":
        with SessionLocal() as db:
            rep = build_report_from_db(db, a.days)
        print(json.dumps(rep, ensure_ascii=False) if a.json else PT.render_markdown(rep))
    elif a.cmd == "status":
        with SessionLocal() as db:
            print(json.dumps(status(db), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

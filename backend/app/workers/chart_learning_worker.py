"""📚 차트 학습 일지 워커 (Fix 353, 2026-09-05) — 스냅샷(매일) · 라벨링(매시간) · 백필(1회) · 보고서(CLI/API).

사장님: "상승 50위 하락 50위 심볼을 차트를 우리가 필요한 시스템로직을 위해서 분석학습 …
         한번에 어려우면 할수 있는 만큼씩 매일 매일 나눠서 학습을 해줘"

  snapshot : UTC 00:05(KST 09:05, 일봉 마감 직후) 감시 대상(당일 50/50 ∪ 3·5일 50/50)의
             15m 200봉 + 4h 61봉을 **완성봉만** 저장. 심볼당 호출 3회(15m·4h·1d) → 분당 ~500 weight 이하.
  outcome  : 매시간, 스냅샷 36h 지난 행에 15m 144봉을 받아 라벨링(`chart_learning.label_row`).
  backfill : 지난 N일을 일봉으로 재구성(그날 00:00 기준 순위 = 미래참조 없음). 1회성 CLI.
  report   : 자리별 기준선 + 규칙별 결과 + 교차검증 → markdown/JSON.

⚠️ API weight: 2026-08-26 IP ban 전력. 심볼당 SLEEP, 연속 실패 3회면 중단(ban 스파이럴 방지).

CLI (컨테이너 안):
  python -m app.workers.chart_learning_worker snapshot --force
  python -m app.workers.chart_learning_worker outcome --limit 5000
  python -m app.workers.chart_learning_worker backfill --days 20
  python -m app.workers.chart_learning_worker report --days 60 [--json]
  python -m app.workers.chart_learning_worker status
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, update

from app.core.database import SessionLocal
from app.models.chart_learning_day import ChartLearningDay
from app.models.exchange_account import ExchangeAccount
from app.services import chart_learning as CL
from app.services.market_movers import MIN_QUOTE_VOLUME, change_pct, quote_volume
from app.services.multiday_movers import returns_from_daily

logger = logging.getLogger(__name__)

FIX = "Fix353"
SLEEP = 0.12               # 심볼당 호출 간격 (Claude 가 정함) — 3호출 × 8/s ≈ 분당 500 weight (한도 2400)
MAX_CONSEC_FAIL = 3        # 연속 실패 → 중단 (418/429 스파이럴 방지)
MIN_PRE_BARS = 120         # chart_events 조정 판정 최소 15m 봉


def _now_ms() -> int:
    return int(time.time() * 1000)


def _open(decrypt_text):
    """(db, BinanceClient). 활성 binance 계정이 없으면 (None, None)."""
    db = SessionLocal()
    try:
        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.exchange_name == "binance",
                                          ExchangeAccount.is_active.is_(True))
        ).scalars().first()
        if account is None:
            logger.warning("[%s] 활성 binance 계정 없음", FIX)
            db.close()
            return None, None
        from app.integrations.binance.client import BinanceClient
        bc = BinanceClient(api_key=decrypt_text(account.api_key_enc),
                           api_secret=decrypt_text(account.api_secret_enc),
                           is_testnet=account.is_testnet)
        return db, bc
    except Exception:
        db.close()
        raise


# ══════════════════════════════════════════════════════════════════════
# 조회 부품
# ══════════════════════════════════════════════════════════════════════

def _fetch_pre(bc, symbol: str, *, end_ms: int | None = None) -> tuple[list[list[float]], list[list[float]]]:
    """스냅샷 전 15m ≤200 + 4h ≤61 완성봉. `end_ms` 를 주면 그 시각 이전(백필)."""
    now = end_ms if end_ms is not None else _now_ms()
    kw: dict[str, Any] = {"end_time": end_ms - 1} if end_ms is not None else {}
    k15 = CL.compact(bc.get_klines(symbol=symbol, interval="15m", limit=CL.PRE_15M + 2, **kw),
                     now_ms=now, interval_ms=CL.MS_15M)[-CL.PRE_15M:]
    k4 = CL.compact(bc.get_klines(symbol=symbol, interval="4h", limit=CL.PRE_4H + 2, **kw),
                    now_ms=now, interval_ms=CL.MS_4H)[-CL.PRE_4H:]
    return k15, k4


def _daily_returns(bc, symbols: list[str], *, now_ms: int) -> dict[str, tuple[float | None, float | None]]:
    """심볼별 (r3, r5) — 완성 일봉만(진행중 제외). multiday_movers 와 같은 정의(전일 종가 기준).
    Redis 캐시를 쓰지 않는 이유: 00:05 스냅샷에 23:40 캐시(하루 낡음)가 섞이면 순위가 어제 것이 된다."""
    out: dict[str, tuple[float | None, float | None]] = {}
    fails = 0
    for sym in symbols:
        try:
            kl = CL.compact(bc.get_klines(symbol=sym, interval="1d", limit=8), now_ms=now_ms, interval_ms=CL.MS_DAY)
            fails = 0
        except Exception as e:  # noqa: BLE001
            fails += 1
            logger.debug("[%s] %s 일봉 실패: %s", FIX, sym, e)
            if fails >= MAX_CONSEC_FAIL:
                logger.error("[%s] 일봉 연속 실패 %d회 → 다일 순위 중단 (ban 보호)", FIX, fails)
                break
            continue
        if len(kl) >= 7:
            out[sym] = returns_from_daily([b[4] for b in kl])
        time.sleep(SLEEP / 2)
    return out


def _new_row(*, snap_date: date, snapshot_at: datetime, symbol: str, source: str, info: dict[str, Any],
             chg24: float | None, r3: float | None, r5: float | None, qv: float | None,
             k15: list[list[float]], k4: list[list[float]]) -> ChartLearningDay:
    return ChartLearningDay(
        snap_date=snap_date, snapshot_at=snapshot_at, symbol=symbol, source=source,
        tags=list(info.get("tags") or []), ranks=dict(info.get("ranks") or {}),
        chg_24h=round(chg24, 4) if chg24 is not None else None,
        chg_3d=round(r3 * 100, 4) if r3 is not None else None,
        chg_5d=round(r5 * 100, 4) if r5 is not None else None,
        quote_volume=round(qv, 2) if qv is not None else None,
        snapshot=CL.snapshot_indicators(k15, k4),
        klines={"15m": k15, "4h": k4},
        outcome_status="PENDING",
    )


# ══════════════════════════════════════════════════════════════════════
# 1) 스냅샷 — 매일
# ══════════════════════════════════════════════════════════════════════

def run_chart_learning_snapshot_once(decrypt_text, *, force: bool = False) -> dict[str, Any]:
    db, bc = _open(decrypt_text)
    if db is None:
        return {"error": "no account"}
    try:
        if not CL.enabled(db):
            return {"skipped": "disabled"}
        now = datetime.now(timezone.utc)
        hours = CL.snapshot_hours(db)
        if not force and now.hour not in hours:
            return {"skipped": f"hour {now.hour} not in {sorted(hours)}"}
        snap_date = now.date()
        n = CL.top_n(db)
        t0 = time.time()

        tickers = bc.get_24hr_ticker()
        if not isinstance(tickers, list) or not tickers:
            logger.warning("[%s] 티커 없음 → 스냅샷 건너뜀", FIX)
            return {"error": "no tickers"}
        usdt = [t for t in tickers if str(t.get("symbol") or "").endswith("USDT")]
        chg = {str(t["symbol"]): change_pct(t) for t in usdt}
        qv = {str(t["symbol"]): quote_volume(t) for t in usdt}
        pool = [s for s in chg if qv.get(s, 0.0) >= MIN_QUOTE_VOLUME]
        rets = _daily_returns(bc, pool, now_ms=_now_ms())
        uni = CL.tag_universe(chg, qv, rets, n=n, min_quote_volume=MIN_QUOTE_VOLUME)

        existing = set(db.execute(
            select(ChartLearningDay.symbol).where(ChartLearningDay.snap_date == snap_date)).scalars())
        todo = [s for s in uni if s not in existing]
        inserted = short = 0
        fails = 0
        for sym in todo:
            try:
                k15, k4 = _fetch_pre(bc, sym)
                fails = 0
            except Exception as e:  # noqa: BLE001
                fails += 1
                logger.warning("[%s] %s 봉 조회 실패 (%d/%d): %s", FIX, sym, fails, MAX_CONSEC_FAIL, e)
                if fails >= MAX_CONSEC_FAIL:
                    logger.error("[%s] 연속 실패 → 스냅샷 중단 (ban 보호). 저장 %d", FIX, inserted)
                    break
                continue
            if len(k15) < MIN_PRE_BARS:
                short += 1
                continue
            r3, r5 = rets.get(sym, (None, None))
            db.add(_new_row(snap_date=snap_date, snapshot_at=now, symbol=sym, source="live", info=uni[sym],
                            chg24=chg.get(sym), r3=r3, r5=r5, qv=qv.get(sym), k15=k15, k4=k4))
            inserted += 1
            if inserted % 25 == 0:
                db.commit()
            time.sleep(SLEEP)
        db.commit()
        res = {"snap_date": snap_date.isoformat(), "universe": len(uni), "existing": len(existing),
               "inserted": inserted, "short_history": short, "seconds": round(time.time() - t0, 1)}
        logger.info("[%s] 스냅샷 %s: 감시 %d · 기존 %d · 저장 %d · 봉부족 %d · %.0fs",
                    FIX, res["snap_date"], res["universe"], res["existing"], inserted, short, res["seconds"])
        return res
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
# 2) 라벨링 — 매시간
# ══════════════════════════════════════════════════════════════════════

def _prune(db) -> int:
    """원시 봉 보존 기간(기본 45일)이 지난 행의 klines 를 비운다. 라벨(outcome)은 남는다."""
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=CL.keep_days(db))
    res = db.execute(
        update(ChartLearningDay)
        .where(ChartLearningDay.snap_date < cutoff, ChartLearningDay.klines.isnot(None),
               ChartLearningDay.outcome_status != "PENDING")
        .values(klines=None)
    )
    db.commit()
    return int(res.rowcount or 0)


def run_chart_learning_outcome_once(decrypt_text, *, limit: int | None = None) -> dict[str, Any]:
    db, bc = _open(decrypt_text)
    if db is None:
        return {"error": "no account"}
    try:
        if not CL.enabled(db):
            return {"skipped": "disabled"}
        batch = limit or CL.outcome_batch(db)
        now = datetime.now(timezone.utc)
        now_ms = _now_ms()
        cutoff = now - timedelta(minutes=15 * CL.FWD_BARS + 20)
        rows = db.execute(
            select(ChartLearningDay)
            .where(ChartLearningDay.outcome_status == "PENDING", ChartLearningDay.snapshot_at <= cutoff)
            .order_by(ChartLearningDay.snapshot_at)
            .limit(batch)
        ).scalars().all()
        t0 = time.time()
        done = expired = waiting = 0
        fails = 0
        for row in rows:
            kl = row.klines or {}
            pre15 = kl.get("15m") or []
            pre4 = kl.get("4h") or []
            if len(pre15) < MIN_PRE_BARS:
                row.outcome = {"version": CL.LABEL_VERSION, "error": "스냅샷 전 봉 부족"}
                row.outcome_status = "EXPIRED"
                row.labeled_at = now
                expired += 1
                continue
            start = (int(row.snapshot_at.timestamp() * 1000) // CL.MS_15M) * CL.MS_15M
            try:
                raw = bc.get_klines(symbol=row.symbol, interval="15m", limit=CL.FWD_BARS + 4, start_time=start)
                fails = 0
            except Exception as e:  # noqa: BLE001
                fails += 1
                logger.warning("[%s] %s 결과 봉 실패 (%d/%d): %s", FIX, row.symbol, fails, MAX_CONSEC_FAIL, e)
                if fails >= MAX_CONSEC_FAIL:
                    logger.error("[%s] 연속 실패 → 라벨링 중단 (ban 보호). 완료 %d", FIX, done)
                    break
                continue
            fwd = [b for b in CL.compact(raw, now_ms=now_ms) if b[0] >= start][:CL.FWD_BARS]
            if len(fwd) < CL.FWD_BARS:
                if now - row.snapshot_at > timedelta(days=4):
                    row.outcome = {"version": CL.LABEL_VERSION, "error": f"결과 봉 {len(fwd)}/{CL.FWD_BARS} (상장폐지?)"}
                    row.outcome_status = "EXPIRED"
                    row.labeled_at = now
                    expired += 1
                else:
                    waiting += 1
                continue
            row.outcome = CL.label_row(pre15, pre4, fwd)
            row.klines = {**kl, "15m_fwd": fwd}          # 새 dict 대입 = JSONB 변경 감지
            row.outcome_status = "DONE"
            row.labeled_at = now
            done += 1
            if done % 25 == 0:
                db.commit()
            time.sleep(SLEEP)
        db.commit()
        pruned = _prune(db)
        res = {"candidates": len(rows), "done": done, "expired": expired, "waiting": waiting,
               "pruned": pruned, "seconds": round(time.time() - t0, 1)}
        if rows or pruned:
            logger.info("[%s] 라벨링: 후보 %d · 완료 %d · 만료 %d · 대기 %d · 정리 %d · %.0fs",
                        FIX, len(rows), done, expired, waiting, pruned, res["seconds"])
        return res
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
# 3) 백필 — 지난 N일을 일봉으로 재구성 (1회성)
# ══════════════════════════════════════════════════════════════════════

def backfill(decrypt_text, days: int, *, label: bool = True) -> dict[str, Any]:
    db, bc = _open(decrypt_text)
    if db is None:
        return {"error": "no account"}
    try:
        n = CL.top_n(db)
        info = bc.get_exchange_info() or {}
        syms = [s["symbol"] for s in info.get("symbols", [])
                if s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL" and s.get("status") == "TRADING"]
        today0 = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        t0 = time.time()
        # 일봉 한 번에 (심볼당 1회): [open_time, o, h, l, c, v, quote_volume]
        daily: dict[str, list[list[float]]] = {}
        fails = 0
        for sym in syms:
            try:
                raw = bc.get_klines(symbol=sym, interval="1d", limit=days + 8)
                fails = 0
            except Exception as e:  # noqa: BLE001
                fails += 1
                logger.warning("[%s] 백필 %s 일봉 실패: %s", FIX, sym, e)
                if fails >= MAX_CONSEC_FAIL:
                    logger.error("[%s] 연속 실패 → 백필 중단", FIX)
                    return {"error": "daily klines failed"}
                continue
            bars = []
            for k in raw or []:
                try:
                    bars.append([int(k[0]), float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[7])])
                except (TypeError, ValueError, IndexError):
                    continue
            daily[sym] = bars
            time.sleep(SLEEP / 2)
        logger.info("[%s] 백필 일봉 %d심볼 %.0fs", FIX, len(daily), time.time() - t0)

        total = 0
        per_day: dict[str, int] = {}
        for d in range(days, 0, -1):
            day0 = today0 - timedelta(days=d)
            day0_ms = int(day0.timestamp() * 1000)
            chg: dict[str, float] = {}
            qv: dict[str, float] = {}
            rets: dict[str, tuple[float | None, float | None]] = {}
            for sym, bars in daily.items():
                done_bars = [b for b in bars if b[0] + CL.MS_DAY <= day0_ms]
                if len(done_bars) < 7 or done_bars[-2][4] <= 0:
                    continue
                chg[sym] = (done_bars[-1][4] / done_bars[-2][4] - 1) * 100
                qv[sym] = done_bars[-1][6]
                rets[sym] = returns_from_daily([b[4] for b in done_bars])
            uni = CL.tag_universe(chg, qv, rets, n=n, min_quote_volume=MIN_QUOTE_VOLUME)
            existing = set(db.execute(
                select(ChartLearningDay.symbol).where(ChartLearningDay.snap_date == day0.date())).scalars())
            ins = 0
            fails = 0
            for sym, inf in uni.items():
                if sym in existing:
                    continue
                try:
                    k15, k4 = _fetch_pre(bc, sym, end_ms=day0_ms)
                    fails = 0
                except Exception as e:  # noqa: BLE001
                    fails += 1
                    logger.warning("[%s] 백필 %s %s 봉 실패: %s", FIX, day0.date(), sym, e)
                    if fails >= MAX_CONSEC_FAIL:
                        logger.error("[%s] 연속 실패 → 백필 중단 (저장 %d)", FIX, total)
                        db.commit()
                        return {"error": "klines failed", "inserted": total, "per_day": per_day}
                    continue
                if len(k15) < MIN_PRE_BARS:
                    continue
                r3, r5 = rets.get(sym, (None, None))
                db.add(_new_row(snap_date=day0.date(), snapshot_at=day0, symbol=sym, source="backfill", info=inf,
                                chg24=chg.get(sym), r3=r3, r5=r5, qv=qv.get(sym), k15=k15, k4=k4))
                ins += 1
                if ins % 25 == 0:
                    db.commit()
                time.sleep(SLEEP)
            db.commit()
            per_day[day0.date().isoformat()] = ins
            total += ins
            logger.info("[%s] 백필 %s: 감시 %d · 저장 %d (누적 %d, %.0fs)", FIX, day0.date(), len(uni), ins, total,
                        time.time() - t0)
    finally:
        db.close()
    res: dict[str, Any] = {"inserted": total, "per_day": per_day}
    if label:
        res["label"] = run_chart_learning_outcome_once(decrypt_text, limit=100000)
    return res


# ══════════════════════════════════════════════════════════════════════
# 4) 보고서 / 상태
# ══════════════════════════════════════════════════════════════════════

def build_report_from_db(db, days: int = 60) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    rows = db.execute(
        select(ChartLearningDay.symbol, ChartLearningDay.snap_date, ChartLearningDay.tags,
               ChartLearningDay.source, ChartLearningDay.outcome)
        .where(ChartLearningDay.snap_date >= cutoff, ChartLearningDay.outcome_status == "DONE")
    ).all()
    inputs = [{"symbol": r.symbol, "snap_date": r.snap_date.isoformat(), "tags": list(r.tags or []),
               "source": r.source, "outcome": r.outcome} for r in rows]
    return CL.build_report(inputs)


def status(db) -> dict[str, Any]:
    rows = db.execute(
        select(ChartLearningDay.snap_date, ChartLearningDay.outcome_status, func.count())
        .group_by(ChartLearningDay.snap_date, ChartLearningDay.outcome_status)
        .order_by(ChartLearningDay.snap_date.desc())
    ).all()
    days: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    for sd, st, cnt in rows:
        days.setdefault(sd.isoformat(), {})[st] = int(cnt)
        totals[st] = totals.get(st, 0) + int(cnt)
    return {"days": days, "totals": totals, "n_days": len(days)}


# ══════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> int:
    import app.core.logging  # noqa: F401
    from app.core.crypto import decrypt_text

    p = argparse.ArgumentParser(description="차트 학습 일지 (Fix 353)")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--force", action="store_true", help="시각 설정 무시하고 지금 저장")
    o = sub.add_parser("outcome")
    o.add_argument("--limit", type=int, default=None)
    b = sub.add_parser("backfill")
    b.add_argument("--days", type=int, default=20)
    b.add_argument("--no-label", action="store_true")
    r = sub.add_parser("report")
    r.add_argument("--days", type=int, default=60)
    r.add_argument("--json", action="store_true")
    sub.add_parser("status")
    sub.add_parser("prune")
    a = p.parse_args(argv)
    try:
        os.nice(10)     # 실매매 워커보다 낮은 우선순위
    except (AttributeError, OSError):
        pass

    if a.cmd == "snapshot":
        print(json.dumps(run_chart_learning_snapshot_once(decrypt_text, force=a.force), ensure_ascii=False))
    elif a.cmd == "outcome":
        print(json.dumps(run_chart_learning_outcome_once(decrypt_text, limit=a.limit), ensure_ascii=False))
    elif a.cmd == "backfill":
        print(json.dumps(backfill(decrypt_text, a.days, label=not a.no_label), ensure_ascii=False))
    elif a.cmd == "report":
        with SessionLocal() as db:
            rep = build_report_from_db(db, a.days)
        print(json.dumps(rep, ensure_ascii=False) if a.json else CL.render_markdown(rep))
    elif a.cmd == "status":
        with SessionLocal() as db:
            print(json.dumps(status(db), ensure_ascii=False, indent=1))
    elif a.cmd == "prune":
        with SessionLocal() as db:
            print(json.dumps({"pruned": _prune(db)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())

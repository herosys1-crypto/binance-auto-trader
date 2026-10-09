"""Fix 424 — EMA 추세 눌림을 「전부 일봉」으로 + 진입 준비·신호 알림(텔레그램 + 화면). 사장님 2026-10-09."""
from __future__ import annotations

import json
import pathlib
from types import SimpleNamespace as NS

import pytest

from app.services import ema_pullback as EP
from app.services import external_strategies as ES

APP = pathlib.Path(EP.__file__).resolve().parents[1]
DAY, M15 = EP.MS_DAY, EP.MS_15M
N = 120                                    # 상장 120일 코인 — EMA200 없이도 판정돼야 한다


def daily(*, vol_mult=2.0, confirm=True):
    c = [100.0 * (1.01 ** i) for i in range(N - 5)]
    top = c[-1]
    for k in range(1, 5):
        c.append(top * (1 - 0.006 * k))
    c.append(c[-1] * (1.02 if confirm else 0.999))
    e20 = EP.emas(c)[EP.EMA_MID]
    h = [x * 1.003 for x in c]
    lo = [x * 0.997 for x in c]
    for i in range(N - 5, N - 1):
        lo[i] = min(lo[i], e20[i] * 0.999)
    v = [100.0] * N
    v[-1] = 100.0 * vol_mult
    return c, h, lo, v


def rows_of(c, h, lo, v, day0=1_760_000_000_000 // DAY * DAY):
    return [[day0 + i * DAY, str(c[i]), str(h[i]), str(lo[i]), str(c[i]), str(v[i])] for i in range(len(c))]


# ── 판정 ────────────────────────────────────────────────────────────────
def test_min_bars_no_longer_needs_ema200():
    assert EP.min_bars() <= 80
    c, h, lo, v = daily()
    ok, d = EP.signal(c, h, lo, v, N - 1, "LONG")
    assert ok, d
    assert d["macro"] is None and "ema200" not in d               # 200봉 미만 = EMA200 기록 안 함


def test_defaults_daily():
    assert ES.SETTINGS["emapb_interval"][0] == "1d"
    assert ES.SETTINGS["emapb_cooldown_hours"][0] == "20"         # 교차 감사: 다음 날 신호는 허용
    assert ES.SETTINGS["emapb_mode"][0] == "shadow"


# ── 가상매매: 하루 마지막 15분봉에서만, 그날 닫힌 일봉으로 ──────────────────
def _ctx(last15_open, kl1d):
    return NS(kl15=[[last15_open, 0, 0, 0, 0, 0]], kl1d=kl1d, c=[], h=[], l=[], v=[], j=0)


def test_paper_fires_only_on_day_close_with_fresh_daily():
    c, h, lo, v = daily()
    kl1d = [[float(x) for x in r] for r in rows_of(c, h, lo, v)]
    last_close_15 = int(kl1d[-1][0]) + DAY - M15
    assert EP.needs_daily([[last_close_15]]) and not EP.needs_daily([[last_close_15 - M15]])
    assert EP._r_long(_ctx(last_close_15, kl1d)) is True
    assert EP._r_long(_ctx(last_close_15 - M15, kl1d)) is False      # 하루 중간 봉에서는 판정 안 함
    assert EP._r_long(_ctx(last_close_15 + DAY, kl1d)) is False      # 일봉이 하루 묵음(조회 누락) → 판정 안 함
    assert EP._r_long(_ctx(last_close_15, None)) is False


def test_paper_worker_fetches_300_daily_only_when_needed():
    w = (APP / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    assert "_need_ep = _ep_ok and EP.needs_daily(_cx.kl15)" in w and 'limit=300 if _need_ep else 61' in w   # Fix 425: 코인만


# ── 진입 준비 ────────────────────────────────────────────────────────────
def test_ready_when_live_price_near_ema20():
    c, h, lo, v = daily(confirm=False)
    e20 = EP.emas(c)[EP.EMA_MID][-1]
    ok, d = EP.ready_state(c, h, lo, v, e20 * 1.01, "LONG", near_pct=2.0)
    assert ok and 0.9 < d["dist_pct"] < 1.1 and d["stop"] <= e20 * 1.01
    assert EP.ready_state(c, h, lo, v, e20 * 1.05, "LONG", near_pct=2.0)[0] is False    # 아직 멀다
    assert EP.ready_state(c, h, lo, v, e20 * 0.95, "LONG", near_pct=2.0)[0] is False    # EMA20 아래로 깨짐
    assert EP.ready_state(c, h, lo, v, e20 * 1.01, "SHORT", near_pct=2.0)[0] is False   # 상승 추세에 SHORT 준비 없음
    assert EP.ready_state(c, h, lo, v, 0, "LONG")[0] is False


def test_ready_short_mirror():
    c, h, lo, v = daily(confirm=False)
    k = 10_000.0
    mc, mh, ml = [k - x for x in c], [k - x for x in lo], [k - x for x in h]
    e20 = EP.emas(mc)[EP.EMA_MID][-1]
    assert EP.ready_state(mc, mh, ml, v, e20 * 0.99, "SHORT", near_pct=2.0)[0] is True


# ── 알림 스캔 ───────────────────────────────────────────────────────────
def test_scan_symbol_signal_and_ready():
    from app.workers import emapb_watch_worker as W
    P = EP.params_from()
    c, h, lo, v = daily()
    rows = rows_of(c, h, lo, v)
    today = int(rows[-1][0]) + DAY
    now = today + 3_600_000                                          # 마지막 일봉 닫히고 1시간 뒤
    its = W.scan_symbol(rows, "LONG", p=P, near_pct=2.0, now_ms=now, iv_ms=DAY)
    assert [x["kind"] for x in its] == ["signal"] and its[0]["bar"] == int(rows[-1][0])   # 진행 중 봉 없음 = 준비 판정 안 함

    c2, h2, lo2, v2 = daily(confirm=False)
    rows2 = rows_of(c2, h2, lo2, v2)
    e20 = EP.emas(c2)[EP.EMA_MID][-1]
    live = [int(rows2[-1][0]) + DAY, "0", "0", "0", str(e20 * 1.01), "1"]   # 오늘 진행 중 봉
    its2 = W.scan_symbol(rows2 + [live], "LONG", p=P, near_pct=2.0, now_ms=int(live[0]) + 3_600_000, iv_ms=DAY)
    assert [x["kind"] for x in its2] == ["ready"] and its2[0]["price"] == pytest.approx(e20 * 1.01)
    assert W.scan_symbol(rows2[:30], "LONG", p=P, near_pct=2.0, now_ms=now, iv_ms=DAY) == []   # 봉 부족


def test_scan_symbol_rejects_stale_response():
    """교차 감사: 거래소가 하루 묵은 응답을 주면 옛 신호를 새 신호로 알리지 않는다."""
    from app.workers import emapb_watch_worker as W
    c, h, lo, v = daily()
    rows = rows_of(c, h, lo, v)
    two_days_later = int(rows[-1][0]) + 2 * DAY + 3_600_000
    assert W.scan_symbol(rows, "LONG", p=EP.params_from(), near_pct=2.0, now_ms=two_days_later, iv_ms=DAY) == []


def test_signal_and_ready_independent():
    from app.workers import emapb_watch_worker as W
    c, h, lo, v = daily()
    rows = rows_of(c, h, lo, v)
    e20 = EP.emas(c)[EP.EMA_MID][-1]
    live = [int(rows[-1][0]) + DAY, "0", "0", "0", str(e20 * 1.005), "1"]
    kinds = [x["kind"] for x in W.scan_symbol(rows + [live], "LONG", p=EP.params_from(), near_pct=2.0,
                                               now_ms=int(live[0]) + 60_000, iv_ms=DAY)]
    assert kinds == ["signal", "ready"]                              # 어제 신호가 있어도 오늘 준비는 따로


def test_ready_ema50_strict():
    c, h, lo, v = daily(confirm=False)
    e = EP.emas(c)
    e50 = e[EP.EMA_SLOW][-1]
    p = EP.params_from(lambda k: "50" if k == "emapb_touch_tol_pct" else EP.SETTINGS[k][0])   # 허용오차를 일부러 크게
    p["touch_tol_pct"] = 5.0
    ok, _ = EP.ready_state(c, h, lo, v, e50 * 0.999, "LONG", p, e, near_pct=50)
    assert ok is False                                               # EMA50 아래는 허용오차가 커도 준비 아님


def test_failed_send_releases_dedup_key(monkeypatch):
    from app.workers import emapb_watch_worker as W
    import app.services.notification_service as NS_

    class R:
        def __init__(self):
            self.deleted = []

        def delete(self, k):
            self.deleted.append(k)

    class Boom:
        def __init__(self, db):
            pass

        def send_system_alert(self, **kw):
            raise RuntimeError("telegram down")
    monkeypatch.setattr(NS_, "NotificationService", Boom)
    r = R()
    fresh = [{"kind": "ready", "side": "LONG", "symbol": "AUSDT", "price": 1, "ema20": 1, "dist_pct": 0, "stop": 1, "_key": "k1"}]
    assert W._send(NS(rollback=lambda: None), r, fresh, "1d") == 0 and r.deleted == ["k1"]   # 다음 주기에 다시 보낸다


def test_chunks_under_telegram_limit():
    from app.workers import emapb_watch_worker as W
    lines = ["x" * 120] * 100
    groups = W.chunks(lines)
    assert len(groups) > 1 and all(sum(len(x) + 1 for x in g) <= W.MSG_LIMIT for g in groups)
    assert sum(len(g) for g in groups) == 100


def test_paper_daily_from_compact_drops_in_progress_bar():
    """교차 감사(확인 요청): 가상매매 일봉은 compact(now_ms) 로 진행 중 봉이 빠진 뒤 들어온다 → 마감 직후 판정이 켜진다."""
    from app.services import chart_learning as CL
    c, h, lo, v = daily()
    rows = rows_of(c, h, lo, v)
    today = int(rows[-1][0]) + DAY
    rows_live = rows + [[today, "1", "1", "1", "1", "1"]]           # 거래소 응답엔 오늘 진행 중 봉이 끼어 있다
    k1 = CL.compact(rows_live, now_ms=today + 60_000, interval_ms=CL.MS_DAY)
    assert int(k1[-1][0]) == int(rows[-1][0])
    assert EP._r_long(_ctx(today - M15, k1)) is True


def test_alert_line_and_dedup_keys():
    from app.workers import emapb_watch_worker as W
    line = W._line({"kind": "ready", "side": "LONG", "symbol": "ABCUSDT", "price": 1.23, "ema20": 1.2, "dist_pct": 2.5, "stop": 1.1})
    assert "진입 준비" in line and "ABCUSDT" in line and "LONG" in line
    assert W._k_sent("ready", "ABCUSDT", "LONG", "20261009") != W._k_sent("signal", "ABCUSDT", "LONG", "20261009")


def test_watch_worker_never_orders():
    src = (APP / "workers" / "emapb_watch_worker.py").read_text(encoding="utf-8")
    for bad in ("create_surge_position", "add_position_now", "ExecutionService", "place_order", "new_order"):
        assert bad not in src
    assert 'r.set(it["_key"], "1", nx=True, ex=2 * 86400)' in src     # 같은 알림 반복 방지


# ── 연결 ────────────────────────────────────────────────────────────────
def test_wiring():
    from app.integrations.binance.weight_priority import LOW_PRIORITY_CALLERS
    sr = (APP / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    assert 'guarded_job("emapb_watch"' in sr and 'id="emapb_watch"' in sr
    assert "emapb_watch" in LOW_PRIORITY_CALLERS
    rt = (APP / "api" / "router.py").read_text(encoding="utf-8")
    assert "ema_pullback_router" in rt
    html = (APP / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="ema-pullback-card"' in html and "ema-pullback-board.js" in html
    js = (APP / "static" / "js" / "ema-pullback-board.js").read_text(encoding="utf-8")
    assert "/ema-pullback/board" in js and "document.hidden" in js


def test_worker_daily_loop_separate_from_15m():
    src = (APP / "workers" / "external_strategies_worker.py").read_text(encoding="utf-8")
    assert 'def _k_last_ep(sym: str, interval: str) -> str: return f"ext:last:emapb:{interval}:{sym}"' in src
    blk = src[src.index("🗓 Fix 424 사장님 「전부 일봉」"):]
    blk = blk[:blk.index("r.setex(CYCLE_KEY")]
    assert 'ES.setting(db, "emapb_interval")' in blk and "last_key=lk" in blk
    assert blk.index("r.setex(lk, ep_ttl, str(ts))") > blk.index("EP.signal(")   # 처리 뒤 기록 (교차 감사)
    assert 'for sym in (universe if (fm != "off" or mm != "off") else []):' in src


def test_api_board(monkeypatch):
    from app.api.v1 import ema_pullback as A
    import app.core.redis_client as RC
    store = {"emapb:board": json.dumps({"at": "x", "items": [{"kind": "ready", "symbol": "A"}]})}
    monkeypatch.setattr(RC, "get_redis_client", lambda: NS(get=lambda k: store.get(k)))
    assert A.ema_pullback_board(user_id=1)["items"][0]["symbol"] == "A"
    store.clear()
    assert A.ema_pullback_board(user_id=1) == {"items": []}

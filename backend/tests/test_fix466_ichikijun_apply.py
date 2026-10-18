"""🗾 Fix 466 — 일목 실험실 변형을 예약 전략 인스턴스에 적용 + 적용 결과 검토 (사장님 10/18)."""
from __future__ import annotations

import ast
import json
import pathlib
import sys
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import ichikijun_apply as IA
from app.services import ichimoku_kijun as IK

ROOT = pathlib.Path(IA.__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from test_fix465_ichikijun_lab import _walk  # noqa: E402

H = 3_600_000


# ───────── 허용값 ─────────
@pytest.mark.parametrize("v,ok,key", [
    (None, True, None), ("", True, None), ("ichikijun", True, "champion"),
    ("ichikijun:4h_loose_pb_r2kj", True, "4h_loose_pb_r2kj"), ("ichikijun:5m_src_now_r2", False, None),
    ("ICHIKIJUN", False, None), ("obv", False, None), (3, False, None)])
def test_parse_entry_signal(v, ok, key):
    assert IA.parse_entry_signal(v) == (ok, key)


def test_every_variant_fits_column():
    assert all(len(f"ichikijun:{k}") <= 32 for k in IK.BY_KEY)


# ───────── 변형 결정 ─────────
def test_resolve_champion_rules():
    ch = json.dumps({"variant": "4h_src_pb_r15", "side": "SHORT", "score": 0.05, "since": "2026-11-07"})
    v, why, extra = IA.resolve_variant("ichikijun", ch, "SHORT")
    assert v.key == "4h_src_pb_r15" and extra["champion_score"] == 0.05
    assert IA.resolve_variant("ichikijun", ch, "LONG")[0] is None              # 방향 다름 = 대기
    v, why, _ = IA.resolve_variant("ichikijun", None, "LONG")
    assert v is None and "챔피언 없음" in why
    assert IA.resolve_variant("ichikijun", "not json", "LONG")[0] is None
    assert IA.resolve_variant("ichikijun:1d_src_now_r2kj", None, "LONG")[0].key == "1d_src_now_r2kj"


# ───────── 판정 = 실험실과 같은 함수 · 신선도 ─────────
def _bars(seed, n=400, step=4 * H):
    return IK.bars_from(_walk(seed, n, step))


def test_decide_matches_entry_at_and_freshness():
    var = IK.BY_KEY["4h_src_now_r2"]
    hits = 0
    for seed in range(8):
        full, btcf = _walk(seed, 600), _walk(50 + seed, 600)
        bs = IK.sma([float(b[4]) for b in btcf], 20)
        up = {int(b[0]): (float(b[4]) > bs[i]) if bs[i] is not None else None for i, b in enumerate(btcf)}
        Bfull = IK.bars_from(full)
        for side in ("LONG", "SHORT"):
            for k in range(IK.min_bars() + 1, 600):
                ref, stop, _ = IK.entry_at(Bfull, k, side, var, lambda i: up.get(Bfull.ts[i]))
                if not ref:
                    continue
                B, btc = IK.bars_from(full[:k + 1]), IK.bars_from(btcf[:k + 1])
                close_ms = B.ts[-1] + 4 * H
                ok, why, meta = IA.decide(B, btc, side, var, close_ms + 10 * 60_000)
                assert ok, why
                hits += 1
                assert meta["entry_bar_ts"] == B.ts[-1] and meta["rr"] == 2.0 and meta["kj_exit_missing"] is False
                assert meta["stop_pct"] == pytest.approx(IK.clamp_stop(B.c[-1], stop)[0] * 100, abs=1e-4)
                late, why2, _ = IA.decide(B, btc, side, var, close_ms + 31 * 60_000)   # 4h 신선도 30분
                assert not late and "늦음" in why2
                break
    assert hits > 0


def test_overrides_values():
    sl, tp = IA.overrides({"stop_pct": 5.0, "rr": 2.0}, 2)
    assert (sl, tp) == (10.0, 20.0)
    assert IA.overrides({"stop_pct": 15.0, "rr": 1.5}, 3) == (45.0, 67.5)
    assert IA.overrides({"stop_pct": 0, "rr": 2}, 2) is None
    assert IA.overrides({"rr": 2}, 2) is None
    assert IA.overrides({"stop_pct": 15.0, "rr": 2.0}, 125)[1] == 999.0       # Numeric(5,2) 상한


# ───────── 워커 쪽 판정 (가짜 거래소·Redis) ─────────
class _R:
    def __init__(self):
        self.d = {}

    def get(self, k):
        return self.d.get(k)

    def setex(self, k, _t, v):
        self.d[k] = v


class _BC:
    def __init__(self, data):
        self.data, self.calls = data, 0

    def get_klines(self, *, symbol, interval, limit):
        self.calls += 1
        kl = self.data[symbol]
        return [list(b) for b in kl] + [[kl[-1][0] + 4 * H, "1", "1", "1", "1", "1"]]


class _DB:
    def __init__(self, champion=None):
        self.ch = champion

    def get(self, _model, key):
        return SimpleNamespace(value=self.ch) if key == "ichikijun_champion" and self.ch else None


def test_judge_no_refetch_same_bar(monkeypatch):
    from app.workers import ichikijun_sched as S
    data = {"AAAUSDT": _walk(1, 300), "BTCUSDT": _walk(2, 300)}
    target = data["AAAUSDT"][-1][0]
    now = target + 4 * H + 61_000
    monkeypatch.setattr(IA, "decide", lambda *a, **k: (False, "대기: 신호 없음", {}))
    si = SimpleNamespace(id=7, symbol="AAAUSDT", side="LONG", entry_signal="ichikijun:4h_src_now_r2", leverage=2)
    bc, r = _BC(data), _R()
    assert S.judge(_DB(), bc, r, si, now)[0] is False and bc.calls == 2
    ok, why, _ = S.judge(_DB(), bc, r, si, now + 5 * 60_000)
    assert not ok and why == "대기: 신호 없음" and bc.calls == 2              # 같은 봉 = 다시 받지 않음
    S.judge(_DB(), bc, r, si, now + 4 * H)                                   # 다음 봉이 생기면… (가짜 데이터엔 없음 → 정착 대기)
    assert bc.calls == 4


def test_judge_champion_missing_waits_without_fetch():
    from app.workers import ichikijun_sched as S
    bc = _BC({})
    si = SimpleNamespace(id=1, symbol="AAAUSDT", side="LONG", entry_signal="ichikijun", leverage=2)
    ok, why, _ = S.judge(_DB(None), bc, _R(), si, 10 ** 13)
    assert not ok and "챔피언 없음" in why and bc.calls == 0


def test_judge_signal_returns_meta_and_overrides(monkeypatch):
    from app.workers import ichikijun_sched as S
    data = {"AAAUSDT": _walk(1, 300), "BTCUSDT": _walk(2, 300)}
    target = data["AAAUSDT"][-1][0]
    meta = {"variant": "4h_src_pb_r15", "stop_pct": 4.0, "rr": 1.5, "entry_bar_ts": target}
    monkeypatch.setattr(IA, "decide", lambda *a, **k: (True, "진입", dict(meta)))
    ch = json.dumps({"variant": "4h_src_pb_r15", "side": "LONG", "score": 0.1, "since": "d"})
    p1 = SimpleNamespace(stage_no=1, trigger_price=Decimal("1.234"), is_enabled=True)
    p2 = SimpleNamespace(stage_no=2, trigger_price=Decimal("1.1"), is_enabled=False)    # 꺼진 단계는 세지 않음
    si = SimpleNamespace(id=3, symbol="AAAUSDT", side="LONG", entry_signal="ichikijun", leverage=3,
                         force_sl_enabled_override=False, force_sl_roi_override=None, tp1_pct_override=Decimal("25"),
                         entry_signal_meta=None, stage_plans=[p2, p1])
    ok, why, m = S.judge(_DB(ch), _BC(data), _R(), si, target + 4 * H + 61_000)
    assert ok and m["champion_score"] == 0.1 and m["by"].startswith("챔피언")
    assert S.apply_overrides(si, m)
    assert si.force_sl_enabled_override is True and si.force_sl_roi_override == Decimal("12.00")
    assert si.tp1_pct_override == Decimal("18.00") and si.entry_signal_meta["tp1_roi"] == 18.0
    # 🗾 Fix 470: DB 의 1단계 가격은 그대로(시장가는 start_stage1(force_market) 로) · 1단계 전략만
    assert p1.trigger_price == Decimal("1.234") and si.entry_signal_meta["market_entry"] is True
    assert S.apply_overrides(SimpleNamespace(leverage=2, stage_plans=[]), m) is False
    two = SimpleNamespace(leverage=2, stage_plans=[SimpleNamespace(stage_no=1, is_enabled=True),
                                                   SimpleNamespace(stage_no=2, is_enabled=True)])
    assert S.apply_overrides(two, m) is False and S.single_stage(two) is False


# ───────── 예약 워커 분기 (전부 가짜 — 주문 없음) ─────────
def _run_worker(monkeypatch, si, judge_result):
    from app.workers import ichikijun_sched as S
    from app.workers import scheduled_entry_worker as W

    calls = {"start": [], "check": 0, "judge": 0}

    class _Res:
        def __init__(self, v):
            self.v = v

        def scalars(self):
            return SimpleNamespace(all=lambda: self.v)

        def scalar_one_or_none(self):
            return self.v

    class DB:
        n = 0

        def get(self, _m, key):
            return SimpleNamespace(value="1") if key == W.ENABLED_KEY else None

        def execute(self, _q):
            DB.n += 1
            return _Res({1: [si], 2: SimpleNamespace(id=1, is_testnet=False, api_key_enc="k", api_secret_enc="s")}.get(DB.n))

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(W, "SessionLocal", DB)
    monkeypatch.setattr(W, "_redis", lambda: _R())
    import app.core.api_backoff as AB
    import app.core.crypto as CR
    import app.integrations.binance.client as BCM
    import app.services.execution_service as ES
    import app.services.position_limit as PL
    import app.services.stage_entry_signal as SES
    monkeypatch.setattr(AB, "is_account_banned", lambda _id: False)
    monkeypatch.setattr(CR, "decrypt_text", lambda x: x)
    monkeypatch.setattr(BCM, "BinanceClient", lambda **k: object())
    monkeypatch.setattr(PL, "check_position_slot", lambda db, w: (True, "", 0, 9))

    def _chk(*a, **k):
        calls["check"] += 1
        return False, "기존 대기", {}
    monkeypatch.setattr(SES, "check_stage_entry_signal", _chk)

    def _judge(*a, **k):
        calls["judge"] += 1
        return judge_result
    monkeypatch.setattr(S, "judge", _judge)

    class _Ex:
        def __init__(self, *a, **k):
            pass

        def start_stage1(self, sid, **kw):
            calls["start"].append(sid)
            calls["force_market"] = kw.get("force_market")
    monkeypatch.setattr(ES, "ExecutionService", _Ex)
    stat = W.run_scheduled_entry_once()
    return calls, stat


def _si(sig, age_s=300):
    from datetime import datetime, timedelta, timezone
    return SimpleNamespace(id=11, symbol="AAAUSDT", side="LONG", entry_signal=sig, leverage=2, is_archived=False,
                           created_at=datetime.now(timezone.utc) - timedelta(seconds=age_s), force_sl_enabled_override=False,
                           force_sl_roi_override=None, tp1_pct_override=Decimal("25"), entry_signal_meta=None,
                           stage_plans=[SimpleNamespace(stage_no=1, trigger_price=Decimal("1"))])


def test_worker_null_signal_uses_old_path(monkeypatch):
    calls, stat = _run_worker(monkeypatch, _si(None), (True, "x", {}))
    assert calls["check"] == 1 and calls["judge"] == 0 and calls["start"] == []
    assert "force_market" not in calls
    assert stat["skipped"] == {"signal_wait": 1}


def test_worker_ichikijun_enters_with_overrides(monkeypatch):
    si = _si("ichikijun:4h_src_now_r2")
    calls, stat = _run_worker(monkeypatch, si, (True, "진입", {"variant": "4h_src_now_r2", "stop_pct": 5.0, "rr": 2.0}))
    assert calls["check"] == 0 and calls["judge"] == 1 and calls["start"] == [11] and stat["entered"] == 1
    assert calls["force_market"] is True                                         # 🗾 Fix 470 일목 = 시장가
    assert si.force_sl_roi_override == Decimal("10.00") and si.tp1_pct_override == Decimal("20.00")


def test_worker_ichikijun_wait_and_bad_meta(monkeypatch):
    calls, stat = _run_worker(monkeypatch, _si("ichikijun"), (False, "대기: 챔피언 없음", {}))
    assert calls["start"] == [] and stat["skipped"] == {"signal_wait": 1}
    calls, stat = _run_worker(monkeypatch, _si("ichikijun"), (True, "진입", {"rr": 2.0}))      # 손절폭 없음
    assert calls["start"] == [] and stat["skipped"] == {"ichikijun_override_fail": 1}


def test_worker_skips_just_created(monkeypatch):
    calls, stat = _run_worker(monkeypatch, _si(None, age_s=5), (True, "x", {}))
    assert calls["check"] == 0 and calls["start"] == [] and stat["skipped"] == {"just_created": 1}


# ───────── 생성 API: 검증 · 저장 실패 보상 ─────────
def _create(monkeypatch, sig, mode, fail_commit=False, stages=1):
    from fastapi import HTTPException
    from app.api.v1.strategies import crud as C
    from app.schemas.strategy import StrategyCreateRequest

    inst = SimpleNamespace(id=5, entry_signal=None, is_archived=False, status="WAITING", capital_management_mode=None,
                           stage_plans=[SimpleNamespace(stage_no=s, is_enabled=True) for s in range(1, stages + 1)])

    class _Svc:
        def __init__(self, db):
            pass

        def create_strategy_instance(self, **k):
            inst.capital_management_mode = k["capital_management_mode"]
            inst.created_mode = k["capital_management_mode"]
            return inst

    class DB:
        commits = 0

        def commit(self):
            DB.commits += 1
            if fail_commit and DB.commits == 1:
                raise RuntimeError("db down")

        def rollback(self):
            pass

        def refresh(self, _x):
            pass

        def get(self, _t, _id):
            raise AssertionError("실패한 세션으로 보상하지 않는다")

    monkeypatch.setattr(C, "StrategyService", _Svc)

    class _Fresh:                                   # 보상은 새 세션으로
        def get(self, _t, _id):
            return inst

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass
    monkeypatch.setattr("app.core.database.SessionLocal", _Fresh)
    monkeypatch.setattr(C.StrategyDetailResponse, "model_validate", classmethod(lambda cls, x: SimpleNamespace(family=None)))
    monkeypatch.setattr("app.services.strategy_family.family_of", lambda x: "legacy_manual")
    body = StrategyCreateRequest(exchange_account_id=1, strategy_template_id=1, symbol="AAAUSDT", side="LONG",
                                 start_price=1, capital_management_mode=mode, entry_signal=sig)
    try:
        C.create_strategy(body, DB(), 1)
        return inst, None
    except HTTPException as e:
        return inst, e.status_code


def test_create_validation_and_save(monkeypatch):
    inst, code = _create(monkeypatch, "ichikijun:4h_src_pb_r15", "scheduled")
    assert code is None and inst.entry_signal == "ichikijun:4h_src_pb_r15"
    assert inst.created_mode == "fixed" and inst.capital_management_mode == "scheduled"   # 한 커밋에 신호+예약
    assert _create(monkeypatch, "ichikijun", "fixed")[1] == 400                 # 예약 아님
    assert _create(monkeypatch, "ichikijun:bogus", "scheduled")[1] == 400
    inst, code = _create(monkeypatch, None, "fixed")
    assert code is None and inst.entry_signal is None                          # 기존 경로 무변경
    inst, code = _create(monkeypatch, None, "scheduled")
    assert code is None and inst.created_mode == "scheduled"                   # 기본 예약도 그대로


def test_create_ichikijun_rejects_multi_stage(monkeypatch):
    inst, code = _create(monkeypatch, "ichikijun", "scheduled", stages=3)
    assert code == 400 and inst.is_archived is True and inst.entry_signal is None      # 만든 것은 보관(fixed 라 진입 없음)
    inst, code = _create(monkeypatch, None, "scheduled", stages=3)
    assert code is None                                                                # 기본 예약은 다단계 그대로


def test_create_signal_save_failure_archives(monkeypatch):
    inst, code = _create(monkeypatch, "ichikijun", "scheduled", fail_commit=True)
    assert code == 500 and inst.is_archived is True and inst.status == "STOPPED"


# ───────── 적용 결과 검토 ─────────
def test_applied_report_r_and_pairing():
    insts = [
        {"id": 1, "symbol": "A", "side": "LONG", "status": "CLOSED_BY_TP", "leverage": 2, "realized_pnl": 2.0,
         "stage1_capital": 10, "stages": 1, "entry_signal": "ichikijun", "started_at": "t",
         "meta": {"variant": "4h_src_now_r2", "entry_bar_ts": 100, "stop_pct": 5.0, "rr": 2.0}},          # 위험 1 USDT → +2R
        {"id": 2, "symbol": "B", "side": "SHORT", "status": "CLOSED_BY_SL", "leverage": 2, "realized_pnl": -1.0,
         "stage1_capital": 10, "stages": 3, "entry_signal": "ichikijun:4h_src_now_r2kj", "started_at": "t",
         "meta": {"variant": "4h_src_now_r2kj", "entry_bar_ts": 200, "stop_pct": 5.0, "rr": 2.0, "kj_exit_missing": True,
                  "clamped": True}},
        {"id": 3, "symbol": "C", "side": "LONG", "status": "WAITING", "leverage": 2, "realized_pnl": 0,
         "stage1_capital": 10, "stages": 1, "entry_signal": "ichikijun", "started_at": None,
         "meta": {"variant": "4h_src_now_r2", "entry_bar_ts": 300, "stop_pct": 5.0}},                    # 손절·익절만 박히고 진입 실패
    ]
    rep = IA.applied_report(insts, {("4h_src_now_r2", "LONG", "A", 100): 1.98})
    by = {r["id"]: r for r in rep["rows"]}
    assert by[1]["live_r"] == pytest.approx(2.0) and by[1]["diff"] == pytest.approx(0.02)
    assert by[2]["live_r"] == pytest.approx(-1.0) and by[2]["lab_r"] is None
    assert set(by[2]["flags"]) == {"기준선 청산 없음", "단계 추가 계획", "손절 15% 상한"}
    assert by[3]["entered"] is False and by[3]["live_r"] is None
    s = rep["summary"]
    assert (s["instances"], s["entered"], s["finished"], s["paired"]) == (3, 2, 2, 1)
    assert s["live_avg_r"] == pytest.approx(0.5) and s["pnl_sum"] == pytest.approx(1.0)


# ───────── 주문 모듈 import 금지 (판정 파일) ─────────
@pytest.mark.parametrize("rel", ["app/services/ichikijun_apply.py", "app/workers/ichikijun_sched.py"])
def test_no_order_imports(rel):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    names = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    names |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(b in x for x in names for b in ("execution_service", "surge_ladder_entry", "order"))

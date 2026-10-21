"""Fix 479 거래소 잔액 시간별 기록 + 변화 설명 — 가짜 redis."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.services import account_snapshot as A

T0 = datetime(2026, 10, 22, 0, 7, tzinfo=timezone.utc)


class _R:
    def __init__(self):
        self.kv, self.ttl, self.z = {}, {}, {}

    def setex(self, k, ttl, v):
        self.kv[k], self.ttl[k] = v, ttl

    def get(self, k):
        return self.kv.get(k)

    def zadd(self, k, mapping):
        self.z.setdefault(k, {}).update(mapping)

    def zremrangebyscore(self, k, lo, hi):
        z = self.z.get(k, {})
        for m in [m for m, s in z.items() if lo <= s <= hi]:
            del z[m]

    def zrangebyscore(self, k, lo, hi, withscores=False):
        items = sorted((s, m) for m, s in self.z.get(k, {}).items() if lo <= s <= hi)
        return [(m, s) for s, m in items] if withscores else [m for s, m in items]


def _acct(w, u, pos=()):
    return lambda: {"totalWalletBalance": str(w), "totalUnrealizedProfit": str(u), "totalMarginBalance": str(w + u),
                    "availableBalance": "100", "positions": [{"symbol": s, "positionSide": "LONG", "positionAmt": "1", "unrealizedProfit": str(v)} for s, v in pos]
                    + [{"symbol": "ZERO", "positionAmt": "0", "unrealizedProfit": "0"}]}


def test_take_saves_overwrites_and_prunes():
    r = _R()
    st = A.take(r, _acct(1000, -50, [("A", -40), ("B", -10)]), T0)
    key = "acct:snap:2026102200"
    assert st["ok"] and r.ttl[key] == A.TTL_DAYS * 86400 and json.loads(r.kv[key])["positions"] == 2
    A.take(r, _acct(990, -60), T0 + timedelta(minutes=20))                 # 같은 시간 = 덮어씀
    assert json.loads(r.kv[key])["wallet"] == 990 and len(r.z[A.INDEX]) == 1
    r.z[A.INDEX]["2026060100"] = (T0 - timedelta(days=200)).timestamp()
    A.take(r, _acct(990, -60), T0 + timedelta(hours=1))
    assert "2026060100" not in r.z[A.INDEX]
    top = json.loads(r.kv[key])["top_upl"]
    assert top == [] or all("symbol" in x for x in top)


def test_take_bad_numbers_and_failure():
    r = _R()
    st = A.take(r, lambda: {"totalWalletBalance": "100", "totalUnrealizedProfit": "nan", "totalMarginBalance": "x"}, T0)
    assert st["wallet"] == 100 and st["unrealized"] is None and st["margin"] is None      # 깨진 칸만 None
    assert A.take(_R(), lambda: {"totalWalletBalance": "nan"}, T0)["ok"] is False          # 숫자가 하나도 없으면 저장 안 함

    def boom():
        raise RuntimeError("418")
    r2 = _R()
    assert A.take(r2, boom, T0) == {"ok": False, "why": "계정 조회 실패: RuntimeError"} and r2.kv == {}


def test_explain_nearest_income_and_unexplained():
    r = _R()
    A.take(r, _acct(1000, -50), T0)
    A.take(r, _acct(900, -350), T0 + timedelta(hours=24))
    got = {}

    def inc(a, b):
        got["range"] = (a, b)
        return [{"incomeType": "FUNDING_FEE", "income": "-60", "symbol": "POW"}, {"incomeType": "REALIZED_PNL", "income": "-30", "symbol": "BLUR"},
                {"incomeType": "COMMISSION", "income": "-2"}, {"incomeType": "TRANSFER", "income": "-5"}, {"incomeType": "X", "income": "bad"}]
    res = A.explain(r, inc, T0 + timedelta(minutes=40), T0 + timedelta(hours=24, minutes=-30))
    assert res["d_wallet"] == -100 and res["d_unrealized"] == -300 and res["d_margin"] == -400
    assert res["income"] == {"펀딩": -60.0, "실현": -30.0, "수수료": -2.0, "이체": -5.0} and res["income_total"] == -97.0
    assert res["unexplained"] == -3.0
    assert got["range"][0] == int(T0.timestamp() * 1000)                    # 소득 구간 = 실제 스냅샷 시각
    txt = A.report_text(res)
    assert "지갑 잔액" in txt and "-100.00" in txt and "펀딩 -60.00" in txt and "설명 안 되는 몫 -3.00" in txt


def test_explain_missing_snapshot_and_income_fail():
    r = _R()
    A.take(r, _acct(1000, 0), T0)
    res = A.explain(r, lambda a, b: [], T0 + timedelta(hours=5), T0 + timedelta(hours=6))    # ±90분 밖
    assert res["snap_start"] is None and res["d_wallet"] is None and res["unexplained"] is None

    def fail(a, b):
        raise RuntimeError("timeout")
    A.take(r, _acct(990, 0), T0 + timedelta(hours=1))
    res2 = A.explain(r, fail, T0, T0 + timedelta(hours=1))
    assert res2["income_ok"] is False and res2["unexplained"] is None and "소득 조회 실패" in A.report_text(res2)


def test_scheduler_and_no_order_code():
    import pathlib
    root = pathlib.Path(A.__file__).resolve().parents[1]
    sch = (root / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    assert 'id="account_snapshot"' in sch
    src = pathlib.Path(A.__file__).read_text(encoding="utf-8")
    assert "place_" not in src and "commit()" not in src and "api_key=" in src and "print(acc" not in src


def test_audit_fixes_error_dict_same_snapshot_other_asset():
    r = _R()
    A.take(r, _acct(1000, 0), T0)
    before = dict(r.kv)
    st = A.take(r, lambda: {"code": -2015, "msg": "Invalid API-key"}, T0 + timedelta(minutes=10))
    assert st["ok"] is False and r.kv == before                              # 오류 응답이 정상 기록을 덮지 않음
    res = A.explain(r, lambda a, b: [], T0 - timedelta(minutes=30), T0 + timedelta(minutes=60))
    assert res["snap_end"] is None and res["d_wallet"] is None and any("같은 기록" in w for w in res["warnings"])
    A.take(r, _acct(995, 0), T0 + timedelta(hours=1))
    res2 = A.explain(r, lambda a, b: [{"incomeType": "COMMISSION", "income": "-0.01", "asset": "BNB"},
                                      {"incomeType": "COMMISSION", "income": "-5", "asset": "USDT"}], T0, T0 + timedelta(hours=1))
    assert res2["income_total"] == -5.0 and res2["unexplained"] == 0.0 and "BNB" in A.report_text(res2)


def test_top_lists_by_magnitude():
    r = _R()
    st = A.take(r, _acct(1000, 0, [("WIN", 1000), ("SMALL", 10), ("LOSS", -500)]), T0)
    assert [x["symbol"] for x in st["top_upl"]] == ["WIN", "LOSS", "SMALL"]
    A.take(r, _acct(900, 0), T0 + timedelta(hours=1))
    res = A.explain(r, lambda a, b: [{"incomeType": "REALIZED_PNL", "income": v, "symbol": s} for s, v in (("P", "300"), ("L", "-400"), ("S", "-1"))], T0, T0 + timedelta(hours=1))
    assert [s for s, _ in res["top_realized"]] == ["L", "P", "S"]

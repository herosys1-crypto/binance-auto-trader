"""📅 Fix 351 — 1일·3일·5일 순위 감시 대상 + 진입 관문 인정.

사장님 2026-09-05: "1일에서 5일 순위를 기준으로 당일 급등락을 같이 공유해서 활용해줘"
실측: 며칠 순위는 진입 신호가 아니라 감시 대상 (일봉 60일: 조정일 종가 진입 롱 −1.90 / 숏 −3.10).
"""
from pathlib import Path

from app.services import multiday_movers as M

ROOT = Path(__file__).resolve().parents[1] / "app"


def _src(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_returns_는_전일_종가_기준():
    closes = [100, 100, 110, 120, 130, 140, 150]          # 완성봉 7개, 마지막 = 어제
    r3, r5 = M.returns_from_daily(closes)
    assert abs(r3 - (150 / 120 - 1)) < 1e-9 and abs(r5 - (150 / 100 - 1)) < 1e-9
    assert M.returns_from_daily([1, 2, 3]) == (None, None)


def test_rank_symbols_상승_하락_각_N위():
    rets = {f"S{i}": (i * 0.01, -i * 0.01) for i in range(1, 8)}   # r3 는 S7 최고, r5 는 S1 최고
    r = M.rank_symbols(rets, 2)
    assert r["S7"]["UP3D"] == 1 and r["S6"]["UP3D"] == 2 and r["S5"]["UP3D"] is None
    assert r["S1"]["UP5D"] == 1 and r["S7"]["DOWN5D"] == 1
    assert M.best_tag(r["S7"]) == ("UP3D", 1)
    assert M.best_tag(r["S4"]) is None and M.best_tag(None) is None


def test_rank_map_multiday_는_당일_뒤에_붙이고_중복_제거(monkeypatch):
    tickers = [{"symbol": f"S{i}USDT", "priceChangePercent": str(10 - i), "quoteVolume": "9000000"} for i in range(6)]
    # 당일 2위까지 = 상승 S0,S1 / 하락 S5,S4 가 base 에 들어간다. 다일 순위는 S2(UP3D), S3(DOWN5D), S0(UP5D=중복)
    monkeypatch.setattr(M, "get_multiday_ranks", lambda bc, t, db=None, min_quote_volume=0: {
        "S0USDT": {"UP5D": 1}, "S2USDT": {"UP3D": 1}, "S3USDT": {"DOWN5D": 2}})
    out = M.rank_map_multiday(tickers, 2, bc=object(), db=None, min_quote_volume=0)
    syms = [(t["symbol"], tag, rk) for t, tag, rk in out]
    assert syms[:2] == [("S0USDT", "UP", 1), ("S1USDT", "UP", 2)]          # 당일 상승 2위까지 먼저
    assert ("S0USDT", "UP5D", 1) not in syms, "당일 순위에 이미 있으면 중복 제거"
    assert ("S2USDT", "UP3D", 1) in syms and ("S3USDT", "DOWN5D", 2) in syms
    tags = [tag for _, tag, _ in syms]
    assert tags.index("UP3D") < tags.index("DOWN5D"), "태그 순서 UP3D → UP5D → DOWN3D → DOWN5D"


def test_bc_없거나_설정_OFF_면_당일만(monkeypatch):
    tickers = [{"symbol": "AUSDT", "priceChangePercent": "5", "quoteVolume": "9000000"}]
    monkeypatch.setattr(M, "get_multiday_ranks", lambda *a, **k: (_ for _ in ()).throw(AssertionError("불리면 안 됨")))
    assert len(M.rank_map_multiday(tickers, 50, bc=None, min_quote_volume=0)) == 1

    class _DB:
        def get(self, _m, key):
            return type("R", (), {"value": "0"})() if key == M.SETTING_ENABLED else None
    assert len(M.rank_map_multiday(tickers, 50, bc=object(), db=_DB(), min_quote_volume=0)) == 1


def test_기본_설정은_ON_이고_top_n_50():
    assert M.multiday_enabled(None) is True and M.gate_multiday_enabled(None) is True
    assert M.top_n(None) == 50 and M.cache_seconds(None) == 1800


def test_배선_감지워커_두_개와_관문():
    for rel in ("workers/pump_top_detector_worker.py", "workers/long_bottom_detector_worker.py"):
        s = _src(rel)
        assert "rank_map_multiday(tickers, MAX_SYMBOLS, bc=bc, db=db)" in s, rel
    g = _src("services/chg24_entry_gate.py")
    i_mh = g.find("multiday_hit as _mh351")
    i_no = g.find("상승/하락 각 {n}위 밖")
    assert 0 < i_mh < i_no, "다일 순위 판정이 「순위 밖 차단」 앞에 있어야 한다"


def test_실측_근거가_모듈에_남아_있다():
    s = _src("services/multiday_movers.py")
    for token in ("−1.90", "−3.10", "HEMI", "감시 대상"):
        assert token in s, token

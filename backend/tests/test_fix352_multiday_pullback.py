"""📅 Fix 352 — 「며칠 상승 뒤 조정 → RSI14 과매도 뒤 첫 상승 마감」 롱 알람.

사장님 2026-09-05: "1일에서 5일 사이 이렇게 조정받는 심볼을 찾아서 숏과 롱으로 수익을 만들어야 하는게 우리 시스템"
실측(263 심볼-일): 이 규칙 LONG +0.63 (n=173, 43%) vs 기준선 −0.73; 숏 규칙은 전부 음수.
"""
import json
from pathlib import Path

from app.services import multiday_movers as M
from app.workers import long_bottom_detector_worker as W

ROOT = Path(__file__).resolve().parents[1] / "app"


def test_rsi14_과매도_뒤_첫_상승_마감():
    closes = [100.0 - i * 1.0 for i in range(25)]          # 25봉 연속 하락 → RSI14 ≈ 0
    ok, d = M.is_pullback_rebound(closes + [closes[-1] * 1.01])   # 마지막 봉 상승 마감
    assert ok is True and d["rsi_prev"] < 35, d
    ok2, _ = M.is_pullback_rebound(closes + [closes[-1] * 0.99])  # 아직 하락 마감
    assert ok2 is False
    up = [100.0 + i for i in range(25)]                      # 상승 중(RSI 높음) → 아님
    ok3, _ = M.is_pullback_rebound(up + [up[-1] * 1.01])
    assert ok3 is False


def test_기본_설정_ON_8퍼_35():
    assert M.pullback_enabled(None) is True
    assert M.pullback_params(None) == (8.0, 35.0)


class _Redis:
    def __init__(self):
        self.store = {}

    def exists(self, k):
        return 1 if k in self.store else 0

    def setex(self, k, ttl, v):
        self.store[k] = v


def test_스캔은_UP3D_UP5D_이면서_당일_하락한_것만(monkeypatch):
    red = _Redis()
    monkeypatch.setattr("app.core.redis_client.get_redis_client", lambda: red)
    down = [100.0 - i for i in range(30)]; rebound = down + [down[-1] * 1.01]

    class _BC:
        def get_klines(self, symbol, interval, limit):
            assert interval == "15m"
            return [[0, 0, 0, 0, str(c), "1"] for c in rebound] + [[0, 0, 0, 0, "1", "1"]]   # 마지막 = 진행중
    ranked = [
        ({"symbol": "HEMIUSDT", "priceChangePercent": "-13"}, "UP5D", 3),     # 대상 → 알람
        ({"symbol": "TAKEUSDT", "priceChangePercent": "-3"}, "UP3D", 7),      # 당일 −3% = 조정 아님
        ({"symbol": "XUSDT", "priceChangePercent": "-20"}, "DOWN", 1),        # 당일 하락만 (며칠 상승 아님)
    ]
    n = W._multiday_pullback_scan(_BC(), None, ranked)
    assert n == 1 and "sajangnim:bottom_long:HEMIUSDT" in red.store
    payload = json.loads(red.store["sajangnim:bottom_long:HEMIUSDT"])
    assert payload["pattern"] == "MULTIDAY_PULLBACK" and payload["multiday_tag"] == "UP5D" and payload["side"] == "LONG"
    # 두 번째 호출은 TTL 알람이 있으니 재발행 안 함
    assert W._multiday_pullback_scan(_BC(), None, ranked) == 0


def test_배선():
    s = (ROOT / "workers" / "long_bottom_detector_worker.py").read_text(encoding="utf-8")
    assert "_mp_n = _multiday_pullback_scan(bc, db, _ranked)" in s
    a = (ROOT / "workers" / "auto_long_at_bottom_worker.py").read_text(encoding="utf-8")
    assert '"MULTIDAY_PULLBACK"' in a and 'in MOMENTUM_ALERT_PATTERNS else None' in a, "알람 패턴 전달 + Fix 349 게이트 통과"
    g = (ROOT / "services" / "long_surge_gate.py").read_text(encoding="utf-8")
    assert '"MULTIDAY_PULLBACK"' in g, "당일 −% 인데 Fix 274(24h<15% 롱 차단)에 걸리면 안 된다"

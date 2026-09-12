"""📅 Fix 352 — 「며칠 상승 뒤 조정 → RSI14 과매도 뒤 첫 상승 마감」 롱 알람.

사장님 2026-09-05: "1일에서 5일 사이 이렇게 조정받는 심볼을 찾아서 숏과 롱으로 수익을 만들어야 하는게 우리 시스템"
실측(263 심볼-일): 이 규칙 LONG +0.63 (n=173, 43%) vs 기준선 −0.73; 숏 규칙은 전부 음수.
대기열 3C (2026-09-13): 자리 = multiday_context (기본 DOWN24 = 옛 자리) + 그림자 multiday_context_shadow (기본 UP24).
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


class _DB:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, _m, key):
        v = self.kv.get(key)
        return None if v is None else type("R", (), {"value": v})()


def _bc_rebound():
    down = [100.0 - i for i in range(30)]; rebound = down + [down[-1] * 1.01]

    class _BC:
        def get_klines(self, symbol, interval, limit):
            assert interval == "15m"
            return [[0, 0, 0, 0, str(c), "1"] for c in rebound] + [[0, 0, 0, 0, "1", "1"]]   # 마지막 = 진행중
    return _BC()


RANKED = [
    ({"symbol": "HEMIUSDT", "priceChangePercent": "-13"}, "UP5D", 3),     # 며칠 상승 + 당일 −13% (옛 자리)
    ({"symbol": "TAKEUSDT", "priceChangePercent": "-3"}, "UP3D", 7),      # 당일 −3% = 조정 아님
    ({"symbol": "XUSDT", "priceChangePercent": "-20"}, "DOWN", 1),        # 당일 하락만 (며칠 상승 아님)
    ({"symbol": "PUMPUSDT", "priceChangePercent": "12"}, "UP", 4),        # 당일 상승 4위
]


def _alerts(red):
    return {k for k in red.store if k.startswith("sajangnim:bottom_long:")}


def _shadows(red, sym):
    return [k for k in red.store if k.startswith(f"multiday:shadow:UP24:{sym}:")]


def test_스캔_기본은_옛자리_실알람이고_UP24는_그림자만(monkeypatch):
    """대기열 3C (9/13 반박 검증 뒤): 실알람은 1회 10 USDT 가 아니라 910 사다리·피라미딩·재진입 → 기본 = 옛 자리, UP24 는 발생만 기록."""
    red = _Redis()
    monkeypatch.setattr("app.core.redis_client.get_redis_client", lambda: red)
    assert W._multiday_pullback_scan(_bc_rebound(), None, RANKED) == 1
    assert _alerts(red) == {"sajangnim:bottom_long:HEMIUSDT"}
    payload = json.loads(red.store["sajangnim:bottom_long:HEMIUSDT"])
    assert payload["pattern"] == "MULTIDAY_PULLBACK" and payload["multiday_tag"] == "UP5D" and payload["side"] == "LONG"
    assert payload["context"] == "DOWN24"
    sh = _shadows(red, "PUMPUSDT")
    assert len(sh) == 1 and json.loads(red.store[sh[0]])["context"] == "UP24"
    # 두 번째 호출: 알람·그림자 모두 30분 TTL 이 있어 다시 쓰지 않는다
    assert W._multiday_pullback_scan(_bc_rebound(), None, RANKED) == 0
    assert len(_shadows(red, "PUMPUSDT")) == 1 and _alerts(red) == {"sajangnim:bottom_long:HEMIUSDT"}


def test_스캔_UP24_를_켜면_당일_상승_순위가_실알람(monkeypatch):
    red = _Redis()
    monkeypatch.setattr("app.core.redis_client.get_redis_client", lambda: red)
    assert W._multiday_pullback_scan(_bc_rebound(), _DB(multiday_context="UP24"), RANKED) == 1
    assert _alerts(red) == {"sajangnim:bottom_long:PUMPUSDT"}
    assert json.loads(red.store["sajangnim:bottom_long:PUMPUSDT"])["context"] == "UP24"
    assert not [k for k in red.store if k.startswith("multiday:shadow")]      # 실알람 자리 = 그림자 자리 → 그림자 없음


def test_스캔_그림자_끄기(monkeypatch):
    red = _Redis()
    monkeypatch.setattr("app.core.redis_client.get_redis_client", lambda: red)
    assert W._multiday_pullback_scan(_bc_rebound(), _DB(multiday_context_shadow="OFF"), RANKED) == 1
    assert not [k for k in red.store if k.startswith("multiday:shadow")]


def test_자리_판정_3종():
    ok = M.pullback_place_ok
    assert ok("UP24", "UP", 12.0, 8.0) and not ok("UP24", "UP5D", -13.0, 8.0) and not ok("UP24", "DOWN", -20.0, 8.0)
    assert ok("DOWN24", "UP5D", -13.0, 8.0) and not ok("DOWN24", "UP5D", -3.0, 8.0) and not ok("DOWN24", "UP", 12.0, 8.0)
    assert ok("DOWN24", "UP3D", -8.0, 8.0)                                   # 옛 필터와 같은 경계 (≤ −min_drop)
    assert ok("ANY", "UP", 12.0, 8.0) and ok("ANY", "UP3D", 5.0, 8.0) and not ok("ANY", "DOWN", -20.0, 8.0)
    assert M.pullback_context(None) == "DOWN24"
    assert M.pullback_context(_DB(multiday_context="up24")) == "UP24"
    assert M.pullback_context(_DB(multiday_context="x")) == "DOWN24"          # 오타 = 옛 동작 (새 동작으로 새지 않는다)
    assert M.pullback_shadow_context(None, "DOWN24") == "UP24"
    assert M.pullback_shadow_context(_DB(multiday_context_shadow="off"), "DOWN24") is None
    assert M.pullback_shadow_context(None, "UP24") is None and M.pullback_shadow_context(None, "ANY") is None


def test_배선():
    s = (ROOT / "workers" / "long_bottom_detector_worker.py").read_text(encoding="utf-8")
    assert "_mp_n = _multiday_pullback_scan(bc, db, _ranked)" in s
    a = (ROOT / "workers" / "auto_long_at_bottom_worker.py").read_text(encoding="utf-8")
    assert '"MULTIDAY_PULLBACK"' in a and 'in MOMENTUM_ALERT_PATTERNS else None' in a, "알람 패턴 전달 + Fix 349 게이트 통과"
    assert '"multiday_context": alert.get("context")' in a, "대기열 3C: 자리별 사후 검증을 위해 제안 기록에 남긴다"
    g = (ROOT / "services" / "long_surge_gate.py").read_text(encoding="utf-8")
    assert '"MULTIDAY_PULLBACK"' in g, "당일 −% 인데 Fix 274(24h<15% 롱 차단)에 걸리면 안 된다"

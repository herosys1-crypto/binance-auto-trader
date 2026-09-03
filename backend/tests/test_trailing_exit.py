"""🚨 Fix 335 — 트레일링이 「정점 >= TP1값」 조건 때문에 사실상 죽어 있었다.

사장님 verbatim (2026-08-23): **"tp1 실행후 -5% 회기하면 청산"** — 값 무관.

## 실측

- 메모리: **607건 중 ROI +15% 도달이 3건(0.5%)** → 「정점 >= 15%」 조건은 0.5% 에서만 켜진다
- #2090 MAGMAUSDT: TP1 이 실제로 25% 청산됐는데 정점 ROI 0.98% 라 트레일링 영영 무장 안 됨
- 위기모드(`CRISIS_TP1`/`CRISIS_TRAIL_FULL`)는 **판정만 있고 실행부가 0곳** —
  `crisis_first_tp_done_at` 전 기간 0건. 죽은 코드다 (이 파일은 그것을 고치지 않는다).

## 이 테스트가 지키는 것

1. 정점이 TP1 값 미만이어도 트레일링이 **켜진다** (사장님 사양)
2. `trailing_require_peak_ge_tp1 = 1` 이면 옛 동작(정점 >= TP1값)으로 돌아간다
3. 되돌림 폭은 건드리지 않는다 (메모리: 「3%p 는 현행이 최고」)
"""
from decimal import Decimal

import pytest

from app.services import risk_service as R


D = Decimal


# ─────────────────────────────────────────────────────────────────────
# 스텁 — evaluate_take_profit_level 이 트레일링 블록까지 가는 데 필요한 것만
# ─────────────────────────────────────────────────────────────────────

class _Strategy:
    def __init__(self, *, status="TP1_DONE_PARTIAL", tp1=15, peak_db=None, retrace=None):
        self.id = 1
        self.symbol = "XUSDT"
        self.side = "LONG"
        self.avg_entry_price = D("100")
        self.leverage = 2
        self.status = status
        self.tp1_pct_override = D(str(tp1)) if tp1 is not None else None
        self.trailing_retrace_pct = D(str(retrace)) if retrace is not None else None
        self.max_profit_pct = D(str(peak_db)) if peak_db is not None else None
        self.max_loss_pct = None
        self.crisis_mode_triggered_at = None
        self.crisis_first_tp_done_at = None
        self.strategy_template_id = 1
        self.current_stage = 1


class _Tpl:
    """tpN_percent 전부 None → 일반 TP 사다리가 비어 트레일링만 남는다."""
    def __getattr__(self, name):
        if name.startswith("tp") and name.endswith("_percent"):
            return None
        raise AttributeError(name)


class _DB:
    def __init__(self, settings=None):
        self._s = settings or {}

    def get(self, model, key):
        n = getattr(model, "__name__", "")
        if n == "SystemSetting":
            if key not in self._s:
                return None
            return type("R", (), {"value": self._s[key]})()
        if n == "StrategyTemplate":
            return _Tpl()
        return None

    def commit(self):
        pass


def _svc(strategy, *, mark, peak, settings=None, monkeypatch=None):
    svc = R.RiskService.__new__(R.RiskService)
    svc.db = _DB(settings)
    svc.strategy_repo = type("SR", (), {"get_strategy": staticmethod(lambda _i: strategy)})()
    svc.position_repo = type("PR", (), {"latest_by_strategy": staticmethod(lambda _i: None)})()
    # 부수효과 메서드는 전부 무력화
    svc._update_pnl_extremes = lambda s, p: None
    svc._maybe_send_loss_threshold_alert = lambda s, a, b: None
    svc._maybe_send_sl_progress_alert = lambda s: None
    svc._should_trigger_crisis_mode = lambda s, p: False
    svc._update_peak_pnl = lambda sid, pnl, dbpeak: D(str(peak))
    # 시세는 Redis 캐시 함수에서 온다 — 모듈 함수를 갈아끼운다
    import app.services.mark_price_cache as mpc
    monkeypatch.setattr(mpc, "get_mark_price", lambda sym: D(str(mark)))
    return svc


# ═════════════════════════════════════════════════════════════════════
# 🚨 핵심 — 사장님 사양: 값 무관
# ═════════════════════════════════════════════════════════════════════

def test_정점이_TP1값_미만이어도_트레일링이_켜진다(monkeypatch):
    """정점 ROI 10% (< TP1 15%), 현재 ROI 4% (= 정점 -6%p, 되돌림 5 초과) → 청산."""
    st = _Strategy(status="TP1_DONE_PARTIAL", tp1=15)
    # LONG avg 100 → mark 102 = raw +2% x 레버2 = ROI +4%
    svc = _svc(st, mark="102", peak=10, monkeypatch=monkeypatch)
    assert svc.evaluate_take_profit_level(1) == "TRAILING_TP"


def test_설정을_켜면_옛_동작_정점_15_이상만(monkeypatch):
    """되돌릴 수 있어야 한다."""
    st = _Strategy(status="TP1_DONE_PARTIAL", tp1=15)
    svc = _svc(st, mark="102", peak=10,
               settings={"trailing_require_peak_ge_tp1": "1"}, monkeypatch=monkeypatch)
    assert svc.evaluate_take_profit_level(1) is None       # 정점 10 < 15 → 옛 조건은 미발동


def test_설정을_켜도_정점이_TP1값_이상이면_발동(monkeypatch):
    st = _Strategy(status="TP1_DONE_PARTIAL", tp1=15)
    svc = _svc(st, mark="102", peak=20,
               settings={"trailing_require_peak_ge_tp1": "1"}, monkeypatch=monkeypatch)
    assert svc.evaluate_take_profit_level(1) == "TRAILING_TP"


def test_되돌림_폭_안이면_안_켜진다(monkeypatch):
    """정점 10, 현재 6 = -4%p (< 5) → 아직 보유."""
    st = _Strategy(status="TP1_DONE_PARTIAL", tp1=15)
    svc = _svc(st, mark="103", peak=10, monkeypatch=monkeypatch)     # ROI +6%
    assert svc.evaluate_take_profit_level(1) is None


def test_TP1이_안_실행됐으면_안_켜진다(monkeypatch):
    """사장님: 「tp1 실행후」 — 첫 익절 전에는 트레일링 없음."""
    st = _Strategy(status="STAGE1_OPEN", tp1=15)
    svc = _svc(st, mark="102", peak=10, monkeypatch=monkeypatch)
    assert svc.evaluate_take_profit_level(1) is None


def test_TP를_끄면_트레일링도_안_켜진다(monkeypatch):
    """v127 HIGH fix 유지: TP1_override=0 = 수동 관리 = 트레일링도 차단."""
    st = _Strategy(status="TP1_DONE_PARTIAL", tp1=0)
    svc = _svc(st, mark="102", peak=10, monkeypatch=monkeypatch)
    assert svc.evaluate_take_profit_level(1) is None


def test_전략별_되돌림_폭이_우선(monkeypatch):
    """trailing_retrace_pct=3 이면 정점 -3%p 에서 켜진다 (폭 자체는 건드리지 않는다)."""
    st = _Strategy(status="TP1_DONE_PARTIAL", tp1=15, retrace=3)
    svc = _svc(st, mark="103", peak=10, monkeypatch=monkeypatch)     # ROI 6 = 정점 -4 → 3 초과
    assert svc.evaluate_take_profit_level(1) == "TRAILING_TP"


# ═════════════════════════════════════════════════════════════════════
# 🚨 코드 형태 — 무심코 되돌리지 못하게
# ═════════════════════════════════════════════════════════════════════

def test_옛_무조건_조건이_사라졌다():
    from pathlib import Path
    src = Path(R.__file__).read_text(encoding="utf-8")
    assert "and peak >= Decimal(str(_tp1_override_val))  # peak >= 사장님 옵션 값!" not in src, \
        "「정점 >= TP1값」 무조건 조건이 되살아났다"
    assert "_peak_ok" in src and "trailing_require_peak_ge_tp1" in src


def test_실측_근거가_주석에_남아_있다():
    from pathlib import Path
    src = Path(R.__file__).read_text(encoding="utf-8")
    for token in ("607건", "0.5%", "값 무관", "3%p 는 현행이 최고"):
        assert token in src, token

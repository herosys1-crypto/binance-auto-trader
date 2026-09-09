"""🎯 Fix 363 — 「새전략 OBV 자동」을 사장님 로직대로 (2026-09-09).

사장님 verbatim: "수동으로 10USDT 포지션 진입하고 손익이고 지속적인 손익이라 차트와 보조지표가 확실 할 때 300USDT 최대 2번 …
반대로 수동으로 10USDT 진입후 손실발생시 지속모니터링중 다시 이익이 가능한 포지션에서 300USDT 포지션 추가하고 …
다시 손실이 발생하면 10USDT만 남기고 부분손절하고 다시 모니터링후 이익이 가능한 구간에서 다시 600USDT …
수익과 손실이 발생하면 전략인스턴스 선택한 옵션으로 운영"
"""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1] / "app"


class _DB:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, _m, key):
        return type("R", (), {"value": self.kv[key]})() if key in self.kv else None


# ── ① OBV 단계: 손실 조건 + 시장가 ─────────────────────────────────────────────────────

def test_obv_stage_needs_loss_and_fires_market():
    src = (ROOT / "workers" / "stage_trigger_worker.py").read_text(encoding="utf-8")
    i_obv = src.find('elif _tpl_trigger_mode == "OBV_REVERSE":')
    i_roi = src.find("_roi363 = _obv_unrealized_roi_pct(strategy, mark)", i_obv)
    i_sig = src.find("check_stage_entry_signal(\n", i_roi)
    assert 0 < i_obv < i_roi < i_sig, "OBV 분기: 손실 조건 판정이 신호 판정보다 먼저"
    assert "elif _roi363 > _thr363:" in src[i_roi:i_sig], "손실 조건 미충족이면 신호를 보지 않고 대기"
    assert "force_market=(_ps_force_market or _is_obv_mode)" in src, "OBV 모드는 신호 시점 시장가"


def test_obv_roi_and_threshold_helpers():
    from app.workers import stage_trigger_worker as W
    s_long = NS(avg_entry_price=Decimal("100"), leverage=2, side="LONG")
    s_short = NS(avg_entry_price=Decimal("100"), leverage=2, side="SHORT")
    assert abs(W._obv_unrealized_roi_pct(s_long, Decimal("97.5")) - (-5.0)) < 1e-9     # 가격 −2.5% × 2 = ROI −5
    assert abs(W._obv_unrealized_roi_pct(s_short, Decimal("97.5")) - 5.0) < 1e-9
    assert W._obv_unrealized_roi_pct(NS(avg_entry_price=None, leverage=2, side="LONG"), 100) is None
    assert W._obv_unrealized_roi_pct(s_long, None) is None
    assert W._obv_stage_loss_threshold(_DB(), 2) == -1.0                                # Fix 364c: 행 없음 = −1 (스프레드 제외, Claude가 정함)
    assert W._obv_stage_loss_threshold(_DB(obv_stage2_loss_roi_pct="-3"), 2) == -3.0
    assert W._obv_stage_loss_threshold(_DB(obv_stage3_loss_roi_pct="7"), 3) == -7.0      # 양수도 손실로 해석
    assert W._obv_stage_loss_threshold(_DB(obv_stage2_loss_roi_pct="garbage"), 2) == -1.0
    assert W._obv_stage_loss_threshold(_DB(), 9) == -1.0                                # 키 없는 단계 = 기본


def test_stage_worker_sees_post_tp_states():
    from app.core.strategy_status import STAGES_WITH_NEXT, TP_PARTIAL_WITH_NEXT
    from app.workers import stage_trigger_worker as W
    assert "TP1_DONE_PARTIAL" in TP_PARTIAL_WITH_NEXT and "TRAILING_ARMED" in TP_PARTIAL_WITH_NEXT
    assert TP_PARTIAL_WITH_NEXT.isdisjoint(STAGES_WITH_NEXT)
    assert W.ACTIVE_STAGE_STATUSES == STAGES_WITH_NEXT | TP_PARTIAL_WITH_NEXT
    # 다른 소비처의 「활성 단계」 의미는 그대로
    assert "TP1_DONE_PARTIAL" not in STAGES_WITH_NEXT


# ── ② 이익 중이면 정리 안 함 ──────────────────────────────────────────────────────────

def test_trim_before_stage_skips_when_in_profit():
    from app.services.execution_service import ExecutionService
    s_short = NS(avg_entry_price=Decimal("100"), leverage=2, side="SHORT")
    assert abs(ExecutionService._unrealized_roi_pct(s_short, Decimal("95")) - 10.0) < 1e-9
    src = (ROOT / "services" / "execution_service.py").read_text(encoding="utf-8")
    i_def = src.find("def _trim_before_stage(")
    i_guard = src.find("_roi363 = self._unrealized_roi_pct(strategy, _mark)", i_def)
    i_trim = src.find("_close_qty, _keep_qty, _why, _act = compute_trim(", i_def)
    assert 0 < i_def < i_guard < i_trim, "정리(compute_trim) 전에 이익 여부를 본다"
    assert "if _roi363 is not None and _roi363 > 0:" in src[i_guard:i_trim]


# ── ③ ⑥ 피라미딩: 손실 고정 기본 OFF · 방향 양방향 ─────────────────────────────────────

def test_cap_loss_default_off_and_sides_both():
    from app.workers import success_pyramiding_worker as W
    assert W._cap_loss_enabled(_DB()) is False
    assert W._cap_loss_enabled(_DB(pyramid_cap_loss_enabled="1")) is True
    assert W._allowed_sides(_DB()) == {"LONG", "SHORT"}
    assert W._allowed_sides(_DB(pyramid_sides="SHORT")) == {"SHORT"}


# ── ⑤ 잔량 대기 상한 ─────────────────────────────────────────────────────────────────

def test_residue_wait_cap_wired():
    from app.services.tp_sl_orchestrator import TPSLOrchestratorService as O
    o = O.__new__(O)
    o.db = _DB()
    assert o._residue_max_wait_hours() == 24.0
    o.db = _DB(stage_residue_max_wait_hours="6")
    assert o._residue_max_wait_hours() == 6.0
    o.db = _DB(stage_residue_max_wait_hours="9999")
    assert o._residue_max_wait_hours() == 24.0
    src = (ROOT / "services" / "tp_sl_orchestrator.py").read_text(encoding="utf-8")
    i_nx = src.find("_nx, _nxwhy = self._has_next_stage(strategy)")
    i_cap = src.find("_waited363 = self._residue_waited_hours(strategy)", i_nx)
    i_keep = src.find('"[Fix326] %s #%s 잔량 유지 — 손절하지 않음', i_cap)
    assert 0 < i_nx < i_cap < i_keep, "잔량 유지 판정 전에 대기 상한을 본다"


# ── ⑦ 화면 ────────────────────────────────────────────────────────────────────────────

def test_ui_strategy_roi_uses_invested_capital():
    js = (ROOT / "static" / "js" / "strategies-list.js").read_text(encoding="utf-8")
    assert "invested_capital_computed" in js and "const _roiBase = _investedCap > 0 ? _investedCap : sCap;" in js


# ── Fix 363b (반박 검증 반영) ─────────────────────────────────────────────────────────

class _Redis:
    def __init__(self, fail=False):
        self.kv = {}
        self.fail = fail

    def get(self, k):
        if self.fail:
            raise RuntimeError("redis down")
        return self.kv.get(k)

    def set(self, k, v, ex=None):
        if self.fail:
            raise RuntimeError("redis down")
        self.kv[k] = v


def test_fix363b_cascade_guards():
    from app.workers import stage_trigger_worker as W
    r = _Redis()
    assert W._obv_stage_cooldown_active(r, 7) is False
    W._obv_set_stage_cooldown(r, 7)
    assert W._obv_stage_cooldown_active(r, 7) is True and r.kv["stage_fire_cooldown:7"] == "1"
    assert W._obv_stage_cooldown_active(None, 7) is True, "Redis 없음 = 보류(fail-closed)"
    assert W._obv_stage_cooldown_active(_Redis(fail=True), 7) is True
    # 직전 단계 미체결이면 보류
    class _Plan:
        def __init__(self, t): self.is_triggered = t
    class _DBp:
        def __init__(self, plan): self.plan = plan
        def execute(self, *_a, **_k):
            plan = self.plan
            return type("R", (), {"scalar_one_or_none": lambda self_: plan})()
    strat = NS(id=1)
    assert W._obv_prev_stage_filled(_DBp(_Plan(False)), strat, 2) == (False, "직전 단계 1 체결 대기")
    assert W._obv_prev_stage_filled(_DBp(_Plan(True)), strat, 2)[0] is True
    assert W._obv_prev_stage_filled(_DBp(None), strat, 2)[0] is True
    assert W._obv_prev_stage_filled(_DBp(_Plan(False)), strat, 1)[0] is True
    src = (ROOT / "workers" / "stage_trigger_worker.py").read_text(encoding="utf-8")
    i_obv = src.find('elif _tpl_trigger_mode == "OBV_REVERSE":')
    i_cool = src.find("if _obv_stage_cooldown_active(_redis, strategy.id):", i_obv)
    i_roi = src.find("elif _roi363 > _thr363:", i_cool)
    assert 0 < i_obv < i_cool < i_roi, "쿨다운·직전 체결 확인이 ROI 판정보다 먼저"
    i_set = src.find("_obv_set_stage_cooldown(_redis, strategy.id, ")          # Fix 364: 초 인자 추가
    i_fire = src.find("exec_service.trigger_next_stage(", i_set)
    assert 0 < i_set < i_fire, "쿨다운은 발주 **전에** 설정"
    assert "if strategy.status in TP_PARTIAL_WITH_NEXT and not _is_obv_mode:" in src, "익절 뒤 상태는 OBV 만"
    i_gate = src.find("if not _is_obv_mode and not _is_retry_mode and int(next_stage_no) >= 2:")
    assert 0 < i_gate < i_fire, "가격/사다리 단계의 이익 중 대기 게이트가 발주 전에"


def test_fix363b_trim_auto_raises_manual_passes():
    from app.services.execution_service import ExecutionService
    src = (ROOT / "services" / "execution_service.py").read_text(encoding="utf-8")
    assert "def _trim_before_stage(self, strategy, stage_no: int, *, auto: bool = True)" in src
    assert 'raise ValueError(\n                            f"[Fix363] {strategy.symbol} 단계 {stage_no}: 이익 중' in src
    i_manual = src.find("def enter_stage_at_market(")
    assert "self._trim_before_stage(strategy, stage_no, auto=False)" in src[i_manual:i_manual + 6000]
    i_auto = src.find("def trigger_next_stage(")
    assert "self._trim_before_stage(strategy, stage_no)   # ✂️ Fix 304" in src[i_auto:i_auto + 6000]


def test_fix363b_residue_clock_anchored_to_last_fill():
    src = (ROOT / "services" / "tp_sl_orchestrator.py").read_text(encoding="utf-8")
    i_def = src.find("def _residue_waited_hours(")
    blk = src[i_def:i_def + 2500]
    assert "func.max(StrategyStagePlan.triggered_at)" in blk and "RiskEvent.created_at > since" in blk

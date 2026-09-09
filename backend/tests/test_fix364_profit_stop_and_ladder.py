"""🎯 Fix 364 — 사장님 2026-09-09 정정: 이익 구간 추가 뒤 손절 −5% · 손실 구간 대기 없음 · 단계별 손절 25/15/25/25 (10/300/600/600).

verbatim: "이익구간에서 손절 발생시 -25%는 -5% 변경하고 / 손실구간에서도 +15분은 의미가 없어 차트와 보조지표가 포지션 진입이면 언제든지
들어가야해 / 두번째 2단계 진입후 손실이면 -15%에서 부분손절 … 3단계를 진입하고 … 손실이면 -25%까지 … 부분 청산하고 … 다시 3단계를
한번더 진입하고 손실이면 -25%에서 청산해줘 / 진입해서 바로 수익은 포지션추가후 손실이면 -5%에서 청산하고 다시 모니터링 대기"
"""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1] / "app"


class _DB:
    def __init__(self, **kv):
        self.kv = kv
        self.committed = 0

    def get(self, _m, key):
        return type("R", (), {"value": self.kv[key]})() if key in self.kv else None

    def commit(self):
        self.committed += 1

    def rollback(self):
        pass


def test_stage_sl_schedule_parse_and_apply():
    from app.workers import stage_trigger_worker as W
    assert [W._obv_stage_sl_roi(_DB(), n) for n in (1, 2, 3, 4, 5)] == [25.0, 15.0, 25.0, 25.0, 25.0]
    assert [W._obv_stage_sl_roi(_DB(obv_stage_sl_roi_pcts="25,10,20"), n) for n in (2, 3, 4)] == [10.0, 20.0, 20.0]
    assert W._obv_stage_sl_roi(_DB(obv_stage_sl_roi_pcts="garbage"), 2) == 15.0            # 파싱 실패 = 기본
    assert W._obv_stage_sl_roi(_DB(obv_stage_sl_roi_pcts="25,0.1"), 2) == 15.0             # 범위 밖 = 기본
    st = NS(id=1, force_sl_enabled_override=False, force_sl_roi_override=None)
    db = _DB()
    assert W._apply_obv_stage_sl(db, st, 2) == 15.0
    assert st.force_sl_enabled_override is True and st.force_sl_roi_override == Decimal("15.0") and db.committed == 1
    W._apply_obv_stage_sl(db, st, 4)
    assert st.force_sl_roi_override == Decimal("25.0")


def test_loss_condition_default_is_any_loss_and_cooldown_is_propagation_only():
    from app.workers import stage_trigger_worker as W
    assert W.OBV_STAGE_LOSS_ROI_DEFAULT == -1.0                                             # Fix 364c: 스프레드·수수료 잡음 제외 (Claude가 정함)
    assert W._obv_stage_loss_threshold(_DB(), 2) == -1.0
    assert W._obv_stage_loss_threshold(_DB(obv_stage2_loss_roi_pct="0"), 2) == 0.0          # 사장님 원문 「손실이면 곧」
    assert W._obv_stage_loss_threshold(_DB(obv_stage2_loss_roi_pct="-5"), 2) == -5.0        # 조이고 싶으면 설정
    assert W.OBV_STAGE_COOLDOWN_SEC == 60
    assert W._obv_stage_cooldown_seconds(_DB()) == 60
    assert W._obv_stage_cooldown_seconds(_DB(obv_stage_cooldown_sec="120")) == 120
    assert W._obv_stage_cooldown_seconds(_DB(obv_stage_cooldown_sec="5")) == 60            # 범위 밖 = 기본
    src = (ROOT / "workers" / "stage_trigger_worker.py").read_text(encoding="utf-8")
    assert "_obv_set_stage_cooldown(_redis, strategy.id, _obv_stage_cooldown_seconds(db))" in src
    i_fired = src.find('_stat["fired"] += 1')
    assert "_apply_obv_stage_sl(db, strategy, next_stage_no)" in src[i_fired:i_fired + 400], "발주 직후 단계별 손절 적용"


def test_fix364b_stage3_needs_prev_stage_trimmed(monkeypatch):
    """다음 단계는 지금 포지션이 잔량일 때만 — 같은 신호로 300→600 연쇄 방지(364b) + 추가(610)가 −5% 정리 전에 2단계로 갈아타는 것 방지(364c C1/C7).
    경계는 부분손절이 쓰는 compute_trim 과 같다(C2/C4)."""
    from app.workers import stage_trigger_worker as W
    from app.services import stage_trim as ST
    assert W._obv_residue_margin_max(_DB()) == 20.0                                       # 잔량 10 × 2
    assert W._obv_residue_margin_max(_DB(stage_keep_notional_usdt="15")) == 30.0
    assert W._obv_residue_margin_max(_DB(obv_stage_residue_margin_max_usdt="50")) == 50.0
    monkeypatch.setattr(W, "_obv_pyramid_count", lambda sid: 0)
    monkeypatch.setattr(W, "_obv_stage1_planned_capital", lambda db, s: 10.0)
    # compute_trim 흉내: 증거금 ≥ 30 이면 TRIM, 아니면 SKIP (실제 기본 경계 = 잔량 10 × (비율 2 + 1))
    def _fake_trim(db, symbol, qty, mark, leverage=1):
        m = float(qty) * float(mark) / float(leverage)
        return (Decimal("1"), Decimal("1"), "fake", ST.ACTION_TRIM) if m >= 30 else (Decimal("0"), Decimal(str(qty)), "fake", ST.ACTION_SKIP)
    monkeypatch.setattr(ST, "compute_trim", _fake_trim)
    st_big = NS(id=1, symbol="XUSDT", current_position_qty=Decimal("620"), leverage=2)   # 620 × 1.0 / 2 = 310 USDT 증거금
    # 2단계: 추가 0회 + 1단계 계획 10 → 310 은 1단계 덩어리가 아니다 → compute_trim TRIM → 보류
    ok, why = W._obv_prev_stage_stopped(_DB(), st_big, 2, 1.0)
    assert ok is False and "정리 대기" in why
    # 2단계: 추가(피라미딩) 1회 → 무조건 정리 대기 (−5% 부분손절 뒤 모니터링)
    monkeypatch.setattr(W, "_obv_pyramid_count", lambda sid: 1)
    ok, why = W._obv_prev_stage_stopped(_DB(), st_big, 2, 1.0)
    assert ok is False and "추가(피라미딩)분 정리 대기" in why
    # 2단계: 추가 0회 + 1단계 계획 50(=10 이 아닌 수동 1단계) → 증거금 50 ≤ 60 → 통과
    monkeypatch.setattr(W, "_obv_pyramid_count", lambda sid: 0)
    monkeypatch.setattr(W, "_obv_stage1_planned_capital", lambda db, s: 50.0)
    st_50 = NS(id=1, symbol="XUSDT", current_position_qty=Decimal("100"), leverage=2)
    assert W._obv_prev_stage_stopped(_DB(), st_50, 2, 1.0) == (True, "")
    # 3단계: 2단계 덩어리(310)가 남아 있으면 보류
    ok, why = W._obv_prev_stage_stopped(_DB(), st_big, 3, 1.0)
    assert ok is False and "직전 단계 정리 대기" in why
    # 부분손절 뒤 잔량(10 USDT)이면 통과 — 4단계도 같은 규칙
    st_res = NS(id=1, symbol="XUSDT", current_position_qty=Decimal("20"), leverage=2)    # 20 × 1.0 / 2 = 10
    assert W._obv_prev_stage_stopped(_DB(), st_res, 3, 1.0) == (True, "")
    assert W._obv_prev_stage_stopped(_DB(), st_res, 4, 1.0) == (True, "")
    # C2: 상한 20 과 정리 경계 30 사이(25) = compute_trim 이 SKIP → 통과 (옛 코드는 정리도 진입도 못 했다)
    st_25 = NS(id=1, symbol="XUSDT", current_position_qty=Decimal("50"), leverage=2)
    assert W._obv_prev_stage_stopped(_DB(), st_25, 3, 1.0) == (True, "")
    # 결손은 보류(fail-closed)
    assert W._obv_prev_stage_stopped(_DB(), st_res, 3, None)[0] is False
    monkeypatch.setattr(ST, "compute_trim", lambda *a, **k: (Decimal("0"), Decimal("0"), "필터 없음", ST.ACTION_BLOCK))
    assert W._obv_prev_stage_stopped(_DB(), st_big, 3, 1.0)[0] is False


def test_fix364c_prev_fill_age_and_residue_clock_and_trim_event():
    from datetime import datetime, timedelta, timezone
    from app.workers import stage_trigger_worker as W
    # C5: 직전 단계 체결 직후(60초 안)는 대기, 지나면 통과
    class _P:
        def __init__(self, ta): self.is_triggered, self.triggered_at = True, ta
    class _DBp(_DB):
        def __init__(self, plan): super().__init__(); self.plan = plan
        def execute(self, *_a, **_k):
            plan = self.plan
            return type("R", (), {"scalar_one_or_none": lambda self_: plan})()
    st = NS(id=1)
    ok, why = W._obv_prev_stage_filled(_DBp(_P(datetime.now(timezone.utc) - timedelta(seconds=5))), st, 2)
    assert ok is False and "체결 직후 대기" in why
    assert W._obv_prev_stage_filled(_DBp(_P(datetime.now(timezone.utc) - timedelta(seconds=120))), st, 2) == (True, "")
    assert W._obv_prev_stage_filled(_DBp(_P(None)), st, 2) == (True, "")
    # C3: 잔량 시계 기준 = max(마지막 체결, 마지막 추가, 마지막 부분손절)
    from app.services.tp_sl_orchestrator import TPSLOrchestratorService as O
    t_fill = datetime(2026, 9, 9, 0, 0, tzinfo=timezone.utc)
    t_add = t_fill + timedelta(hours=26)
    class _DBo:
        def __init__(self, seq): self.seq = list(seq)
        def execute(self, *_a, **_k):
            v = self.seq.pop(0)
            return type("R", (), {"scalar": lambda self_: v})()
    o = O.__new__(O)
    o.db = _DBo([t_fill, t_add])
    assert o._residue_clock_anchor(NS(id=1)) == t_add
    o.db = _DBo([t_fill.replace(tzinfo=None), None])
    assert o._residue_clock_anchor(NS(id=1)) == t_fill
    o.db = _DBo([None, None])
    assert o._residue_clock_anchor(NS(id=1)) is None
    src = (ROOT / "services" / "tp_sl_orchestrator.py").read_text(encoding="utf-8")
    assert src.count("self._record_partial_trim(strategy, _c, _k, _why)") == 2, "부분손절 실행 2곳 모두 이벤트"
    assert 'event_type="FORCE_SL_PARTIAL_TRIM"' in src
    i_def = src.find("def _residue_waited_hours(")
    assert "since = self._residue_clock_anchor(strategy)" in src[i_def:i_def + 1200]
    # C1-2: 진입 전 정리도 카운터 리셋
    es = (ROOT / "services" / "execution_service.py").read_text(encoding="utf-8")
    i_trim = es.find("def _trim_before_stage(")
    i_close = es.find("for_stage_transition=True,", i_trim)
    assert "reset_pyramid_count(strategy.id)" in es[i_close:i_close + 700]
    src = (ROOT / "workers" / "stage_trigger_worker.py").read_text(encoding="utf-8")
    i_prev = src.find("elif not _prev_ok363:")
    i_stop = src.find("elif not _stopped_ok364:", i_prev)
    i_roi = src.find("elif _roi363 is None:", i_stop)
    assert 0 < i_prev < i_stop < i_roi, "체결 확인 → 잔량 게이트 → ROI 순서"


def test_after_add_stop_is_5pct_and_wired_after_add():
    from app.workers import success_pyramiding_worker as W
    assert W._after_add_sl_roi(_DB()) == 5.0
    assert W._after_add_sl_roi(_DB(pyramid_after_add_sl_roi="0")) == 0.0
    assert W._after_add_sl_roi(_DB(pyramid_after_add_sl_roi="999")) == 5.0
    _obv_tpl = NS(trigger_mode="OBV_REVERSE")
    si = NS(id=9, symbol="XUSDT", force_sl_enabled_override=None, force_sl_roi_override=Decimal("25"), strategy_template=_obv_tpl)
    db = _DB()
    assert W._apply_after_add_sl(db, si) == 5.0 and si.force_sl_roi_override == Decimal("5.0") and si.force_sl_enabled_override is True
    assert db.committed == 1
    assert W._apply_after_add_sl(_DB(pyramid_after_add_sl_roi="0"), si) is None
    # C8: 템플릿을 넘기면 lazy-load 없이, commit=False 면 호출자 커밋에 얹는다
    db2 = _DB()
    si2 = NS(id=12, symbol="WUSDT", force_sl_enabled_override=None, force_sl_roi_override=Decimal("25"), strategy_template=None)
    assert W._apply_after_add_sl(db2, si2, tpl=_obv_tpl, commit=False) == 5.0 and db2.committed == 0 and si2.force_sl_roi_override == Decimal("5.0")
    # C6: 래칫(Fix 269) ON 이면 더 낮은 값 유지
    si3 = NS(id=13, symbol="VUSDT", force_sl_enabled_override=True, force_sl_roi_override=Decimal("0.8065"), strategy_template=_obv_tpl)
    assert W._apply_after_add_sl(_DB(pyramid_cap_loss_enabled="1"), si3) == 0.8065 and si3.force_sl_roi_override == Decimal("0.8065")
    si4 = NS(id=14, symbol="UUSDT", force_sl_enabled_override=True, force_sl_roi_override=Decimal("0.8065"), strategy_template=_obv_tpl)
    assert W._apply_after_add_sl(_DB(), si4) == 5.0
    # Fix 364b: 가족별 — 기본 scope=obv 면 가격 트리거 인스턴스는 그대로, scope=all 이면 적용
    other = NS(id=10, symbol="YUSDT", force_sl_enabled_override=None, force_sl_roi_override=Decimal("25"), strategy_template=NS(trigger_mode="PRICE_DOWN_PCT"))
    assert W._apply_after_add_sl(_DB(), other) is None and other.force_sl_roi_override == Decimal("25")
    assert W._apply_after_add_sl(_DB(pyramid_after_add_sl_scope="all"), other) == 5.0
    assert W._apply_after_add_sl(_DB(), NS(id=11, symbol="Z", force_sl_enabled_override=None, force_sl_roi_override=None, strategy_template=None)) is None
    src = (ROOT / "workers" / "success_pyramiding_worker.py").read_text(encoding="utf-8")
    i_add = src.find("db.add(sugg)")
    i_commit = src.find("db.commit()", i_add)
    i_apply = src.find("_apply_after_add_sl(db, si, tpl=_parent_tpl, commit=False)", i_add)
    assert 0 < i_add < i_apply < i_commit, "C8: 추가 뒤 손절은 추가 기록과 **같은 커밋**에 (커밋 뒤 lazy-load 없음)"

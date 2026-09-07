"""🎯 Fix 358 — 익절 후 추가(피라미딩) 명시 스위치 + 트레일링 청산 임박 시 보류 + 실패한 추가 쿨다운.

사장님 2026-09-07: "수익중일때 차트와 보조지표가 강력한 상승이 하락으로 포지션이 맞을 때 최대2번 익절전 또는
익절후에도 가능하게 하는거야 익절후는 지금 처음 지시는거고"
실측(7일): 익절 후 추가 2건 모두 18초 뒤 트레일링 전량청산 / #3964 실패 추가 30초마다 74회 재시도.
"""
from pathlib import Path

from app.workers import success_pyramiding_worker as W

ROOT = Path(__file__).resolve().parents[1] / "app"


class _DB:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, _model, key):
        if key in self.kv and self.kv[key] is not None:
            return type("R", (), {"value": self.kv[key]})()
        return None


class _SI:
    def __init__(self, status="TP1_DONE_PARTIAL", max_profit_pct=None, trailing_retrace_pct=None):
        self.status = status
        self.max_profit_pct = max_profit_pct
        self.trailing_retrace_pct = trailing_retrace_pct


def test_익절_후_판정과_기본_스위치_ON():
    assert W._is_after_tp("TP1_DONE_PARTIAL") and W._is_after_tp("TP20_DONE_PARTIAL") and W._is_after_tp("TRAILING_ARMED")
    assert not W._is_after_tp("STAGE1_OPEN") and not W._is_after_tp("STAGE3_OPEN")
    assert W._after_tp_enabled(_DB()) is True
    assert W._after_tp_enabled(_DB(pyramid_after_tp_enabled="0")) is False
    assert W._after_tp_min_room(_DB()) == 2.0 and W._after_tp_min_room(_DB(pyramid_after_tp_min_trail_room_pct="3.5")) == 3.5
    assert W._after_tp_min_room(_DB(pyramid_after_tp_min_trail_room_pct="999")) == 2.0       # 범위 밖 = 기본


def test_트레일링_여유_계산():
    # 되돌림 허용 5%p(기본), 최고 ROI 20, 지금 18.5 → 여유 = 5 − 1.5 = 3.5
    assert abs(W._trailing_room_pct(_SI(max_profit_pct=20), 18.5) - 3.5) < 1e-9
    # 전략별 3%p, 최고 17.1, 지금 16.1 → 2.0 (경계: 최소 여유 2.0 이면 통과)
    assert abs(W._trailing_room_pct(_SI(max_profit_pct=17.1, trailing_retrace_pct=3), 16.1) - 2.0) < 1e-9
    # 지금이 최고보다 높으면 여유 = 허용폭 전부
    assert abs(W._trailing_room_pct(_SI(max_profit_pct=10, trailing_retrace_pct=3), 12.0) - 3.0) < 1e-9
    assert W._trailing_room_pct(_SI(max_profit_pct=None), 5.0) is None                     # 모르면 막지 않음


def test_배선_순서와_쿨다운():
    s = (ROOT / "workers" / "success_pyramiding_worker.py").read_text(encoding="utf-8")
    i_sus = s.find('_bump("peak_not_sustained")')
    i_tp = s.find('_bump("after_tp_disabled")')
    i_imm = s.find('_bump("trailing_imminent")')
    i_ind = s.find('_bump("indicator_not_rising")')
    assert 0 < i_sus < i_tp < i_imm < i_ind, "정점 지속 → 익절 후 스위치 → 트레일링 여유 → 지표 게이트 순서"
    i_fail = s.find('_bump("add_position_failed")')
    assert "_set_cooldown(si.symbol, si.side)" in s[i_fail:i_fail + 300], "실패한 추가에 쿨다운"
    i_exc = s.find('_bump("exception")')
    assert "_set_cooldown(si.symbol, si.side)" in s[i_exc:i_exc + 400], "예외 경로에도 쿨다운"
    assert '"after_tp": bool(_after_tp)' in s and '"status_at_add": str(si.status)' in s

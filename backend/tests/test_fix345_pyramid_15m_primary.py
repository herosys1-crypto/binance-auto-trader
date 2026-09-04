"""🎯 Fix 345 — 피라미딩 지표 게이트 = 「15분이 기준, 4시간은 참고」.

사장님 2026-09-04: "이건 왜 포지션 추가 진입이 없는거죠 문제가 있는것 같아" (#2690 LPTUSDT SHORT +11.77%)
실측: [Fix273] ⛔ LPTUSDT SHORT 추가 차단 — 4h MACD hist 가 내 편으로 상승 중이 아님
      {'4h': {'delta': -0.00218, 'hist_signed': -0.0146}}   ← 진행중 4H 봉, 15m 은 평가조차 안 됨
사장님 사상: "15분이 기준이고 4시간을 참고" — 4H 는 거부권이 아니다.
"""
from pathlib import Path

from app.services import trend_4h_gate as G


class _DB:
    def __init__(self, veto=None):
        self._v = veto

    def get(self, _model, key):
        if key == G.SETTING_PYRAMID_4H_VETO and self._v is not None:
            return type("R", (), {"value": self._v})()
        return None


def _patch(monkeypatch, m15, m4, calls):
    def fake(bc, symbol, side, tf, *, use_completed=False):
        calls.append((tf, use_completed))
        v = m15 if tf == "15m" else m4
        return v, {"tf": tf, "delta": 0.0 if v is None else (1.0 if v else -1.0)}
    monkeypatch.setattr(G, "check_hist_rising", fake)


def test_2690_재현_15m_상승_4H_아님_이면_통과(monkeypatch):
    calls = []
    _patch(monkeypatch, True, False, calls)
    ok, why, det = G.check_pyramid_trend(None, "LPTUSDT", "SHORT", db=_DB())
    assert ok is True, why
    assert "참고" in why
    assert det["4h_role"] == "reference"


def test_15m_이_아니면_차단(monkeypatch):
    calls = []
    _patch(monkeypatch, False, True, calls)
    ok, why, _ = G.check_pyramid_trend(None, "X", "LONG", db=_DB())
    assert ok is False and "15m" in why
    # 15m 이 막았으면 4H 는 부르지 않는다 (API 절약 + 4H 가 판정에 끼어들 수 없음)
    assert [c[0] for c in calls] == ["15m"]


def test_완성봉만_쓴다(monkeypatch):
    """4H 진행중 봉은 첫 25% 구간에서 부호가 뒤집힌다 (2026-09-03 실측) — 둘 다 완성봉."""
    calls = []
    _patch(monkeypatch, True, True, calls)
    G.check_pyramid_trend(None, "X", "LONG", db=_DB())
    assert calls == [("15m", True), ("4h", True)]


def test_설정으로_옛_AND_복귀(monkeypatch):
    calls = []
    _patch(monkeypatch, True, False, calls)
    ok, why, det = G.check_pyramid_trend(None, "X", "SHORT", db=_DB(veto="1"))
    assert ok is False and "4h" in why and det["4h_role"] == "veto"


def test_fail_open_은_그대로(monkeypatch):
    calls = []
    _patch(monkeypatch, None, None, calls)
    ok, why, _ = G.check_pyramid_trend(None, "X", "SHORT", db=_DB())
    assert ok is True and "판정 불가" in why
    calls.clear()
    _patch(monkeypatch, True, None, calls)
    ok, why, _ = G.check_pyramid_trend(None, "X", "SHORT", db=_DB())
    assert ok is True and "4H 판정 불가" in why


def test_db_없이_불러도_참고_모드():
    """옛 호출자(db 인자 없음)가 남아 있어도 4H 는 참고다."""
    assert G._pyramid_4h_veto_enabled(None) is False


def test_워커가_db를_넘긴다():
    src = (Path(__file__).resolve().parents[1] / "app" / "workers"
           / "success_pyramiding_worker.py").read_text(encoding="utf-8")
    assert "_pt273(_bc273, si.symbol, si.side, db=db)" in src, "db 를 안 넘기면 설정을 못 읽는다"

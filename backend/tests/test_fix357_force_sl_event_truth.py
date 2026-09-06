"""🧾 Fix 357 — FORCE_STOP_LOSS_TRIGGERED 는 「도달 판정」이지 실행이 아니다: 문구 사실화 + 60분 중복 억제 + 잔량 유지 이벤트.

실측(2026-09-07, 7일 63건): 「손절 지연 51건 −994」의 정체는 1단계 10 USDT 잔량 유지(Fix 326, 사장님 로직) 상태에서
15초마다 「전량 강제 청산 + 전략 종료」 이벤트가 다시 기록된 것. 지연으로 커진 손실 0. 매매 동작은 바꾸지 않는다.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services import risk_service as RS

ROOT = Path(__file__).resolve().parents[1] / "app"


class _FakeDB:
    """execute(select).scalar() 가 마지막 기록 시각을 돌려주는 흉내 (SQLite 는 JSONB 를 못 만들어 실 DB 픽스처 불가)."""
    def __init__(self, last=None):
        self.last = last

    def execute(self, *a, **k):
        last = self.last
        return type("R", (), {"scalar": staticmethod(lambda: last)})()


def test_최근_60분_안_기록이_있으면_중복으로_본다():
    now = datetime.now(timezone.utc)
    assert RS.force_sl_event_recently_recorded(_FakeDB(None), 7) is False
    assert RS.force_sl_event_recently_recorded(_FakeDB(now - timedelta(minutes=5)), 7) is True
    assert RS.force_sl_event_recently_recorded(_FakeDB(now - timedelta(minutes=120)), 7) is False
    naive = (now - timedelta(minutes=3)).replace(tzinfo=None)                 # tz 없는 값도 UTC 로 본다
    assert RS.force_sl_event_recently_recorded(_FakeDB(naive), 7) is True
    assert RS.FORCE_SL_EVENT_DEDUP_MINUTES == 60


def test_조회_실패는_기록하는_쪽(monkeypatch):
    class _Bad:
        def execute(self, *a, **k):
            raise RuntimeError("db down")
    assert RS.force_sl_event_recently_recorded(_Bad(), 1) is False


def test_문구와_배선():
    s = (ROOT / "services" / "risk_service.py").read_text(encoding="utf-8")
    assert "전량 강제 청산 + 전략 종료 (재진입 X)" not in s, "거짓 문구가 남아 있다"
    assert "실행은 단계 규칙이 결정" in s and "force_sl_event_recently_recorded(self.db, strategy.id)" in s
    o = (ROOT / "services" / "tp_sl_orchestrator.py").read_text(encoding="utf-8")
    i_skip = o.find('"[Fix326] %s #%s 잔량 유지 — 손절하지 않음 (%s): %s | %s"')
    i_rec = o.find("self._record_residue_kept(strategy, _why, _nxwhy)")
    assert 0 < i_skip < i_rec, "잔량 유지 skip 경로 바로 뒤에 기록해야 한다"
    assert 'event_type="FORCE_SL_RESIDUE_KEPT"' in o

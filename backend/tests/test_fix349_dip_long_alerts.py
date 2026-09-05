"""📉 Fix 349 — 저점 잡기 롱 알람(패턴 A/B, macd_reversal LONG)은 기본 OFF, 급등 계열(SURGE_START/SURGE_PULLBACK)만.

사장님 2026-09-05: "정지가 아니라 개선안을 찾아줘" / 사상 ②⑤ "롱은 급등중인 심볼 … 원점을 간 심볼은 힘들어"
실측: macd_reversal LONG 4/50 (−537), 저점 패턴 B 0/24 (−413); 100종목 검증에서 저점 규칙 롱 < 무작위 롱.
"""
from pathlib import Path

from app.workers import auto_long_at_bottom_worker as W

ROOT = Path(__file__).resolve().parents[1] / "app"


class _DB:
    def __init__(self, v=None):
        self._v = v

    def get(self, _model, key):
        if key == W.SETTING_DIP_ALERTS and self._v is not None:
            return type("R", (), {"value": self._v})()
        return None


def test_기본은_저점_알람_OFF():
    assert W._dip_alerts_enabled(_DB()) is False


def test_설정으로_켤_수_있다():
    assert W._dip_alerts_enabled(_DB("1")) is True
    assert W._dip_alerts_enabled(_DB("0")) is False


def test_급등_계열만_통과_목록():
    assert set(W.MOMENTUM_ALERT_PATTERNS) == {"SURGE_START", "SURGE_PULLBACK", "MULTIDAY_PULLBACK"}


def test_알람_소비_경로에_게이트가_활성심볼_검사_다음에_있다():
    s = (ROOT / "workers" / "auto_long_at_bottom_worker.py").read_text(encoding="utf-8")
    i_act = s.find('"[Fix75/alert-skip] %s: 이미 활성 심볼"')
    i_gate = s.find('_bump("alert_dip_disabled")')
    i_conf = s.find('_bump("alert_confidence_below_min")')
    assert 0 < i_act < i_gate < i_conf, "활성 심볼 skip → 저점 알람 게이트 → confidence 순서"
    assert 'str(alert.get("pattern") or "").upper() not in MOMENTUM_ALERT_PATTERNS' in s

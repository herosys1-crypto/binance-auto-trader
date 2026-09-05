"""📈 Fix 347 — 급등 계열 롱(상승 초입·급등중 조정)은 「24h 15% 미만 롱 차단」(Fix 274)에서 뺀다.

사장님 2026-09-04: "15% 심볼 롱 차단 이건 또 뭐지 차단 자체가없어 올라가면 롱으로 진입을 해야지"

Fix 274 는 「급등 중이 아닌 종목의 저점 롱」을 거르려고 24h < 15% 면 롱을 막는다(Claude 실측).
상승 초입(SURGE_START)은 24h 가 아직 15% 가 안 된 경우가 많다(MINIMAXUSDT +8%) — 그런데도
「올라가는 심볼」이다. 급등 계열 패턴은 이 게이트를 지나지 않는다.
"""
from pathlib import Path

from app.services import long_surge_gate as L

ROOT = Path(__file__).resolve().parents[1] / "app"


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class _DB:
    def __init__(self, v=None):
        self._v = v

    def get(self, _model, key):
        if key == L.SETTING_SURGE_EXEMPT and self._v is not None:
            return type("R", (), {"value": self._v})()
        return None


def test_기본은_면제_ON():
    assert L.surge_pattern_exempt_enabled(_DB()) is True
    assert L.surge_pattern_exempt_enabled(None) is True


def test_설정으로_끌_수_있다():
    assert L.surge_pattern_exempt_enabled(_DB("0")) is False


def test_면제_패턴은_두_가지():
    assert set(L.SURGE_PATTERNS) == {"SURGE_START", "SURGE_PULLBACK", "MULTIDAY_PULLBACK"}


def test_LONG_생성기가_패턴을_cfg_로_넘긴다():
    s = _src("workers/auto_long_at_bottom_worker.py")
    assert '"entry_pattern": pattern,' in s


def test_공용_관문이_패턴_면제를_재진입_면제_다음에_본다():
    s = _src("workers/auto_bb_breakdown_worker.py")
    i_334 = s.find('reentry_key="long_surge_reentry_exempt"')
    i_347 = s.find("surge_pattern_exempt_enabled as _spx347")
    i_blk = s.find('logger.info("[Fix274/LONG급등] ⛔ %s 차단 — %s", symbol, _why274)')
    assert 0 < i_334 < i_347 < i_blk, "재진입 면제 → 급등 패턴 면제 → 차단 순서"
    assert '(cfg or {}).get("entry_pattern")' in s

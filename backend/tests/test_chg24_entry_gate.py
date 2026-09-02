"""Fix 310 — 「당일 10% 이상 상승/하락한 심볼만 진입」 단위 테스트.

사장님 2026-09-03: "당분간 당일 10%이상 상승과 하락한 심볼만 모니터링하고
                   포지션에 진입하도록해줘"
"""
import ast
from pathlib import Path

from app.services import chg24_entry_gate as G
from app.services import execution_service as E

ESRC = Path(E.__file__).read_text(encoding="utf-8")


class _DB:
    def __init__(self, vals=None, boom=False):
        self.vals = vals or {}
        self.boom = boom

    def get(self, _model, key):
        if self.boom:
            raise RuntimeError("db down")
        if key not in self.vals:
            return None
        return type("R", (), {"value": self.vals[key]})()


class _BC:
    def __init__(self, chg=None, boom=False, as_list=False):
        self.chg, self.boom, self.as_list = chg, boom, as_list

    def get_24hr_ticker(self, symbol=None):
        if self.boom:
            raise RuntimeError("api down")
        t = {"symbol": symbol, "priceChangePercent": str(self.chg)}
        return [t] if self.as_list else t


ON = {G.SETTING_ENABLED: "1"}


# ── 사장님 지시 그대로 ────────────────────────────────────────────────

def test_상승도_하락도_10퍼센트_이상이면_통과():
    """「상승과 하락」 = 절대값 기준. 급등도 급락도 대상이다."""
    for chg in (10.0, 12.5, 40.0, -10.0, -12.5, -40.0):
        ok, why = G.passes(_DB(ON), _BC(chg), "X")
        assert ok, f"{chg}% 가 막혔다 — {why}"


def test_10퍼센트_미만은_막힌다():
    for chg in (9.99, 5.0, 0.0, -5.0, -9.99):
        ok, why = G.passes(_DB(ON), _BC(chg), "X")
        assert not ok, f"{chg}% 가 통과했다"
        assert "미충족" in why


def test_경계값_10은_포함():
    assert G.passes(_DB(ON), _BC(10.0), "X")[0] is True
    assert G.passes(_DB(ON), _BC(-10.0), "X")[0] is True


# ── 「당분간」 = 끄고 켜고 값 바꾸기 ──────────────────────────────────

def test_기본은_꺼져있다():
    """설정을 넣어야 작동한다 — 기본 동작을 바꾸지 않는다."""
    assert G.gate_enabled(_DB()) is False
    assert G.passes(_DB(), _BC(0.0), "X")[0] is True


def test_임계값을_바꿀_수_있다():
    db = _DB({G.SETTING_ENABLED: "1", G.SETTING_MIN_ABS: "15"})
    assert G.passes(db, _BC(12.0), "X")[0] is False
    assert G.passes(db, _BC(16.0), "X")[0] is True


def test_손상값이면_기본_10():
    for bad in ("", "abc", "-1", "101"):
        db = _DB({G.SETTING_ENABLED: "1", G.SETTING_MIN_ABS: bad})
        assert G.min_abs_chg24(db) == 10.0, bad


# ── 🚨 수동 진입은 사장님 판단 ────────────────────────────────────────

def test_수동진입은_게이트를_적용하지_않는다():
    """사장님이 손으로 넣으신 것을 자동 규칙으로 막으면 안 된다."""
    ok, why = G.passes(_DB(ON), _BC(1.0), "X", template_name="_quick_20260903_1")
    assert ok and "수동" in why


def test_자동_템플릿은_적용된다():
    for name in ("auto_bb_break_SAJANGNIM_TOP", "BB_MIDLINE_x", None):
        ok, _w = G.passes(_DB(ON), _BC(1.0), "X", template_name=name)
        assert not ok, name


# ── fail 방향 ────────────────────────────────────────────────────────

def test_조회_실패는_통과시킨다():
    """🚨 fail-closed 하면 API 가 한 번 흔들릴 때마다 모든 신규 진입이 멈춘다."""
    ok, why = G.passes(_DB(ON), _BC(boom=True), "X")
    assert ok and "fail-open" in why


def test_DB_장애도_통과():
    assert G.passes(_DB(boom=True), _BC(1.0), "X")[0] is True


def test_리스트_응답도_처리한다():
    assert G.passes(_DB(ON), _BC(20.0, as_list=True), "X")[0] is True


# ── 🚨 어디에 걸렸는가 (이게 핵심) ────────────────────────────────────

def _fn(name):
    tree = ast.parse(ESRC)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.get_source_segment(ESRC, n) or ""
    raise AssertionError(f"{name} 없음")


def test_신규진입_1단계에_걸린다():
    assert "chg24_entry_gate import passes" in _fn("start_stage1")


def test_단계진입에는_걸지_않는다():
    """🚨 여기 걸면 1단계 때 12%였다가 2단계에서 8%로 떨어질 때
    사다리가 영원히 멈춘다. 이미 자금이 들어간 전략을 변동률로 끊으면 안 된다."""
    assert "chg24_entry_gate" not in _fn("trigger_next_stage")
    assert "chg24_entry_gate" not in _fn("enter_stage_at_market")
    assert "chg24_entry_gate" not in _fn("add_position_now")


def test_게이트_오류가_매매를_막지_않는다():
    src = _fn("start_stage1")
    blk = src[src.index("chg24_entry_gate"):]
    assert "except Exception as _ge:" in blk
    assert "fail-open" in blk


def test_근거가_모듈에_남아_있다():
    doc = G.__doc__ or ""
    assert "start_stage1" in doc and "trigger_next_stage" in doc
    assert "_quick_" in doc

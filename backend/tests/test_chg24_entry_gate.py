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
    """순위 방식은 전체 티커 목록을 받는다 (symbol 인자 없이 호출)."""

    def __init__(self, chg=None, boom=False, as_list=False, others=None, sym="X"):
        self.chg, self.boom, self.as_list = chg, boom, as_list
        self.others = others or []
        self.sym = sym          # 순위 방식은 symbol 인자 없이 전체를 받는다

    def get_24hr_ticker(self, symbol=None):
        if self.boom:
            raise RuntimeError("api down")
        me = {"symbol": symbol or self.sym, "priceChangePercent": str(self.chg),
              "quoteVolume": "999999999"}
        if symbol is not None:
            return [me] if self.as_list else me
        return [me] + list(self.others)


ON = {G.SETTING_ENABLED: "1"}
ABS = {G.SETTING_ENABLED: "1", G.SETTING_MODE: "abs"}


# ── 사장님 지시 그대로 ────────────────────────────────────────────────

def test_상승도_하락도_10퍼센트_이상이면_통과():
    """「상승과 하락」 = 절대값 기준. 급등도 급락도 대상이다."""
    for chg in (10.0, 12.5, 40.0, -10.0, -12.5, -40.0):
        ok, why = G.passes(_DB(ABS), _BC(chg), "X")
        assert ok, f"{chg}% 가 막혔다 — {why}"


def test_10퍼센트_미만은_막힌다():
    for chg in (9.99, 5.0, 0.0, -5.0, -9.99):
        ok, why = G.passes(_DB(ABS), _BC(chg), "X")
        assert not ok, f"{chg}% 가 통과했다"
        assert "미충족" in why


def test_경계값_10은_포함():
    assert G.passes(_DB(ABS), _BC(10.0), "X")[0] is True
    assert G.passes(_DB(ABS), _BC(-10.0), "X")[0] is True


# ── 「당분간」 = 끄고 켜고 값 바꾸기 ──────────────────────────────────

def test_기본은_꺼져있다():
    """설정을 넣어야 작동한다 — 기본 동작을 바꾸지 않는다."""
    assert G.gate_enabled(_DB()) is False
    assert G.passes(_DB(), _BC(0.0), "X")[0] is True


def test_임계값을_바꿀_수_있다():
    db = _DB({G.SETTING_ENABLED: "1", G.SETTING_MODE: "abs", G.SETTING_MIN_ABS: "15"})
    assert G.passes(db, _BC(12.0), "X")[0] is False
    assert G.passes(db, _BC(16.0), "X")[0] is True


def test_손상값이면_기본_10():
    for bad in ("", "abc", "-1", "101"):
        db = _DB({G.SETTING_ENABLED: "1", G.SETTING_MIN_ABS: bad})
        assert G.min_abs_chg24(db) == 10.0, bad


# ── 🚨 수동 진입은 사장님 판단 ────────────────────────────────────────

def test_수동진입은_게이트를_적용하지_않는다():
    """사장님이 손으로 넣으신 것을 자동 규칙으로 막으면 안 된다."""
    ok, why = G.passes(_DB(ABS), _BC(1.0), "X", template_name="_quick_20260903_1")
    assert ok and "수동" in why


def test_자동_템플릿은_적용된다():
    for name in ("auto_bb_break_SAJANGNIM_TOP", "BB_MIDLINE_x", None):
        ok, _w = G.passes(_DB(ABS), _BC(1.0), "X", template_name=name)
        assert not ok, name


# ── fail 방향 ────────────────────────────────────────────────────────

def test_조회_실패는_통과시킨다():
    """🚨 fail-closed 하면 API 가 한 번 흔들릴 때마다 모든 신규 진입이 멈춘다."""
    ok, why = G.passes(_DB(ABS), _BC(boom=True), "X")
    assert ok and "fail-open" in why


def test_DB_장애도_통과():
    assert G.passes(_DB(boom=True), _BC(1.0), "X")[0] is True


def test_리스트_응답도_처리한다():
    assert G.passes(_DB(ABS), _BC(20.0, as_list=True), "X")[0] is True


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



# ═══════════════════════════════════════════════════════════════════════
# Fix 325 — 사장님 「상승 50 / 하락 50 = 100개」
# ═══════════════════════════════════════════════════════════════════════

def _tick(sym, chg):
    return {"symbol": sym, "priceChangePercent": str(chg), "quoteVolume": "999999999"}


def test_기본은_순위_방식이다():
    assert G.gate_mode(_DB()) == "rank"
    assert G.top_n(_DB()) == 50


def _pool(n_up, n_dn):
    """상승 n_up + 하락 n_dn 짜리 시장.

    🚨 `top_movers` 는 심볼이 적으면 상승/하락 목록이 **겹친다**(docstring 경고).
    그래서 대상이 한쪽에만 들도록 반대편을 충분히 두껍게 깐다.
    """
    return ([_tick("U%dUSDT" % i, 80 - i * 0.5) for i in range(1, n_up + 1)]
            + [_tick("D%dUSDT" % i, -80 + i * 0.5) for i in range(1, n_dn + 1)])


def test_상승_50위_안이면_통과():
    """+3% 라도 상승 50위 안(21위)이면 대상이다 — 절대값 10% 방식이면 막혔다."""
    ok, why = G.passes(_DB(ON), _BC(3.0, others=_pool(20, 60), sym="XUSDT"), "XUSDT")
    assert ok and "상승" in why, why


def test_하락_50위_안이면_통과():
    ok, why = G.passes(_DB(ON), _BC(-3.0, others=_pool(60, 20), sym="XUSDT"), "XUSDT")
    assert ok and "하락" in why, why


def test_순위_밖이면_막힌다():
    """상승 50 + 하락 50 어디에도 안 들면 대상이 아니다."""
    ok, why = G.passes(_DB(ON), _BC(0.0, others=_pool(60, 60), sym="XUSDT"), "XUSDT")
    assert not ok and "위 밖" in why, why


def test_순위_개수를_설정으로_바꾼다():
    """50위 안이던 것이 top_n=10 이면 밖이 된다 — 설정이 실제로 먹는다."""
    n50 = _DB({G.SETTING_ENABLED: "1"})
    n10 = _DB({G.SETTING_ENABLED: "1", G.SETTING_TOP_N: "10"})
    assert G.top_n(n10) == 10

    pool = _pool(20, 60)        # 대상 +3% = 상승 21위
    assert G.passes(n50, _BC(3.0, others=pool, sym="XUSDT"), "XUSDT")[0]
    assert not G.passes(n10, _BC(3.0, others=pool, sym="XUSDT"), "XUSDT")[0]


def test_손상된_순위값은_기본_50():
    for bad in ("", "abc", "0", "-1", "9999"):
        assert G.top_n(_DB({G.SETTING_TOP_N: bad})) == 50, bad


def test_abs_모드로_되돌릴_수_있다():
    db = _DB({G.SETTING_ENABLED: "1", G.SETTING_MODE: "abs"})
    assert G.gate_mode(db) == "abs"
    assert G.passes(db, _BC(12.0), "X")[0] is True
    assert G.passes(db, _BC(3.0), "X")[0] is False


def test_시세_조회_실패는_통과():
    """🚨 fail-closed 하면 API 가 흔들릴 때마다 모든 신규 진입이 멈춘다."""
    ok, why = G.passes(_DB(ON), _BC(boom=True), "X")
    assert ok and "fail-open" in why

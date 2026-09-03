"""🔁 Fix 334 — 손절 후 재진입이 신규 진입 게이트에 막혀 24시간 608회 시도 / 성공 0건.

사장님 사양: "실패하면 10usdt 남기고 부분손절하고 ... 다시 2단계 진입하고
             그리고도 실패하면 다시 부분손절하고 다시 모니터링 하고 다시 진입시점에 진입"

## 감사 실측 (2026-09-03)

    방향   시도   주 차단자                        건수
    LONG   304   Fix 274 (24h 급등 15% 미만)      297   ← 통과율 0.19%
    SHORT  297   Fix 270 (4H MACD hist)           294

    [reentry_alert v130] 🎯 재진입 알람! SUIUSDT LONG obv_reverse=True rsi_reverse=True
    [Fix274/LONG급등]    ⛔ SUIUSDT 차단 — 24h +7.6% < 15%
    [RT_REENTRY]         🚨 skip: _create_auto_bb_strategy None 반환!

재진입 워커는 자기 판정(OBV·RSI 반전)을 통과한 심볼만 보내는데, 그 위에 신규 진입용
추세 게이트를 또 걸어 **이중 필터**가 됐다.

## 이 테스트가 지키는 것

1. 재진입(`_reentry1`)은 Fix 270 / 247 / 274 를 **참고로만** 지난다
2. 🚨 **면제하면 안 되는 것은 여전히 막는다** — 이 파일은 그 경계를 코드로 고정한다
3. 신규 진입(`""`)은 **기존 동작 그대로**
4. 판정이 **한 곳**에만 정의된다 (흩어지면 한쪽만 고치는 사고 — Fix 318→319)
5. 워커가 **실제로 호출**한다 (안 하면 코드에만 있고 안 돈다 — Fix 247/318)
"""
import ast
from pathlib import Path

from app.services import trend_4h_gate as G
from app.services import confluence_gate as C


class _DB:
    def __init__(self, settings=None):
        self._s = settings or {}

    def get(self, model, key):
        if getattr(model, "__name__", "") == "SystemSetting":
            if key not in self._s:
                return None
            return type("R", (), {"value": self._s[key]})()
        return None


def _kl(closes):
    return [[i * 14400000, str(c), str(c * 1.01), str(c * 0.99), str(c), "1000"]
            for i, c in enumerate(closes)]


class _BC:
    def __init__(self, closes):
        self._c = closes

    def get_klines(self, *, symbol, interval, limit=60, **_kw):
        return _kl(self._c)


#: SHORT 에게 불리한 4H (계속 오르는 중)
RISING = [100.0 * (1.004 ** i) for i in range(60)]


# ═════════════════════════════════════════════════════════════════════
# 판정 함수
# ═════════════════════════════════════════════════════════════════════

def test_재진입_판정():
    for s in ("_reentry1", "_reentry2", "auto_bb_break_reentry1", "_REENTRY_success"):
        assert G.is_reentry_strategy(s) is True, s
    for s in ("", None, "_SAJANGNIM_TOP", "_OBV_HOLD", "_success", "bb_mid_line"):
        assert G.is_reentry_strategy(s) is False, s


def test_gate_exempt_는_반전과_재진입을_한_곳에서_가른다():
    db = _DB()
    assert G.gate_exempt(db, "_SAJANGNIM_TOP")[0] is True
    assert G.gate_exempt(db, "_reentry1")[0] is True
    assert G.gate_exempt(db, "")[0] is False
    assert G.gate_exempt(db, "_OBV_HOLD")[0] is False
    assert G.gate_exempt(None, "_reentry1")[0] is False      # db 없으면 면제 없음
    assert G.gate_exempt(db, None)[0] is False               # 종류 없으면 면제 없음


def test_gate_exempt_reversal_False_면_반전은_안_본다():
    """합의 게이트처럼 반전 스위치를 따로 가진 호출자용."""
    db = _DB()
    assert G.gate_exempt(db, "_SAJANGNIM_TOP", reversal=False)[0] is False
    assert G.gate_exempt(db, "_reentry1", reversal=False)[0] is True


# ═════════════════════════════════════════════════════════════════════
# 🚨 핵심 — 재진입은 막히지 않는다
# ═════════════════════════════════════════════════════════════════════

def test_Fix270_재진입은_4H가_나빠도_막히지_않는다():
    ok, why, d = G.check_trend_4h(_BC(RISING), "XUSDT", "SHORT",
                                  db=_DB(), strategy_kind="_reentry1")
    assert ok is True, why
    assert "재진입" in d.get("exempt_why", ""), d
    assert d.get("ref_note"), "「4H 가 안 좋다」는 기록은 남아야 한다"


def test_Fix270_신규_진입은_기존대로_막힌다():
    """🚨 게이트를 통째로 여는 것이 아니다."""
    ok, _w, d = G.check_trend_4h(_BC(RISING), "XUSDT", "SHORT",
                                 db=_DB(), strategy_kind="")
    assert ok is False and d.get("reversal_exempt") is False


def test_Fix270_재진입_면제를_설정으로_끈다():
    db = _DB({G.SETTING_REENTRY_EXEMPT: "0"})
    ok, _w, _d = G.check_trend_4h(_BC(RISING), "XUSDT", "SHORT",
                                  db=db, strategy_kind="_reentry1")
    assert ok is False


def test_Fix270_재진입_면제를_꺼도_반전은_남는다():
    """두 스위치는 독립이다."""
    db = _DB({G.SETTING_REENTRY_EXEMPT: "0"})
    ok, _w, _d = G.check_trend_4h(_BC(RISING), "XUSDT", "SHORT",
                                  db=db, strategy_kind="_SAJANGNIM_TOP")
    assert ok is True


def test_기본값은_ON():
    assert G.reentry_exempt_enabled(_DB()) is True
    assert G.reentry_exempt_enabled(_DB({G.SETTING_REENTRY_EXEMPT: "0"})) is False
    # 다른 키로도 같은 방식으로 읽힌다
    assert G.reentry_exempt_enabled(_DB({"confluence_reentry_exempt": "false"}),
                                    "confluence_reentry_exempt") is False


# ═════════════════════════════════════════════════════════════════════
# 🚨 판정이 한 곳에만 정의된다 + 워커가 실제로 부른다
# ═════════════════════════════════════════════════════════════════════

def _fn_src(mod, name):
    src = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.get_source_segment(src, n) or ""
    raise AssertionError(f"{name} 없음")


def test_재진입_판정이_한_곳에만_정의된다():
    """🚨 게이트마다 `"_reentry" in ...` 를 따로 쓰면 한쪽만 고치는 사고가 난다."""
    from app.workers import auto_bb_breakdown_worker as W
    for mod in (C, W):
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "def is_reentry_strategy" not in src, f"{mod.__name__} 에 재진입 판정이 중복 정의됐다"
        assert "def gate_exempt" not in src, f"{mod.__name__} 에 gate_exempt 가 중복 정의됐다"
    src_g = Path(G.__file__).read_text(encoding="utf-8")
    assert src_g.count("def is_reentry_strategy") == 1
    assert src_g.count("def gate_exempt") == 1


def test_합의_게이트가_gate_exempt_를_쓴다():
    src = _fn_src(C, "check_confluence_gate")
    assert "gate_exempt(" in src, "합의 게이트가 재진입 면제를 안 본다"
    assert 'reentry_key="confluence_reentry_exempt"' in src


def test_워커_Fix274_가_재진입_면제를_실제로_부른다():
    """🚨 안 부르면 LONG 재진입은 여전히 0.19% 로 죽는다."""
    from app.workers import auto_bb_breakdown_worker as W
    src = _fn_src(W, "_create_auto_bb_strategy")
    assert 'reentry_key="long_surge_reentry_exempt"' in src, "Fix274 블록에 재진입 면제가 없다"
    # 면제 판정이 `return None` **앞**에 있어야 한다
    i_ex = src.index('reentry_key="long_surge_reentry_exempt"')
    i_ret = src.index("[Fix274/LONG급등] ⛔")
    assert i_ex < i_ret, "면제 판정이 차단 뒤에 있어 의미가 없다"


def test_Fix251_되돌림은_재진입에도_그대로_건다():
    """🚨 원점 회귀(6건 -1,845)는 손절 뒤에 **더** 위험하다. 면제하면 안 된다."""
    from app.workers import auto_bb_breakdown_worker as W
    src = _fn_src(W, "_create_auto_bb_strategy")
    i_251 = src.index("[Fix251] 🚫")
    # Fix251 차단 직전 200자 안에 재진입 면제 호출이 있으면 안 된다
    window = src[max(0, i_251 - 1200):i_251]
    assert "long_surge_reentry_exempt" not in window
    assert "gate_exempt" not in window, "Fix251 에 재진입 면제가 걸렸다 — 위험"


def test_실측_근거가_주석에_남아_있다():
    src = Path(G.__file__).read_text(encoding="utf-8")
    for token in ("608회", "0.19%", "297", "294", "이중 필터"):
        assert token in src, token

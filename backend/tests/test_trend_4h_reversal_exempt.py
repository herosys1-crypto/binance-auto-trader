"""🚨 Fix 330 — 4H 는 「거부권」이 아니라 「참고」다 (반전 전략 한정).

사장님 2026-09-03 정정:

  "**15분이 기준이고 4시간을 참고**하고 4시간 장기 흐름을 판단하는 차트라고
   그렇게 이야기를 했으고 차트전문가라면 **4시간 차트의 의미는 중단기 지속적인
   흐름을 판단하는 정도** 차트라는걸 알잖아"

## 왜 이 파일이 필요한가

Fix 270 의 4H 게이트는 「4H MACD hist 가 내 편으로 상승 중 AND 내 편 부호」를
**통과 조건**으로 걸었다. 실측 결과:

    최근 6시간  차단 1,546건 / 통과 52건 = **통과율 3.3%**

🚨 정점 SHORT 는 **정의상 4H 가 아직 안 꺾인 자리**를 잡는다.
   그런데 이 게이트는 "이미 꺾였을 것"을 요구한다 = 정면 충돌.
   그래서 사다리를 켠 2026-09-03 07:22 이후 v219 정점 SHORT 가
   **단 한 건도 생성되지 않았고**, 사장님 루프의 출발점이 막혀 있었다.

## 이 테스트가 지키는 것

1. 반전 전략(정점/저점)은 4H 가 안 좋아도 **막히지 않는다**
2. 그 외 전략은 **기존 동작 그대로** (남의 전략을 바꾸지 않는다)
3. 설정으로 되돌릴 수 있다
4. 워커가 전략 종류를 **실제로 넘긴다** (안 넘기면 이 기능이 죽은 채로 산다)
"""
import ast
from pathlib import Path

from app.services import trend_4h_gate as G


# ─────────────────────────────────────────────────────────────────────
# 스텁
# ─────────────────────────────────────────────────────────────────────

class _DB:
    def __init__(self, settings):
        self._s = settings

    def get(self, model, key):
        if getattr(model, "__name__", "") == "SystemSetting":
            if key not in self._s:
                return None
            return type("R", (), {"value": self._s[key]})()
        return None


def _kl(closes):
    """4H kline. MACD 계산에 40봉 이상 필요."""
    return [[i * 14400000, str(c), str(c * 1.01), str(c * 0.99), str(c), "1000"]
            for i, c in enumerate(closes)]


class _BC:
    def __init__(self, closes):
        self._c = closes

    def get_klines(self, *, symbol, interval, limit=60, **_kw):
        return _kl(self._c)


#: SHORT 에게 **불리한** 4H — 계속 오르는 중이라 hist 가 SHORT 편이 아니다
RISING = [100.0 * (1.004 ** i) for i in range(60)]


# ═════════════════════════════════════════════════════════════════════
# 🚨 핵심 — 반전 전략은 막히지 않는다
# ═════════════════════════════════════════════════════════════════════

def test_정점SHORT은_4H가_나빠도_막히지_않는다():
    """v219 급등 정점 SHORT. 사장님 사상 ①의 출발점이다."""
    ok, why, d = G.check_trend_4h(
        _BC(RISING), "XUSDT", "SHORT",
        db=_DB({}), strategy_kind="_SAJANGNIM_TOP",
    )
    assert ok is True, f"정점 SHORT 가 막혔다: {why}"
    assert d.get("reversal_exempt") is True
    assert "참고" in why, why
    # 🚨 「4H 가 안 좋다」는 사실 자체는 기록으로 남아야 한다
    assert d.get("ref_note"), "판단 근거가 사라지면 나중에 못 잰다"


def test_저점LONG도_같다():
    falling = [100.0 * (0.996 ** i) for i in range(60)]
    ok, why, d = G.check_trend_4h(
        _BC(falling), "XUSDT", "LONG",
        db=_DB({}), strategy_kind="_SAJANGNIM_BOTTOM",
    )
    assert ok is True and d.get("reversal_exempt") is True, why


#: SHORT 에게 **유리한** 4H — 하락이 막 시작돼 hist 가 SHORT 편으로 커지는 중.
#  🚨 이 모양을 찾는 데 후보 5개가 전부 실패했다. 게이트 조건
#  (`rising AND signed > 0`)이 그만큼 좁다는 뜻이고, 그것이 실측 통과율
#  **3.3%** (6시간 차단 1,546 / 통과 52)의 실체다.
#  ⚠️ 정률 하락은 오히려 hist 가 **회복**된다(절대 하락폭이 줄어서).
#     "내려가면 SHORT 에 유리하다"는 직관이 MACD 에서는 성립하지 않는다.
FALLING_FRESH = [100.0] * 46 + [100.0 - (i + 1) * 0.5 for i in range(14)]


def test_4H가_좋으면_반전전략도_그냥_통과():
    """면제는 「막지 않는다」이지 「판정을 안 한다」가 아니다."""
    ok, why, d = G.check_trend_4h(
        _BC(FALLING_FRESH), "XUSDT", "SHORT",
        db=_DB({}), strategy_kind="_SAJANGNIM_TOP",
    )
    assert ok is True, why
    assert "참고" not in why, "4H 가 지지하는데 참고 문구가 붙었다"
    assert not d.get("ref_note")


def test_게이트_조건이_실제로_좁다():
    """🚨 통과율 3.3% 의 근거를 코드로 남긴다.

    「하락 중이면 SHORT 에 유리」라는 직관은 MACD 에서 성립하지 않는다.
    정률 하락·선형 하락·평탄후 급락·가속 급락 — 전부 통과하지 못한다.
    """
    shapes = {
        "정률하락": [100.0 * (0.996 ** i) for i in range(60)],
        "선형하락": [100.0 - i * 0.5 for i in range(60)],
        "평탄후_급락": [100.0] * 40 + [100.0 - (i + 1) * 3.0 for i in range(20)],
        "가속급락": [100.0 * (0.97 ** i) for i in range(60)],
    }
    passed = [k for k, v in shapes.items()
              if G.check_trend_4h(_BC(v), "XUSDT", "SHORT")[0]]
    assert passed == [], f"통과한 모양이 생겼다 (조건이 느슨해졌는가?): {passed}"


# ═════════════════════════════════════════════════════════════════════
# 남의 전략은 바꾸지 않는다
# ═════════════════════════════════════════════════════════════════════

def test_반전이_아니면_기존대로_막힌다():
    """🚨 게이트를 통째로 여는 것이 아니다. 실측(게이트 없음 158건 -3,599.87)이
    말하는 위험은 추세 편승 계열에 그대로 있다."""
    for kind in ("_OBV_HOLD", "_reentry1", "", "_success"):
        ok, why, d = G.check_trend_4h(
            _BC(RISING), "XUSDT", "SHORT", db=_DB({}), strategy_kind=kind,
        )
        assert ok is False, f"{kind!r} 가 통과했다 — 남의 전략이 바뀌었다"
        assert d.get("reversal_exempt") is False


def test_인자를_안_넘기면_기존_동작():
    """호출자가 전략 종류를 안 넘기면 예전과 똑같이 막는다 (하위호환)."""
    ok, _why, _d = G.check_trend_4h(_BC(RISING), "XUSDT", "SHORT")
    assert ok is False


def test_db만_넘기고_종류를_안_넘겨도_기존_동작():
    ok, _why, _d = G.check_trend_4h(_BC(RISING), "XUSDT", "SHORT", db=_DB({}))
    assert ok is False


# ═════════════════════════════════════════════════════════════════════
# 되돌릴 수 있어야 한다
# ═════════════════════════════════════════════════════════════════════

def test_설정으로_끄면_반전전략도_막힌다():
    db = _DB({G.SETTING_REVERSAL_EXEMPT: "0"})
    ok, _why, d = G.check_trend_4h(
        _BC(RISING), "XUSDT", "SHORT", db=db, strategy_kind="_SAJANGNIM_TOP",
    )
    assert ok is False and d.get("reversal_exempt") is False


def test_기본값은_ON():
    """사장님 정정이 기본이어야 한다 — 설정을 안 넣어도 켜져 있어야 한다."""
    assert G.reversal_exempt_enabled(_DB({})) is True
    for v in ("1", "true", "on", "yes"):
        assert G.reversal_exempt_enabled(_DB({G.SETTING_REVERSAL_EXEMPT: v})) is True
    for v in ("0", "false", "off", "no"):
        assert G.reversal_exempt_enabled(_DB({G.SETTING_REVERSAL_EXEMPT: v})) is False


def test_빈값이면_기본_ON():
    assert G.reversal_exempt_enabled(_DB({G.SETTING_REVERSAL_EXEMPT: "  "})) is True


# ═════════════════════════════════════════════════════════════════════
# 반전 판정
# ═════════════════════════════════════════════════════════════════════

def test_반전_전략_판정():
    for s in ("_SAJANGNIM_TOP", "_SAJANGNIM_BOTTOM",
              "auto_bb_break_SAJANGNIM_TOP", "TOP_REVERSAL"):
        assert G.is_reversal_strategy(s) is True, s
    for s in ("_OBV_HOLD", "_reentry1", "", None, "bb_mid_line", "pump_split"):
        assert G.is_reversal_strategy(s) is False, s


# ═════════════════════════════════════════════════════════════════════
# 🚨 실제로 호출되는가 (Fix 247/318 의 교훈)
# ═════════════════════════════════════════════════════════════════════

def test_워커가_전략_종류를_실제로_넘긴다():
    """🚨 안 넘기면 이 기능은 코드에만 있고 한 번도 안 도는 것이 된다.

    오늘만 해도 Fix 318 이 엉뚱한 함수에 붙어 정적 검사 13건을 전부 통과하고도
    실제로는 아무 효과가 없었다.
    """
    from app.workers import auto_bb_breakdown_worker as W
    src = Path(W.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_create_auto_bb_strategy")
    seg = ast.get_source_segment(src, fn) or ""
    assert "strategy_kind=strategy_type_suffix" in seg, \
        "워커가 전략 종류를 안 넘긴다 — Fix 330 이 죽은 채로 산다"
    assert "db=db" in seg, "db 를 안 넘기면 설정을 읽지 못해 면제가 항상 꺼진다"


def test_실측_근거가_주석에_남아_있다():
    """다음에 무심코 되돌리지 않도록."""
    src = Path(G.__file__).read_text(encoding="utf-8")
    for token in ("1,546", "3.3%", "15분이 기준", "SAJANGNIM_TOP"):
        assert token in src, token

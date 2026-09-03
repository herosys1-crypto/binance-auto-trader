"""📐 지지선 7점 판정 테스트 (Fix 327).

사장님 2026-09-03:
  "차트와 보조지표 급등과 급락 그리고 보합 그리고 다시 **지지반등과 지지선
   추가 하락**시 보조지표의 움직임과 수치를 전문가가 분석해서 수치화"

## 이 파일이 지키는 것

1. **역방향 규칙이 진짜 역방향인가** — 이 판정식의 핵심 발견이다.
   "이미 오르고 있으면 점수를 주지 않는다". 이게 뒤집히면 판정식 전체가
   "반등을 보고 사는" 옛 방식으로 되돌아간다.
2. **지지선 접촉 시점이 아니면 막지 않는가** — 판정식은 접촉 264건으로
   만들어졌다. 다른 자리에 적용하면 표본 밖이다.
3. **1단계에만 걸리고 단계 진입에는 안 걸리는가** — 사다리를 끊으면 안 된다.
4. **실제로 호출되는가** — Fix 247/318 의 교훈: 계산만 하고 안 쓰면 무의미.
"""
import ast
from pathlib import Path

from app.services import support_score as S


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


ON = {S.SETTING_ENABLED: "1"}


def _kl(closes, *, lows=None, highs=None, vol=1000.0):
    """Binance kline 형식으로 만든다."""
    out = []
    for i, c in enumerate(closes):
        lo = lows[i] if lows else c * 0.995
        hi = highs[i] if highs else c * 1.005
        out.append([i * 900000, str(c), str(hi), str(lo), str(c),
                    str(vol), i * 900000 + 899999, "0", 0, "0", "0", "0"])
    return out


class _BC:
    def __init__(self, kl15, kl1h):
        self._15, self._1h = kl15, kl1h

    def get_klines(self, *, symbol, interval, limit=200, **_kw):
        return self._15 if interval == "15m" else self._1h


# ═════════════════════════════════════════════════════════════════════
# 🚨 핵심 — 역방향 규칙
# ═════════════════════════════════════════════════════════════════════

def test_이미_오르고_있으면_점수를_주지_않는다():
    """🚨 이 판정식의 가장 중요한 발견.

    실측: 15m MACD hist 「3봉 상승중」 d = **-0.380** (역방향).
    아래꼬리·RSI 상향전환·거래량 급증은 전부 부호가 반대이거나
    "이미 반등해서 비싸게 사는" 아티팩트였다.

    이 테스트가 실패하면 판정식이 옛 방식(반등 보고 사기)으로 돌아간 것이다.
    """
    flat1h = [100.0] * 60

    # 🚨 「상승 중」은 **가속** 상승이다. 선형 상승은 모멘텀이 일정해서
    #    MACD hist 가 0 으로 수렴한다 = 상승 중이 아니다.
    #    (이 테스트를 처음 쓸 때 선형으로 썼다가 반증됐다 — MACD 의 성질)
    accel = [100.0 * (1.004 ** i) for i in range(150)]
    score, d = S.compute_score(_kl(accel), _kl(flat1h))
    assert score is not None
    assert d["rules"]["m15_macdh_not_rising3"] is False, \
        "가속 상승 중인데 점수를 줬다 — 역방향 규칙이 뒤집혔다"

    # 가속 하락 — 아직 떨어지는 중이므로 1점 (= 미리 걸어둘 자리)
    #   ⚠️ 선형 하락은 hist 가 음수에서 0 으로 **올라온다**(하락 모멘텀 약화)
    #      = 「상승 중」으로 잡힌다. 이것도 MACD 의 성질이다.
    falling = [100.0 * (0.996 ** i) for i in range(150)]
    _s2, d2 = S.compute_score(_kl(falling), _kl(flat1h))
    assert d2["rules"]["m15_macdh_not_rising3"] is True

    # 급락 직후 횡보 — 사장님 AKEUSDT 같은 자리. 1점.
    crash = [100.0] * 100 + [100.0 - i * 2.0 for i in range(30)] + [40.0] * 20
    _s3, d3 = S.compute_score(_kl(crash), _kl(flat1h))
    assert d3["rules"]["m15_macdh_not_rising3"] is True


def test_규칙이_정확히_7개다():
    """가중치 없는 7점 만점. 규칙이 늘거나 줄면 임계값(6 / 1)이 무의미해진다."""
    score, d = S.compute_score(_kl([100.0] * 150), _kl([100.0] * 60))
    assert len(d["rules"]) == S.MAX_SCORE == 7
    assert 0 <= score <= 7


# ═════════════════════════════════════════════════════════════════════
# 판정 임계값 — 실측 근거대로
# ═════════════════════════════════════════════════════════════════════

def test_LONG은_6점_이상():
    """score >= 6 → 승률 70.6% (n=80, A 75.0 / B 64.3), 기준선 55.0%."""
    assert S.decide(7, "LONG")[0] is True
    assert S.decide(6, "LONG")[0] is True
    assert S.decide(5, "LONG")[0] is False
    assert S.decide(0, "LONG")[0] is False


def test_SHORT은_1점_이하():
    """score <= 1 → 승률 63.9% (n=67, A 72.2 / B 60.5)."""
    assert S.decide(0, "SHORT")[0] is True
    assert S.decide(1, "SHORT")[0] is True
    assert S.decide(2, "SHORT")[0] is False
    assert S.decide(7, "SHORT")[0] is False


def test_중간_구간은_양쪽_다_막힌다():
    """2~5 = 관망. 「어느 쪽도 근거가 없다」가 판정 결과다."""
    for sc in (2, 3, 4, 5):
        assert S.decide(sc, "LONG")[0] is False, f"{sc}점에 LONG 허용"
        assert S.decide(sc, "SHORT")[0] is False, f"{sc}점에 SHORT 허용"


def test_임계값을_설정으로_바꾼다():
    db = _DB({S.SETTING_ENABLED: "1", S.SETTING_MIN_LONG: "5",
              S.SETTING_MAX_SHORT: "2"})
    assert S.min_long_score(db) == 5
    assert S.max_short_score(db) == 2
    assert S.decide(5, "LONG", min_long=5)[0] is True
    assert S.decide(2, "SHORT", max_short=2)[0] is True


def test_손상된_설정값은_기본값():
    for bad in ("abc", "-1", "99", ""):
        db = _DB({S.SETTING_ENABLED: "1", S.SETTING_MIN_LONG: bad})
        assert S.min_long_score(db) == S.MIN_LONG_DEFAULT, bad


# ═════════════════════════════════════════════════════════════════════
# 지지선 찾기
# ═════════════════════════════════════════════════════════════════════

def test_피벗_저점을_찾는다():
    """좌우 3봉보다 낮은 저점."""
    lows = [10.0] * 40
    lows[20] = 8.0                      # 뚜렷한 피벗 저점
    sup, idx = S.find_swing_low(lows)
    assert sup == 8.0 and idx == 20


def test_최근_4봉은_피벗으로_쓰지_않는다():
    """오른쪽 3봉이 없으면 피벗이 확정되지 않는다 (미래참조 방지)."""
    lows = [10.0] * 40
    lows[38] = 8.0                      # 끝에서 2번째 = 확정 불가
    sup, _idx = S.find_swing_low(lows)
    assert sup != 8.0, "확정되지 않은 저점을 지지선으로 썼다"


def test_가장_최근_피벗을_고른다():
    lows = [10.0] * 60
    lows[15] = 7.0
    lows[40] = 8.0                      # 더 최근 (더 높아도 이쪽)
    sup, idx = S.find_swing_low(lows)
    assert idx == 40 and sup == 8.0


def test_봉이_적으면_지지선_없음():
    assert S.find_swing_low([10.0] * 5) == (None, None)


# ═════════════════════════════════════════════════════════════════════
# 접촉 감지
# ═════════════════════════════════════════════════════════════════════

def test_직전봉이_이미_아래면_접촉이_아니다():
    """이탈은 접촉이 아니다 — 판정식 표본 밖이다."""
    closes = [9.0] * 30                 # 이미 지지선(10) 아래에 있음
    lows = [8.9] * 30
    highs = [9.1] * 30
    ok, why, _d = S.is_touching(highs, lows, closes, 10.0)
    assert ok is False and "이탈" in why


def test_고점권이면_접촉으로_보지_않는다():
    """최근 24봉 고점 대비 -1% 도 안 내려왔으면 잡티다.

    직전 봉이 지지선 위여야(=이탈이 아니어야) 이 조건까지 온다.
    """
    closes = [10.05] * 29 + [10.02]     # 직전 봉이 지지선 위
    lows = [10.0] * 29 + [9.995]        # 이번 봉이 지지선(9.99)에 닿음
    highs = [10.06] * 30                # 고점 대비 낙폭이 -1% 미만
    ok, why, _d = S.is_touching(highs, lows, closes, 9.99)
    assert ok is False and "고점권" in why, why


def test_제대로_접촉하면_True():
    """급락 후 지지선에 막 닿은 정상 사례."""
    closes = [12.0] * 20 + [11.5, 11.2, 11.0, 10.7, 10.5,
                            10.3, 10.2, 10.1, 10.05, 10.02]
    lows = closes[:-1] + [9.98]         # 마지막 봉이 지지선 10 을 살짝 뚫음
    highs = [c * 1.002 for c in closes]
    ok, why, d = S.is_touching(highs, lows, closes, 10.0)
    assert ok is True, f"{why} {d}"


# ═════════════════════════════════════════════════════════════════════
# evaluate — fail 방향과 적용 범위
# ═════════════════════════════════════════════════════════════════════

def test_게이트가_꺼져있으면_통과():
    ok, why, _d = S.evaluate(_DB({}), _BC([], []), "XUSDT", "LONG")
    assert ok is True and why == ""


def test_시세_조회_실패면_통과():
    """🚨 fail-open — 필터가 매매를 멈추게 하면 안 된다."""
    class _Bad:
        def get_klines(self, **_kw):
            raise RuntimeError("API 500")
    ok, why, _d = S.evaluate(_DB(ON), _Bad(), "XUSDT", "LONG")
    assert ok is True and "fail-open" in why


def test_1H가_없으면_판정하지_않는다():
    """1H 규칙 3개가 점수의 핵심이다. 없으면 채점 자체를 하면 안 된다."""
    score, d = S.compute_score(_kl([100.0] * 150), _kl([100.0] * 10))
    assert score is None and "1h" in d["reason"]


def test_지지선_접촉이_아니면_막지_않는다():
    """🚨 판정식은 접촉 264건으로 만들어졌다. 다른 자리는 표본 밖이다."""
    flat = [100.0] * 200
    ok, why, _d = S.evaluate(_DB(ON), _BC(_kl(flat), _kl([100.0] * 120)),
                             "XUSDT", "LONG")
    assert ok is True, f"접촉도 아닌데 막았다: {why}"


# ═════════════════════════════════════════════════════════════════════
# 🚨 실제로 호출되는가 (Fix 247/318 의 교훈)
# ═════════════════════════════════════════════════════════════════════

def _fn_src(mod, name):
    src = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.get_source_segment(src, n) or ""
    raise AssertionError(f"{name} 없음")


def test_start_stage1이_실제로_부른다():
    """🚨 계산만 하고 진입에 안 쓰이면 무의미하다 (Fix 247 = 효과크기 -2.06 짜리
    신호가 화면·학습에만 쓰이고 진입엔 한 번도 안 불렸다)."""
    from app.services import execution_service as E
    src = _fn_src(E, "start_stage1")
    assert "support_score" in src, "start_stage1 이 지지선 판정을 부르지 않는다"
    assert "_sup_eval(" in src
    assert "raise ValueError" in src, "차단이 실제로 진입을 막아야 한다"


def test_단계_진입에는_걸지_않는다():
    """🚨 이미 자금이 들어간 사다리를 새 판정으로 끊으면 그 자리에서 멈춘다
    (Fix 203/235 전력)."""
    from app.services import execution_service as E
    for name in ("trigger_next_stage", "enter_stage_at_market"):
        src = _fn_src(E, name)
        assert "support_score" not in src, f"{name} 에 걸렸다 — 사다리가 멈춘다"


def test_판정_함수가_하나뿐이다():
    """두 곳에서 각자 채점하면 한쪽만 고쳐지는 사고가 난다."""
    src = Path(S.__file__).read_text(encoding="utf-8")
    assert src.count("def compute_score") == 1
    assert src.count("def decide") == 1
    assert src.count("def evaluate") == 1


def test_실측_근거가_주석에_남아_있다():
    """다음에 무심코 임계값을 바꾸지 않도록."""
    src = Path(S.__file__).read_text(encoding="utf-8")
    for token in ("70.6", "63.9", "55.0", "264", "-0.380"):
        assert token in src, token

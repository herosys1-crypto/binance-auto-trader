"""🎯 Fix 336 — bb_mid_line 「중단 저항」에 4H 참고 + 적응 TP 배선 확대.

## 실측 (2026-09-03)

- bb_mid_line 오늘 **29건 전부 SHORT, 합계 -29.12**
- PYTHUSDT: 4H RSI 68/69/64 · MACD hist 양수 확대 · OBV 상승 = **명확한 상승**인데
  15분 중단선 터치 하나만 보고 SHORT → 상승 추세에서 중단선은 저항이 아니라 지지다
- 파일 헤더 스스로: "4H 확인을 진입 조건으로 거는 것은 「중단 하락돌파」 하나뿐"
- 적응 TP(Fix 299) 호출처가 auto_bb_breakdown_worker **단 1개** →
  bb_mid_line / pump_split 은 TP1 15% 고정 (607건 중 ROI +15% 도달 3건 = 0.5%)

## 이 테스트가 지키는 것

1. 4H 가 LONG 편으로 **확대 중**이면 mid_resist SHORT 를 보류한다 (설정으로 끌 수 있다)
2. 패턴 자체는 **끄지 않는다** (+785.11, 양쪽 절반 양수)
3. 두 워커가 적응 TP 를 **실제로 호출**한다 (Fix 247/318 의 교훈)
4. 판정 함수는 trend_4h_gate 의 것을 **재사용**한다 (중복 정의 금지)
"""
import ast
from pathlib import Path

from app.services import trend_4h_gate as G


def _kl(closes):
    return [[i * 14400000, str(c), str(c * 1.01), str(c * 0.99), str(c), "1000"]
            for i, c in enumerate(closes)]


class _BC:
    def __init__(self, closes):
        self._c = closes

    def get_klines(self, *, symbol, interval, limit=60, **_kw):
        return _kl(self._c)


def _fn_src(mod_path: Path, name: str) -> str:
    src = mod_path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.get_source_segment(src, n) or ""
    raise AssertionError(f"{name} 없음")


# ═════════════════════════════════════════════════════════════════════
# 4H 참고 판정 — check_hist_rising 의 의미가 우리가 쓰는 것과 같은가
# ═════════════════════════════════════════════════════════════════════

def test_4H_급등_시작이면_LONG_편_확대로_잡힌다():
    """평탄 후 급등 → hist 가 LONG 편으로 커지는 중 → mid_resist SHORT 보류 대상.

    🚨 실측으로 고친 테스트 (2026-09-03). 처음엔 `1.004**i` 정률 상승을 썼는데
       **rising=False(delta -0.0016)** 였다 — 정률 상승은 MACD 가 수렴해 「확대 중」이
       아니다. 실제 4H 모양별 측정:
           정률가속 1.004^i     False  delta -0.001646
           강가속 1.02^i        True   delta +0.037979
           평탄후 급등(14봉)     True   delta +0.000313
           평탄후 급등(6봉)      True   delta +0.159742   ← PYTHUSDT 형
           선형상승             False  delta -0.002442
       이 게이트가 잡으려는 것은 「막 힘이 붙는 상승」이고, 그것이 위 True 들이다.
    """
    surge = [100.0] * 54 + [100.0 + (i + 1) * 1.5 for i in range(6)]
    rising, d = G.check_hist_rising(_BC(surge), "XUSDT", "LONG", "4h")
    assert rising is True, d


def test_4H_정률상승은_확대_아님_이라_막지_않는다():
    """🚨 반증 기록: 완만한 정률 상승은 hist 가 수렴한다 → SHORT 를 막지 않는다.
    (이걸 막으면 mid_resist 가 상승장에서 통째로 죽는다 — +785.11 근거 훼손)"""
    steady = [100.0 * (1.004 ** i) for i in range(60)]
    rising, _d = G.check_hist_rising(_BC(steady), "XUSDT", "LONG", "4h")
    assert rising is False


def test_4H_하락시작이면_LONG_편_확대_아님():
    """막 하락이 시작된 4H → SHORT 를 막을 이유가 없다."""
    fresh_fall = [100.0] * 46 + [100.0 - (i + 1) * 0.5 for i in range(14)]
    rising, _d = G.check_hist_rising(_BC(fresh_fall), "XUSDT", "LONG", "4h")
    assert rising is False


def test_4H_데이터_부족이면_None_이라_막지_않는다():
    """판정 불가 = 통과 (좋은 자리를 고르는 필터이지 안전장치가 아니다)."""
    rising, d = G.check_hist_rising(_BC([100.0] * 10), "XUSDT", "LONG", "4h")
    assert rising is None and d.get("reason")


# ═════════════════════════════════════════════════════════════════════
# 🚨 워커가 실제로 배선했는가
# ═════════════════════════════════════════════════════════════════════

def _bb_mid_src() -> str:
    from app.workers import bb_mid_line_worker as W
    return Path(W.__file__).read_text(encoding="utf-8")


def _pump_split_src() -> str:
    from app.workers import pump_split_entry_worker as W
    return Path(W.__file__).read_text(encoding="utf-8")


def test_mid_resist_4H_참고가_생성_직전에_있다():
    src = _bb_mid_src()
    assert 'pat == "mid_resist" and side == "SHORT" and _resist_4h_ref' in src
    assert 'check_hist_rising(bc, sym, "LONG", "4h")' in src
    assert '_blk("resist_4h_uptrend")' in src
    # 판정 → continue 가 create_surge_position **앞**에 있어야 한다
    i_ref = src.index('_blk("resist_4h_uptrend")')
    i_create = src.index("st = create_surge_position(")
    assert i_ref < i_create, "4H 참고가 생성 뒤에 있어 의미가 없다"


def test_mid_resist_4H_참고를_설정으로_끌_수_있다():
    src = _bb_mid_src()
    assert '_setting(db, "bb_mid_resist_4h_ref_enabled", True)' in src, "기본 ON + 설정키"


def test_mid_resist_패턴_자체는_끄지_않는다():
    """🚨 +785.11 근거가 있다. 기본 ON 이 바뀌면 안 된다."""
    from app.services import bb_mid_line as M
    assert M.PATTERN_DEFAULT_ON["mid_resist"] is True


def test_bb_mid_line_이_적응TP를_실제로_부른다():
    src = _bb_mid_src()
    assert "from app.services.adaptive_tp import" in src
    assert "pick_tp1 as _atp_pick" in src and "tp_ladder_from_tp1 as _atp_ladder" in src
    assert "tp_percents=_tp_percents" in src, "적응 사다리가 create 에 안 넘어간다"
    assert "tp_percents=TP_PERCENTS" not in src, "고정 TP 가 그대로 남아 있다"


def test_bb_mid_line_적응TP는_추가_API_호출_없이_티커를_재사용한다():
    """🚨 IP ban 이력(8/26). 심볼마다 티커를 또 부르면 안 된다."""
    src = _bb_mid_src()
    assert "_chg24_map[str(_t.get(\"symbol\") or \"\")]" in src
    assert "_atp_pick(db, _chg24_map.get(sym))" in src


def test_pump_split_이_적응TP를_실제로_부른다():
    src = _pump_split_src()
    assert "from app.services.adaptive_tp import" in src
    assert "_atp_pick(db, chg)" in src, "루프가 이미 가진 chg 를 써야 한다"
    assert "strategy.tp1_pct_override = _tp1_pick" in src
    assert "strategy.tp1_pct_override = Decimal(str(TP_PERCENTS[0]))" not in src


def test_적응TP_실패시_기존_TP를_유지한다():
    """fail-open: 적응 TP 오류가 진입 자체를 막으면 안 된다."""
    for src in (_bb_mid_src(), _pump_split_src()):
        assert "[Fix299] 적응 TP 오류" in src


def test_4H_판정을_중복_정의하지_않는다():
    """🚨 trend_4h_gate 의 check_hist_rising 을 재사용해야 한다."""
    src = _bb_mid_src()
    assert "def check_hist_rising" not in src
    assert "def _macd_hist" not in src
    assert "from app.services.trend_4h_gate import check_hist_rising" in src


def test_실측_근거가_주석에_남아_있다():
    src = _bb_mid_src()
    for token in ("-29.12", "+785.11", "PYTHUSDT", "0.5%"):
        assert token in src, token

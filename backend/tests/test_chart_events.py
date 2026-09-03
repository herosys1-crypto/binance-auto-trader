"""📊 차트 국면 판정식 테스트 (Fix 331).

사장님 2026-09-03:
  "지금까지 학습을 통해서 **최고점의 차트와 보조지표로 알수 있잖아**
   첫진입은 그렇게 하고 그것이 실패하면 10usdt 남기고 부분손절하고
   차트와 보조지표가 다시 최고점에서 하락으로 보이는 지표 15분과 4시간일때
   2단계 진입하는 거잖아. **최저점도 같은 전략**이고"
  "**15분이 기준이고 4시간을 참고**하고 ... 4시간 차트의 의미는
   **중단기 지속적인 흐름을 판단하는 정도** 차트"

## 이 파일이 지키는 것

1. **4H 가 거부권이 되지 않는가** — 사장님이 명시적으로 정정한 사안이고,
   현행 `trend_4h_gate.py` 가 실제로 그 오해로 1,546건을 막았다.
   모든 판정 함수에 **4H 없이 통과하는 15분 단독 경로**가 있어야 한다.
2. **무너진 규칙이 다시 들어오지 않았는가** — 12+9+7+3 개 중 대부분이
   반증됐다. 「좋아 보이는데 왜 없지?」로 되살아나는 것을 막는다.
3. **학습 근거 숫자가 주석에 남아 있는가** — 다음 사람이 무심코 임계값을
   바꾸지 못하게. 이 저장소 관행이다.
4. **fail-open 하는가** — 데이터가 없다고 매매를 막으면 안 된다.
   이건 좋은 자리를 고르는 필터이지 안전장치가 아니다.
5. **설정으로 임계값이 바뀌는가** — 하드코딩을 사장님이 바꾸고 싶어 할 때
   값을 바꾸지 말고 설정으로 빼라(2026-09-03 교훈).
"""
from pathlib import Path

import pytest

from app.services import chart_events as C


# ─────────────────────────────────────────────────────────────────────
# 스텁 / 캔들 생성기
# ─────────────────────────────────────────────────────────────────────

class _DB:
    """SystemSetting 스텁 (support_score 테스트와 같은 형태)."""

    def __init__(self, settings):
        self._s = settings

    def get(self, model, key):
        if getattr(model, "__name__", "") == "SystemSetting":
            if key not in self._s:
                return None
            return type("R", (), {"value": self._s[key]})()
        return None


def _k(i, o, h, l, c, v=1000.0):
    """[open_time, open, high, low, close, volume] — 학습 데이터와 같은 6필드."""
    return [i * 900_000, f"{o}", f"{h}", f"{l}", f"{c}", f"{v}"]


def mk_top15(*, run24_small=True, n=70):
    """정점 반전 후보 15m 캔들.

    구조: 완만한 상승 → 고점권 횡보 → 쌍고점(119.5 / 120.0) → 음봉 꺾임.
    마지막 봉은 **진행 중 봉**(모듈이 잘라낸다).
    """
    kl = []
    for i in range(39):                      # 0..38  100 → 116 완만 상승
        base = 100 + i * 16 / 38
        kl.append(_k(i, base, base + 0.4, base - 0.4, base + 0.1))
    hover_low = 117.0 if run24_small else 100.0
    for i in range(39, 60):                  # 39..59 고점권 횡보
        kl.append(_k(i, 117.6, 118.2, hover_low, 117.8))
    kl.append(_k(60, 118.0, 119.5, 117.5, 118.2))          # 60 첫 고점(피벗)
    for i in range(61, 67):                  # 61..66 눌림
        kl.append(_k(i, 117.9, 118.3, 117.4, 118.0))
    kl.append(_k(67, 118.0, 120.0, 117.8, 119.0))          # 67 신고가(정점)
    kl.append(_k(68, 118.5, 118.6, 114.5, 115.0))          # 68 음봉 꺾임 ← 판정봉
    kl.append(_k(69, 115.0, 115.2, 114.0, 114.2))          # 69 진행 중 봉
    assert len(kl) == n
    return kl


def mk_4h(direction, n=80):
    """4H 캔들. direction: "up"(hist>0 상승중) / "down"(hist<=0) / "flat"."""
    closes = []
    for i in range(40):
        closes.append(100.0)
    for i in range(1, n - 40 + 1):
        if direction == "up":
            closes.append(100.0 + 0.05 * i * i)
        elif direction == "down":
            closes.append(100.0 - 0.05 * i * i)
        else:
            closes.append(100.0)
    kl = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        kl.append(_k(i, o, max(o, c) + 0.2, min(o, c) - 0.2, c))
        prev = c
    return kl


def mk_bottom15(n=60):
    """저점 반전 후보 15m 캔들 — 하락 후 마지막 봉이 최저 + 양봉(작은 몸통)."""
    kl = []
    for i in range(n - 1):
        base = 110.0 - i * 0.2
        kl.append(_k(i, base, base + 0.5, base - 0.5, base - 0.1))
    last = 110.0 - (n - 2) * 0.2
    # 최저 저가 + 양봉 + 작은 몸통(아래꼬리 긴 형태)
    kl.append(_k(n - 1, last - 0.6, last - 0.1, last - 1.6, last - 0.5))
    kl.append(_k(n, last - 0.5, last - 0.3, last - 0.7, last - 0.4))   # 진행 중 봉
    return kl


def mk_pullback15(*, depth_deep=True, big_leg=True, n=121):
    """조정 진입 후보 15m 캔들 — 100봉 상승 leg → 20봉 조정."""
    kl = []
    start, peak = (90.0, 130.0) if big_leg else (128.0, 130.0)
    for i in range(100):                     # 0..99 상승 (99 가 러닝 하이)
        base = start + (peak - start) * i / 99
        kl.append(_k(i, base - 0.2, base + 0.1, base - 0.4, base))
    end = 120.0 if depth_deep else 129.4     # depth 7.7% vs 0.46%
    for i in range(100, 120):                # 100..119 조정 (20봉 < 24봉)
        base = peak - (peak - end) * (i - 99) / 20
        kl.append(_k(i, base + 0.2, base + 0.3, base - 0.3, base, 3000.0))
    kl.append(_k(120, end, end + 0.1, end - 0.1, end))     # 진행 중 봉
    assert len(kl) == n
    return kl


SRC = Path(C.__file__).read_text(encoding="utf-8")


# ═════════════════════════════════════════════════════════════════════
# 1. 지표
# ═════════════════════════════════════════════════════════════════════

def test_rsi_bounds_and_direction():
    up = [100 + i for i in range(60)]
    down = [100 - i * 0.5 for i in range(60)]
    assert C._rsi(up, 12) > 90
    assert C._rsi(down, 12) < 10
    assert C._rsi([100.0] * 5, 12) is None      # 데이터 부족 → None


def test_macd_hist_requires_40_bars():
    assert C._macd_hist([100.0] * 39) is None
    assert C._macd_hist([100.0 + i for i in range(60)]) is not None


def test_obv_slope_is_volume_normalized():
    """🚨 원시 OBV 를 쓰면 폭주한다 (과거 최대 2,249,160 사고)."""
    closes = [100 + i for i in range(40)]
    small = C._obv_slope_norm(closes, [1.0] * 40, 20)
    huge = C._obv_slope_norm(closes, [1_000_000.0] * 40, 20)
    assert small == pytest.approx(1.0)
    assert huge == pytest.approx(1.0)          # 거래량 규모가 달라도 같은 값
    assert -1.5 <= small <= 1.5


def test_bb_width_rank_is_self_percentile():
    """🚨 밴드폭은 절대값이 아니라 자기 순위."""
    calm = [100.0 + (i % 2) * 0.1 for i in range(120)] + [100.0 + (i % 2) * 5 for i in range(40)]
    r = C._bb_width_rank(calm)
    assert r is not None and 0.0 <= r <= 1.0


def test_trim_open_bar_drops_last():
    kl = [_k(i, 1, 1, 1, 1) for i in range(10)]
    assert len(C.trim_open_bar(kl)) == 9
    assert C.trim_open_bar(None) is None


# ═════════════════════════════════════════════════════════════════════
# 2. ① 정점 반전 (SHORT 1단계)
# ═════════════════════════════════════════════════════════════════════

def test_top_reversal_detects_candidate():
    ok, score, d = C.is_top_reversal(mk_top15(), mk_4h("flat"))
    assert d["decided"] is True, d
    assert d["peak_idx"] == 67
    assert d["peak_high"] == pytest.approx(120.0)
    assert d["rules"]["m15_run24_le_3pct"] is True
    assert d["run24_peak"] < 0.03
    assert 0.0 <= score <= 1.0


def test_top_reversal_rejects_when_still_making_new_high():
    """꺾임이 없으면 후보가 아니다 (TURN_BASE 필수)."""
    kl = mk_top15()
    kl[68] = _k(68, 119.0, 121.0, 118.5, 120.5)     # 여전히 신고가 + 양봉
    ok, score, d = C.is_top_reversal(kl, mk_4h("flat"))
    assert ok is False
    assert d["decided"] is False                     # 🚨 차단이 아니라 「판정 안 함」


def test_top_reversal_run24_rule_flips_with_price_history():
    """직전 6시간 상승폭이 크면 「조용히 다지던 고점」이 아니다."""
    _, _, d = C.is_top_reversal(mk_top15(run24_small=False), mk_4h("flat"))
    assert d["rules"]["m15_run24_le_3pct"] is False
    assert d["run24_peak"] > 0.03


def test_top_reversal_has_15m_only_path():
    """🚨 4H 가 거부권이 아니다 — 4H 캔들 없이도 판정·통과가 가능해야 한다."""
    ok, _, d = C.is_top_reversal(mk_top15(), None, kl_1h=None,
                                 cfg=C.Thresholds(toprev_min_points=1))
    assert d["decided"] is True
    assert ok is True
    assert "h4_hist_rising" not in d["rules"]
    assert "4h 봉 부족" in d["h4"]


def test_top_reversal_touch_rule_uses_1h():
    """사장님 「지지 여러번 반복 후 하락 시작」 (TOPREV_S1_TOUCH_1H)."""
    _, _, d = C.is_top_reversal(mk_top15(), mk_4h("flat"), kl_1h=mk_4h("down"))
    assert d["peak_touch"] >= 2
    assert "m15_touch_and_h1_not_rising" in d["rules"]


def test_top_reversal_threshold_is_configurable():
    kl15, kl4 = mk_top15(), mk_4h("flat")
    strict = C.is_top_reversal(kl15, kl4, cfg=C.Thresholds(toprev_min_points=4))
    loose = C.is_top_reversal(kl15, kl4, cfg=C.Thresholds(toprev_min_points=0))
    assert strict[0] is False
    assert loose[0] is True


def test_top_reversal_obv_threshold_default_is_minus_015():
    """🚨 -0.30 (STRICT_OBV) 은 시간축에서 뒤집혔다 — 기본값을 조이지 마라."""
    assert C.Thresholds().toprev_obv_slope_max == -0.15


# ═════════════════════════════════════════════════════════════════════
# 3. ①-2 정점 2단계 재진입
# ═════════════════════════════════════════════════════════════════════

def test_restage_top_requires_higher_peak():
    """사장님 「다시 최고점에서 하락으로 보이는 지표」."""
    ok, _, d = C.is_restage_top(mk_top15(), mk_4h("up"), {"peak": 999.0})
    assert ok is False
    assert d["decided"] is True
    assert "이전 정점보다 높지 않음" in d["reason"]

    ok2, _, d2 = C.is_restage_top(mk_top15(), mk_4h("up"), {"peak": 110.0})
    assert d2.get("higher_peak") is True
    assert ok2 is True                       # 게이트 + 고점터치 = 2점


def test_restage_top_veto_blocks_when_4h_hist_not_positive():
    """TOPREV_S2_VETO — n=69 승률 37.7%. 30배 자본(300 USDT) 증액 금지."""
    ok, _, d = C.is_restage_top(mk_top15(), mk_4h("down"), {"peak": 110.0})
    assert ok is False
    assert d["veto"] is True
    assert "TOPREV_S2_VETO" in d["reason"]


def test_restage_top_veto_can_be_disabled_by_setting():
    cfg = C.Thresholds(restage_top_veto=False, restage_top_min_points=1)
    ok, _, d = C.is_restage_top(mk_top15(), mk_4h("down"), {"peak": 110.0}, cfg=cfg)
    assert d.get("veto") is not True
    assert d["decided"] is True


def test_restage_top_tp_hint_is_3pct():
    """⚠️ 5% 목표로 재면 63.3% → 45% 로 떨어진다."""
    _, _, d = C.is_restage_top(mk_top15(), mk_4h("up"), {"peak": 110.0})
    assert d["tp_hint_pct"] == 3.0


# ═════════════════════════════════════════════════════════════════════
# 4. ② 저점 반전 (LONG 1단계)
# ═════════════════════════════════════════════════════════════════════

def test_bottom_reversal_detects_candidate():
    ok, score, d = C.is_bottom_reversal(mk_bottom15(), mk_4h("down"))
    assert d["decided"] is True, d
    assert d["rules"]["m15_smallbody"] is True
    assert 0.0 <= score <= 1.0


def test_bottom_reversal_rejects_red_candle():
    kl = mk_bottom15()
    kl[-2] = _k(len(kl) - 2, 100.0, 100.2, 98.0, 98.5)      # 음봉
    _, _, d = C.is_bottom_reversal(kl, mk_4h("down"))
    assert d["decided"] is False
    assert "양봉이 아님" in d["reason"]


def test_bottom_reversal_does_not_use_4h_as_gate():
    """🚨 4H 조건은 LONG 저점에서 해롭다 (심볼+블록 FE -0.052). 기록만 한다."""
    up = C.is_bottom_reversal(mk_bottom15(), mk_4h("up"))
    down = C.is_bottom_reversal(mk_bottom15(), mk_4h("down"))
    assert up[0] == down[0]
    assert up[2]["points"] == down[2]["points"]
    assert not any(k.startswith("h4") for k in up[2]["rules"])
    assert "4H 는 LONG 저점 판정에 쓰지 않는다" in up[2]["h4_note"]
    # 4H 캔들이 아예 없어도 동일하게 판정한다
    none4 = C.is_bottom_reversal(mk_bottom15(), None)
    assert none4[2]["points"] == up[2]["points"]


def test_bottom_reversal_thresholds_are_configurable():
    kl = mk_bottom15()
    wide = C.is_bottom_reversal(kl, None, cfg=C.Thresholds(
        bottom_pctb_max=1.0, bottom_atr_pct_lo=0.0, bottom_atr_pct_hi=1.0,
        bottom_body_ratio_max=1.0, bottom_min_points=4))
    narrow = C.is_bottom_reversal(kl, None, cfg=C.Thresholds(
        bottom_pctb_max=0.0, bottom_atr_pct_lo=0.9, bottom_atr_pct_hi=1.0,
        bottom_body_ratio_max=0.0, bottom_min_points=2))
    assert wide[0] is True
    assert narrow[0] is False


def test_bottom_reversal_has_no_chg48_rule():
    """🚨 `chg48_pit > -8%` 는 종목 선택 편향이었다 (FE +0.119 → -0.029)."""
    rules = C.is_bottom_reversal(mk_bottom15(), None)[2]["rules"]
    assert not any("chg48" in k or "dump" in k for k in rules)


def test_market_breadth_is_weight_not_veto():
    """R6 — breadth <= 0.40 이면 LONG 우호. 결손이면 판정 안 함 + 배수 1.0."""
    low = C.is_bottom_reversal(mk_bottom15(), None, market_breadth=0.30)
    high = C.is_bottom_reversal(mk_bottom15(), None, market_breadth=0.80)
    missing = C.is_bottom_reversal(mk_bottom15(), None, market_breadth=None)
    assert low[2]["capital_mult"] == pytest.approx(1.10)
    assert high[2]["capital_mult"] == pytest.approx(1.0)
    assert missing[2]["capital_mult"] == pytest.approx(1.0)
    assert missing[2]["breadth_detail"]["decided"] is False
    # 배수만 다르고 통과 여부는 같다 = 거부권이 아니다
    assert low[0] == high[0] == missing[0]
    assert low[2]["points"] == high[2]["points"]


def test_market_breadth_context_rejects_bad_input():
    for bad in (None, "abc", 1.5, -0.1):
        bias, mult, d = C.market_breadth_context(bad)
        assert d["decided"] is False
        assert mult == 1.0


# ═════════════════════════════════════════════════════════════════════
# 5. ②-2 저점 2단계 재진입
# ═════════════════════════════════════════════════════════════════════

def test_restage_bottom_requires_min_drop():
    """BOTTOM_L2_MIN_DROP — 간발의 신저점(0~2.7%)은 승률 47.4% 로 최악."""
    kl = mk_bottom15()
    new_low = float(kl[-2][3])
    near = C.is_restage_bottom(kl, None, {"low": new_low * 1.005})   # 0.5% 하락
    far = C.is_restage_bottom(kl, None, {"low": new_low * 1.05})     # 5% 하락
    assert near[0] is False
    assert "BOTTOM_L2_MIN_DROP" in near[2]["reason"]
    assert far[2]["min_drop"] > 0.027
    assert far[2]["decided"] is True


def test_restage_bottom_uses_same_score_as_stage1():
    """🚨 2단계 전용 규칙은 전부 탐색 잡음이었다(순열 p=1.000) → 같은 점수."""
    kl = mk_bottom15()
    new_low = float(kl[-2][3])
    s1 = C.is_bottom_reversal(kl, None)
    s2 = C.is_restage_bottom(kl, None, {"low": new_low * 1.05})
    assert s1[2]["rules"] == s2[2]["rules"]


def test_restage_bottom_has_no_touch_veto():
    """🚨 BOTTOM_L2_TOUCH_VETO 는 넣지 않았다 (사장님 사상을 뒤집을 근거 없음)."""
    kl = mk_bottom15()
    new_low = float(kl[-2][3])
    d = C.is_restage_bottom(kl, None, {"low": new_low * 1.05})[2]
    assert "low_touch_40" in d               # 기록은 한다
    assert not any("touch" in k for k in d["rules"])   # 판정에는 안 쓴다


# ═════════════════════════════════════════════════════════════════════
# 6. ③④ 상승 중 조정 (사장님 주력 LONG)
# ═════════════════════════════════════════════════════════════════════

def test_pullback_detects_deep_pullback():
    ok, score, d = C.is_pullback_entry(mk_pullback15(), mk_4h("up"))
    assert d["decided"] is True, d
    assert d["peak_idx"] == 99
    assert d["depth"] > 0.05
    assert d["leg"] > 0.05
    assert d["rules"]["m15_depth_ge_deep"] is True


def test_pullback_rejects_shallow_depth():
    """🚨 깊이 2%대는 무작위 진입보다 나쁘다. 기본 하한 3%."""
    _, _, d = C.is_pullback_entry(mk_pullback15(depth_deep=False), mk_4h("up"))
    assert d["decided"] is False
    assert "조정 깊이" in d["reason"]
    assert C.Thresholds().pb_min_depth == 0.03


def test_pullback_rejects_small_leg():
    _, _, d = C.is_pullback_entry(mk_pullback15(big_leg=False), mk_4h("up"))
    assert d["decided"] is False
    assert "leg" in d["reason"]


def test_pullback_entry_style_is_market_on_closed_bar():
    """🚨🚨 지정가 사다리로 만들면 +0.2~0.4% → -0.6~-1.0% 로 뒤집힌다."""
    _, _, d = C.is_pullback_entry(mk_pullback15(), mk_4h("up"))
    assert d["entry_style"] == "market_on_closed_bar"


def test_pullback_has_15m_only_path():
    """🚨 PB_S3_OBVNEG_RSI24 = 4H 없이 3점. 4H 는 거부권이 아니다."""
    ok, _, d = C.is_pullback_entry(mk_pullback15(), None)
    assert d["decided"] is True
    assert not any(k.startswith("h4") for k in d["rules"])
    assert "4h 봉 부족" in d["h4"]
    # 4H 를 붙여도 점수만 늘고 판정 자체가 막히지 않는다
    with4 = C.is_pullback_entry(mk_pullback15(), mk_4h("up"))
    assert with4[2]["points"] >= d["points"]


def test_pullback_thresholds_are_configurable():
    kl = mk_pullback15()
    loose = C.is_pullback_entry(kl, None, cfg=C.Thresholds(pb_min_points=1))
    strict = C.is_pullback_entry(kl, None, cfg=C.Thresholds(pb_min_points=7))
    assert loose[0] is True
    assert strict[0] is False


def test_pullback_has_no_capital_040_weight():
    """🚨 학습자의 `capital *= 0.4` 는 넣지 않았다 (h4_ctx_score 가 비단조)."""
    _, _, d = C.is_pullback_entry(mk_pullback15(), mk_4h("up"))
    assert d["capital_mult"] in (1.0, 1.10)


# ═════════════════════════════════════════════════════════════════════
# 7. ⑦ 지속 상승/하락 — 결론 못 냄
# ═════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("side", ["LONG", "SHORT"])
def test_continuation_never_approves(side):
    """🚨 9개 중 8개가 무작위 라벨 귀무분포에서 재현됐다. 유일한 생존자는
    약세 다이버전스(사장님 사상의 반대) + 15분 지연으로 60% 증발."""
    ok, score, d = C.is_continuation(mk_pullback15(), mk_4h("up"), side)
    assert ok is False
    assert score == 0.0
    assert d["decided"] is False
    assert d["verdict"] == "결론 못 냄"
    assert d["observations"] is not None      # 관측은 남긴다


def test_continuation_observations_are_descriptive_only():
    _, _, d = C.is_continuation(mk_pullback15(), mk_4h("up"), "LONG")
    obs = d["observations"]
    for key in ("consec_same_dir", "m15_obv_slope20", "vol_ratio",
                "bb_width_rank", "atr_pct"):
        assert key in obs
    assert "rules" not in d                   # 채점하지 않는다


def test_continuation_does_not_include_bw_obv_diverge():
    """유일한 통계 생존자를 코드에 넣지 않았다 — 사상 정면 충돌 + 실행 불가."""
    assert "L_BW_OBV_DIVERGE" in SRC          # 사유는 남아 있어야 한다
    assert 'rules["l_bw_obv_diverge"]' not in SRC


# ═════════════════════════════════════════════════════════════════════
# 8. ⑦ 4H 「참고」 맥락
# ═════════════════════════════════════════════════════════════════════

def test_trend_4h_context_never_vetoes():
    """🚨 사장님 정정: 15분이 기준, 4시간은 참고. 이 함수는 아무것도 막지 않는다."""
    for direction in ("up", "down", "flat"):
        bias, conf, d = C.trend_4h_context(mk_4h(direction))
        assert d["decided"] is True
        assert d["veto"] is False
        assert bias in ("up", "down", "range")
        assert 0.0 <= conf <= 1.0
        assert d["capital_mult"] >= 1.0       # 깎지 않는다


def test_trend_4h_short_strong_multiplier_is_conservative():
    """🚨 반증관 권고: 배수 1.309 가 아니라 부트스트랩 하한 기준 1.05~1.10."""
    assert C.Thresholds().trend4h_short_mult == 1.08
    assert C.Thresholds().trend4h_short_mult < 1.31


def test_trend_4h_context_fail_open_on_short_data():
    bias, conf, d = C.trend_4h_context(mk_4h("up", n=30))
    assert d["decided"] is False
    assert bias == "range"
    assert conf == 0.0


# ═════════════════════════════════════════════════════════════════════
# 9. fail-open
# ═════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("fn,args", [
    (C.is_top_reversal, (None, None)),
    (C.is_bottom_reversal, (None, None)),
    (C.is_pullback_entry, (None, None)),
    (C.is_restage_top, (None, None, {"peak": 1.0})),
    (C.is_restage_bottom, (None, None, {"low": 1.0})),
])
def test_fail_open_on_missing_data(fn, args):
    ok, score, d = fn(*args)
    assert ok is False
    assert score == 0.0
    assert d["decided"] is False              # 🚨 「차단」이 아니라 「판정 안 함」
    assert C.is_decided(d) is False


@pytest.mark.parametrize("fn", [C.is_top_reversal, C.is_bottom_reversal,
                                C.is_pullback_entry])
def test_fail_open_on_garbage_klines(fn):
    junk = [["x", "y", "z", "w", "q", "r"]] * 200
    ok, score, d = fn(junk, junk)
    assert ok is False
    assert d["decided"] is False


def test_fail_open_on_too_few_bars():
    short = [_k(i, 100, 101, 99, 100) for i in range(10)]
    for fn in (C.is_top_reversal, C.is_bottom_reversal, C.is_pullback_entry):
        assert fn(short, short)[2]["decided"] is False


# ═════════════════════════════════════════════════════════════════════
# 10. 설정
# ═════════════════════════════════════════════════════════════════════

def test_all_setting_keys_use_prefix():
    keys = [v for k, v in vars(C).items()
            if k.startswith(("S_", "SETTING_")) and isinstance(v, str)]
    assert len(keys) >= 20
    assert all(k.startswith("chart_events_") for k in keys), keys


def test_thresholds_load_from_db():
    db = _DB({
        C.S_TOPREV_MIN_POINTS: "4",
        C.S_BOTTOM_PCTB_MAX: "0.5",
        C.S_PB_MIN_DEPTH: "0.08",
        C.S_RESTAGE_TOP_VETO: "false",
        C.S_TREND4H_SHORT_MULT: "1.20",
    })
    cfg = C.Thresholds.load(db)
    assert cfg.toprev_min_points == 4
    assert cfg.bottom_pctb_max == 0.5
    assert cfg.pb_min_depth == 0.08
    assert cfg.restage_top_veto is False
    assert cfg.trend4h_short_mult == 1.20
    # 지정 안 한 키는 학습 기본값 유지
    assert cfg.toprev_obv_slope_max == -0.15


def test_thresholds_reject_out_of_range_and_garbage():
    db = _DB({
        C.S_TOPREV_MIN_POINTS: "99",          # 범위밖
        C.S_BOTTOM_PCTB_MAX: "abc",           # 파싱 실패
        C.S_PB_MIN_DEPTH: "-1",               # 범위밖
    })
    cfg = C.Thresholds.load(db)
    assert cfg.toprev_min_points == C.Thresholds().toprev_min_points
    assert cfg.bottom_pctb_max == C.Thresholds().bottom_pctb_max
    assert cfg.pb_min_depth == C.Thresholds().pb_min_depth


def test_thresholds_load_without_db_uses_defaults():
    assert C.Thresholds.load(None) == C.Thresholds()


def test_db_settings_reach_public_functions():
    """설정이 실제로 판정을 바꾸는가 (계산만 하고 안 쓰면 무의미 — Fix 247)."""
    kl15, kl4 = mk_top15(), mk_4h("flat")
    assert C.is_top_reversal(kl15, kl4, db=_DB({C.S_TOPREV_MIN_POINTS: "0"}))[0] is True
    assert C.is_top_reversal(kl15, kl4, db=_DB({C.S_TOPREV_MIN_POINTS: "4"}))[0] is False


def test_module_enabled_defaults_on():
    assert C.module_enabled(_DB({})) is True
    assert C.module_enabled(_DB({C.SETTING_ENABLED: "false"})) is False


# ═════════════════════════════════════════════════════════════════════
# 11. 🚨 학습 근거 숫자가 주석에 남아 있는가
#     (다음 사람이 무심코 임계값을 바꾸는 것을 막는다 — 이 저장소 관행)
# ═════════════════════════════════════════════════════════════════════

ADOPTED_EVIDENCE = [
    # ① 정점 반전
    ("TOPREV_S1_TURN_BASE", ["n=762", "54.33%"]),
    ("TOPREV_S1_4H_DIR", ["n=458", "57.9%"]),
    ("TOPREV_S1_4H_OBV", ["n=209", "67.0%"]),
    ("TOPREV_S1_STRICT_RUN", ["n=114", "74.6%"]),
    ("TOPREV_S1_TOUCH_1H", ["n=88", "70.5%"]),
    ("TOPREV_S2_VETO", ["n=69", "37.7%"]),
    ("TOPREV_S2_GATE_TOUCH", ["n=109", "63.3%"]),
    # ② 저점 반전
    ("BOTTOM_L1_STRICT", ["n=167", "68.9%"]),
    ("BOTTOM_L1_BB", ["n=169", "65.1%"]),
    ("BOTTOM_L1_CORE", ["n=230", "65.2%"]),
    ("BOTTOM_L2_MIN_DROP", ["n=430", "57.9%"]),
    # ③④ 조정
    ("PB_S3_PCTB_H4S2", ["n=39", "79.5%", "d=0.591"]),
    ("PB_S3_RSI24_H4S2", ["n=37", "78.4%"]),
    ("PB_S2_VOLSPIKE_H4S3", ["n=55", "74.6%"]),
    ("PB_S3_VOLSPIKE_H4S2", ["n=50", "72.0%"]),
    ("PB_S3_OBVNEG_H4S2", ["n=49", "71.4%"]),
    ("PB_S3_OBVNEG_RSI24", ["n=80", "63.8%"]),
    # ⑤⑥ 저항 / ⑧ 추세
    ("R6_long_breadth_low", ["n=2236", "59.8%"]),
    ("TREND_4H_SHORT_STRONG", ["n=93", "75.27%", "0.447"]),
]


@pytest.mark.parametrize("rule_id,numbers", ADOPTED_EVIDENCE)
def test_adopted_rule_keeps_its_measurements(rule_id, numbers):
    assert rule_id in SRC, f"채택 규칙 {rule_id} 의 출처 표기가 사라졌다"
    for num in numbers:
        assert num in SRC, f"{rule_id} 의 실측 근거 {num} 가 주석에서 사라졌다"


REFUTED_RULES = [
    # (규칙 id, 반증 근거로 반드시 남아야 할 문자열)
    ("TOPREV_S1_STRICT_OBV", "33.3%"),      # 시간 3분할에서 붕괴
    ("TOPREV_S2_GATE", "50.5"),             # 4H슬롯 CI 가 기준선을 배제 못함
    ("BOTTOM_NO_DUMP_48H", "-0.029"),       # 심볼FE 보정 후 소멸·역전
    ("BOTTOM_L2_CORE", "p=1.000"),          # 순열 귀무 중앙값보다 낮음
    ("BOTTOM_L2_TOUCH_VETO", "-0.053"),     # FE 보정 후 2/3 소멸
    ("TREND_4H_SHORT_SUSTAINED", "-3.1"),   # 15m 창 3등분 마지막 구간 음수
    ("TREND_4H_LONG_STRONG", "Simpson"),    # 심볼 혼합 효과
    ("L_BW_OBV_DIVERGE", "45.4%"),          # 1봉 지연으로 60% 증발
    ("L_PX_EXT", "p=1.000"),                # 아무 정보 없음
]


@pytest.mark.parametrize("rule_id,evidence", REFUTED_RULES)
def test_refuted_rule_documents_why_it_is_absent(rule_id, evidence):
    """🚨 「좋아 보이는데 왜 없지?」로 되살아나는 것을 막는다."""
    assert rule_id in SRC, f"무너진 규칙 {rule_id} 의 기각 사유가 사라졌다"
    assert evidence in SRC, f"{rule_id} 기각 근거 {evidence} 가 사라졌다"


def test_doctrine_correction_is_documented():
    """사장님 2026-09-03 정정 — 15분이 기준, 4시간은 참고."""
    assert "15분이 기준이고 4시간을 참고" in SRC
    assert "중단기 지속적인 흐름을 판단하는 정도" in SRC
    assert "거부권" in SRC


def test_sample_limitation_warning_is_documented():
    """🚨 97종목이지만 시장은 하나이고 15m 은 3.5~5일뿐이다."""
    assert "기준선 +5pp" in SRC
    assert "1,546건" in SRC                   # 현행 게이트가 만든 피해 규모


def test_public_functions_have_korean_docstrings():
    for name in ("is_top_reversal", "is_bottom_reversal", "is_restage_top",
                 "is_restage_bottom", "is_pullback_entry", "is_continuation",
                 "trend_4h_context"):
        doc = getattr(C, name).__doc__ or ""
        assert len(doc) > 200, f"{name} 의 근거 주석이 너무 짧다"
        assert "n=" in doc or "결론 못 냄" in doc, name


def test_module_starts_with_future_annotations():
    body = SRC.split('"""', 2)[2]
    assert body.lstrip().startswith("from __future__ import annotations")

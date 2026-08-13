"""📉 4H BB 자동 제안 스캐너 단위 테스트 (v143a).

사장님 지시: "자동전략 제안은 4시간봉이 볼밴 중단과 하단 깨는 경우로 해줘 롱과 숏을"
합성 상태 dict 만 사용 = 네트워크 X!
"""
from __future__ import annotations

from app.agents.strategy_suggestion_team.bb_4h_scanner import BB4HScanner as S


def _st(close, mid=100.0, lower=95.0, upper=105.0, cross=None, bars=None):
    return {
        "available": True, "close": close, "mid": mid,
        "lower": lower, "upper": upper,
        "cross": cross, "bars_since_cross": bars,
    }


# ----------------------------------------------------------------------
# 트리거 분류 — 롱/숏 대칭
# ----------------------------------------------------------------------
def test_중단_하향이탈_SHORT():
    t = S.classify(_st(98.0, cross="DOWN", bars=0))
    assert t == "MID_DOWN"
    assert S.PLAYS[t][0] == "SHORT"


def test_중단_상향돌파_LONG():
    t = S.classify(_st(102.0, cross="UP", bars=1))
    assert t == "MID_UP"
    assert S.PLAYS[t][0] == "LONG"


def test_하단_이탈_SHORT():
    t = S.classify(_st(94.0, cross="DOWN", bars=5))
    assert t == "LOWER_BREAK"
    assert S.PLAYS[t][0] == "SHORT"


def test_상단_돌파_LONG():
    t = S.classify(_st(106.0, cross="UP", bars=5))
    assert t == "UPPER_BREAK"
    assert S.PLAYS[t][0] == "LONG"


def test_밴드이탈이_중단이탈보다_우선():
    """하단 밖 + 중단 이탈이 신선해도 = 밴드 이탈이 더 최근 사건!"""
    assert S.classify(_st(94.0, cross="DOWN", bars=0)) == "LOWER_BREAK"


def test_중단이탈_오래되면_신호없음():
    assert S.classify(_st(98.0, cross="DOWN", bars=9)) is None


def test_밴드안_이탈없으면_신호없음():
    assert S.classify(_st(100.0)) is None


def test_판정불가():
    assert S.classify({"available": False}) is None
    assert S.classify({"available": True, "close": None}) is None


# ----------------------------------------------------------------------
# 제안 생성
# ----------------------------------------------------------------------
def test_제안_형식_중단하향():
    p = S.build_prediction("ARBUSDT", "MID_DOWN", _st(98.0, cross="DOWN", bars=0))
    assert p["symbol"] == "ARBUSDT"
    assert p["side"] == "SHORT"
    assert p["type"] == "bb4h_mid_down"
    assert 0 < p["confidence"] <= 1
    assert p["target_price"] == 95.0, "TP = 하단!"
    assert p["change_pct"] < 0, "SHORT = 목표가 아래!"
    assert "82.8%" in p["reason"]
    assert p["expected_value_pct"] == 0.42


def test_제안_형식_중단상향():
    p = S.build_prediction("ARBUSDT", "MID_UP", _st(102.0, cross="UP", bars=0))
    assert p["side"] == "LONG"
    assert p["target_price"] == 105.0, "TP = 상단!"
    assert p["change_pct"] > 0
    assert "86.6%" in p["reason"]


def test_제안_형식_하단이탈():
    p = S.build_prediction("ARBUSDT", "LOWER_BREAK", _st(94.0))
    assert p["side"] == "SHORT"
    assert p["sl_pct"] == 5.0
    assert p["target_price"] < 94.0
    assert "기대값 낮음" in p["reason"], "중단 이탈보다 약하다는 경고 필수!"


def test_제안_형식_상단돌파():
    p = S.build_prediction("ARBUSDT", "UPPER_BREAK", _st(106.0))
    assert p["side"] == "LONG"
    assert p["target_price"] > 106.0
    assert p["expected_value_pct"] == 0.27


def test_중단이탈_confidence가_더_높음():
    """실측 기대값이 2~3배이므로 confidence 도 높아야 함!"""
    mid_down = S.PLAYS["MID_DOWN"][5]
    lower_break = S.PLAYS["LOWER_BREAK"][5]
    assert mid_down > lower_break
    assert S.PLAYS["MID_UP"][5] > S.PLAYS["UPPER_BREAK"][5]


def test_롱숏_대칭_4종_모두_존재():
    sides = {k: v[0] for k, v in S.PLAYS.items()}
    assert sides == {
        "MID_DOWN": "SHORT", "MID_UP": "LONG",
        "LOWER_BREAK": "SHORT", "UPPER_BREAK": "LONG",
    }


def test_모든_트리거_기대값_양수():
    """실측 기대값이 음수인 트리거는 제안에 넣지 않습니다!"""
    for k, v in S.PLAYS.items():
        assert v[4] > 0, f"{k} 기대값이 양수여야 함"

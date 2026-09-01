"""Fix 278 — 볼밴 중단선 4종 단위 테스트.

사장님 지시 검증 지점:
  ① 4종의 **방향**이 사장님이 말한 대로인가
     (지지→LONG / 저항→SHORT / 상향돌파→LONG / **하락돌파→SHORT**)
     🚨 옛 pump_split 중단 모드는 하락돌파를 **LONG** 으로 봤다 = 정반대였다.
  ② 판정은 **완료봉**으로만 (진행 중 봉이 신호를 만들면 안 된다)
  ③ 실측을 통과 못 한 패턴은 **기본 OFF**
"""
from app.services import bb_mid_line as M


def _bands(mid_vals):
    return list(mid_vals)


def _mk(n=20, mid=100.0):
    """평탄한 중단선 시계열."""
    return [mid] * n


# ─────────────────────────────────────────────────────────────────────
# 방향 — 사장님 지시 그대로인가
# ─────────────────────────────────────────────────────────────────────

def test_사장님_방향_매핑():
    assert M.PATTERN_SIDE["mid_support"] == "LONG"
    assert M.PATTERN_SIDE["mid_resist"] == "SHORT"
    assert M.PATTERN_SIDE["mid_break_up"] == "LONG"
    # 🚨 옛 코드(pump_split 중단 모드)는 여기가 LONG 이었다 = 사장님과 정반대
    assert M.PATTERN_SIDE["mid_break_down"] == "SHORT"


def test_실측_통과분만_기본ON():
    """중단 저항/하락돌파만 과적합 검사를 통과했다 (전·후반 모두 양수)."""
    assert M.PATTERN_DEFAULT_ON["mid_resist"] is True
    assert M.PATTERN_DEFAULT_ON["mid_break_down"] is True
    assert M.PATTERN_DEFAULT_ON["mid_support"] is False
    assert M.PATTERN_DEFAULT_ON["mid_break_up"] is False


def test_4H_필수는_하락돌파_하나뿐():
    """중단 저항은 4H 를 걸면 오히려 나빠진다 (+785 -> +662)."""
    assert M.PATTERN_NEEDS_4H["mid_break_down"] is True
    assert M.PATTERN_NEEDS_4H["mid_resist"] is False


# ─────────────────────────────────────────────────────────────────────
# 판정
# ─────────────────────────────────────────────────────────────────────

def test_중단_지지_상승중_저가터치_위로마감():
    n = 20
    mid = [100.0 + i * 0.5 for i in range(n)]          # 상승 중
    closes = [110.0] * n
    highs = [111.0] * n
    lows = [100.0] * n
    i = n - 2
    lows[i] = mid[i] - 0.5                              # 중단선을 찍고
    closes[i] = mid[i] + 0.5                            # 위로 마감
    closes[i - 1] = mid[i - 1] + 0.5                    # 돌파는 아님
    r = M.evaluate_mid_line(closes, highs, lows, mid)
    assert "mid_support" in r["hits"], r
    assert r["slope_up"] is True


def test_중단_저항_하락중_고가터치_아래마감():
    n = 20
    mid = [110.0 - i * 0.5 for i in range(n)]           # 하락 중
    closes = [100.0] * n
    highs = [101.0] * n
    lows = [99.0] * n
    i = n - 2
    highs[i] = mid[i] + 0.5
    closes[i] = mid[i] - 0.5
    closes[i - 1] = mid[i - 1] - 0.5                    # 돌파는 아님
    r = M.evaluate_mid_line(closes, highs, lows, mid)
    assert "mid_resist" in r["hits"], r
    assert r["slope_up"] is False


def test_중단_상향돌파():
    n = 20
    mid = _mk(n)
    closes = [99.0] * n
    i = n - 2
    closes[i - 1] = 99.0                                # 아래
    closes[i] = 101.0                                   # 위 = 돌파
    r = M.evaluate_mid_line(closes, [102.0] * n, [98.0] * n, mid)
    assert "mid_break_up" in r["hits"], r


def test_중단_하락돌파():
    n = 20
    mid = _mk(n)
    closes = [101.0] * n
    i = n - 2
    closes[i - 1] = 101.0
    closes[i] = 99.0
    r = M.evaluate_mid_line(closes, [102.0] * n, [98.0] * n, mid)
    assert "mid_break_down" in r["hits"], r


def test_판정은_완료봉_진행중봉_무시():
    """closes[-1] 은 아직 안 끝난 봉 — 그 값이 결과를 바꾸면 안 된다."""
    n = 20
    mid = _mk(n)
    base = [101.0] * n
    base[n - 2] = 99.0                                   # 완료봉에서 하락돌파
    a = M.evaluate_mid_line(base[:-1] + [999.0], [1000.0] * n, [1.0] * n, mid)
    b = M.evaluate_mid_line(base[:-1] + [1.0], [1000.0] * n, [1.0] * n, mid)
    assert a["hits"] == b["hits"] == ["mid_break_down"], (a["hits"], b["hits"])


def test_지지와_저항은_동시에_안_난다():
    """기울기가 하나뿐이므로 상호배타여야 한다."""
    n = 20
    mid = [100.0 + i * 0.5 for i in range(n)]
    i = n - 2
    closes = [mid[k] + 0.5 for k in range(n)]
    r = M.evaluate_mid_line(closes, [200.0] * n, [1.0] * n, mid)
    assert not ("mid_support" in r["hits"] and "mid_resist" in r["hits"])


def test_봉_부족이면_빈_결과():
    r = M.evaluate_mid_line([1, 2, 3], [1, 2, 3], [1, 2, 3], [1, 2, 3])
    assert r["hits"] == []
    assert "부족" in r["why"]


def test_중단선_None이면_보류():
    n = 20
    mid = [None] * n
    r = M.evaluate_mid_line([100.0] * n, [101.0] * n, [99.0] * n, mid)
    assert r["hits"] == []


def test_평탄한_중단선은_지지도_저항도_아니다():
    """실측 판정식이 양쪽 다 엄격(`>` / `<`)이었다 — 평탄은 어느 쪽도 아니다."""
    n = 20
    mid = _mk(n)                                          # 완전 평탄
    i = n - 2
    closes = [100.5] * n
    highs = [101.0] * n
    lows = [99.0] * n
    closes[i] = 99.5                                      # 고가는 중단선 위, 종가는 아래
    r = M.evaluate_mid_line(closes, highs, lows, mid)
    assert "mid_resist" not in r["hits"], r
    assert "mid_support" not in r["hits"], r
    assert r["slope_dir"] == 0


def test_slope_up_값없으면_None():
    assert M.slope_up([None] * 10, 9) is None
    assert M.slope_up([1.0] * 10, 2, bars=6) is None      # 창 부족
    assert M.slope_up([float(i) for i in range(10)], 9, bars=6) is True
    assert M.slope_up([float(-i) for i in range(10)], 9, bars=6) is False


def test_worker_상수_기본_shadow():
    """새 전략은 자금이 안 나가는 상태로 태어나야 한다 (헌법 161)."""
    from app.workers import bb_mid_line_worker as W
    assert W.MODE_DEFAULT == "shadow"
    assert W.TEMPLATE_PREFIX == "BB_MIDLINE"
    assert W.MAX_CONCURRENT_DEFAULT <= 5

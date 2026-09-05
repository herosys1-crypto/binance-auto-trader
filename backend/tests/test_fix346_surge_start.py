"""📈 Fix 346 — 「가격은 고점인데 보조지표는 상승 초입」 = SHORT 보류 + LONG 알람.

사장님 2026-09-04 (MINIMAXUSDT #2755):
  "차트는 고점인데 다른 보조지표는 상승초입니다. 이건 롱으로 들어가야 승률이 높을 지점인것 같아
   분석해서 수정해줘 보조지표를 적용할수 있게 개선해줘"

실측(96종목 10일, n=592): 이 자리 SHORT −0.88 / LONG +1.64 (momentum_phase.py 머리말).
"""
from pathlib import Path

from app.services import momentum_phase as M

ROOT = Path(__file__).resolve().parents[1] / "app"


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _flat_then_surge(n_flat=70, n_surge=8, step=0.02):
    """평탄 → 급등 = hist 가 가속하며 양수, 종가·OBV 신고점 (2026-09-03 교훈: 선형 상승은 hist 수렴)."""
    closes = [100.0] * n_flat
    vols = [1000.0] * n_flat
    for i in range(1, n_surge + 1):
        closes.append(closes[-1] * (1 + step * i))     # 가속
        vols.append(1000.0 + 500.0 * i)
    return closes, vols


def test_상승_초입_판정():
    closes, vols = _flat_then_surge()
    ok, d = M.classify_surge_start(closes, vols)
    assert d["decided"] and ok is True, d


def test_완만한_하락_구간은_아님():
    closes = [100.0 - i * 0.01 for i in range(90)]      # 신고점 아님, hist ≤ 0
    vols = [1000.0] * 90
    ok, d = M.classify_surge_start(closes, vols)
    assert d["decided"] and ok is False and d["checks"]["신고점"] is False


def test_고점에서_hist_가_꺾이면_초입_아님():
    """MINIMAX 와 반대: 급등 뒤 3봉 되돌림 → hist 감소 = 정점 후보 (SHORT 유지)."""
    closes, vols = _flat_then_surge()
    for _ in range(3):
        closes.append(closes[-1] * 0.985)
        vols.append(800.0)
    ok, d = M.classify_surge_start(closes, vols)
    assert ok is False and d["checks"]["hist 가속"] is False


def test_데이터_부족은_판정_안_함():
    ok, d = M.classify_surge_start([100.0] * 30, [1.0] * 30)
    assert ok is False and d["decided"] is False


def test_is_surge_start_는_진행중_봉을_버린다():
    closes, vols = _flat_then_surge()
    rows = [[0, 0, 0, 0, str(c), str(v)] for c, v in zip(closes, vols)]
    rows.append([0, 0, 0, 0, "1.0", "1.0"])            # 진행중 봉 = 폭락값 — 버려져야 한다

    class _BC:
        def get_klines(self, symbol, interval, limit):
            assert interval == "15m"
            return rows
    ok, why, d = M.is_surge_start(_BC(), "MINIMAXUSDT", db=None)
    assert ok is True, why


def test_is_surge_start_는_예외에_fail_open():
    class _BC:
        def get_klines(self, **kw):
            raise RuntimeError("API 끊김")
    ok, why, _ = M.is_surge_start(_BC(), "X", db=None)
    assert ok is False and "fail-open" in why


def test_기본_설정은_둘_다_ON():
    assert M.short_veto_enabled(None) is True and M.long_handoff_enabled(None) is True


class _DB:
    def __init__(self, **kv):
        self._kv = kv

    def get(self, _model, key):
        v = self._kv.get(key)
        return None if v is None else type("R", (), {"value": v})()


def test_설정으로_끌_수_있고_숫자도_바꿀_수_있다():
    assert M.short_veto_enabled(_DB(surge_start_short_veto_enabled="0")) is False
    assert M._int(_DB(surge_start_accel_bars="5"), M.SETTING_ACCEL_BARS, 3, 2, 10) == 5
    assert M._int(_DB(surge_start_accel_bars="99"), M.SETTING_ACCEL_BARS, 3, 2, 10) == 3, "범위 밖은 기본"


# ── 배선 (정적 검사 ≠ 실행이지만, 호출 위치와 순서는 여기서 고정한다) ──

def test_정점_SHORT_워커가_정점확인_뒤_생성_전에_판정한다():
    s = _src("workers/auto_short_at_top_worker.py")
    i_pk = s.find('logger.info("[auto_short_top+Fix111] %s %s | %s", symbol, _pk_why, _pk_det)')
    i_ss = s.find("is_surge_start as _is_ss")
    i_cr = s.find('strategy_type_suffix="_SAJANGNIM_TOP"')
    assert 0 < i_pk < i_ss < i_cr, "정점확인 OK → 국면 판정 → 생성 순서"
    assert 'f"sajangnim:bottom_long:{symbol}"' in s, "LONG 알람 키 형식이 auto_long_at_bottom 과 같아야 한다"
    assert '"pattern": _SS_PATTERN' in s


def test_LONG_워커가_SURGE_START_패턴을_받아_저점게이트를_건너뛴다():
    s = _src("workers/auto_long_at_bottom_worker.py")
    assert '_skip_pk = (pattern in ("SURGE_PULLBACK", "SURGE_START", "MULTIDAY_PULLBACK"))' in s
    assert 'in MOMENTUM_ALERT_PATTERNS else None' in s
    assert "pattern=_alert_pattern" in s


def test_실측_근거가_모듈에_남아_있다():
    s = _src("services/momentum_phase.py")
    for token in ("+1.64", "−0.88", "n=592", "MINIMAXUSDT"):
        assert token in s, token

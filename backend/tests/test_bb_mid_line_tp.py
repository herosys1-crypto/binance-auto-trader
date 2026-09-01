"""Fix 281 — 익절이 **백테스트 가정과 같은가**.

## 왜 이 테스트가 있는가

Fix 278 로 중단선 전략을 켠 직후, 실자금이 나가기 전에 확인하다가 잡았다:

  백테스트 가정: **TP +5% ROI** (그 가정 위에서 SHORT 건당 +1.800 / 승률 77.0%)
  실제 코드    : create_surge_position 의 템플릿이 **TP1 15%**,
                게다가 strategy_service 가 인스턴스에 tp1_pct_override=15 를 **또** 넣는다.

  레버 2 에서 ROI 15% = 가격 7.5%. 측정한 규칙(가격 2.5%)과 **완전히 다른 매매**가 된다.

## 이 저장소가 이미 한 번 빠진 함정 (Fix 205)

  "템플릿만 5 로 바꾸면 이 override 가 이겨서 사장님이 지정한 5% 가 무효가 된다"

  → 템플릿 **과** 인스턴스 **둘 다** 박아야 한다. 그 둘을 여기서 못박는다.
"""
import ast
import inspect
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "app" / "services" / "surge_ladder_entry.py"
WORKER = ROOT / "app" / "workers" / "bb_mid_line_worker.py"


def test_중단선_TP1은_백테스트와_같은_5퍼센트():
    from app.workers import bb_mid_line_worker as W
    assert W.TP_PERCENTS[0] == 5.0, (
        "백테스트가 TP +5% ROI 가정이었다. 이 값을 바꾸면 측정 결과가 무효다."
    )
    assert list(W.TP_PERCENTS) == sorted(W.TP_PERCENTS), "익절 사다리는 오름차순이어야 한다"
    assert W.TRAILING_PCT and W.TRAILING_PCT > 0, "트레일링이 없으면 수익이 되돌아간다"


def test_급등사다리_기본값은_무변경():
    """인자 추가는 **추가일 뿐**이어야 한다 — 급등 사다리 동작을 바꾸면 안 된다."""
    from app.services.surge_ladder_entry import create_surge_position
    sig = inspect.signature(create_surge_position)
    assert tuple(sig.parameters["tp_percents"].default) == (15.0, 20.0, 25.0, 30.0)
    assert sig.parameters["trailing_pct"].default is None
    # 다른 신규 인자들도 옛 값이 기본이어야 한다
    assert sig.parameters["template_prefix"].default == "SURGE_LADDER"
    assert sig.parameters["strategy_type"].default == "surge_peak_ladder"


def test_중단선_워커가_TP를_실제로_넘긴다():
    """상수만 정의하고 안 넘기면 아무 소용이 없다 — 호출부를 AST 로 확인한다."""
    tree = ast.parse(WORKER.read_text(encoding="utf-8"))
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "create_surge_position"
    ]
    assert calls, "create_surge_position 호출을 못 찾았다"
    for c in calls:
        kw = {k.arg for k in c.keywords}
        assert "tp_percents" in kw, "TP 를 안 넘기면 기본 15% 가 쓰인다"
        assert "trailing_pct" in kw
        assert "template_prefix" in kw and "strategy_type" in kw


def test_인스턴스_override_를_반드시_박는다():
    """🚨 Fix 205 함정 — 템플릿만 바꾸면 strategy_service 의 override(15)가 이긴다."""
    src = ENTRY.read_text(encoding="utf-8")
    assert "strategy.tp1_pct_override" in src, (
        "템플릿만 바꾸고 인스턴스 override 를 안 박으면 TP1 이 15% 로 되돌아간다 (Fix 205)"
    )
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "create_surge_position")
    body = ast.dump(fn)
    assert "tp1_pct_override" in body, "override 를 create_surge_position 안에서 박아야 한다"
    assert "tp1_percent" in body, "템플릿에도 박아야 한다"


def test_템플릿과_인스턴스가_같은_값을_쓴다():
    """둘이 다른 상수를 쓰면 나중에 한쪽만 바뀌어 조용히 어긋난다."""
    src = ENTRY.read_text(encoding="utf-8")
    assert "tp1_percent=Decimal(str(tp_percents[0]))" in src
    assert "strategy.tp1_pct_override = Decimal(str(tp_percents[0]))" in src


def test_손절은_ROI_10퍼센트_로_환산된다():
    """백테스트 가정 SL -10% ROI = 가격 -5% x 레버 2."""
    from app.services.surge_peak_ladder import sl_roi_for_price_pct
    from app.workers import bb_mid_line_worker as W
    assert sl_roi_for_price_pct(W.SL_PRICE_PCT_DEFAULT, W.LEVERAGE) == 10.0


# ═══════════════════════════════════════════════════════════════════════
# Fix 282 — 피라미딩이 1회 진입 전략을 건드리면 안 된다
# ═══════════════════════════════════════════════════════════════════════

def test_피라미딩_제외_목록에_들어있다():
    """🚨 발동선(ROI +5%)과 이 전략들의 TP1(+5%)이 **같다**.
    막지 않으면 익절 지점에서 300 USDT 추가 매수가 나간다 (볼밴 -252.18 사고와 동형).
    """
    from app.workers import success_pyramiding_worker as P
    assert "bb_mid_line" in P.NO_PYRAMID_STRATEGY_TYPES
    assert "surge_peak_ladder" in P.NO_PYRAMID_STRATEGY_TYPES
    assert P.MIN_UNREALIZED_ROI_PCT == 5.0        # 발동선
    from app.workers import bb_mid_line_worker as W
    assert W.TP_PERCENTS[0] == P.MIN_UNREALIZED_ROI_PCT, (
        "TP1 과 피라미딩 발동선이 같다 = 반드시 제외돼야 한다"
    )


def test_이름_접두사로도_거른다():
    """strategy_type 에 접미사가 붙는 전략이 있어 DB 필터만으로는 부족하다."""
    from app.workers.success_pyramiding_worker import _is_no_pyramid

    class _T:
        def __init__(self, st, nm):
            self.strategy_type, self.name = st, nm

    class _S:
        def __init__(self, st, nm):
            self.strategy_template = _T(st, nm)

    assert _is_no_pyramid(_S("bb_mid_line", "BB_MIDLINE_X_SHORT_1_A1")) is True
    assert _is_no_pyramid(_S("something_else", "BB_MIDLINE_X_SHORT_1_A1")) is True
    assert _is_no_pyramid(_S("surge_peak_ladder", "SURGE_LADDER_Y")) is True
    # 다른 전략은 **그대로 피라미딩 대상**이어야 한다 (사장님 "이익일때 추가 300씩")
    assert _is_no_pyramid(_S("auto_bb_break_SAJANGNIM", "AUTO_BB_X")) is False


def test_판정_실패는_제외로_간주된다():
    """자본이 늘어나는 판정 = fail-closed."""
    from app.workers.success_pyramiding_worker import _is_no_pyramid

    class _Boom:
        @property
        def strategy_template(self):
            raise RuntimeError("db detached")

    assert _is_no_pyramid(_Boom()) is True

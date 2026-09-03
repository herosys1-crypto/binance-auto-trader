"""🧾 Fix 341 — 화면 표기: 「사다리」와 「피라미딩」을 가른다.

사장님 2026-09-03: "이런 표기가 이상하잖아 완전 엉망이 되었네 정말 답답하네"

#2116 BULLAUSDT 실측:
    화면            "진입 1/3"   "702 / 1500  47%"
    단계 계획       100(발동) / 300 / 500  = 합계 900
    total_capital  1500        ← 피라미딩 2회(+300, +300)가 올린 값
    실제 증거금     700.75      (= 1단계 100 + 피라미딩 300 + 300)

「1/3」은 사다리 단계, 「702」는 피라미딩 포함 총 증거금 — 서로 다른 축이다.
→ ladder_capital / pyramid_capital / invested_capital_computed 를 따로 준다.
🚨 계산 불가면 None. 0 으로 채우면 그게 바로 거짓 표시다 (Fix 333 의 교훈).
"""
import ast
from decimal import Decimal
from pathlib import Path

from app.api.v1.strategies import helpers as H
from app.schemas.strategy import StrategyDetailResponse


D = Decimal


def _resp(total=None):
    """필수 필드만 채운 응답 객체."""
    return StrategyDetailResponse.model_construct(
        id=2116, symbol="BULLAUSDT", side="LONG", status="STAGE1_OPEN",
        leverage=2, current_stage=1, current_position_qty=D("47181"),
        invested_capital=D("0"), realized_pnl=D("0"), unrealized_pnl=D("0"),
        total_capital=D(str(total)) if total is not None else None,
    )


class _Strategy:
    id = 2116
    leverage = 2
    current_position_qty = D("47181")
    avg_entry_price = D("0.02970482")


# ═════════════════════════════════════════════════════════════════════
# 🎯 #2116 재현 — 900 / 600 / 1500
# ═════════════════════════════════════════════════════════════════════

def test_2116_사다리_900_피라미딩_600(monkeypatch):
    import app.services.capital_accounting as C
    monkeypatch.setattr(C, "compute_invested_capital", lambda db, s: D("700.75"))
    r = H.apply_capital_split(_resp(total=1500), _Strategy(),
                              {"ladder_capital": D("900"), "stage_count": 3}, db=None)
    assert r.ladder_capital == D("900")
    assert r.ladder_stage_count == 3
    assert r.pyramid_capital == D("600"), "1500 − 900 = 피라미딩 600"
    assert r.invested_capital_computed == D("700.75")


def test_단계_계획이_없으면_None_이지_0이_아니다():
    r = H.apply_capital_split(_resp(total=1500), _Strategy(), None, db=None)
    assert r.ladder_capital is None
    assert r.ladder_stage_count is None
    assert r.pyramid_capital is None, "계획이 없는데 피라미딩을 1500 으로 계산하면 거짓이다"


def test_total_이_사다리보다_작아도_음수가_안_된다():
    r = H.apply_capital_split(_resp(total=800), _Strategy(),
                              {"ladder_capital": D("900"), "stage_count": 3}, db=None)
    assert r.pyramid_capital == D("0")


def test_total_capital_이_None_이면_pyramid_도_None():
    r = H.apply_capital_split(_resp(total=None), _Strategy(),
                              {"ladder_capital": D("900"), "stage_count": 3}, db=None)
    assert r.ladder_capital == D("900") and r.pyramid_capital is None


def test_증거금_계산_실패해도_응답을_막지_않는다(monkeypatch):
    import app.services.capital_accounting as C
    def _boom(db, s):
        raise RuntimeError("DB 끊김")
    monkeypatch.setattr(C, "compute_invested_capital", _boom)
    r = H.apply_capital_split(_resp(total=1500), _Strategy(),
                              {"ladder_capital": D("900"), "stage_count": 3}, db=None)
    assert r.invested_capital_computed is None
    assert r.pyramid_capital == D("600"), "다른 필드는 정상이어야 한다"


def test_기존_필드는_그대로다():
    """화면 호환 — 옛 필드를 지우거나 이름을 바꾸면 index.html 이 깨진다."""
    fields = set(StrategyDetailResponse.model_fields)
    for f in ("invested_capital", "total_capital", "current_stage", "total_active_stages",
              "tp_triggered_count", "total_active_tps"):
        assert f in fields, f
    for f in ("ladder_capital", "ladder_stage_count", "pyramid_capital", "invested_capital_computed"):
        assert f in fields, f
        assert StrategyDetailResponse.model_fields[f].default is None, f"{f} 기본값은 None 이어야 한다"


# ═════════════════════════════════════════════════════════════════════
# 🚨 실제로 호출되는가 — 목록·단건 둘 다 (Fix 247/318 의 교훈)
# ═════════════════════════════════════════════════════════════════════

def _fn_src(mod, name):
    src = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.get_source_segment(src, n) or ""
    raise AssertionError(f"{name} 없음")


def test_목록과_단건_엔드포인트가_둘_다_부른다():
    from app.api.v1.strategies import crud as CR
    for name in ("list_strategies", "get_strategy"):
        seg = _fn_src(CR, name)
        assert "apply_capital_split(" in seg, f"{name} 이 표기 분리를 안 한다"
        assert "_fetch_ladder_batch(" in seg, f"{name} 이 사다리 합계를 안 가져온다"


def test_배치_fetch_는_전략_id_집합_한_번에():
    """N+1 방지 — 목록은 전략 수만큼 쿼리하면 안 된다."""
    src = _fn_src(H, "_fetch_ladder_batch")
    assert ".in_(" in src and "group_by" in src


def test_실측_근거가_주석에_남아_있다():
    from app.schemas import strategy as S
    src = Path(S.__file__).read_text(encoding="utf-8")
    for token in ("2116", "702/1500", "1/3"):
        assert token in src, token

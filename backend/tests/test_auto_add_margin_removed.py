"""⛔ Fix 340 — 자동 증거금 주입 폐지 (사장님 2026-09-04 지시).

사장님: "증거금 주입은 필요없는 기능이야. 지금 포지션 진입후 손실이면 10usdt 남기고
        부분손절입니다. 그런데 왜 증거금 주입이 필요한가 이기능은 삭제해줘"

## 왜 충돌인가

    v220 자동 증거금 (08-22) : ROI < -30% 이면 300 USDT 를 더 넣어 청산가를 민다
                              = 손실 포지션에 돈을 더 넣고 **버틴다**
    현행 부분손절 (Fix 304~326): 손실이면 10 USDT 만 남기고 청산 → 다음 단계 진입
                              = 손실 포지션을 **줄이고** 좋은 자리에 다시 진입

같은 포지션에 둘 다 걸리면 손절해야 할 것에 300 을 얹고 -80% 까지 끌고 간다.

## 이 테스트가 지키는 것

1. 스케줄러에 auto_add_margin 이 **살아 있는 등록으로** 없다
2. `run_auto_add_margin()` 은 진입 즉시 반환한다 — DB·거래소를 건드리지 않는다
3. 🚨 **수동 증거금 추가는 그대로 살아 있다** (사장님 판단은 막지 않는다)
"""
import ast
from pathlib import Path


def _src(mod) -> str:
    return Path(mod.__file__).read_text(encoding="utf-8")


def test_스케줄러에_살아있는_등록이_없다():
    from app.workers import scheduler_runner as S
    live = [ln for ln in _src(S).splitlines()
            if 'id="auto_add_margin"' in ln and not ln.strip().startswith("#")]
    assert live == [], f"auto_add_margin 이 여전히 등록돼 있다: {live}"


def test_워커_진입점이_즉시_반환한다():
    """AST: run_auto_add_margin 본문의 첫 실행문이 return 이어야 한다 (로그 제외)."""
    from app.workers import auto_add_margin_worker as W
    tree = ast.parse(_src(W))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "run_auto_add_margin")
    body = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
    # 첫 두 문장 = logger.info(...) 그리고 return
    kinds = [type(n).__name__ for n in body[:2]]
    assert "Return" in kinds[:2], f"진입 가드가 없다: {kinds}"
    ret_idx = kinds.index("Return")
    assert ret_idx <= 1, "return 앞에 실제 로직이 있다"


def test_워커를_실제로_불러도_아무것도_안_한다(monkeypatch):
    """🚨 스케줄러 밖의 어떤 호출자가 남아 있어도 발주되면 안 된다."""
    from app.workers import auto_add_margin_worker as W
    touched = []
    # DB 세션을 만들려 하면 실패로 기록
    monkeypatch.setattr(W, "SessionLocal", lambda: touched.append("db") or (_ for _ in ()).throw(RuntimeError("DB 접근")))
    W.run_auto_add_margin()            # 예외 없이 즉시 반환해야 한다
    assert touched == [], "폐지된 워커가 DB 에 손을 댔다"


def test_수동_증거금_추가는_살아_있다():
    """사장님이 직접 넣는 경로는 건드리지 않는다."""
    from app.api.v1.strategies import lifecycle as L
    src = _src(L)
    assert "add_position_margin(" in src, "수동 증거금 추가 경로가 사라졌다"


def test_폐지_사유가_두_파일에_남아_있다():
    from app.workers import scheduler_runner as S
    from app.workers import auto_add_margin_worker as W
    for mod in (S, W):
        src = _src(mod)
        assert "Fix 340" in src and "부분손절" in src, mod.__name__

"""Fix 303 — 자동매매 제외 심볼 단위 테스트.

사장님 2026-09-03: "BTCUSDT / BTCUSDC / BTCUSD1 (50) ,
                   ETHUSDT / ETHUSDC / LTCUSDT / LINKUSDT / ETCUSDT / BCHUSDT (20)
                   이것들은 포지션에서 제외해줘"

이유: 사장님 사양 「모든 단계에서 10 USDT 만 남기고 청산」에서, MIN_NOTIONAL 이
10 을 넘는 종목은 잔량을 남길 수 없다. 남기면 팔 수 없는 dust 가 된다.
"""
import ast
from pathlib import Path

from app.services import symbol_exclusion as X
from app.services import execution_service as E

ESRC = Path(E.__file__).read_text(encoding="utf-8")


class _DB:
    def __init__(self, val=None, boom=False):
        self.val, self.boom = val, boom

    def get(self, _model, key):
        if self.boom:
            raise RuntimeError("db down")
        if key != X.SETTING_KEY or self.val is None:
            return None
        return type("R", (), {"value": self.val})()


# ── 사장님이 지목한 종목이 전부 들어 있는가 ──────────────────────────

def test_사장님이_지목한_9종목이_전부_제외된다():
    사장님 = ["BTCUSDT", "BTCUSDC", "BTCUSD1", "ETHUSDT", "ETHUSDC",
             "LTCUSDT", "LINKUSDT", "ETCUSDT", "BCHUSDT"]
    for s in 사장님:
        assert X.is_excluded(_DB(), s), s


def test_같은_이유의_BTC_분기물도_제외된다():
    """stepSize 0.001 x 고가 = 최소 잔량 78 USDT — 10 을 못 남기는 건 같다."""
    assert X.is_excluded(_DB(), "BTCUSDT_261225")
    assert X.is_excluded(_DB(), "BTCUSDT_260925")


def test_나머지_종목은_통과한다():
    for s in ("DOGEUSDT", "SOLUSDT", "AKEUSDT", "XRPUSDT"):
        assert not X.is_excluded(_DB(), s), s


def test_대소문자와_공백을_정규화한다():
    for s in (" btcusdt ", "BtcUsdt", "BTCUSDT"):
        assert X.is_excluded(_DB(), s), repr(s)


# ── fail 방향 ────────────────────────────────────────────────────────

def test_조회가_실패해도_제외는_유지된다():
    """🚨 여기서 fail-open 하면 사장님이 빼라고 한 종목에 자금이 들어간다."""
    assert X.is_excluded(_DB(boom=True), "BTCUSDT")
    assert not X.is_excluded(_DB(boom=True), "DOGEUSDT")


def test_심볼을_모르면_막는다():
    """알 수 없는 대상에 자금을 넣지 않는다."""
    for bad in (None, "", "   "):
        assert X.is_excluded(_DB(), bad), repr(bad)


# ── 설정으로 사장님이 목록을 통제한다 ────────────────────────────────

def test_설정이_있으면_그것으로_대체된다():
    db = _DB("DOGEUSDT,SOLUSDT")
    assert X.is_excluded(db, "DOGEUSDT")
    assert not X.is_excluded(db, "BTCUSDT"), "설정이 있으면 기본 목록은 안 쓴다"


def test_빈_설정은_명시적_해제다():
    assert not X.is_excluded(_DB(""), "BTCUSDT")


def test_설정의_공백과_빈칸을_견딘다():
    db = _DB(" doge , , sol ,")
    assert X.excluded_symbols(db) == frozenset({"DOGE", "SOL"})


# ── 후보 목록 필터 ───────────────────────────────────────────────────

def test_dict_와_객체_둘_다_거른다():
    rows = [{"symbol": "BTCUSDT"}, {"symbol": "DOGEUSDT"}]
    assert X.drop_excluded(_DB(), rows) == [{"symbol": "DOGEUSDT"}]
    objs = [type("O", (), {"symbol": s})() for s in ("ETHUSDT", "SOLUSDT")]
    assert [o.symbol for o in X.drop_excluded(_DB(), objs)] == ["SOLUSDT"]


def test_제외가_없으면_원본을_그대로():
    rows = [{"symbol": "BTCUSDT"}]
    assert X.drop_excluded(_DB(""), rows) == rows


def test_빈_입력을_견딘다():
    assert X.drop_excluded(_DB(), None) == []
    assert X.drop_excluded(_DB(), []) == []


# ── 🚨 진입 경로를 하나도 빠뜨리지 않았는가 (이 저장소의 반복 사고) ──

def _entry_order_functions():
    """`purpose="ENTRY"` 주문을 만드는 메서드 이름을 소스에서 직접 뽑는다."""
    tree = ast.parse(ESRC)
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        seg = ast.get_source_segment(ESRC, node) or ""
        if 'purpose="ENTRY"' in seg:
            out.add(node.name)
    return out


def test_진입주문을_만드는_모든_함수가_게이트를_부른다():
    """🚨 이 저장소는 「게이트는 있는데 한 경로가 안 부른다」를 반복해서 겪었다.
    새 진입 경로가 생기면 이 테스트가 자동으로 잡는다."""
    fns = _entry_order_functions()
    assert fns, "ENTRY 주문 생성 함수를 못 찾았다 — 테스트가 무력화됐다"
    tree = ast.parse(ESRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in fns:
            seg = ast.get_source_segment(ESRC, node) or ""
            assert "_assert_symbol_allowed" in seg, (
                f"{node.name} 이 제외 게이트를 안 부른다 — 이 경로로 새어나간다"
            )


def test_시장가와_지정가_양쪽_모두_걸린다():
    for fn in ("_place_stage_entry_order", "_place_market_entry", "_place_limit_entry"):
        assert f"def {fn}(" in ESRC, fn
    assert ESRC.count("self._assert_symbol_allowed(strategy)") >= 3


def test_게이트는_예외를_던진다():
    """🚨 조용히 None 을 돌려주면 호출자가 성공으로 오해할 수 있다."""
    body = ESRC[ESRC.index("def _assert_symbol_allowed"):]
    body = body[:body.index("\n    def ", 10)]
    assert "raise ValueError" in body


def test_기존_포지션은_건드리지_않는다는_것이_명시돼_있다():
    """자금 조작은 사장님 판단이다 — 다음 사람이 자동 청산을 붙이지 않도록."""
    body = ESRC[ESRC.index("def _assert_symbol_allowed"):]
    body = body[:body.index("\n    def ", 10)]
    assert "신규 진입만" in body


def test_실측_근거가_모듈에_남아_있다():
    doc = X.__doc__ or ""
    assert "98.5%" in doc and "743" in doc, "전 종목 검산 결과"
    assert "MIN_NOTIONAL" in doc and "dust" in doc

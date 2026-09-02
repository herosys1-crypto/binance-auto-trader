"""Fix 304 — 단계 전환 시 「10 USDT 만 남기고 청산」 단위 테스트.

사장님 2026-09-03:
  "모든 단계에서 청산은 10usdt 만 남기고 모두 청산하고 다음 단계 진입하게 해줘"
  "기본전략과 같이 ... 전략 인스턴스에 남겨둬야 겠어"

🚨 남긴 잔량이 MIN_NOTIONAL 아래면 **영원히 팔 수 없는 dust** 가 된다.
   이 저장소는 dust orphan 하나로 계정 전체가 막힌 전력이 있다.
"""
from decimal import Decimal
from pathlib import Path

from app.services import stage_trim as T
from app.services import execution_service as E

ESRC = Path(E.__file__).read_text(encoding="utf-8")
D = Decimal


class _Sym:
    def __init__(self, step, mq, mn):
        self.step_size, self.min_qty, self.min_notional = step, mq, mn


class _DB:
    """SystemSetting + Symbol 조회를 흉내내는 최소 스텁."""

    def __init__(self, settings=None, sym=None, boom=False):
        self.settings = settings or {}
        self.sym = sym
        self.boom = boom

    def get(self, _model, key):
        if self.boom:
            raise RuntimeError("db down")
        if key not in self.settings:
            return None
        return type("R", (), {"value": self.settings[key]})()

    def execute(self, _stmt):
        db = self

        class _R:
            def scalar_one_or_none(self_inner):
                if db.boom:
                    raise RuntimeError("db down")
                return db.sym
        return _R()


# 흔한 알트코인: step 1, minQty 1, minNotional 5
ALT = _Sym(D("1"), D("1"), D("5"))


# ── 기본 동작 ────────────────────────────────────────────────────────

def test_10USDT_만_남기고_나머지를_청산한다():
    db = _DB(sym=ALT)
    close, keep, why = T.compute_trim(db, "AKEUSDT", D("34417"), D("0.0224"))
    assert keep * D("0.0224") >= D("10"), why      # 잔량 명목 >= 10
    assert close + keep == D("34417"), why         # 합이 보유량
    assert close > 0


def test_1단계_100이든_1000이든_같은_10을_남긴다():
    """사장님: "1단계 100이든 1000이든 10usdt 남기고"."""
    db = _DB(sym=ALT)
    px = D("0.05")
    keeps = []
    for qty in ("2000", "20000", "200000"):          # 명목 100 / 1000 / 10000
        _c, k, _w = T.compute_trim(db, "X", D(qty), px)
        keeps.append(k * px)
    assert len(set(keeps)) == 1, f"잔량이 포지션 크기에 따라 달라졌다: {keeps}"
    assert keeps[0] >= D("10")


def test_잔량이_보유량보다_크면_전량청산():
    """포지션이 10 USDT 도 안 되면 남길 것이 없다."""
    db = _DB(sym=ALT)
    close, keep, why = T.compute_trim(db, "X", D("100"), D("0.05"))   # 명목 5
    assert keep == 0 and close == D("100"), why
    assert "전량" in why


# ── 🚨 dust 방지 ─────────────────────────────────────────────────────

def test_MIN_NOTIONAL_이_10보다_크면_그만큼_남긴다():
    """ETHUSDT(20) / BTCUSDT(50). 10 을 남기면 못 파는 dust 가 된다."""
    db = _DB(sym=_Sym(D("0.001"), D("0.001"), D("20")))
    _c, keep, why = T.compute_trim(db, "ETHUSDT", D("10"), D("3000"))
    assert keep * D("3000") >= D("20") * T.MIN_NOTIONAL_SAFETY, why


def test_잔량은_항상_최소치_이상이다():
    """여러 가격/스텝 조합에서 잔량이 MIN_NOTIONAL 아래로 안 떨어진다."""
    for step, mq, mn, px in (
        (D("1"), D("1"), D("5"), D("0.0224")),
        (D("0.1"), D("0.1"), D("5"), D("2.5")),
        (D("0.001"), D("0.001"), D("20"), D("3000")),
        (D("0.01"), D("0.01"), D("5"), D("180")),
    ):
        db = _DB(sym=_Sym(step, mq, mn))
        close, keep, why = T.compute_trim(db, "X", D("100000"), px)
        if close == 0:
            continue
        assert keep * px >= mn, f"dust 발생: keep={keep} px={px} mn={mn} — {why}"


def test_잔량은_stepSize_배수다():
    for step in (D("1"), D("0.1"), D("0.001")):
        db = _DB(sym=_Sym(step, step, D("5")))
        close, keep, _w = T.compute_trim(db, "X", D("100000"), D("1.7"))
        assert keep % step == 0, keep
        assert close % step == 0, close


def test_청산분이_최소주문금액_미만이면_실행하지_않는다():
    """🚨 발주해도 거부된다. 시도하면 로그만 더럽히고 상태가 어긋난다."""
    db = _DB(sym=_Sym(D("1"), D("1"), D("5")))
    # 보유 명목 10.5, 잔량 목표 10 → 청산분 명목 0.5 < 5
    close, keep, why = T.compute_trim(db, "X", D("21"), D("0.5"))
    assert close == 0, why


# ── 🚨 불확실하면 아무것도 하지 않는다 ───────────────────────────────

def test_거래소_필터가_없으면_미실행():
    """잘못 청산하면 실제 자금이 사라진다. 되돌릴 수 없다."""
    close, _k, why = T.compute_trim(_DB(sym=None), "X", D("1000"), D("1"))
    assert close == 0 and "필터 없음" in why


def test_stepSize가_0이면_미실행():
    db = _DB(sym=_Sym(D("0"), D("1"), D("5")))
    assert T.compute_trim(db, "X", D("1000"), D("1"))[0] == 0


def test_포지션이나_가격이_없으면_미실행():
    db = _DB(sym=ALT)
    assert T.compute_trim(db, "X", D("0"), D("1"))[0] == 0
    assert T.compute_trim(db, "X", D("1000"), D("0"))[0] == 0
    assert T.compute_trim(db, "X", None, None)[0] == 0


def test_DB가_죽어도_예외를_밖으로_던지지_않는다():
    close, _k, _w = T.compute_trim(_DB(boom=True), "X", D("1000"), D("1"))
    assert close == 0


# ── 설정 ─────────────────────────────────────────────────────────────

def test_기본은_꺼져있다():
    """매매 흐름을 바꾸는 큰 변경이라 명시적으로 켠다 (헌법 161)."""
    assert T.trim_enabled(_DB()) is False
    assert T.trim_enabled(_DB({T.SETTING_ENABLED: "1"})) is True
    assert T.trim_enabled(_DB({T.SETTING_ENABLED: "0"})) is False
    assert T.trim_enabled(_DB(boom=True)) is False


def test_잔량_금액을_설정으로_바꿀_수_있다():
    assert T.keep_notional(_DB()) == D("10")
    assert T.keep_notional(_DB({T.SETTING_KEEP_NOTIONAL: "25"})) == D("25")
    for bad in ("", "abc", "0", "-5", "99999"):
        assert T.keep_notional(_DB({T.SETTING_KEEP_NOTIONAL: bad})) == D("10"), bad


# ── 진입 경로에 실제로 연결됐는가 ────────────────────────────────────

def test_단계_전환부에_연결돼_있다():
    """상수만 만들고 안 부르면 소용없다 — 이 저장소의 반복 사고."""
    assert "from app.services.stage_trim import compute_trim, trim_enabled" in ESRC
    assert "if trim_enabled(self.db) and stage_no > 1:" in ESRC


def _fn_src(name):
    """함수 하나의 소스만 잘라낸다 (다른 함수의 호출부에 걸리지 않도록)."""
    import ast
    tree = ast.parse(ESRC)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return ast.get_source_segment(ESRC, n) or ""
    raise AssertionError(f"{name} 를 못 찾음")


def test_다음단계_주문보다_먼저_실행된다():
    """🚨 순서가 뒤바뀌면 평단이 오염된 뒤에 청산하게 된다 = 의미 없음."""
    src = _fn_src("trigger_next_stage")
    i_trim = src.index("if trim_enabled(self.db)")
    i_order = src.index("order = self._place_stage_entry_order(strategy, stage_plan")
    assert i_trim < i_order


def test_1단계_진입은_정리하지_않는다():
    """`start_stage1` 은 첫 진입이라 정리할 기존 포지션이 없다.
    여기에 trim 이 끼면 첫 진입이 즉시 잘려나간다."""
    assert "trim_enabled" not in _fn_src("start_stage1")


def test_단계진행_경로가_trigger_next_stage_하나인가():
    """🚨 다른 경로로 단계가 오르면 그 경로는 정리 없이 물타기가 된다."""
    import ast
    from pathlib import Path
    callers = []
    root = Path(E.__file__).resolve().parents[1]      # app/
    for p in root.rglob("*.py"):
        try:
            src = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if "_place_stage_entry_order" not in src or p.name == "execution_service.py":
            continue
        # 🚨 주석 언급은 호출이 아니다 — AST 로 **실제 호출**만 센다.
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "_place_stage_entry_order"):
                callers.append(f"{p.name}:{node.lineno}")
    assert not callers, f"execution_service 밖에서 단계 진입 주문을 낸다: {callers}"


def test_1단계에는_적용하지_않는다():
    """1단계는 첫 진입이라 정리할 기존 포지션이 없다."""
    assert "stage_no > 1" in ESRC


def test_정리_불가면_단계진입을_중단한다():
    """🚨 fail-open 하면 물타기가 그대로 일어난다 — 고치려던 것이 그대로 남는다."""
    blk = ESRC[ESRC.index("if trim_enabled(self.db)"):]
    blk = blk[:blk.index("order = self._place_stage_entry_order")]
    assert "raise ValueError" in blk
    assert "진입 **중단**" in blk


def test_부분청산_경로를_쓴다():
    """전량 청산 함수를 쓰면 전략이 죽어 「인스턴스에 남겨둬야겠어」가 깨진다."""
    blk = ESRC[ESRC.index("if trim_enabled(self.db)"):]
    blk = blk[:blk.index("order = self._place_stage_entry_order")]
    assert "self.emergency_close_position(strategy.id, quantity=_close_qty)" in blk


def test_실측_근거가_모듈에_남아_있다():
    doc = T.__doc__ or ""
    assert "-88.17%" in doc, "물타기로 생긴 실제 손실률"
    assert "dust" in doc and "MIN_NOTIONAL" in doc
    assert "reconcile_worker.py:330" in doc, "잔량이 자동 정리되지 않는다는 근거"

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


def test_청산분이_최소주문금액_미만이면_전량으로_떨어진다():
    """🚨 Fix 305: 여기서 미실행으로 두면 그 심볼의 단계가 **영구히 멈춘다**
    (호출자가 fail-CLOSED). 잔량을 남길 수 없는 크기이므로 전량 청산이 맞다."""
    db = _DB(sym=_Sym(D("1"), D("1"), D("5")))
    # 보유 명목 10.5, 잔량 목표 10 → 청산분 명목 0.5 < 5 → 전량으로
    close, keep, why = T.compute_trim(db, "X", D("21"), D("0.5"))
    assert close == D("21") and keep == 0, why


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
    i_trim = src.index("self._trim_before_stage(strategy, stage_no)")
    i_order = src.index("order = self._place_stage_entry_order(strategy, stage_plan")
    assert i_trim < i_order


def test_수동경로도_주문보다_먼저_정리한다():
    src = _fn_src("enter_stage_at_market")
    assert src.index("self._trim_before_stage(strategy, stage_no)") < src.index(
        "order = self._place_market_entry("
    )


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
    src = _fn_src("_trim_before_stage")
    assert "raise ValueError" in src
    assert "진입 **중단**" in src


def test_부분청산_경로를_쓴다():
    """전량 청산 함수를 쓰면 전략이 죽어 「인스턴스에 남겨둬야겠어」가 깨진다."""
    src = _fn_src("_trim_before_stage")
    assert "self.emergency_close_position(" in src
    assert "quantity=_close_qty" in src


def test_실측_근거가_모듈에_남아_있다():
    doc = T.__doc__ or ""
    assert "-88.17%" in doc, "물타기로 생긴 실제 손실률"
    assert "dust" in doc and "MIN_NOTIONAL" in doc
    assert "reconcile_worker.py:330" in doc, "잔량이 자동 정리되지 않는다는 근거"


# ═══════════════════════════════════════════════════════════════════════
# Fix 305 — 전수 감사가 찾아낸 차단 요인 5건 (전부 실제로 확인된 것)
# ═══════════════════════════════════════════════════════════════════════

def test_BLOCKER4_사각지대에서_영구정지하지_않는다():
    """🚨 보유 명목이 「목표 잔량 ~ 목표+MIN_NOTIONAL」이면 청산분이
    MIN_NOTIONAL 미만이라 미실행 → 호출자가 fail-CLOSED 라 단계가 영원히 멈춘다.
    이 구간은 전량 청산으로 떨어져야 한다."""
    db = _DB(sym=_Sym(D("1"), D("1"), D("5")))
    for qty, px in ((D("24"), D("0.5")), (D("28"), D("0.5")), (D("13"), D("1"))):
        close, keep, why = T.compute_trim(db, "X", qty, px)
        assert close > 0, f"영구 정지: qty={qty} px={px} — {why}"
        if keep > 0:
            assert keep * px >= D("5"), why          # dust 안 만든다


def test_BLOCKER4_정말_못_파는_크기면_미실행():
    """보유 자체가 MIN_NOTIONAL 미만이면 전량 청산도 발주가 거부된다."""
    db = _DB(sym=_Sym(D("1"), D("1"), D("5")))
    close, _k, why = T.compute_trim(db, "X", D("8"), D("0.5"))   # 명목 4 < 5
    assert close == 0, why
    assert "청산 불가" in why


def test_BLOCKER2_재시도가_요청분을_넘지_않는다():
    """🚨 옛 코드 `retry_qty = post_position` 은 **남은 전부**를 던졌다.
    Fix 304 가 남기려던 10 USDT 까지 사라져 전략이 종료된다."""
    # 🚨 주석에 옛 코드를 인용해 두었으므로 **대입문**만 본다 (과잉 매칭 방지).
    import re
    assert not re.search(r"^\s*retry_qty = post_position\s*$", ESRC, re.M)
    assert "_shortfall = (requested_close_qty or Decimal(\"0\")) - _reduced" in ESRC
    assert "retry_qty = min(post_position," in ESRC


def test_BLOCKER1_단계전환중_전량정리는_주문을_안_지운다():
    """🚨 cancel_all_orders 가 아직 안 걸린 2·3단계 LIMIT 을 지워
    사다리가 통째로 사라진다."""
    assert "if is_full_close and not for_stage_transition:" in ESRC
    assert "for_stage_transition: bool = False," in ESRC


def test_BLOCKER1_단계전환중_STOPPING을_안_찍는다():
    """🚨 reconcile 이 포지션 수량을 안 보고 5분 뒤 MANUAL_CLEANUP_REQUIRED 를
    찍는다. EXIT 체결이 겹치면 STOPPED 로 확정돼 전략이 죽는다."""
    assert "단계 전환 중 전량 정리 — STOPPING 마킹 생략" in ESRC


def test_BLOCKER1_정리_호출이_전환플래그를_넘긴다():
    src = _fn_src("_trim_before_stage")
    assert "for_stage_transition=True" in src


def test_BLOCKER3_현재가_조회_실패가_예외로_새지_않는다():
    """🚨 `_fetch_current_mark_price` 는 실패 시 ValueError 를 던진다.
    감싸지 않으면 시세 오류가 곧 단계 진입 실패 알림이 된다 (15초 주기)."""
    src = _fn_src("_trim_before_stage")
    i_try = src.index("try:\n                    _mark = self._fetch_current_mark_price")
    i_call = src.index("_mark = self._fetch_current_mark_price")
    assert i_try <= i_call
    assert "except Exception as _me:" in src


def test_BLOCKER5_수동_다음단계도_정리를_거친다():
    """🚨 수동 「▶ 다음 단계」는 `enter_stage_at_market` 을 쓴다.
    여기를 빠뜨리면 손으로 누른 단계만 물타기가 된다."""
    assert "_trim_before_stage" in _fn_src("enter_stage_at_market")


def test_자동과_수동이_같은_코드를_쓴다():
    """두 경로가 각자 구현하면 한쪽만 고쳐지는 사고가 난다."""
    assert ESRC.count("def _trim_before_stage") == 1
    assert ESRC.count("self._trim_before_stage(strategy, stage_no)") == 2


def test_알림_쿨다운이_있다():
    """🚨 15초 주기 워커 + fail-CLOSED = 쿨다운 없으면 하루 5,760건."""
    from app.workers import stage_trigger_worker as W
    src = Path(W.__file__).read_text(encoding="utf-8")
    blk = src[src.index("[시스템 오류] Stage 자동 진입 실패") - 2000:]
    blk = blk[:blk.index("[시스템 오류] Stage 자동 진입 실패") + 1200]
    assert "stage_trigger_alert:" in blk
    assert "nx=True" in blk and "ex=1800" in blk

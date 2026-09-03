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
    close, keep, why, _act = T.compute_trim(db, "AKEUSDT", D("34417"), D("0.0224"))
    assert keep * D("0.0224") >= D("10"), why      # 잔량 명목 >= 10
    assert close + keep == D("34417"), why         # 합이 보유량
    assert close > 0


def test_1단계_100이든_1000이든_같은_10을_남긴다():
    """사장님: "1단계 100이든 1000이든 10usdt 남기고"."""
    db = _DB(sym=ALT)
    px = D("0.05")
    keeps = []
    for qty in ("2000", "20000", "200000"):          # 명목 100 / 1000 / 10000
        _c, k, _w, _act = T.compute_trim(db, "X", D(qty), px)
        keeps.append(k * px)
    assert len(set(keeps)) == 1, f"잔량이 포지션 크기에 따라 달라졌다: {keeps}"
    assert keeps[0] >= D("10")


def test_잔량목표가_보유량_이상이면_정리하지_않는다():
    """🚨 Fix 324: 전량이 아니라 **SKIP** 이다.

    사장님 사다리 1단계가 이 경우다 — 자본 10 이고 목표 잔량도 증거금 10.
    사장님 "첫진입이 10이라 손절없이 그냥 2단계 300으로 진입", 그리고 주신
    수치도 2단계 총 증거금이 310(=10+300) 이라 1단계가 살아 있다.
    손절 경로는 SKIP 을 받으면 스스로 전량으로 떨어지므로 양쪽 다 옳다."""
    db = _DB(sym=ALT)
    close, keep, why, act = T.compute_trim(db, "X", D("100"), D("0.05"))   # 명목 5
    assert close == 0 and act == T.ACTION_SKIP, why


# ── 🚨 dust 방지 ─────────────────────────────────────────────────────

def test_MIN_NOTIONAL_이_10보다_크면_그만큼_남긴다():
    """ETHUSDT(20) / BTCUSDT(50). 10 을 남기면 못 파는 dust 가 된다."""
    db = _DB(sym=_Sym(D("0.001"), D("0.001"), D("20")))
    _c, keep, why, _act = T.compute_trim(db, "ETHUSDT", D("10"), D("3000"))
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
        close, keep, why, _act = T.compute_trim(db, "X", D("100000"), px)
        if close == 0:
            continue
        assert keep * px >= mn, f"dust 발생: keep={keep} px={px} mn={mn} — {why}"


def test_잔량은_stepSize_배수다():
    for step in (D("1"), D("0.1"), D("0.001")):
        db = _DB(sym=_Sym(step, step, D("5")))
        close, keep, _w, _act = T.compute_trim(db, "X", D("100000"), D("1.7"))
        assert keep % step == 0, keep
        assert close % step == 0, close


def test_청산분이_최소주문금액_미만이면_정리하지_않는다():
    """🚨 Fix 324: SKIP 이다 (전량 폴백 철회).

    Fix 305 는 「영구 정지」를 막으려 전량으로 떨어뜨렸는데, Fix 316 이
    SKIP/BLOCK 을 도입하면서 그 이유가 사라졌다 — SKIP 이면 진입이 그대로
    진행되므로 정지하지 않는다. 전량으로 두면 사장님 1단계가 통째로 잘린다."""
    db = _DB(sym=_Sym(D("1"), D("1"), D("5")))
    close, keep, why, act = T.compute_trim(db, "X", D("21"), D("0.5"))
    assert close == 0 and act == T.ACTION_SKIP, why


# ── 🚨 불확실하면 아무것도 하지 않는다 ───────────────────────────────

def test_거래소_필터가_없으면_미실행():
    """잘못 청산하면 실제 자금이 사라진다. 되돌릴 수 없다."""
    close, _k, why, _act = T.compute_trim(_DB(sym=None), "X", D("1000"), D("1"))
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
    close, _k, _w, _act = T.compute_trim(_DB(boom=True), "X", D("1000"), D("1"))
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
    assert "from app.services.stage_trim import (" in ESRC
    assert "compute_trim, cumulative_loss_exceeded, trim_enabled," in ESRC
    assert "if trim_enabled(self.db, strategy) and stage_no > 1:" in ESRC


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
    """🚨 이 구간이 **BLOCK 이면** 호출자(fail-CLOSED)가 단계를 영원히 멈춘다.

    Fix 324 이후 SKIP 으로 떨어지므로 진입은 그대로 진행된다 = 정지하지 않는다.
    핵심은 「BLOCK 이 아닐 것」이지 「청산할 것」이 아니다."""
    db = _DB(sym=_Sym(D("1"), D("1"), D("5")))
    for qty, px in ((D("24"), D("0.5")), (D("28"), D("0.5")), (D("13"), D("1"))):
        close, keep, why, act = T.compute_trim(db, "X", qty, px)
        assert act != T.ACTION_BLOCK, f"영구 정지: qty={qty} px={px} — {why}"
        if close > 0 and keep > 0:
            assert keep * px >= D("5"), why          # dust 안 만든다


def test_BLOCKER4_정말_못_파는_크기면_미실행():
    """보유 자체가 MIN_NOTIONAL 미만이면 전량 청산도 발주가 거부된다."""
    db = _DB(sym=_Sym(D("1"), D("1"), D("5")))
    close, _k, why, _act = T.compute_trim(db, "X", D("8"), D("0.5"))   # 명목 4 < 5
    assert close == 0, why
    assert "정리 불필요" in why   # Fix 316: SKIP 으로 바뀜


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


# ═══════════════════════════════════════════════════════════════════════
# Fix 306 — 사장님 "손실 그래도 계산되어야 하는거 아닌가?"
# ═══════════════════════════════════════════════════════════════════════

class _Strat:
    def __init__(self, cum):
        self.cumulative_realized_loss = cum


def test_상한_미설정이면_무제한():
    """기본 동작을 바꾸지 않는다 — 상한은 사장님이 넣어야 작동."""
    over, _w = T.cumulative_loss_exceeded(_DB(), _Strat(D("9999")))
    assert over is False


def test_누적손실이_상한을_넘으면_중단():
    db = _DB({T.SETTING_MAX_CUM_LOSS: "60"})
    assert T.cumulative_loss_exceeded(db, _Strat(D("60")))[0] is True
    assert T.cumulative_loss_exceeded(db, _Strat(D("120")))[0] is True
    assert T.cumulative_loss_exceeded(db, _Strat(D("59.99")))[0] is False


def test_부호와_무관하게_절대값으로_본다():
    db = _DB({T.SETTING_MAX_CUM_LOSS: "60"})
    assert T.cumulative_loss_exceeded(db, _Strat(D("-70")))[0] is True


def test_손상값이나_DB장애면_무제한():
    """🚨 여기서 fail-closed 하면 모든 사다리가 멈춘다."""
    for bad in ("", "abc", "0", "-1"):
        assert T.cumulative_loss_exceeded(_DB({T.SETTING_MAX_CUM_LOSS: bad}),
                                          _Strat(D("999")))[0] is False, bad
    assert T.cumulative_loss_exceeded(_DB(boom=True), _Strat(D("999")))[0] is False


def test_필드가_없어도_안_터진다():
    assert T.cumulative_loss_exceeded(_DB(), object())[0] is False


def test_단계진입_게이트에_연결돼_있다():
    src = _fn_src("_trim_before_stage")
    assert "cumulative_loss_exceeded(self.db, strategy)" in src
    assert "raise ValueError" in src


def test_누적손실_확인이_청산보다_먼저다():
    """🚨 순서가 뒤바뀌면 「상한을 넘었는데 청산은 이미 나간」 상태가 된다."""
    src = _fn_src("_trim_before_stage")
    assert src.index("cumulative_loss_exceeded") < src.index("emergency_close_position")


def test_화면이_실현손익을_합산한다():
    """🚨 미실현만 보면 단계 청산으로 확정된 손실이 화면에서 사라진다."""
    js = (Path(E.__file__).resolve().parents[1] / "static" / "js"
          / "strategies-list.js").read_text(encoding="utf-8")
    assert "totalRealized += Number(s.realized_pnl || 0);" in js
    assert "const totalNetPnl = totalRealized + totalUnrealized;" in js
    assert "(totalNetPnl / totalMarginUsed * 100)" in js


def test_retry모드와_정리모드_충돌_가드():
    """🚨 둘 다 켜면 STAGE_N_OPEN 이 건너뛰어져 사다리가 영원히 멈춘다.

    Fix 323 이 조건을 넓혔다 — trim 이 꺼져 있어도 **손절이 명시된 전략**이면
    정상 단계 진입을 막지 않는다 (OBV 모달이 retry 를 켜 두던 문제).
    """
    from app.workers import stage_trigger_worker as W
    src = Path(W.__file__).read_text(encoding="utf-8")
    assert "if (not _trim_on and not _sl_explicit" in src
    assert '_sl_explicit' in src


# ═══════════════════════════════════════════════════════════════════════
# Fix 311 — 사장님 "첫진입이 10이라 손절없이 그냥"
# ═══════════════════════════════════════════════════════════════════════

def test_1단계_10USDT는_정리하지_않는다():
    """🚨 1단계 10 x 레버2 = 명목 20. 10 을 남기면 **절반만 청산**된다.
    사장님 사다리에서 1단계는 「자리 탐색」이라 그대로 둔다."""
    db = _DB(sym=ALT)
    close, keep, why, _act = T.compute_trim(db, "X", D("400"), D("0.05"))   # 명목 20
    assert close == 0, why
    assert "손절없이 그냥" in why


def test_2단계급_큰_포지션은_정상_정리된다():
    """명목 600 (2단계 300 x 레버2) → 10 남기고 590 청산."""
    db = _DB(sym=ALT)
    close, keep, why, _act = T.compute_trim(db, "X", D("12000"), D("0.05"))  # 명목 600
    assert close > 0, why
    assert keep * D("0.05") >= D("10"), why


def test_경계_비율을_설정으로_바꿀_수_있다():
    assert T.min_trim_ratio(_DB()) == D("2")
    assert T.min_trim_ratio(_DB({T.SETTING_MIN_TRIM_RATIO: "5"})) == D("5")
    # 0 = 비율 검사 끔
    db = _DB({T.SETTING_MIN_TRIM_RATIO: "0"}, sym=ALT)
    assert T.compute_trim(db, "X", D("400"), D("0.05"))[0] > 0


def test_손상값이면_기본_2배():
    for bad in ("", "abc", "-1", "9999"):
        assert T.min_trim_ratio(_DB({T.SETTING_MIN_TRIM_RATIO: bad})) == D("2"), bad


# ═══════════════════════════════════════════════════════════════════════
# Fix 312 — 「모니터링 후 좋은 포지션에 진입」 (v219 사다리 전용)
# ═══════════════════════════════════════════════════════════════════════

def test_세_방식_중_v219_사다리에만_적용된다():
    """🚨 기본방식은 「정해진 트리거에 즉시」, OBV 자동은 이미 4중 게이트가 있다.
    거기에 얹으면 사장님 설계가 깨지고 Fix 232 가 없앤 중복 게이트가 부활한다."""
    from app.services import stage_entry_timing as W
    db = _DB({W.SETTING_ENABLED: "1"})
    # v219 사다리 → 적용 대상
    ok, why = W.should_enter_now(db, None, "X", "SHORT", "auto_bb_break_SAJANGNIM_TOP")
    assert "대기 대상 아님" not in why
    # 기본방식/볼밴/수동 → 미적용
    for st in ("bb_mid_line", "pump_split", "DYNAMIC_SHORT", None, ""):
        ok2, why2 = W.should_enter_now(db, None, "X", "SHORT", st)
        assert ok2 is True and "대기 대상 아님" in why2, st


def test_LONG은_기본적으로_대기하지_않는다():
    """실측: SHORT +15.3%p / LONG -1.4%p."""
    from app.services import stage_entry_timing as W
    db = _DB({W.SETTING_ENABLED: "1"})
    ok, why = W.should_enter_now(db, None, "X", "LONG", "auto_bb_break_SAJANGNIM_BOTTOM")
    assert ok is True and "대기 대상 아님" in why


def test_기본은_꺼져있다():
    from app.services import stage_entry_timing as W
    assert W.wait_enabled(_DB()) is False
    assert W.should_enter_now(_DB(), None, "X", "SHORT", "auto_bb_break_SAJANGNIM_TOP")[0] is True


def test_캔들_조회_실패는_진입을_허용한다():
    """🚨 fail-closed 하면 조회가 한 번 실패할 때마다 단계가 멈춘다."""
    from app.services import stage_entry_timing as W

    class _Boom:
        def get_klines(self, **_k):
            raise RuntimeError("api down")

    db = _DB({W.SETTING_ENABLED: "1"})
    ok, why = W.should_enter_now(db, _Boom(), "X", "SHORT", "auto_bb_break_SAJANGNIM_TOP")
    assert ok is True and "fail-open" in why


def test_대기가_정리보다_먼저다():
    """🚨 순서가 뒤바뀌면 「좋은 자리가 아닌데 청산은 이미 나간」 상태가 된다."""
    src = _fn_src("_trim_before_stage")
    assert src.index("stage_entry_timing") < src.index("stage_trim import")


def test_실측_근거가_모듈에_남아_있다():
    from app.services import stage_entry_timing as W
    doc = W.__doc__ or ""
    assert "+15.3%p" in doc and "47.6%" in doc
    assert "기본방식" in doc and "OBV 자동" in doc, "세 방식 구분이 적혀 있어야 한다"


# ═══════════════════════════════════════════════════════════════════════
# Fix 313 — 전역 스위치 하나가 다른 전략의 설계를 부수면 안 된다
# ═══════════════════════════════════════════════════════════════════════

class _Strat2:
    def __init__(self, mode, sid=1, sym="X"):
        self.capital_management_mode = mode
        self.id, self.symbol = sid, sym


def test_볼밴분할은_절대_정리하지_않는다():
    """🚨 `pump_split` 은 100→200→500 으로 **일부러 물타기**하는 설계다.
    단계마다 청산하면 그 전략이 통째로 망가진다. 설정으로도 못 켜게 한다."""
    db = _DB({T.SETTING_ENABLED: "1"})
    assert T.trim_enabled(db, _Strat2("split_entry")) is False
    assert "split_entry" in T.ALWAYS_EXCLUDED_MODES


def test_그_외_전략은_정상_적용():
    db = _DB({T.SETTING_ENABLED: "1"})
    for mode in ("", None, "preserve", "reset"):
        assert T.trim_enabled(db, _Strat2(mode)) is True, mode


def test_설정으로_더_제외할_수_있다():
    db = _DB({T.SETTING_ENABLED: "1", T.SETTING_EXCLUDE_MODES: "preserve, reset"})
    assert T.trim_enabled(db, _Strat2("preserve")) is False
    assert T.trim_enabled(db, _Strat2("other")) is True


def test_스위치가_꺼져있으면_전략과_무관하게_꺼짐():
    assert T.trim_enabled(_DB(), _Strat2("")) is False


def test_전략을_안_넘기면_전역판정만():
    """구 호출부 호환 — 인자 없이도 동작해야 한다."""
    assert T.trim_enabled(_DB({T.SETTING_ENABLED: "1"})) is True


def test_모든_호출부가_strategy를_넘긴다():
    """🚨 한 곳이라도 안 넘기면 그 경로에서 볼밴 분할이 청산된다."""
    import re
    from pathlib import Path
    from app.workers import stage_trigger_worker as W
    for src in (ESRC, Path(W.__file__).read_text(encoding="utf-8")):
        for m in re.finditer(r"trim_enabled\(([^)]*)\)", src):
            args = m.group(1)
            if "db" not in args:
                continue
            assert "strategy" in args, f"strategy 를 안 넘긴다: trim_enabled({args})"


# ═══════════════════════════════════════════════════════════════════════
# Fix 314 — 「설정만 수정」이 OBV 전략을 기본전략으로 강등시키던 버그
# ═══════════════════════════════════════════════════════════════════════

def test_템플릿_복사가_trigger_mode를_보존한다():
    """🚨 빠뜨리면 server_default='PRICE_DOWN_PCT' 가 들어가
    OBV 자동 전략이 수정 한 번에 기본전략이 된다."""
    from pathlib import Path
    from app.api.v1.strategies import control as C
    src = Path(C.__file__).read_text(encoding="utf-8")
    blk = src[src.index("new_tpl = StrategyTemplate("):]
    blk = blk[:blk.index("\n    )")]
    assert "trigger_mode=old_tpl.trigger_mode," in blk


def test_모델_기본값이_PRICE_DOWN_PCT_임을_확인():
    """이 기본값 때문에 누락이 조용한 강등이 된다 — 근거 고정."""
    from pathlib import Path
    from app.models import strategy_template as M
    src = Path(M.__file__).read_text(encoding="utf-8")
    assert 'server_default="PRICE_DOWN_PCT"' in src or "server_default='PRICE_DOWN_PCT'" in src


# ═══════════════════════════════════════════════════════════════════════
# Fix 316 — 「정리 불필요」와 「정리 불가」는 다르다
# ═══════════════════════════════════════════════════════════════════════

def test_1단계_소액은_SKIP이지_BLOCK이_아니다():
    """🚨 이것이 Fix 311 이 만든 사고다. 사장님 사다리 1단계
    (10 USDT x 레버2 = 명목 20)가 「진입 중단」으로 처리돼 2단계가 막혔다."""
    db = _DB(sym=ALT)
    close, keep, why, act = T.compute_trim(db, "X", D("400"), D("0.05"))   # 명목 20
    assert close == 0
    assert act == T.ACTION_SKIP, f"BLOCK 이면 2단계가 막힌다 — {why}"


def test_판정_불가만_BLOCK():
    """필터·가격이 없으면 정리 여부를 알 수 없다 → 물타기를 막기 위해 중단."""
    assert T.compute_trim(_DB(sym=None), "X", D("1000"), D("1"))[3] == T.ACTION_BLOCK
    assert T.compute_trim(_DB(sym=_Sym(D("0"), D("1"), D("5"))), "X", D("1000"), D("1"))[3] \
        == T.ACTION_BLOCK


def test_팔_수_없는_크기는_SKIP():
    """보유가 MIN_NOTIONAL 미만이면 정리할 것이 없다 → 그냥 진입."""
    db = _DB(sym=ALT)
    close, _k, _w, act = T.compute_trim(db, "X", D("8"), D("0.5"))   # 명목 4
    assert close == 0 and act == T.ACTION_SKIP


def test_정상_정리는_TRIM():
    db = _DB(sym=ALT)
    close, keep, _w, act = T.compute_trim(db, "X", D("12000"), D("0.05"))
    assert close > 0 and act == T.ACTION_TRIM


def test_남길_만큼_크지_않으면_SKIP():
    """Fix 324: 전량 폴백을 철회했다 — 1단계를 자르지 않기 위해서."""
    db = _DB(sym=ALT)
    close, _k, _w, act = T.compute_trim(db, "X", D("21"), D("0.5"))
    assert close == 0 and act == T.ACTION_SKIP


def test_호출부가_세_행동을_모두_구분한다():
    src = _fn_src("_trim_before_stage")
    assert "if _act == ACTION_SKIP:" in src, "SKIP 을 중단으로 처리하면 1단계가 막힌다"
    assert "elif _act == ACTION_BLOCK:" in src
    assert "elif _close_qty > 0:" in src
    # SKIP 분기에는 raise 가 없어야 한다
    skip_blk = src[src.index("if _act == ACTION_SKIP:"):src.index("elif _act == ACTION_BLOCK:")]
    assert "raise" not in skip_blk


def test_포지션_조회_실패는_중단한다():
    """🚨 None 을 falsy 로 흘리면 trim 을 건너뛰고 진입 = 물타기로 조용히 복귀.
    주석은 fail-CLOSED 라고 선언했는데 코드가 반대였다."""
    src = _fn_src("_trim_before_stage")
    assert "if _cur_qty is None:" in src
    blk = src[src.index("if _cur_qty is None:"):]
    blk = blk[:blk.index("if _cur_qty > 0:")]
    assert "raise ValueError" in blk

"""💰 Fix 333 — 투입 자본이 화면에서 거짓말하지 않게.

사장님 2026-09-03: "수도(수동) 포지션 추가를 500 두번을 했는데 왜 이런 나오는거지"
                  화면 `100 / 3500  3%` — 실제 증거금은 **1,124 USDT**

## 왜 위험했나

`invested_capital` 은 **전 코드베이스에서 대입된 적이 없다**(선언 + default=0 뿐).
살아있는 전략 13건 전부 0 이었고, 화면이 다른 값으로 퍼센트를 내고 있었다.

🚨 숫자가 틀리면 사장님 판단이 오염된다. 실제로 그 일이 났다:

    화면 정점 +17.34% → +8.20%   ("최고점에서 -5% 회귀했는데 왜 청산이 안된거지")
    실제 ROI  +0.98%  → +0.51%   (회귀 -0.47%p = 트레일링이 **정상 동작**이었다)
"""
from decimal import Decimal

from app.services import capital_accounting as C


D = Decimal


# ─────────────────────────────────────────────────────────────────────
# 스텁 — orders 테이블만 흉내낸다
# ─────────────────────────────────────────────────────────────────────

class _Strategy:
    def __init__(self, sid=1, leverage=2, invested=0, qty=None, avg=None):
        self.id = sid
        self.leverage = leverage
        self.invested_capital = D(str(invested))
        # Fix 333-b: 수량·평단이 있으면 그것이 우선. None 이면 주문 기반 폴백.
        self.current_position_qty = D(str(qty)) if qty is not None else None
        self.avg_entry_price = D(str(avg)) if avg is not None else None


class _DB:
    """`select(...).where(...)` 체인을 받아 purpose 로만 갈라 행을 돌려준다."""

    def __init__(self, entries, exits):
        # (executed_qty, orig_qty, avg_price, price)
        self._e = entries
        self._x = exits

    def execute(self, stmt):
        txt = str(stmt)
        rows = self._x if "'EXIT'" in txt or '"EXIT"' in txt else self._e
        # 파라미터가 바인딩으로 빠지는 경우를 대비해 compile 로 한 번 더 본다
        try:
            compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
            rows = self._x if "'EXIT'" in compiled else self._e
        except Exception:
            pass

        class _R:
            def all(self_inner):
                return rows
        return _R()


def _mk(entries, exits, leverage=2, invested=0):
    return _DB(entries, exits), _Strategy(leverage=leverage, invested=invested)


# ═════════════════════════════════════════════════════════════════════
# 🎯 실측 재현 — #2090 MAGMAUSDT (2026-09-03)
# ═════════════════════════════════════════════════════════════════════

def test_실서버_2090_을_재현한다():
    """거래소 실제 isolatedWallet 1,124.42 와 오차 0.1% 이내여야 한다.

    ENTRY  2473 x 0.40427 + 2446 x 0.40852 + 2445 x 0.40935 = 2,999.86
    EXIT   1841 x 0.40887                                   =   752.73
    순 명목 2,247.13 ÷ 레버 2                                = 1,123.57
    """
    db, st = _mk(
        entries=[
            (D("2473"), D("2473"), D("0.40426950"), None),
            (D("2446"), D("2446"), D("0.40852030"), None),
            (D("2445"), D("2445"), D("0.40934740"), None),
        ],
        exits=[(D("1841"), D("1841"), D("0.40886760"), None)],
        leverage=2,
    )
    got = C.compute_invested_capital(db, st)
    assert got is not None
    real = D("1124.42428696")          # 거래소 isolatedWallet
    assert abs(got - real) / real < D("0.001"), f"{got} vs {real}"


def test_수동_추가가_반영된다():
    """🚨 사장님 질문의 핵심 — 수동 추가 500 x 2 가 잡혀야 한다."""
    only_first = _mk(entries=[(D("2473"), D("2473"), D("0.40427"), None)],
                     exits=[], leverage=2)
    with_adds = _mk(
        entries=[
            (D("2473"), D("2473"), D("0.40427"), None),
            (D("2446"), D("2446"), D("0.40852"), None),   # 수동 추가 1
            (D("2445"), D("2445"), D("0.40935"), None),   # 수동 추가 2
        ],
        exits=[], leverage=2)
    a = C.compute_invested_capital(*only_first)
    b = C.compute_invested_capital(*with_adds)
    assert b > a * D("2.9"), f"추가가 반영 안 됐다: {a} → {b}"


# ═════════════════════════════════════════════════════════════════════
# 계산 규칙
# ═════════════════════════════════════════════════════════════════════

def test_레버리지로_나눈다():
    """명목이 아니라 **증거금**이다."""
    e = [(D("100"), D("100"), D("10"), None)]      # 명목 1000
    assert C.compute_invested_capital(*_mk(e, [], leverage=1)) == D("1000")
    assert C.compute_invested_capital(*_mk(e, [], leverage=2)) == D("500")
    assert C.compute_invested_capital(*_mk(e, [], leverage=10)) == D("100")


def test_부분_청산이_빠진다():
    e = [(D("100"), D("100"), D("10"), None)]      # 1000
    x = [(D("25"), D("25"), D("10"), None)]        # 250
    assert C.compute_invested_capital(*_mk(e, x, leverage=2)) == D("375")


def test_진입이_없으면_0():
    assert C.compute_invested_capital(*_mk([], [], leverage=2)) == D("0")


def test_청산이_진입보다_커도_음수가_안_된다():
    """기록 오류로 음수 증거금이 나오면 화면이 더 이상해진다."""
    e = [(D("10"), D("10"), D("10"), None)]
    x = [(D("99"), D("99"), D("10"), None)]
    assert C.compute_invested_capital(*_mk(e, x, leverage=2)) == D("0")


def test_avg_price_가_없으면_price_로_대체():
    e = [(D("100"), D("100"), None, D("10"))]
    assert C.compute_invested_capital(*_mk(e, [], leverage=1)) == D("1000")


def test_executed_qty_가_없으면_orig_qty_로_대체():
    e = [(None, D("100"), D("10"), None)]
    assert C.compute_invested_capital(*_mk(e, [], leverage=1)) == D("1000")


def test_수량이나_가격이_둘_다_없으면_그_행을_건너뛴다():
    """🚨 0 으로 치면 합계가 조용히 작아져 「덜 넣은 것처럼」 보인다."""
    e = [(D("100"), D("100"), D("10"), None), (None, None, None, None)]
    assert C.compute_invested_capital(*_mk(e, [], leverage=1)) == D("1000")


def test_레버리지가_0이거나_None이면_1로_본다():
    e = [(D("100"), D("100"), D("10"), None)]
    for lev in (0, None):
        assert C.compute_invested_capital(*_mk(e, [], leverage=lev)) == D("1000")


# ═════════════════════════════════════════════════════════════════════
# sync — 기존 값을 함부로 덮지 않는다
# ═════════════════════════════════════════════════════════════════════

def test_sync_가_값을_채운다():
    db, st = _mk([(D("100"), D("100"), D("10"), None)], [], leverage=2, invested=0)
    changed, why = C.sync_invested_capital(db, st)
    assert changed is True and st.invested_capital == D("500"), why


def test_sync_는_같은_값이면_건드리지_않는다():
    db, st = _mk([(D("100"), D("100"), D("10"), None)], [], leverage=2, invested=500)
    changed, _why = C.sync_invested_capital(db, st)
    assert changed is False and st.invested_capital == D("500")


def test_계산_불가면_기존_값을_유지한다():
    """🚨 None 을 0 으로 바꾸면 그게 바로 이 Fix 가 고치려는 거짓 표시다."""
    class _Boom:
        def execute(self, _s):
            raise RuntimeError("DB 끊김")
    st = _Strategy(invested=777)
    assert C.compute_invested_capital(_Boom(), st) is None
    changed, why = C.sync_invested_capital(_Boom(), st)
    assert changed is False and st.invested_capital == D("777"), why


# ═════════════════════════════════════════════════════════════════════
# 🚨 실제로 호출되는가 (Fix 247/318 의 교훈)
# ═════════════════════════════════════════════════════════════════════

def test_reconcile_가_실제로_부른다():
    """🚨 안 부르면 이 모듈은 코드에만 있고 화면은 계속 거짓말한다."""
    import ast
    from pathlib import Path
    from app.workers import reconcile_worker as W
    src = Path(W.__file__).read_text(encoding="utf-8")
    assert "sync_invested_capital" in src, "reconcile 이 투입자본을 동기화하지 않는다"
    # 포지션 동기화(current_position_qty 대입) 와 **같은 블록**에 있어야 한다
    tree = ast.parse(src)
    assert "strategy.current_position_qty = exchange_position_amt" in src
    i_pos = src.index("strategy.current_position_qty = exchange_position_amt")
    i_cap = src.index("sync_invested_capital")
    assert 0 < i_cap - i_pos < 3000, "포지션 동기화 자리에서 멀다 — 다른 경로일 수 있다"


def test_실측_근거가_주석에_남아_있다():
    """다음에 무심코 지우지 않도록."""
    from pathlib import Path
    src = Path(C.__file__).read_text(encoding="utf-8")
    for token in ("1,124", "2090", "+17.34%", "+0.98%", "대입된 적이 없다"):
        assert token in src, token


# ═════════════════════════════════════════════════════════════════════
# 🚨 Fix 333-b — 「Σ진입 − Σ청산」은 틀린 식이었다 (#2116 이 반증)
#
#   진입 명목 1,401.50 − 청산 명목 1,327.96 = 73.54 ÷ 2 = 36.77   ← 틀림
#   실제 잔량 689주 × 평단 0.02970 ÷ 2                 = 10.23   ← 맞음
#
#   청산가 < 평단이라 차액에 실현손실 -53 이 섞였다. 증거금은 손익과 섞이면 안 된다.
# ═════════════════════════════════════════════════════════════════════

def test_Fix333b_실서버_2116_을_재현한다():
    """손절로 46,492주를 0.02856 에 판 뒤 689주 남은 상태."""
    db = _DB(
        entries=[
            (D("6890"), D("6890"), D("0.02902600"), None),
            (D("20313"), D("20313"), D("0.02956200"), None),
            (D("19978"), D("19978"), D("0.03008410"), None),
        ],
        exits=[(D("46492"), D("46492"), D("0.02856300"), None)],
    )
    st = _Strategy(leverage=2, qty="689", avg="0.02970482")
    got = C.compute_invested_capital(db, st)
    assert got is not None
    assert abs(got - D("10.23")) < D("0.05"), f"잔량 증거금이 아니다: {got}"
    assert got < D("20"), f"옛 식(36.77)이 다시 쓰였다: {got}"


def test_Fix333b_2090_도_수량x평단이_거래소와_더_가깝다():
    """거래소 isolatedWallet 1,124.42 — 수량x평단 = 1,124.95 (오차 0.05%)."""
    st = _Strategy(leverage=2, qty="5523", avg="0.40736743")
    got = C.compute_invested_capital(_DB([], []), st)
    real = D("1124.42428696")
    assert abs(got - real) / real < D("0.001"), f"{got} vs {real}"


def test_Fix333b_수량이_0이면_0():
    st = _Strategy(leverage=2, qty="0", avg="0.5")
    assert C.compute_invested_capital(_DB([(D("1"), D("1"), D("1"), None)], []), st) == D("0")


def test_Fix333b_평단_결손이면_주문_기반_폴백():
    """수량은 있는데 평단이 없으면 옛 근사식으로 떨어진다 (None 보다 낫다)."""
    db = _DB([(D("100"), D("100"), D("10"), None)], [])
    st = _Strategy(leverage=2, qty="100", avg=None)
    assert C.compute_invested_capital(db, st) == D("500")


def test_Fix333b_손익이_증거금에_섞이지_않는다():
    """같은 잔량이면 청산가가 얼마였든 증거금은 같아야 한다."""
    e = [(D("1000"), D("1000"), D("1.0"), None)]
    st = _Strategy(leverage=1, qty="500", avg="1.0")
    a = C.compute_invested_capital(_DB(e, [(D("500"), D("500"), D("0.8"), None)]), st)  # 손실 청산
    b = C.compute_invested_capital(_DB(e, [(D("500"), D("500"), D("1.2"), None)]), st)  # 이익 청산
    assert a == b == D("500"), f"청산가에 따라 증거금이 달라졌다: {a} vs {b}"


def test_Fix333b_반증_근거가_주석에_남아_있다():
    from pathlib import Path
    src = Path(C.__file__).read_text(encoding="utf-8")
    for token in ("2116", "36.77", "10.23", "실현손실"):
        assert token in src, token

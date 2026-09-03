r"""💰 투입 자본 집계 — 화면 숫자가 거짓말하지 않게 (Fix 333).

## 사장님이 발견한 것 (2026-09-03)

  "수도(수동) 포지션 추가를 500 두번을 했는데 왜 이런 나오는거지"
  화면: `100 / 3500  3%`

실제로는 증거금 **1,124 USDT** 가 들어가 있었다. 화면은 **3%** 라고 했다.

## 원인 — 이 필드는 **한 번도 대입된 적이 없다**

`StrategyInstance.invested_capital` 은 모델에 선언되고(`default=0`) 화면·알림·
export·학습이 전부 읽는데, **전 코드베이스에서 대입하는 코드가 0곳**이었다.

    grep -rn "invested_capital\s*=" app/  →  stream_service.py:123 (알림 함수 인자) 하나뿐

게다가 `api/v1/strategies/lifecycle.py:117` docstring 은
「증거금 추가와 다름: qty 도 늘어남 + 평단 갱신 + **invested_capital 증가**」
라고 적어 놓았지만 **코드는 그 일을 하지 않는다.** 주석이 거짓이었다.

→ 살아있는 전략 13건이 **전부 0** 이었고, 화면은 다른 값(1단계 계획 자본)으로
  퍼센트를 계산해 **완전히 틀린 숫자**를 보여주고 있었다.

## 🚨 왜 이것이 위험한가

숫자가 틀리면 **사장님 판단이 오염된다.** 실제로 그 일이 일어났다:

    화면 정점 +17.34% → 현재 +8.20%   ("최고점에서 -5% 회귀했는데 왜 청산이 안된거지")
    실제 ROI  +0.98%  → 현재 +0.51%   (회귀폭 -0.47%p)

사장님은 트레일링이 고장난 줄 아셨지만 실제로는 **정상 동작**이었다.
화면이 `17.30 / 100` 으로 퍼센트를 낸 것이 원인이다.

## 어떻게 세는가 — **체결된 주문**에서 역산한다

경로마다 대입하는 방식은 **반드시 하나를 빠뜨린다.** 이 저장소가 그 사고를
반복해서 겪었다(Fix 318 은 손절 함수 두 개 중 하나만 고쳤고, Fix 315 는 마커를
저장하는 코드가 0곳이었다). 진입 경로는 최소 다섯이다 —
1단계 진입 / 단계 진입 / 수동 포지션 추가 / 피라미딩 / 재진입.

그래서 **단일 진실을 주문 테이블에 둔다**:

    투입 증거금 = (Σ ENTRY 체결명목 − Σ EXIT 체결명목) ÷ 레버리지

어느 경로로 들어왔든 주문은 반드시 남으므로 **자동으로 잡힌다.**

### 실측 검증 (#2090 MAGMAUSDT, 2026-09-03)

    ENTRY  2473 x 0.40427 + 2446 x 0.40852 + 2445 x 0.40935 = 2,999.86
    EXIT   1841 x 0.40887                                   =   752.73
    순 명목 2,247.13 ÷ 레버 2                                = **1,123.57**
    거래소 실제 isolatedWallet                                = **1,124.42**
    오차 0.08% ✅

## ⚠️ 한계

- **CANCELED 주문은 세지 않는다** (체결이 아니다). 실제로 ENTRY 952건이 취소 상태다.
- 부분 청산이 있으면 순 명목이 줄어드는데, 이는 「지금 묶여 있는 증거금」에 해당한다.
  「누적으로 얼마를 넣었나」와는 다르다 — 화면이 묻는 것은 전자다.
- 수수료·펀딩비는 반영하지 않는다. 증거금 지표이지 손익 지표가 아니다.
- 거래소 `isolatedWallet` 과 미세하게 다를 수 있다(체결가 반올림). 판단에는 무해하다.
"""
from __future__ import annotations

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

__all__ = ["compute_invested_capital", "sync_invested_capital"]

ZERO = Decimal("0")


def _filled_notional(db, strategy_id: int, purpose: str) -> Decimal:
    """해당 용도의 **체결된** 주문 명목가치 합.

    수량은 `executed_qty` 를 쓰고 없으면 `orig_qty` 로, 가격은 `avg_price` 를 쓰고
    없으면 `price` 로 대체한다. 둘 다 없으면 그 주문은 건너뛴다
    (🚨 0 으로 치면 합계가 조용히 작아져 「덜 넣은 것처럼」 보인다).
    """
    from sqlalchemy import select
    from app.models.order import Order

    rows = db.execute(
        select(Order.executed_qty, Order.orig_qty, Order.avg_price, Order.price)
        .where(Order.strategy_instance_id == strategy_id)
        .where(Order.purpose == purpose)
        .where(Order.status == "FILLED")
    ).all()

    total = ZERO
    for eq, oq, ap, px in rows:
        qty = eq if eq is not None else oq
        prc = ap if ap is not None else px
        if qty is None or prc is None:
            continue
        try:
            total += abs(Decimal(str(qty))) * abs(Decimal(str(prc)))
        except Exception:      # 파싱 실패한 한 행이 전체를 망치면 안 된다
            continue
    return total


def compute_invested_capital(db, strategy) -> Decimal | None:
    """지금 이 전략에 묶여 있는 **증거금**(USDT).

    Returns:
        계산값. 판정 불가면 **None** — 호출자는 기존 값을 그대로 둔다.

    🚨 None 을 0 으로 바꾸지 마라. 0 은 「안 넣었다」는 뜻이고, 그것이 바로
       이 Fix 가 고치려는 거짓 표시다.
    """
    try:
        lev = Decimal(str(getattr(strategy, "leverage", None) or 1))
        if lev <= 0:
            lev = Decimal("1")

        # ═══════════════════════════════════════════════════════════════
        # 🚨 Fix 333-b (같은 날 정정): 「Σ진입명목 − Σ청산명목」은 **틀린 식**이었다.
        #
        #   #2116 BULLAUSDT 로 반증됐다:
        #     진입 명목 1,401.50 − 청산 명목 1,327.96 = 73.54 ÷ 레버2 = **36.77**
        #     실제 잔량 689주 × 평단 0.02970 ÷ 레버2           = **10.23**
        #
        #   청산가(0.02856)가 평단(0.02970)보다 낮아서 차액에 **실현손실 −53 이
        #   섞여 들어갔다.** 그 식은 「증거금」이 아니라 「증거금 + 실현손익」이었다.
        #   #2090 에서 맞아 보였던 건 청산가 ≈ 평단이라 우연히 비슷했던 것이다.
        #
        #   → 지금 묶인 증거금 = **현재 수량 × 평단 ÷ 레버리지**. 이것이 거래소가
        #     initial margin 으로 잡는 값이고 손익과 섞이지 않는다.
        #   주문 기반 집계는 수량·평단이 결손일 때의 **폴백**으로만 쓴다.
        # ═══════════════════════════════════════════════════════════════
        qty = getattr(strategy, "current_position_qty", None)
        avg = getattr(strategy, "avg_entry_price", None)
        if qty is not None and avg is not None:
            q = abs(Decimal(str(qty)))
            a = abs(Decimal(str(avg)))
            if q == 0:
                return ZERO          # 포지션 없음 = 묶인 증거금 없음
            if a > 0:
                return (q * a / lev).quantize(Decimal("0.00000001"))

        # ── 폴백: 수량·평단 결손 시 체결 주문으로 근사 (손익이 섞일 수 있다) ──
        entry = _filled_notional(db, strategy.id, "ENTRY")
        if entry <= 0:
            return ZERO
        exit_ = _filled_notional(db, strategy.id, "EXIT")
        net = entry - exit_
        if net < 0:
            net = ZERO
        logger.debug("[Fix333] #%s 수량·평단 결손 → 주문 기반 근사 사용",
                     getattr(strategy, "id", "?"))
        return (net / lev).quantize(Decimal("0.00000001"))
    except Exception as e:
        logger.warning("[Fix333] #%s 투입자본 계산 실패 (기존 값 유지): %s",
                       getattr(strategy, "id", "?"), e)
        return None


def sync_invested_capital(db, strategy) -> tuple[bool, str]:
    """전략의 `invested_capital` 을 체결 주문 기준으로 맞춘다.

    Returns:
        (바뀌었는가, 설명)

    ⚠️ commit 은 **하지 않는다.** 호출자의 트랜잭션에 얹는다
       (reconcile 이 한 사이클을 한 번에 commit 하는 구조를 깨지 않기 위해).
    """
    got = compute_invested_capital(db, strategy)
    if got is None:
        return False, "계산 불가 — 기존 값 유지"
    old = Decimal(str(getattr(strategy, "invested_capital", None) or 0))
    if old == got:
        return False, f"변화 없음 ({got})"
    strategy.invested_capital = got
    return True, f"{old} → {got}"

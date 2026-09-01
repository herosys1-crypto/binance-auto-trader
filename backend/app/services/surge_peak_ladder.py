"""🎯 급등 정점 SHORT — 이기면 늘리고, 지면 다시 (Fix 267).

## 사장님 지시 (2026-09-01)

  "당일 급등하는 **1위 10위까지만** 모니터링하고 우리로직상 **최고점에 조정 시작할 심볼**에
   1단계 500 진입하고 손절 -5%에서 청산하고 다시 대기모니터링하고
   상승과조정을 하고 하락할 시점에 다시 2단계 1000으로 포지션 진입하고
   -10%면 청산하고 한번더 대기모니터링해서 다시 같은 조건의 로직으로 진행"

  정정: "한번 실패후 다시 한번더 진행하고도 실패 하면 **250**인거야.
        당연히 **첫진입부터 성공해서 포지션 추가를 하고 싶은거야**"

  "이건 **새로운 전략**이야" -> 기존 워커 확장이 아니라 독립 전략.

## 손절은 「가격 기준」이다 — 사장님 250 이 그 증거

    자본(증거금) 500  x 2x = 명목 1,000 -> 가격 5%  역행 = 손실  50
    자본        1,000 x 2x = 명목 2,000 -> 가격 10% 역행 = 손실 200
                                                         합계  250  O

코드의 `force_sl_roi_override` 는 **ROI 기준**이다
(risk_service.py: `pnl_ratio = raw_pnl_pct * leverage`).
따라서 「가격 5%」를 표현하려면 override 에 **가격% x 레버리지** 를 넣어야 한다.
레버리지가 2가 아니어도 등식이 유지되도록 이 파일에서 **항상 역산**한다.

## 실측 (급등 사건 75건 / 12일, 그 시점부터 4일 walk-forward)

**① 1단계 진입 자리 — 「정점 즉시」는 손절을 넓혀도 못 살린다**

    정점 즉시            -3,325.00   건당 -44.33
    정점 대비 8% 하락       +69.29   건당  +0.92

  별도 측정(SHORT 90건, 정점 대비 어디서 진입했나):
    0~1%(정점) 11건 승률 **0.0%** 건당 -133.70   <- 승자 0명
    8% 이상    23건 승률  43.5%  건당  +26.34   <- 유일한 흑자

**② 🌟 「이겼을 때 추가」가 주 엔진이다**

    추가 없음                    +69.29   건당  +0.92
    가격 2.5% 이익시 x0.5 2회  +2,563.34   건당 +34.18
    가격 2.5% 이익시 x1.0 2회  +4,355.73   건당 **+58.08**   (63배)

  과적합 검사 — 양쪽 절반 모두 크게 개선:
    최근 절반(37건) 추가없음 +194.3 -> +2,037.2
    이전 절반(38건) 추가없음 -125.0 -> +2,318.5

  승률은 32%(24승 49패). **이길 때 크게 버는 손익비 전략**이라 승률로 판단하면 안 된다.

**③ 🚨 「250」과 수익은 함께 못 가진다 — 사장님이 C 를 선택하셨다**

    A  x1.0 추가, 손실고정 없음   건당 +58.08   최악 -650
    B  x0.5 추가, 손실고정 없음   건당 +34.18   최악 -450
    C  x0.5 추가, **손실고정**    건당 +12.67   최악 **-250**  <- 채택
       x1.0 추가, 손실고정        건당  -2.33   최악 -250

  손실을 **완전히** 고정하면 수익이 사라진다(+58 -> -2.33) — 손절 폭이 좁아져
  노이즈에 잘리기 때문이다. 250 을 지키면서 흑자인 유일한 조합이 C 다.
  사장님: "C로 시작해 실적 보고 B -> A"

⚠️ 표본 75건 / 12일. 3시도는 시뮬레이션에서 거의 발동하지 않아 **미검증**이다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

__all__ = [
    "LadderVerdict",
    "evaluate_surge_entry",
    "update_peak",
    "sl_roi_for_price_pct",
    "add_step",
    "cycle_worst_case_loss",
    "BAR_MINUTES",
    "STALL_BARS",
    "DROP_MIN_PCT",
    "CAPITAL_LADDER",
    "SL_PRICE_LADDER",
    "ADD_TRIGGER_PRICE_PCT",
    "ADD_CAPITAL_RATIO",
    "MAX_ADDS",
    "MAX_ATTEMPTS",
]

BAR_MINUTES: int = 15

# ── 1단계 진입 (실측 ①) ────────────────────────────────────────────────
# 「정점 대비 이만큼 떨어진 뒤」에만 들어간다. 0~1% 구간은 승자가 **한 명도 없었다**.
DROP_MIN_PCT: float = 8.0
# 신고점 갱신이 멈춘 봉 수. Fix 260(정점-주춤)이 독립적으로 같은 5봉을 골랐다.
STALL_BARS: int = 5

# ── 사다리 (사장님 원문 그대로) ────────────────────────────────────────
CAPITAL_LADDER: tuple[float, ...] = (500.0, 1000.0, 500.0)   # 3시도 = 「같은 조건」 복귀
SL_PRICE_LADDER: tuple[float, ...] = (5.0, 10.0, 5.0)        # **가격** 기준 %
MAX_ATTEMPTS: int = 3

# ── 승리 경로 = 주 엔진 (실측 ②, 사장님 선택 C) ────────────────────────
ADD_TRIGGER_PRICE_PCT: float = 2.5    # 가격이 이만큼 유리해지면 추가 (SHORT 이면 하락)
ADD_CAPITAL_RATIO: float = 0.5        # 추가 자본 = 1시도 자본 x 0.5  (C 안)
MAX_ADDS: int = 2
CAP_LOSS_ON_ADD: bool = True          # 추가해도 손절 **금액**을 고정 (C 안)


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


# ═══════════════════════════════════════════════════════════════════════
# 손절 — 「가격 %」와 「ROI %」의 변환은 여기서만 한다
# ═══════════════════════════════════════════════════════════════════════

def sl_roi_for_price_pct(price_pct: Any, leverage: Any) -> float | None:
    """가격 X% 역행 = ROI 몇 % 인가.

    🚨 사장님 손절은 **가격 기준**이다(「두번 실패하면 250」이 그 증거).
       코드의 force_sl_roi_override 는 ROI 기준이므로 반드시 변환해야 한다.
       레버리지가 2가 아니어도 손실 금액이 유지되도록 **항상 역산**한다.
    """
    p, lev = _f(price_pct), _f(leverage)
    if p is None or lev is None or p <= 0 or lev <= 0:
        return None
    return p * lev


def add_step(
    *,
    base_capital: Any,
    current_capital: Any,
    base_sl_price_pct: Any,
    leverage: Any,
    adds_done: int,
) -> dict[str, Any] | None:
    """추가 1회의 자본과, 추가 후 적용할 손절 ROI.

    C 안: 추가 자본은 1시도 자본의 절반, 손절 **금액**은 고정.
      기준 손실 = base_capital x leverage x base_sl_price_pct / 100
      추가 후 자본이 늘면 같은 손실 금액이 되도록 ROI 를 **줄인다**.

    Returns:
        {"add_capital", "new_capital", "new_sl_roi", "base_loss_usdt"} 또는
        더 추가할 수 없으면 None.
    """
    b, c = _f(base_capital), _f(current_capital)
    sp, lev = _f(base_sl_price_pct), _f(leverage)
    if None in (b, c, sp, lev) or b <= 0 or c <= 0 or lev <= 0:
        return None
    if adds_done >= MAX_ADDS:
        return None

    add_cap = b * ADD_CAPITAL_RATIO
    new_cap = c + add_cap
    base_loss = b * lev * sp / 100.0          # 고정하고 싶은 손실 금액 (USDT)
    if CAP_LOSS_ON_ADD:
        # 손실 금액 고정 -> ROI = 손실 / 자본 x 100
        new_sl_roi = base_loss / new_cap * 100.0
    else:
        new_sl_roi = sp * lev
    return {
        "add_capital": add_cap,
        "new_capital": new_cap,
        "new_sl_roi": new_sl_roi,
        "base_loss_usdt": base_loss,
    }


def cycle_worst_case_loss(leverage: float = 2.0) -> float:
    """이 설정에서 **한 심볼 한 사이클**의 최악 손실 (USDT).

    C 안은 추가해도 손절 금액이 고정되므로, 최악 = 각 시도의 기본 손실 합이다.
    사장님 전제 「두번 실패하면 250」의 검산에 쓴다.
    """
    return sum(
        CAPITAL_LADDER[i] * leverage * SL_PRICE_LADDER[i] / 100.0
        for i in range(min(len(CAPITAL_LADDER), MAX_ATTEMPTS))
    )


# ═══════════════════════════════════════════════════════════════════════
# 진입 판정
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class LadderVerdict:
    ok: bool = False
    checks: dict[str, bool | None] = field(default_factory=dict)
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def reason(self) -> str:
        if self.ok:
            return (
                f"정점 대비 {self.detail.get('drop_pct', 0):.2f}% 하락 + "
                f"{self.detail.get('stall_min', 0):.0f}분 갱신정지"
            )
        miss = [k for k, v in self.checks.items() if v is not True]
        return f"대기 — 미충족: {', '.join(miss) or '데이터 부족'}"


def update_peak(peak: Any, high: Any) -> tuple[float | None, bool]:
    """SHORT 이므로 **고가**를 추적한다. (신고점 = 나에게 불리한 극값)"""
    h = _f(high)
    if h is None or h <= 0:
        return _f(peak), False
    p = _f(peak)
    if p is None or p <= 0:
        return h, True
    return (h, True) if h > p else (p, False)


def evaluate_surge_entry(
    *,
    rank: Any,
    chg_24h: Any,
    quote_volume: Any,
    mark: Any,
    peak: Any,
    peak_seen_at: datetime | None,
    bb4h_broken: Any = None,
    obv_extreme_up: Any = None,
    now: datetime | None = None,
    min_rank: int = 10,
    min_chg: float = 15.0,
    min_volume: float = 5_000_000.0,
) -> LadderVerdict:
    """지금 이 심볼에 SHORT 으로 들어갈 자리인가.

    필수 — **전부 AND**. 「N중 M」 다수결은 정의 조건을 덮어쓴다 (Fix 250 사고).

    Args:
        rank: 급등 순위 (1 이 1위). market_movers.rank_map 의 값.
        peak: 이 사이클의 신고점 (update_peak 로 갱신된 값)
        peak_seen_at: 그 신고점이 마지막으로 갱신된 시각
        bb4h_broken: 최근 4H 종가가 볼밴 상단 밖이었나 (None = 모름 -> 통과로 세지 않음)
        obv_extreme_up: OBV 가 극단 상승인가 (True 면 차단, 사상 ④)
    """
    v = LadderVerdict()
    c, d = v.checks, v.detail
    now = now or datetime.now(timezone.utc)

    r = _f(rank)
    chg, vol = _f(chg_24h), _f(quote_volume)
    m, p = _f(mark), _f(peak)
    d.update(rank=r, chg_24h=chg, quote_volume=vol, mark=m, peak=p)

    # ── M1. 급등 1~10위 + 유동성 ────────────────────────────────────
    c["급등 순위"] = r is not None and 1 <= r <= min_rank
    c["급등폭"] = chg is not None and chg >= min_chg
    c["유동성"] = vol is not None and vol >= min_volume

    if m is None or p is None or p <= 0:
        c["데이터"] = None
        v.ok = False
        return v

    # ── M3. 정점 대비 하락 (실측: 이게 이 설계의 핵심) ──────────────
    # 🚨 「정점 즉시」는 승자가 한 명도 없었다(11건 0.0%). 이 조건을 빼면 안 된다.
    drop = (p - m) / p * 100.0
    d["drop_pct"] = drop
    c["정점대비 하락"] = drop >= DROP_MIN_PCT

    # ── M4. 신고점 갱신 정지 = 「조정이 시작됐다」 ───────────────────
    if peak_seen_at is None:
        c["갱신 정지"] = None
        d["stall_min"] = None
    else:
        seen = peak_seen_at if peak_seen_at.tzinfo else peak_seen_at.replace(tzinfo=timezone.utc)
        stall = (now - seen) / timedelta(minutes=1)
        d["stall_min"] = stall
        c["갱신 정지"] = stall >= STALL_BARS * BAR_MINUTES

    # ── M2. 4H 볼밴 상단 밖 경험 (사상 ①·⑥) ────────────────────────
    #   ⚠️ 「지금 밖」이 아니라 「최근에 밖이었다」. 「지금 밖」을 요구하면
    #      되돌아온 자리에서 진입할 수 없어 조건이 서로를 막는다 (Fix 249 함정).
    d["bb4h_broken"] = bb4h_broken
    c["4H 상단 경험"] = None if bb4h_broken is None else bool(bb4h_broken)

    # ── M5. OBV 극단 상승 아님 (사상 ④) ─────────────────────────────
    d["obv_extreme_up"] = obv_extreme_up
    c["OBV"] = None if obv_extreme_up is None else (not bool(obv_extreme_up))

    # 🚨 결측은 통과로 세지 않는다 — 자본이 나가는 판정이라 fail-closed.
    v.ok = all(x is True for x in c.values())
    return v

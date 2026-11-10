"""🛡 Fix 486 — 증거금을 넣으면 손절선도 따라 내려가게 (2026-11-11).

사장님 (verbatim): "증거금을 넣으면 손절선도 따라 내려가게" · "운영중인 인스턴스도 모두 같이 적용되게 해줘"

배경 (실측 #4570 PONSUSDT LONG, 2026-11-11 01:56 KST 손절 −13,355.73 USDT):
  사장님이 「증거금 추가」를 2회(1,000 + 1,100 USDT) 해서 거래소 청산가는 0.12885 까지 내려가 있었는데,
  시스템 손절은 0.14249(= 평단 0.28498 × (1 − 100% ÷ 2배))에서 발동했다.
  옛 판정 `ROI = 가격변동% × 레버리지 ≤ −sl_pct` 에는 **증거금이 없다** — 추가한 증거금은
  거래소 청산가만 낮추고 시스템 손절선은 그대로 뒀다.

규칙 (이 파일은 순수 함수 — DB·네트워크·시계 없음):
  초기 증거금      M0 = |수량| × 평단 ÷ 레버리지
  스냅샷 추가분     E_snap = (격리증거금 − 미실현손익) − |스냅샷수량| × 스냅샷평단 ÷ 레버리지
                   (격리지갑 W = isolated_margin − unrealized_pnl · 같은 positionRisk 응답의 두 값)
  인정 추가분       E = min(E_snap × min(1, |수량| ÷ |스냅샷수량|), DB 에 기록된 증거금 추가 합 A)
  유효 손절%        sl_eff = sl_pct × (M0 + E) ÷ M0          (ROI 는 지금처럼 M0 기준)
  거래소 청산 가드   LONG: 현재가 ≤ 청산가 × (1 + 버퍼%)  ·  SHORT: 현재가 ≥ 청산가 × (1 − 버퍼%)

  손절 = `roi ≤ −sl_eff`  또는  (`적용 중` 그리고 `가드 닿음` 그리고 `roi ≤ −sl_pct`)

안전 원칙:
  · **옛 규칙보다 일찍 닫지 않는다** (I1) — 가드도 옛 손절선을 넘은 뒤에만 작동한다.
  · **기록된 추가분보다 더 넓어지지 않는다** (I3) — 거래소 값이 이상해도 DB 기록 A 가 상한.
  · 두 출처가 모두 「추가했다」고 해야 켜진다 (DB 기록 A > 0 그리고 거래소 지갑이 M0 보다 큼).
  · 입력이 하나라도 이상하면(None·0·NaN·오래된 스냅샷·격리 아님·청산가 없음) **옛 판정 그대로** (I4).
    청산 가드를 세울 수 없으면 넓히지 않는다 — 가드 없이 넓히면 거래소 청산이 먼저 온다.
  · 추가분 E 는 스냅샷 **자체의** 수량·평단으로 구한다 → 「포지션 추가」 직후(스냅샷이 아직 옛 수량)에도
    E 가 유지돼, 추가 주문 하나로 옛 손절선이 되살아나 즉시 전량 청산되는 일이 없다.
    그 사이(동기화 ≤2분) 청산가는 새 수량으로 다시 추정해 스냅샷 값과 비교, 더 가까운 쪽으로 가드를 세운다.
  · 스냅샷은 **positionRisk 동기화(source=POSITION_RISK_SYNC)** 것만 쓴다 (호출부 책임).
    사용자 스트림(ACCOUNT_UPDATE) 스냅샷은 isolated_margin 칸에 「격리지갑(iw)」이 들어 있어 뜻이 다르고
    청산가도 전략의 옛 값이다 — 그것으로 W 를 구하면 손실만큼 지갑이 부풀어 보인다.

숫자(버퍼 3% · 스냅샷 300초 · 최소 추가 2%)는 「Claude가 정함」 — system_settings 키로 바꾼다.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from typing import Any

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")
_Q = Decimal("1e-12")          # 유효 손절% 자릿수 (내림)
_QTY_TOL = Decimal("0.01")     # 수량이 스냅샷보다 이만큼(1%) 넘게 크면 「포지션 추가 반영 전」으로 본다

SNAPSHOT_SOURCE = "POSITION_RISK_SYNC"   # 이 출처의 스냅샷만 쓴다 (isolated_margin = 지갑 + 미실현손익)

S_ENABLED = "sl_margin_follow_enabled"
S_LIQ_BUFFER = "sl_margin_follow_liq_buffer_pct"
S_MAX_AGE = "sl_margin_follow_max_snapshot_age_sec"
S_MIN_EXTRA = "sl_margin_follow_min_extra_pct"

DEFAULT_ENABLED = True                 # 사장님 지시로 켬 (2026-11-11)
DEFAULT_LIQ_BUFFER_PCT = Decimal("3")  # 「Claude가 정함」 거래소 청산가 앞 여유 %
DEFAULT_MAX_AGE_SEC = 300              # 「Claude가 정함」 스냅샷 신선도 (동기화 주기 2분의 2.5배)
DEFAULT_MIN_EXTRA_PCT = Decimal("2")   # 「Claude가 정함」 이보다 작은 차이는 추가로 보지 않는다 (수수료·반올림 잡음)


@dataclass(frozen=True)
class FollowParams:
    enabled: bool = DEFAULT_ENABLED
    liq_buffer_pct: Decimal = DEFAULT_LIQ_BUFFER_PCT
    max_snapshot_age_sec: int = DEFAULT_MAX_AGE_SEC
    min_extra_pct: Decimal = DEFAULT_MIN_EXTRA_PCT


@dataclass(frozen=True)
class FollowResult:
    applied: bool                 # False = 옛 판정 그대로
    sl_pct_effective: Decimal     # applied=False 면 입력 sl_pct
    guard_hit: bool               # 거래소 청산 가드선에 닿았나 (applied 일 때만 True 가능)
    extra_margin: Decimal         # 인정 추가분 E (미적용 0)
    reason: str                   # 미적용 사유 / 적용 요약
    guard_price: Decimal | None = None   # 가드선 가격 (적용 시)


def _num(v: Any) -> Decimal | None:
    """유한한 Decimal 로. None·NaN·무한·변환 실패는 None."""
    if v is None or isinstance(v, bool):
        return None
    try:
        d = v if isinstance(v, Decimal) else Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if d.is_finite() else None


def _roi(v: Any) -> Decimal | None:
    """ROI 용 — NaN 만 버리고 ±Infinity 는 살린다 (옛 규칙 `roi <= -sl_pct` 와 같은 결과를 내기 위해)."""
    if v is None or isinstance(v, bool):
        return None
    try:
        d = v if isinstance(v, Decimal) else Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return None if d.is_nan() else d


def _pos(v: Any) -> Decimal | None:
    """양수인 유한 Decimal 만."""
    d = _num(v)
    return d if d is not None and d > ZERO else None


def follow(*, side: str, sl_pct: Any, leverage: Any, qty: Any, avg_entry: Any, mark_price: Any,
           added_margin_recorded: Any,
           snap_qty: Any, snap_entry_price: Any, snap_isolated_margin: Any, snap_unrealized_pnl: Any,
           snap_liq_price: Any, snap_margin_type: Any, snapshot_age_sec: Any,
           params: FollowParams | None = None, snap_side: Any = None) -> FollowResult:
    """증거금 추가를 반영한 유효 손절%. **예외를 던지지 않는다** — 이상하면 옛 판정."""
    base_pct = _pos(sl_pct) or ZERO

    def old(reason: str) -> FollowResult:
        return FollowResult(False, base_pct, False, ZERO, reason, None)

    try:
        p = params or FollowParams()
        if not p.enabled:
            return old("꺼짐")
        s = str(side or "").upper()
        if s not in ("LONG", "SHORT"):
            return old("방향 불명")
        lev, avg, mark = _pos(leverage), _pos(avg_entry), _pos(mark_price)
        q = _num(qty)
        if base_pct <= ZERO or lev is None or avg is None or mark is None or q is None or q == ZERO:
            return old("입력 결손")
        a = _pos(added_margin_recorded)
        if a is None:
            return old("증거금 추가 기록 없음")

        age = _num(snapshot_age_sec)
        if age is None or age < ZERO or age > Decimal(int(p.max_snapshot_age_sec)):
            return old("스냅샷 없음/오래됨")
        if str(snap_margin_type or "").lower() != "isolated":
            return old("격리 증거금 아님")
        # 헤지 모드 = 같은 종목에 두 다리. 스냅샷이 반대 다리 것이면 쓰지 않는다 (duel 감사 지적).
        #   단방향 모드의 "BOTH" 나 빈 값은 방향 정보가 없는 것이므로 검사하지 않는다.
        if str(snap_side or "").upper() in ("LONG", "SHORT") and str(snap_side).upper() != s:
            return old("스냅샷 방향 불일치")
        sq, se, liq = _num(snap_qty), _pos(snap_entry_price), _pos(snap_liq_price)
        iso, upnl = _num(snap_isolated_margin), _num(snap_unrealized_pnl)
        if sq is None or sq == ZERO or se is None or iso is None or upnl is None:
            return old("스냅샷 값 결손")
        if liq is None:
            return old("청산가 없음 — 가드를 세울 수 없어 넓히지 않는다")
        # 청산가는 손실 방향에 있어야 한다 (LONG 은 평단 아래 · SHORT 은 평단 위)
        if (s == "LONG" and liq >= avg) or (s == "SHORT" and liq <= avg):
            return old("청산가가 평단의 손실 쪽이 아님")

        m0_snap = abs(sq) * se / lev
        e_snap = (iso - upnl) - m0_snap                     # 격리지갑 − 스냅샷 초기증거금
        min_extra = _num(p.min_extra_pct)
        min_extra = min_extra if min_extra is not None and min_extra >= ZERO else DEFAULT_MIN_EXTRA_PCT
        if m0_snap <= ZERO or e_snap < m0_snap * min_extra / HUNDRED or e_snap <= ZERO:
            return old("거래소 지갑에 추가분이 보이지 않음")

        scale = min(ONE, abs(q) / abs(sq))                  # 부분 청산으로 수량이 줄었으면 추가분도 비례
        extra = min(e_snap * scale, a)                      # DB 기록 A 가 상한 (I3)
        m0 = abs(q) * avg / lev
        if extra <= ZERO or m0 <= ZERO:
            return old("인정 추가분 없음")
        sl_eff = max(base_pct, (base_pct * (m0 + extra) / m0).quantize(_Q, rounding=ROUND_DOWN))

        # 「포지션 추가」가 아직 스냅샷에 없을 때(수량이 스냅샷보다 1% 넘게 큼) — 스냅샷 청산가는 옛 수량 기준이다.
        #   옛 손절선으로 되돌리면 추가 주문 하나가 전량 청산을 부르므로(사장님 뜻과 반대) 넓힌 손절%는 유지하되,
        #   청산가는 「추가분이 초기 증거금만 들고 들어왔다」고 보고 다시 추정해 **더 가까운(보수적인) 쪽**을 쓴다.
        #     LONG  청산가 = (수량×평단 − 지갑) ÷ (수량×k)   · k 는 스냅샷에서 역산 (유지증거금률·누적액 흡수)
        #     SHORT 청산가 = (수량×평단 + 지갑) ÷ (수량×k)
        #   추정이 서지 않으면(k ≤ 0 등) 옛 판정. 수량이 줄어든 경우(부분 청산)는 청산가가 거의 그대로라 스냅샷 값을 쓴다.
        liq_used, liq_note = liq, ""
        if abs(q) > abs(sq) * (ONE + _QTY_TOL):
            w_snap = iso - upnl
            cost_delta = abs(q) * avg - abs(sq) * se
            if cost_delta <= ZERO:
                return old("수량이 늘었는데 원가가 늘지 않음 — 스냅샷 불일치")
            w_est = w_snap + cost_delta / lev
            if s == "LONG":
                k = (abs(sq) * se - w_snap) / (abs(sq) * liq)
                if k <= ZERO:
                    return old("청산가 추정 불가 — 옛 판정")
                liq_used = max(liq, (abs(q) * avg - w_est) / (abs(q) * k))
            else:
                k = (abs(sq) * se + w_snap) / (abs(sq) * liq)
                if k <= ZERO:
                    return old("청산가 추정 불가 — 옛 판정")
                liq_used = min(liq, (abs(q) * avg + w_est) / (abs(q) * k))
            if liq_used <= ZERO or (s == "LONG" and liq_used >= avg) or (s == "SHORT" and liq_used <= avg):
                return old("추정 청산가가 평단의 손실 쪽이 아님")
            liq_note = " (포지션 추가 반영 전 스냅샷 — 청산가 보수 추정)"

        buf = _num(p.liq_buffer_pct)
        buf = buf if buf is not None and buf >= ZERO else DEFAULT_LIQ_BUFFER_PCT
        if s == "LONG":
            guard_price = liq_used * (ONE + buf / HUNDRED)
            hit = mark <= guard_price
        else:
            guard_price = liq_used * (ONE - buf / HUNDRED)
            hit = mark >= guard_price
        return FollowResult(
            True, sl_eff, bool(hit), extra,
            f"증거금 추가 {extra:.2f} 인정 → 손절 −{base_pct:.2f}% → −{sl_eff:.2f}% · 청산 가드 {guard_price:.8f}{liq_note}",
            guard_price,
        )
    except Exception as e:  # noqa: BLE001 — 판정 보조가 손절 경로를 죽이면 안 된다
        return old(f"계산 예외 {type(e).__name__} — 옛 판정")


def should_stop(*, roi: Any, sl_pct: Any, result: FollowResult | None) -> bool:
    """손절 여부. `roi` = 평단 기준 ROI%(손실이면 음수). 옛 판정 = `roi <= -sl_pct`.

    어떤 경우에도 옛 규칙보다 일찍 닫지 않는다: True ⇒ roi <= -sl_pct (I1).
    """
    base = _pos(sl_pct)
    r = _roi(roi)
    if r is None or base is None:          # NaN·변환 불가 = 판정 불가 (옛 코드도 여기서는 손절하지 못한다)
        return False
    old_stop = r <= -base                  # ±Infinity 는 그대로 비교한다 (−∞ = 손절)
    if result is None or not result.applied:
        return old_stop
    eff = _pos(result.sl_pct_effective)
    if eff is None or eff < base:          # 방어 — 유효값이 기준보다 좁으면 옛 판정
        return old_stop
    return r <= -eff or (bool(result.guard_hit) and old_stop)

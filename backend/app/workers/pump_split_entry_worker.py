"""📊 Fix 179 (2026-08-27): 급등락 심볼 「볼밴 이탈 분할 매수」 전략.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 verbatim (2026-08-27):
  "급등락중인 심볼을 모니터링하고 있는데 15분차트로 상승중인 심볼은 볼밴 하단
   이탈 하면 분할 매수 1-3번 정도 매수하고 긴상승에는 중단 이탈시 1-3번 분할
   매수하고 1-3번 매수 했는데 -5% 청산하고 tp1 익절도 5%부터 분할로 25%씩
   롱과숏을 이렇게 운영하는 시스템 ... 자금 100 200 300 이렇게 600으로 포지션
   운영하는 방식이야 익절 회기도 -3% 짧게"

사장님 선택 (2026-08-27):
  · 「긴 상승」 판정 = 15분 종가가 15분 중단선 위(LONG)/아래(SHORT) **연속 유지** (Fix204)
  · 분할 = **더 깊은 이탈** (기준선 대비 -3% / -5% / -7%)
  · 손절 -10%, TP1 5% 부터 25%씩, 트레일링 -3%
  · 기존 사다리(10/300/600 청산 후 대체)와 **병행** — 별도 전략으로 공존
  · (Fix 180) **전용 상한 + 자본 금액을 설정으로 변경 가능**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

■ 기존 사다리와 자본 모델이 **정반대**다 (그래서 별도 전략이다)

    사다리 (Fix 133/177) : 10 → 청산 → 300 → 청산 → 600   (한 번에 1개 포지션)
    이 전략             : 100 + 200 + 300 = 600 **동시 보유** (평단 형성)

  같은 워커/템플릿에 섞으면 -5% 의 의미가 달라져 사고가 난다.
  구분자 = `capital_management_mode = "split_entry"` (Fix 178 이 이 값을 읽는다).

■ 진입 규칙 (15m 기준선 이탈)

    ┌──────────────┬──────────────────────┬──────────────────────┐
    │ 추세 상태     │ LONG (상승 중 눌림)   │ SHORT (하락 중 반등)  │
    ├──────────────┼──────────────────────┼──────────────────────┤
    │ 일반          │ close < BB 하단       │ close > BB 상단       │
    │ 긴 추세       │ close < BB 중단       │ close > BB 중단       │
    └──────────────┴──────────────────────┴──────────────────────┘

    「긴 추세」= 15분 종가가 15분 중단선 위(LONG)/아래(SHORT)로 LONG_TREND_BARS(6봉=1.5h) 연속 유지.

    분할 차수 = 기준선을 **얼마나 더 벗어났는가** (SHORT 는 부호 반대):
        1차 100 : 기준선 -3%
        2차 200 : 기준선 -5%
        3차 300 : 기준선 -7%
    → 2·3차는 stage_plan.trigger_price 로 심어두고 **기존 stage_trigger_worker 가
      가격 트리거로 처리**한다. 새 진입 경로를 만들지 않는다 (헌법 6).

■ 청산 규칙

    손절   : 평단 ROI **-10%** → 전량 (1·2·3차 어느 시점이든. Fix 178 이 보장)
    익절   : TP1 **+5%** 부터 **25%씩 4회** = +5 / +10 / +15 / +20  (Fix 205)
    트레일링: 고점 대비 **-3%** 회귀 시 잔량 청산

■ 손실 규모 (2x 기준)

    1차만 물림  : 투입 100U → 손절 시 -10U
    2차까지     : 투입 300U → -30U
    3차까지     : 투입 600U → **-60U**  (최악)

■ 안전장치

    · **전용 상한** (`pump_split_max_concurrent`, 기본 3) — 전역 상한과 **독립**이다.
      ⚠️ 계정 전체 동시 보유 = 「전역 상한 + 이 전략 상한」의 합이 된다.
         이 전략이 다른 워커의 슬롯에 굶지 않게 하려는 사장님 의도(Fix 180)이므로
         그렇게 두되, 로그에 두 숫자를 함께 찍어 합계가 보이게 한다.
    · **자본 변경 시 정합성 검산** (`check_no_dead_stage`) — 자본을 바꾸면 평단이
      달라져 「손절이 다음 차수 트리거보다 먼저 오는」 상태가 될 수 있다.
      그렇게 되면 그 차수는 **조용히 죽는다**. 매 사이클 검산하고, 실패하면 진입 중단.
    · 같은 심볼/방향 활성 전략이 있으면 skip (중복 진입 금지)
    · API ban / 계정 없음 / 현재가 없음 = 진입 보류 (fail-SAFE)
    · 진입하지 못한 이유는 항상 집계해 로그로 남긴다 (헌법 80)
    · ⚠️ 이 전략은 **물타기**다. 방향이 틀리면 총액 전부가 물린다.
      -10% 손절이 반드시 살아 있어야 하므로 force_sl_enabled_override=True 를 강제한다.

■ 설정 (SystemSetting)

    pump_split_enabled        "1" 이어야 동작 (기본 OFF)
    pump_split_max_concurrent 이 전략 전용 동시 보유 상한 (기본 3, 0=OFF)
    pump_split_capitals       "100,200,300" 형식 3칸 (기본 100/200/300)
    pump_split_steps          "3,5,7" 형식 3칸 = 기준선 대비 이탈 심도 (Fix 206)
    pump_split_sl_roi         "10" = 평단 ROI 손절 % (Fix 206)
    ⚠️ 이 셋은 서로 얽혀 있다 — 손절을 얕게 하면 뒤 차수가 죽는다.
       저장 시·매 사이클 check_no_dead_stage 로 검산한다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.strategy_status import ACTIVE_LIKE
from app.models.exchange_account import ExchangeAccount
from app.models.strategy_instance import StrategyInstance
from app.models.strategy_template import StrategyTemplate

logger = logging.getLogger(__name__)

__all__ = ["run_pump_split_entry_once"]

# ── 사장님 확정 파라미터 (2026-08-27) ──────────────────────────────────
#   "볼밴 하단 -3% 이탈하면 100 진입 / -5% 이탈하면 200 / -7% 이탈하면 300
#    손절가는 -10% ... tp1 익절도 5%부터 분할로 25%씩"
#
# 실측 계산 (볼밴 기준선=1.0, 2x, 1차 진입가를 0% 로 두고):
#   1차 100U @ -3%  → 평단  0.00% (진입가대비)
#   2차 200U @ -5%  → 평단 -1.38%   누적 300U
#   3차 300U @ -7%  → 평단 -2.77%   누적 600U
#   손절 ROI -10%   → 진입가대비 -7.63% = 볼밴 -10.41%  손실 60U
#   TP1 5%          → 평단 대비 +2.5% (2x). 단계와 무관하게 **같은 수익률**이고,
#                     평단이 낮을수록 그 수익률에 닿는 가격이 낮아진다:
#                     1차만 기준선 -0.58% / 2차까지 -1.95% / 3차까지 -3.33%
#
# ⚠️ 왜 손절이 ROI 인가: 시스템 force SL 은 ROI 기준이다(risk_service).
#    ROI -10% 를 넣으면 3차까지 물렸을 때 볼밴 -10.41% 에서 잘려
#    사장님이 지정한 「-10%」와 사실상 일치하고, 2·3차 트리거보다 항상 뒤에 온다
#    (1차보유 손절 -7.85% / 2차보유 -9.13% → 3차 트리거 -7% 가 먼저).
#    = 어느 차수도 「죽은 단계」가 되지 않는다. 이 정합성은 검증 테스트로 고정한다.
CAPITALS = [Decimal("100"), Decimal("200"), Decimal("300")]   # 총 600
SPLIT_STEP_PCT = [Decimal("3"), Decimal("5"), Decimal("7")]   # 기준선 대비 이탈 심도
FORCE_SL_ROI = Decimal("10")       # 평단 ROI -10% 전량 청산
TP_PERCENTS = [5, 10, 15, 20]      # Fix 205: TP1 +5% 부터 (사장님 원문 복원)
TP_QTY_RATIOS = [25, 25, 25, 25]   # 25% 씩
TRAILING_RETRACE_PCT = Decimal("3")  # 익절 회귀 -3% (짧게)
LEVERAGE = 2

# ── 대상 선정 ──────────────────────────────────────────────────────────
MIN_ABS_24H_CHANGE = 15.0   # 급등락 = |24h 변동| 이상
MAX_CANDIDATES = 40
# Fix 204: 긴 추세 판정도 15분봉 (사장님 정정). 별도 4H 조회는 없앴다.
LONG_TREND_BARS = 6         # 15분 6봉 = 1시간 30분 (사장님이 바꾸실 수 있는 값)
KLINE_15M = 60

STRATEGY_TYPE = "pump_split"
MODE_MARKER = "split_entry"   # Fix 178 이 읽는 값

# ── Fix 180 (2026-08-27 사장님): 이 전략 **전용** 상한 + 자본 설정 ─────────
#   "이건 별도로 상한 전략을 설정할수 있게 하고 포지션금액도 100 200 300도 변경가능하게"
#
# ⚠️ 상한이 **전역 상한과 독립**이다. 즉 계정 전체 동시 보유는
#      기존 자동 진입 상한(sajangnim_top_short_daily_limit) + 이 전략 상한
#    의 합이 된다. 이 전략이 다른 워커의 슬롯에 굶지 않게 하려는 사장님 의도이므로
#    그렇게 만들되, 로그에 두 숫자를 함께 찍어 합계가 보이게 한다.
MAX_CONCURRENT_KEY = "pump_split_max_concurrent"
DEFAULT_MAX_CONCURRENT = 3
CAPITALS_KEY = "pump_split_capitals"
# Fix 206 (2026-08-29 사장님): 트리거·손절도 변경 가능하게
STEPS_KEY = "pump_split_steps"        # "3,5,7" (기준선 대비 이탈 심도)
SL_ROI_KEY = "pump_split_sl_roi"      # "10"   (평단 ROI 손절 %)


def _parse_capitals(raw: str) -> list[Decimal]:
    """\"100,200,300\" → [100, 200, 300]. 3칸 고정, 각 1~100000."""
    vals: list[Decimal] = []
    for part in str(raw).split(","):
        p = part.strip()
        if not p:
            continue
        v = Decimal(p)
        if v <= 0:
            raise ValueError(f"자본은 0보다 커야 합니다: {p}")
        if v > Decimal("100000"):
            raise ValueError(f"자본 상한 100000 초과: {p}")
        vals.append(v)
    if len(vals) != 3:
        raise ValueError(f"자본은 3칸이어야 합니다 (입력 {len(vals)}칸)")
    return vals


def check_no_dead_stage(
    caps: list[Decimal], steps: list[Decimal], sl_roi: Decimal, lev: int,
) -> tuple[bool, str]:
    """🚨 헌법 130 — 각 차수 트리거가 손절가보다 **먼저** 오는지 검산.

    어긋나면 그 단계는 영원히 진입되지 않고 **로그에도 안 남는다**.
    실제로 -1/-3/-5% 안을 검토할 때 3차가 이렇게 죽는 걸 발견했다.
    사장님이 자본을 바꾸면 평단이 달라져 이 관계가 깨질 수 있으므로
    **매 사이클 진입 전에 검산**한다.
    """
    try:
        px = [Decimal("1") - s / Decimal("100") for s in steps]
        for n in (1, 2):
            q = sum(caps[i] * lev / px[i] for i in range(n))
            if q <= 0:
                return False, "수량 계산 불가"
            avg = sum(caps[i] * lev for i in range(n)) / q
            stop = avg * (Decimal("1") - sl_roi / Decimal("100") / lev)
            if stop >= px[n]:
                return False, (
                    f"{n + 1}차 트리거({float(px[n]):.5f})보다 "
                    f"손절({float(stop):.5f})이 먼저 = {n + 1}차가 죽은 단계"
                )
        return True, "정합성 OK (모든 차수 진입 가능)"
    except Exception as e:
        return False, f"정합성 검산 실패: {e}"


def _parse_steps(raw: str) -> list[Decimal]:
    """\"3,5,7\" → [3, 5, 7]. 3칸 고정 · 오름차순 · 0 < s < 50.

    🚨 Fix 206 (2026-08-29 사장님): 진입 트리거도 변경 가능하게.
      오름차순이 아니면 「2차보다 3차가 얕다」가 되어 3차가 먼저 닿아버린다.
      50% 를 상한으로 둔 이유 = 그보다 깊으면 2x 에서 이미 청산가에 가깝다.
    """
    vals: list[Decimal] = []
    for part in str(raw).split(","):
        p = part.strip()
        if not p:
            continue
        v = Decimal(p)
        if v <= 0:
            raise ValueError(f"트리거는 0보다 커야 합니다: {p}")
        if v >= Decimal("50"):
            raise ValueError(f"트리거 상한 50% 미만: {p}")
        vals.append(v)
    if len(vals) != 3:
        raise ValueError(f"트리거는 3칸이어야 합니다 (입력 {len(vals)}칸)")
    for i in range(1, 3):
        if vals[i] <= vals[i - 1]:
            raise ValueError(
                f"트리거는 갈수록 깊어져야 합니다 "
                f"({i}차 {vals[i-1]}% → {i+1}차 {vals[i]}%)"
            )
    return vals


def _parse_sl_roi(raw) -> Decimal:
    """손절 ROI. 1 ~ 90% 사이만 (0 = 손절 없음 = 물타기에서 금지)."""
    v = Decimal(str(raw).strip())
    if v <= 0:
        raise ValueError("손절은 0보다 커야 합니다 (물타기 전략에 손절 없음 = 금지)")
    if v > Decimal("90"):
        raise ValueError(f"손절 상한 90%: {v}")
    return v


def _load_config(db) -> tuple[list[Decimal], int, list[Decimal], Decimal, str]:
    """(자본 3칸, 전용 상한, 트리거 3칸, 손절 ROI, 설명) — 손상 시 기본값 fail-SAFE."""
    from app.models.system_setting import SystemSetting
    caps = list(CAPITALS)
    src = "기본값"
    try:
        row = db.get(SystemSetting, CAPITALS_KEY)
        if row is not None and row.value is not None and str(row.value).strip():
            caps = _parse_capitals(row.value)
            src = f"설정({row.value})"
    except Exception as e:
        logger.warning(
            "[pump_split] %s 파싱 실패 → 기본값 %s 사용: %s",
            CAPITALS_KEY, [str(c) for c in CAPITALS], e,
        )
        caps = list(CAPITALS)
        src = "기본값(설정 손상)"

    cap_n = DEFAULT_MAX_CONCURRENT
    try:
        row = db.get(SystemSetting, MAX_CONCURRENT_KEY)
        if row is not None and row.value is not None and str(row.value).strip():
            v = int(str(row.value).strip())
            cap_n = max(0, min(v, 100))   # 0 = 이 전략만 OFF
    except Exception as e:
        logger.warning("[pump_split] %s 파싱 실패 → 기본 %d: %s",
                       MAX_CONCURRENT_KEY, DEFAULT_MAX_CONCURRENT, e)

    # Fix 206: 진입 트리거 (기준선 대비 이탈 심도)
    steps = list(SPLIT_STEP_PCT)
    try:
        row = db.get(SystemSetting, STEPS_KEY)
        if row is not None and row.value is not None and str(row.value).strip():
            steps = _parse_steps(row.value)
            src += f" 트리거({row.value})"
    except Exception as e:
        logger.warning("[pump_split] %s 파싱 실패 → 기본값 %s: %s",
                       STEPS_KEY, [str(s) for s in SPLIT_STEP_PCT], e)
        steps = list(SPLIT_STEP_PCT)

    # Fix 206: 손절 ROI
    sl_roi = Decimal(str(FORCE_SL_ROI))
    try:
        row = db.get(SystemSetting, SL_ROI_KEY)
        if row is not None and row.value is not None and str(row.value).strip():
            sl_roi = _parse_sl_roi(row.value)
            src += f" 손절({row.value}%)"
    except Exception as e:
        logger.warning("[pump_split] %s 파싱 실패 → 기본 %s%%: %s",
                       SL_ROI_KEY, FORCE_SL_ROI, e)
        sl_roi = Decimal(str(FORCE_SL_ROI))

    return caps, cap_n, steps, sl_roi, src


def _fmt(v) -> str:
    return f"{float(v):.6f}"


def _is_long_trend(a15: dict, side: str) -> tuple[bool, str]:
    """15분 종가가 15분 중단선 위(LONG)/아래(SHORT)로 LONG_TREND_BARS 연속 유지했는가.

    🚨 Fix 204 (2026-08-29 사장님 정정): "긴 추세도 그냥 15분봉이야"
      옛 코드는 4H 로 판정했다(4H 6봉 = 24시간). 그런데 이 전략은 사장님 원문부터
      **"15분차트로 상승중인 심볼"** 이 전제다 — 진입 밴드도 15분이다.
      판정만 4H 로 하면 「15분에서는 추세인데 4H 에서는 아니다」로 중단선 모드가
      거의 안 켜진다 = 사장님이 의도한 「긴 상승엔 중단 이탈에 분할」이 사실상 죽는다.
      → 진입과 **같은 15분봉**으로 판정한다. 덤으로 4H 호출이 사라져 weight 도 준다.

    ⚠️ analyze_timeframe 은 마지막 봉의 밴드값만 준다. 과거 봉마다의 중단선을
       다시 계산하는 대신, 20MA(=중단선) 를 직접 산출해 봉별로 비교한다.
    """
    closes = a15.get("closes") or []
    n = len(closes)
    # Fix 216: 진행 중 봉(-1)과 진입 판정봉(-2)을 뺀 만큼 창이 한 칸 더 필요하다.
    if n < 21 + LONG_TREND_BARS:
        return False, f"15m 봉 부족({n})"
    ok = 0
    # i=1 이 마지막 봉. 각 봉의 20MA 는 **그 봉을 포함한** 직전 20봉 평균이다
    # (볼린저 중단선 정의와 동일). 음수 슬라이스는 i=1 에서 빈 배열이 되므로
    # 양수 인덱스로 계산한다.
    #
    # 🚨 Fix 212 (2026-08-30 사장님 승인): **현재 봉(i=1)은 판정에서 뺀다.**
    #   옛 코드는 i=1 부터 봤는데, 그러면 「긴 추세」가 참이려면 현재 종가가
    #   중단선 **위**여야 한다. 그런데 그때 _entry_plan 은 base=중단선 으로
    #   `종가 <= 중단선 × 0.97` 을 요구한다 — 같은 봉이 중단선 위이면서 동시에
    #   3% 아래일 수는 없다. **긴 추세 모드는 진입이 수학적으로 불가능했다.**
    #   (사장님 확정 "볼밴 중단은 지속 상승일때 같은 전략으로" 가 한 번도 안 돌았다)
    #   → 직전 LONG_TREND_BARS 봉으로 추세를 보고, 현재 봉의 눌림목에서 산다.
    #
    # 🚨 Fix 216 (2026-08-30): 한 칸 **더** 민다 — i=3 부터.
    #   closes[-1] 은 **진행 중인 봉**이다 (chart_analyzer:274 가 klines 를 안 자른다).
    #   Fix 215 로 중단 모드 진입 판정을 「마지막 **완료봉**」(closes[-2])으로 바꿨으므로,
    #   그 봉이 추세 판정에도 들어가면 Fix 212 의 자기모순이 그대로 재발한다
    #   (같은 봉이 중단선 위이면서 동시에 아래일 수 없다).
    #   → 추세는 진입 판정봉 **이전** 6봉으로 본다.
    for i in range(3, LONG_TREND_BARS + 3):
        end = n - i + 1          # exclusive
        start = end - 20
        if start < 0:
            return False, "15m 20MA 창 부족"
        window = closes[start:end]
        mb = sum(float(x) for x in window) / 20.0
        c = float(closes[n - i])
        if (side == "LONG" and c > mb) or (side == "SHORT" and c < mb):
            ok += 1
        else:
            break
    return (ok >= LONG_TREND_BARS,
            f"15m 중단선 {'위' if side == 'LONG' else '아래'} "
            f"직전 {ok}/{LONG_TREND_BARS}봉 연속 (현재봉 제외 — Fix 212)")


def mid_steps(steps: list[Decimal] | None = None) -> list[Decimal]:
    """긴 추세(중단선) 모드의 단계 심도 — 1차는 **이탈 즉시**, 간격은 그대로.

    🚨 Fix 215 (2026-08-30 사장님 「b」): 사장님 원문이 하단과 중단을 **다르게** 말한다.
        "볼밴 하단 **-3%**일때 100 진입"   → 하단은 -3% 명시
        "긴상승에는 중단 **이탈시**"        → 중단은 「이탈(통과)」

    실측 2026-08-29 16:19 사이클 — 중단에도 -3% 를 요구하면 1차 목표가가
    현재가에서 **중앙값 -7.2%, 최대 -15.1%**(PROMUSDT) 나 떨어져 있다.
    급등 종목은 가격이 중단선보다 한참 위(PROMUSDT 는 +14.2%)라서
    「중단 -3%」가 실제로는 「현재가 -15%」가 된다. 그건 눌림목이 아니라 추세 붕괴다.
    그래서 후보 9~14건이 몇 시간째 전부 no_break 였다.

    → 1차는 중단선 이탈(0%), 2·3차는 **원 간격 그대로**.
      3/5/7 이면 [0, 2, 4] (간격 2.00% / 2.04% ≈ 원래 2.06% / 2.11%).
      사장님이 트리거를 3/6/9 로 바꾸면 중단은 [0, 3, 6] 으로 따라간다.
    """
    s = steps or SPLIT_STEP_PCT
    return [Decimal("0"), s[1] - s[0], s[2] - s[0]]


def _entry_plan(a15: dict, side: str, long_trend: bool,
                steps: list[Decimal] | None = None,
                ) -> tuple[Decimal | None, str, list[Decimal]]:
    """기준선(base)·사유·**이 진입에 쓸 steps** 를 반환. 미충족이면 base=None.

    ⚠️ 하단/상단 모드의 1차는 「기준선 이탈 즉시」가 아니라 **기준선 대비
       SPLIT_STEP_PCT[0](-3%) 까지 밀렸을 때** 진입한다
       (사장님 확정: "볼밴 하단 -3% 이탈하면 100 진입").
       기준선을 스치고 바로 되돌리는 가짜 이탈을 걸러내기 위함이다.
    ⚠️ 긴 추세(중단선) 모드는 Fix 215 로 **이탈 즉시**다 — mid_steps 참조.

    반환하는 steps 를 템플릿·검산·재앵커가 **전부 같이** 써야 한다 (헌법 101).
    """
    up, mid, lo = a15.get("bb_up_last"), a15.get("bb_mid_last"), a15.get("bb_lo_last")
    closes = a15.get("closes") or []
    _base_steps = steps or SPLIT_STEP_PCT     # Fix 206
    _steps = mid_steps(_base_steps) if long_trend else _base_steps   # Fix 215
    if not closes or up is None or mid is None or lo is None:
        return None, "15m 밴드/종가 없음", _steps
    close = Decimal(str(closes[-1]))
    # ═══════════════════════════════════════════════════════════════════
    # 🚨 Fix 216 (2026-08-30): 중단 모드는 **완료봉**으로 판정한다.
    #   chart_analyzer:274 는 klines 를 자르지 않는다 → closes[-1] 과 bb_*_last 는
    #   **아직 안 끝난 15분봉**이다. 하단 모드는 -3% 버퍼가 있어 덜 위험했지만,
    #   중단 모드는 Fix 215 로 여유가 **0(이탈 즉시)** 이라 봉 안의 틱 하나로
    #   시장가가 나가고, 그 봉이 되돌리면 「완료봉 기준으로는 없던 이탈」 위에
    #   2·3차 트리거와 손절이 앵커된다 (= 가짜 이탈에 자본이 물린다).
    #   → 마지막 완료봉(closes[-2])의 종가와 그 시점 밴드로 본다.
    #   ⚠️ 하단/상단 모드는 **건드리지 않는다** — 지금까지의 동작을 바꾸지 않는다.
    # ═══════════════════════════════════════════════════════════════════
    if long_trend and len(closes) >= 21:
        try:
            from app.services.bb_4h_band_analyzer import BB4HBandAnalyzer
            _m, _u, _l = BB4HBandAnalyzer.bollinger([float(x) for x in closes])
            if _m[-2] is not None:
                mid, up, lo = _m[-2], _u[-2], _l[-2]
                close = Decimal(str(closes[-2]))
        except Exception as _e:      # 밴드 재계산 실패 = 진행 중 봉으로 내려가지 않는다
            return None, f"완료봉 밴드 계산 실패 (보류): {_e}", _steps
    step1 = _steps[0] / Decimal("100")
    # 중단 모드는 step1=0 이므로 need == base = 「이탈(통과)」 판정이 된다.
    # Fix 216: 부호는 방향을 따른다 (SHORT 를 -3% 로 찍던 것 정정).
    _cond = "이탈" if long_trend else (
        f"{'-' if side == 'LONG' else '+'}{_base_steps[0]}%"
    )
    if side == "LONG":
        base = Decimal(str(mid)) if long_trend else Decimal(str(lo))
        label = "중단" if long_trend else "하단"
        need = base * (Decimal("1") - step1)
        if close > need:
            return None, (
                f"{label} {_cond} 미도달 "
                f"(close {_fmt(close)} > 목표 {_fmt(need)} / {label} {_fmt(base)})"
            ), _steps
    else:
        base = Decimal(str(mid)) if long_trend else Decimal(str(up))
        label = "중단" if long_trend else "상단"
        need = base * (Decimal("1") + step1)
        if close < need:
            return None, (
                f"{label} {_cond} 미도달 "
                f"(close {_fmt(close)} < 목표 {_fmt(need)} / {label} {_fmt(base)})"
            ), _steps
    return base, (
        f"{label} {_cond} 확인 "
        f"(close {_fmt(close)} / {label} {_fmt(base)} / 목표 {_fmt(need)} "
        f"/ 단계 {'/'.join(str(x) for x in _steps)}%)"
    ), _steps


def base_multipliers(side: str, steps: list[Decimal]) -> list[Decimal]:
    """기준선 대비 각 차수의 목표 가격 배수. LONG 은 아래로, SHORT 는 위로."""
    sign = Decimal("-1") if side == "LONG" else Decimal("1")
    return [Decimal("1") + sign * Decimal(str(s)) / Decimal("100") for s in steps]


def compounded_trigger_pcts(side: str, steps: list[Decimal]) -> list[Decimal | None]:
    """🚨 Fix 195 (2026-08-28): 「기준선 대비 심도」를 계산기가 쓰는 「직전 단계 대비」로 변환.

    StrategyCalculator 는 앵커를 **직전 단계 가격으로 이어붙인다**(복리):
        price_i = price_(i-1) × multiplier(pct_i)
    그래서 기준선 대비 -3/-5/-7% 를 그대로 넣으면 3차가 엉뚱한 곳에 걸린다.

    실측(2026-08-28, 계산기 직접 실행):
        LONG  3차 = base × 0.95 × 0.80 = base × 0.76 = 기준선 **-24%** (의도 -7%)
        SHORT 3차 = base × 1.05 × 1.20 = base × 1.26 = 기준선 **+26%** (의도 +7%)
    2차까지 물렸을 때 손절가가 기준선 -9.13% 이므로 **손절이 압도적으로 먼저 온다**
    → 계획 자본 600 중 **300(절반)이 영원히 진입되지 않았다** (헌법 130 「죽은 단계」).

    원인 2겹:
      ① stages_config 에 last_stage_trigger_percent 를 안 넘겨서 마지막 단계가
         DEFAULT_LAST_*_TRIGGER_PCT = 20% 로 떨어졌다 (trigger_percents[2]=7 은 읽히지도 않음)
      ② 설령 7 을 넘겨도 복리 앵커 때문에 base×0.95×0.93 = -11.65% 라 여전히 죽는다
    → 두 겹을 한 번에 없애려면 **비율을 복리 기준으로 환산**해야 한다.

    1차는 기준선에서 IMMEDIATE 로 잡히고(start_price=base) 앵커가 base 이므로,
    2차는 기준선 대비 값이 그대로 맞고 3차부터 환산이 필요하다.
    """
    mult = base_multipliers(side, steps)
    out: list[Decimal | None] = [None]          # 1차 = 즉시 진입 (트리거 없음)
    prev = Decimal("1")                          # 앵커 시작 = 기준선(start_price)
    for i in range(1, len(steps)):
        ratio = mult[i] / prev
        out.append((Decimal("1") - ratio) * 100 if side == "LONG" else (ratio - Decimal("1")) * 100)
        prev = mult[i]
    return out


def verify_stage_plans(plans, base, side: str, caps: list[Decimal],
                       steps: list[Decimal] | None = None,
                       sl_roi=FORCE_SL_ROI, lev=LEVERAGE) -> tuple[bool, str]:
    """🚨 Fix 195: **DB 에 실제로 저장된 트리거 가격**으로 죽은 단계를 검산한다.

    check_no_dead_stage 는 워커의 「의도값」으로 계산하므로, 계산기가 다른 가격을
    만들어내면 그 어긋남을 못 잡는다 — 실제로 3차가 기준선 -24% 인데도
    「정합성 OK (모든 차수 진입 가능)」를 찍고 있었다 (헌법 101: 읽는 함수가
    여러 개면 어긋난다 / 헌법 132: 검사가 실제로 잡는지 증명할 것).

    여기서는 저장된 trigger_price 를 그대로 읽어, n차까지 체결된 평단의 손절가보다
    (n+1)차 트리거가 **먼저 오는지**를 본다. 먼저 오지 않으면 그 차수는 영원히
    진입되지 않는다 = 계획한 자본이 조용히 죽는다.
    """
    # 1차는 stage plan 에 트리거가 없다(MARKET). 진입 조건이 「기준선 -3% 도달」이므로
    # 체결가는 기준선 × (1-3%) 이하다. 가장 불리한 쪽(= 정확히 -3%)으로 잡아 보수적으로 본다.
    px: dict[int, Decimal] = {
        1: Decimal(str(base)) * base_multipliers(side, steps or SPLIT_STEP_PCT)[0],
    }
    for p in plans:
        if p.stage_no != 1 and p.trigger_price is not None:
            px[p.stage_no] = Decimal(str(p.trigger_price))
    for k in range(1, len(caps) + 1):
        if k not in px:
            return False, f"{k}차 트리거 가격이 저장되지 않았습니다"
    lev_d = Decimal(str(lev))
    drop = Decimal(str(sl_roi)) / Decimal("100") / lev_d
    for n in range(1, len(caps)):          # n차까지 체결됐을 때 (n+1)차에 닿는가
        qty = sum(Decimal(str(caps[i])) * lev_d / px[i + 1] for i in range(n))
        avg = sum(Decimal(str(caps[i])) * lev_d for i in range(n)) / qty
        stop = avg * (Decimal("1") - drop) if side == "LONG" else avg * (Decimal("1") + drop)
        nxt = px[n + 1]
        ok = (stop < nxt) if side == "LONG" else (stop > nxt)
        if not ok:
            return False, (
                f"{n+1}차 트리거 {_fmt(nxt)} 보다 손절 {_fmt(stop)} 이 먼저 도달 "
                f"= {n+1}차({caps[n]} USDT)가 죽은 단계"
            )
    return True, "저장된 트리거로 검산 OK (" + " / ".join(
        f"{k}차 {_fmt(px[k])}" for k in sorted(px)
    ) + ")"


def stage_gap_pcts(side: str, steps: list[Decimal]) -> list:
    """각 차수가 **직전 차수 대비** 얼마나 더 밀렸는가. 3/5/7 → [None, 2.06, 2.11].

    ⚠️ compounded_trigger_pcts 와 헷갈리면 안 된다. 저건 앵커가 **기준선**이라
       2차가 5.00% 로 나온다 (계산기가 start_price 부터 복리로 접기 때문).
       재앵커(Fix 209)는 앵커가 **1차 체결가**라 「1차 대비」 간격이 필요하다.
       실제로 처음에 compounded 값을 그대로 썼다가 간격이 5% 로 벌어졌고,
       테스트가 그걸 잡았다 (tests/unit/test_pump_split_reanchor.py).
    """
    mult = base_multipliers(side, steps)
    out: list = [None]
    for i in range(1, len(steps)):
        ratio = mult[i] / mult[i - 1]
        out.append(
            (Decimal("1") - ratio) * 100 if str(side).upper() == "LONG"
            else (ratio - Decimal("1")) * 100
        )
    return out


def reanchor_from_fill(plans, side: str, steps: list[Decimal] | None = None) -> tuple[int, str]:
    """🚨 Fix 209 (2026-08-30 사장님 「b」): 남은 단계를 **실제 체결가** 기준으로 다시 깐다.

    1차는 MARKET 이라 「기준선 -3% 도달」을 감지한 **그 순간** 가격에 체결된다.
    워커 주기(15분) 사이에 더 빠지면 1차가 -5.5% 에 체결되고, 그때 기준선 기준으로
    미리 계산해 둔 2차(-5%)는 **이미 지나간 가격**이 된다. 실측 (2026-08-29):

        #1727  1차 -5.02% / 2차 -5.03%   = 간격 0.01%p (사실상 같은 자리)
        #1639  1차 -5.49% / 2차 -5.01%   = 2차가 1차보다 **위** = 태어날 때 이미 죽음

    17건 중 3차 체결 **0건**, 12건이 1차 100 USDT 만 물린 채 손절.

    사장님 선택(2026-08-30 「b」): 앵커를 기준선 → **실체결가** 로 바꾼다.
    단계 간 간격은 원 설계 그대로다 — stage_gap_pcts(side, steps)
    (3/5/7 이면 -2.06% / -2.11%). 즉 **간격 불변, 앵커만 이동.**

    앵커 = 체결된 **마지막** 단계의 체결가. 2차가 체결되면 3차는 2차 체결가에서 다시 깐다
    (「내려갈수록 더 크게」가 1차가 어디서 잡히든 항상 성립).

    안전:
      - 이미 체결된 단계는 절대 건드리지 않는다.
      - 값이 사실상 같으면 쓰지 않는다 (헌법 148 — 같은 값 대입은 UPDATE 도 안 나간다).
      - 앵커가 없으면(1차 미체결) 아무것도 하지 않는다.
      - 순수 함수 + 계산만 한다. commit 은 호출자 책임.

    반환: (바뀐 단계 수, 사유/내역)
    """
    by_no = {p.stage_no: p for p in plans if getattr(p, "stage_no", None)}
    if not by_no:
        return 0, "단계 계획 없음"
    pcts = stage_gap_pcts(side, steps or SPLIT_STEP_PCT)
    filled = [
        n for n in sorted(by_no)
        if by_no[n].is_triggered and by_no[n].trigger_price
        and Decimal(str(by_no[n].trigger_price)) > 0
    ]
    if not filled:
        return 0, "체결된 단계 없음 = 앵커 없음 (재계산 안 함)"
    anchor_no = filled[-1]
    px = Decimal(str(by_no[anchor_no].trigger_price))
    sign = Decimal("-1") if str(side).upper() == "LONG" else Decimal("1")
    changed, detail = 0, []
    for n in range(anchor_no + 1, max(by_no) + 1):
        p = by_no.get(n)
        if p is None or p.is_triggered:
            continue
        try:
            gap = pcts[n - 1]
        except (IndexError, TypeError):
            gap = None
        if gap is None:
            continue
        px = px * (Decimal("1") + sign * Decimal(str(gap)) / Decimal("100"))
        old = Decimal(str(p.trigger_price)) if p.trigger_price is not None else None
        # 0.01% 이내면 같은 값으로 본다 (부동소수 반올림으로 매 사이클 UPDATE 되는 것 방지)
        if old is not None and abs(old - px) <= px * Decimal("0.0001"):
            continue
        p.trigger_price = px
        changed += 1
        detail.append(
            f"{n}차 {_fmt(old) if old is not None else 'None'}→{_fmt(px)}"
            f"({float(gap):+.2f}% from {anchor_no}차 체결 {_fmt(Decimal(str(by_no[anchor_no].trigger_price)))})"
        )
    if not changed:
        return 0, f"{anchor_no}차 체결가 기준으로 이미 정렬됨"
    return changed, " / ".join(detail)


def _build_template(
    db, symbol: str, side: str, base: Decimal, caps: list[Decimal],
    steps: list[Decimal] | None = None,
) -> StrategyTemplate:
    """3단계 분할 + TP 25%×4 + 트레일링 -3% 템플릿. caps 는 설정에서 온 자본 3칸."""
    now = datetime.now(timezone.utc)
    # Fix 195: 기준선 대비 심도 → 계산기의 복리 앵커 기준으로 환산
    _steps = steps or SPLIT_STEP_PCT          # Fix 206
    _pcts = compounded_trigger_pcts(side, _steps)
    trig = [None] + [float(p) for p in _pcts[1:]]
    tpl = StrategyTemplate(
        name=f"PUMPSPLIT_{symbol}_{side}_{now.strftime('%Y%m%d_%H%M%S')}",
        strategy_type=STRATEGY_TYPE,
        side=side,
        leverage=LEVERAGE,
        total_capital=sum(caps),
        stages_config={
            "capitals": [float(c) for c in caps],
            "trigger_percents": trig,
            # 🚨 Fix 195: 마지막 단계는 계산기가 trigger_percents 를 **읽지 않고**
            #   last_stage_* 를 쓴다. 안 넘기면 기본 20% 로 떨어져 3차가 죽는다.
            "last_stage_trigger_mode": "PRICE_DOWN_PCT" if side == "LONG" else "PRICE_UP_PCT",
            "last_stage_trigger_percent": float(_pcts[-1]),
            "stages_count": 3,
            "base_price": float(base),
            "split_entry": True,
            # Fix 209: 생성 당시의 트리거 심도. 재앵커가 「1차 대비 간격」을 복원할 때 쓴다.
            #   설정이 나중에 바뀌어도 이미 열린 전략에는 소급되지 않아야 한다.
            "steps": [float(s) for s in _steps],
        },
        stage1_capital=caps[0],
        stage2_capital=caps[1],
        stage3_capital=caps[2],
        stage4_capital=None,
        # 기준선 대비 이탈 심도 = 가격 트리거 % (stage_trigger_worker 가 처리)
        stage2_trigger_percent=_steps[1],
        stage3_trigger_percent=_steps[2],
        stage4_trigger_percent=None,
        tp1_percent=Decimal(str(TP_PERCENTS[0])),
        tp2_percent=Decimal(str(TP_PERCENTS[1])),
        tp3_percent=Decimal(str(TP_PERCENTS[2])),
        tp4_percent=Decimal(str(TP_PERCENTS[3])),
        tp1_qty_ratio=Decimal(str(TP_QTY_RATIOS[0])),
        tp2_qty_ratio=Decimal(str(TP_QTY_RATIOS[1])),
        tp3_qty_ratio=Decimal(str(TP_QTY_RATIOS[2])),
        tp4_qty_ratio=Decimal(str(TP_QTY_RATIOS[3])),
        stop_loss_percent_of_capital=Decimal("90"),
        is_active=True,
    )
    db.add(tpl)
    db.flush()
    return tpl


def run_pump_split_entry_once() -> dict:
    """15분 주기. 급등락 심볼의 볼밴 이탈에 100/200/300 분할 진입."""
    db = SessionLocal()
    stat: dict = {"scanned": 0, "entered": 0, "skipped": {}}

    def _skip(why: str) -> None:
        stat["skipped"][why] = stat["skipped"].get(why, 0) + 1

    try:
        # ⚠️ 기본 OFF. 새로 돈을 넣는 전략이므로 사장님이 **명시적으로 켜야** 돈다.
        #   심볼당 600 USDT × 후보 다수 = 노출이 순식간에 커질 수 있다.
        #   켜기: SystemSetting `pump_split_enabled` = "1"
        from app.models.system_setting import SystemSetting
        _sw = db.get(SystemSetting, "pump_split_enabled")
        if _sw is None or str(_sw.value).strip() != "1":
            logger.info(
                "[pump_split] ⏹️ OFF (pump_split_enabled != 1) — 켜려면 이 설정을 1 로",
            )
            return {"note": "OFF (기본값)", **stat}

        # ── Fix 180: 자본/상한 설정 로드 + 정합성 검산 ──
        caps, max_concurrent, steps, sl_roi, cfg_src = _load_config(db)
        if max_concurrent <= 0:
            logger.info("[pump_split] ⏹️ %s=0 = 이 전략 OFF", MAX_CONCURRENT_KEY)
            return {"note": "전용 상한 0", **stat}
        _ok, _why = check_no_dead_stage(caps, steps, sl_roi, LEVERAGE)
        if not _ok:
            # 죽은 단계가 생기는 설정으로는 **진입하지 않는다**.
            # 조용히 죽는 단계를 만드는 것이 가장 위험하다 (헌법 130).
            logger.error(
                "[pump_split] ⛔ 자본 설정 정합성 실패 → 진입 중단: %s "
                "| 자본=%s 심도=%s SL=-%s%% | %s 를 조정하세요",
                _why, [str(c) for c in caps], [str(s) for s in steps],
                sl_roi, CAPITALS_KEY,
            )
            return {"note": f"정합성 실패: {_why}", **stat}
        # 🚨 Fix 215: 중단(긴 추세) 모드는 단계표가 다르다(0/2/4) — **따로** 검산한다.
        #   여기서 안 보면 「하단은 멀쩡한데 중단 3차만 죽은」 상태를 못 잡는다.
        _mok, _mwhy = check_no_dead_stage(caps, mid_steps(steps), sl_roi, LEVERAGE)
        if not _mok:
            logger.error(
                "[pump_split] ⛔ 중단(긴추세) 단계 정합성 실패 → 진입 중단: %s "
                "| 자본=%s 중단심도=%s SL=-%s%%",
                _mwhy, [str(c) for c in caps],
                [str(s) for s in mid_steps(steps)], sl_roi,
            )
            return {"note": f"중단 정합성 실패: {_mwhy}", **stat}
        logger.info(
            "[pump_split] 설정: 자본 %s (%s) | 전용 상한 %d | 하단 %s | 중단 %s | %s",
            "/".join(str(c) for c in caps), cfg_src, max_concurrent,
            "/".join(str(s) for s in steps),
            "/".join(str(s) for s in mid_steps(steps)),
            _why,
        )

        account = db.execute(
            select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
        ).scalar_one_or_none()
        if not account:
            logger.warning("[pump_split] mainnet 계정 없음")
            return stat

        from app.core.api_backoff import is_account_banned
        if is_account_banned(account.id):
            logger.info("[pump_split] API ban 중 = skip")
            return stat

        from app.core.crypto import decrypt_text
        from app.integrations.binance.client import BinanceClient
        from app.services.chart_analyzer import ChartAnalyzer
        bc = BinanceClient(
            api_key=decrypt_text(account.api_key_enc),
            api_secret=decrypt_text(account.api_secret_enc),
            is_testnet=False,
        )

        # 1) 급등락 후보 (24h 변동 절대값 기준)
        tickers = bc.get_24hr_ticker()
        if isinstance(tickers, dict):
            tickers = [tickers]
        cands = []
        for t in (tickers or []):
            sym = t.get("symbol") or ""
            if not sym.endswith("USDT"):
                continue
            try:
                chg = float(t.get("priceChangePercent") or 0)
            except Exception:
                continue
            if abs(chg) >= MIN_ABS_24H_CHANGE:
                cands.append((sym, chg))
        cands.sort(key=lambda x: -abs(x[1]))
        cands = cands[:MAX_CANDIDATES]
        stat["scanned"] = len(cands)
        if not cands:
            logger.info("[pump_split] 급등락 후보 0건 (|24h| >= %.0f%%)", MIN_ABS_24H_CHANGE)
            return stat

        # 2) 활성 심볼 (중복 진입 금지)
        active = db.execute(
            select(StrategyInstance)
            .where(StrategyInstance.status.in_(list(ACTIVE_LIKE)))
            .where(StrategyInstance.is_archived.is_(False))
        ).scalars().all()
        active_keys = {(s.symbol, s.side) for s in active}

        # ── Fix 180: 이 전략 **전용** 상한 (전역 상한과 독립) ──
        #   전역 상한에 굶지 않게 하려는 사장님 의도. 대신 계정 전체 동시 보유는
        #   「전역 상한 + 이 전략 상한」의 합이 되므로 두 숫자를 함께 찍는다.
        _tpl_ids = {s.strategy_template_id for s in active if s.strategy_template_id}
        _split_tpls = set()
        if _tpl_ids:
            _split_tpls = {
                t.id for t in db.execute(
                    select(StrategyTemplate)
                    .where(StrategyTemplate.id.in_(list(_tpl_ids)))
                    .where(StrategyTemplate.strategy_type == STRATEGY_TYPE)
                ).scalars().all()
            }
        n_split = sum(1 for s in active if s.strategy_template_id in _split_tpls)
        logger.info(
            "[pump_split] 현재 이 전략 %d/%d 건 (계정 전체 활성 %d건)",
            n_split, max_concurrent, len(active),
        )

        from app.services.strategy_service import StrategyService

        for sym, chg in cands:
            # 방향 = 급등이면 LONG(눌림목 매수) / 급락이면 SHORT(반등 매도)
            side = "LONG" if chg > 0 else "SHORT"
            if (sym, side) in active_keys:
                _skip("already_active")
                continue

            # 전용 상한을 **진입 직전마다** 재확인 (헌법 119)
            if n_split >= max_concurrent:
                logger.info(
                    "[pump_split] SKIP: 이 전략 상한 도달 %d/%d (%s 로 조정)",
                    n_split, max_concurrent, MAX_CONCURRENT_KEY,
                )
                _skip("split_cap_full")
                break

            try:
                a15 = ChartAnalyzer.analyze_timeframe(bc, sym, "15m", limit=KLINE_15M)
                # Fix 204: 4H 조회 제거 — 긴 추세도 15분봉으로 본다 (weight 절감)
            except Exception as e:
                logger.warning("[pump_split] %s 분석 실패: %s", sym, e)
                _skip("analyze_error")
                continue
            if not a15:
                _skip("no_analysis")
                continue

            long_trend, trend_why = _is_long_trend(a15, side)
            # Fix 215: 긴 추세면 「이탈 즉시」 단계표(0/2/4)를 쓴다. 이후 템플릿·검산·
            #   재앵커가 **모두 이 eff_steps 하나**를 봐야 한다 (헌법 101).
            base, why, eff_steps = _entry_plan(a15, side, long_trend, steps)
            if base is None:
                # 🚨 Fix 211 (2026-08-30): 옛 코드는 사유를 `no_break` 한 단어로만 뭉갰다.
                #   그래서 「후보 12건 전부 no_break」 만 남고 **어느 조건이 막았는지**
                #   알 수 없었다 (중단선 모드인지 하단 모드인지조차). 헌법 93 위반.
                #   후보는 사이클당 10건 안팎이라 전건 INFO 로 남겨도 시끄럽지 않다.
                _skip("no_break_중단" if long_trend else "no_break_하단")
                logger.info(
                    "[pump_split] ⏳ %s %s 24h=%+.1f%% — %s | %s",
                    sym, side, chg, why, trend_why,
                )
                continue

            logger.info(
                "[pump_split] 🎯 %s %s 24h=%+.1f%% | %s | %s | 기준선=%s",
                sym, side, chg, trend_why, why, _fmt(base),
            )

            # 3) 전략 생성 — 1차는 MARKET 즉시, 2·3차는 가격 트리거로 대기
            try:
                tpl = _build_template(db, sym, side, base, caps, eff_steps)
                strategy = StrategyService(db).create_strategy_instance(
                    user_id=1,
                    exchange_account_id=account.id,
                    strategy_template_id=tpl.id,
                    symbol=sym,
                    side=side,
                    start_price=base,             # 기준선 = 트리거 계산 기준
                    leverage_override=LEVERAGE,
                    capital_management_mode=MODE_MARKER,   # Fix 178 마커
                )
                # -5% 전량 손절 강제 + 트레일링 -3%
                strategy.force_sl_enabled_override = True
                strategy.force_sl_roi_override = sl_roi      # Fix 206: 설정값
                strategy.trailing_retrace_pct = TRAILING_RETRACE_PCT
                # 🚨 Fix 205 (2026-08-29 사장님): TP1 을 **전략 인스턴스에도** 박는다.
                #   strategy_service 가 생성 시 tp1_pct_override = TP1_PCT_DEFAULT(15) 를
                #   모든 전략에 넣는다. 템플릿만 5 로 바꾸면 이 override 가 이겨서
                #   (Fix 183/184 가 label 로 TP1 을 덮고 사다리를 통째로 shift 한다)
                #   사장님이 지정한 5% 가 무효가 된다.
                strategy.tp1_pct_override = Decimal(str(TP_PERCENTS[0]))
                db.commit()

                # 1차 = MARKET 즉시 진입 (지정가로 걸어두면 미체결 위험)
                from app.models.strategy_stage_plan import StrategyStagePlan
                s1 = db.execute(
                    select(StrategyStagePlan)
                    .where(StrategyStagePlan.strategy_instance_id == strategy.id)
                    .where(StrategyStagePlan.stage_no == 1)
                ).scalar_one_or_none()
                if s1 is not None:
                    s1.trigger_price = None
                    db.commit()

                # 🚨 Fix 195: 주문을 내기 **전에** 저장된 트리거로 죽은 단계를 재검산한다.
                #   의도값 검산(check_no_dead_stage)은 통과했는데 실제 저장값이
                #   기준선 -24% 였던 사고가 있었다. 여기서 막지 못하면
                #   계획 자본의 절반이 영원히 안 들어간 채로 손절만 맞는다.
                _plans = db.execute(
                    select(StrategyStagePlan)
                    .where(StrategyStagePlan.strategy_instance_id == strategy.id)
                ).scalars().all()
                _ok, _why = verify_stage_plans(_plans, base, side, caps, eff_steps, sl_roi)
                if not _ok:
                    strategy.status = "STOPPED"
                    strategy.is_archived = True
                    strategy.last_error_code = "SPLIT_DEAD_STAGE"
                    strategy.last_error_message = _why[:500]
                    db.commit()
                    logger.error(
                        "[pump_split] ⛔ #%s %s %s 진입 취소 — %s "
                        "(주문 전에 막았으므로 자본 손실 없음)",
                        strategy.id, sym, side, _why,
                    )
                    # 🚨 Fix 210 (2026-08-30): 옛 코드는 `stat.get("skipped", 0) + 1` 로
                    #   **dict + int** 를 해 TypeError 를 냈다. 그 예외는 바깥 except 가
                    #   삼켜 `create_failed` 로 기록되므로, 죽은 단계 취소가 진입 실패로
                    #   둔갑해 사유 통계가 거짓이 됐다 (헌법 93 — 차단은 정확히 남긴다).
                    _skip("dead_stage_cancelled")
                    continue
                logger.info("[pump_split] #%s 단계 검산: %s", strategy.id, _why)

                from app.services.execution_service import ExecutionService
                ExecutionService(
                    db,
                    api_key=decrypt_text(account.api_key_enc),
                    api_secret=decrypt_text(account.api_secret_enc),
                    is_testnet=account.is_testnet,
                ).start_stage1(strategy.id)

                active_keys.add((sym, side))
                n_split += 1          # Fix 180: 전용 상한 즉시 반영
                stat["entered"] += 1
                logger.warning(
                    "[pump_split] ✅ 진입! #%s %s %s [%s] 1차 %s USDT@%s%% "
                    "(2차 %s@%s%% / 3차 %s@%s%%) SL -%s%% TP %s%% 25%%×4 트레일 -%s%%",
                    strategy.id, sym, side,
                    "중단이탈" if long_trend
                    else f"밴드{'-' if side == 'LONG' else '+'}{eff_steps[0]}%",
                    caps[0], eff_steps[0], caps[1], eff_steps[1],
                    caps[2], eff_steps[2], sl_roi, TP_PERCENTS[0],
                    TRAILING_RETRACE_PCT,
                )
            except Exception as e:
                db.rollback()
                logger.error("[pump_split] ❌ %s %s 진입 실패: %s", sym, side, e)
                _skip("create_failed")

        logger.info(
            "[pump_split] 완료: 후보=%d 진입=%d 사유=%s",
            stat["scanned"], stat["entered"], stat["skipped"],
        )
        return stat
    except Exception as e:
        logger.exception("[pump_split] 실패: %s", e)
        return stat
    finally:
        db.close()

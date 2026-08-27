"""📊 Fix 179 (2026-08-27): 급등락 심볼 「볼밴 이탈 분할 매수」 전략.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 verbatim (2026-08-27):
  "급등락중인 심볼을 모니터링하고 있는데 15분차트로 상승중인 심볼은 볼밴 하단
   이탈 하면 분할 매수 1-3번 정도 매수하고 긴상승에는 중단 이탈시 1-3번 분할
   매수하고 1-3번 매수 했는데 -5% 청산하고 tp1 익절도 5%부터 분할로 25%씩
   롱과숏을 이렇게 운영하는 시스템 ... 자금 100 200 300 이렇게 600으로 포지션
   운영하는 방식이야 익절 회기도 -3% 짧게"

사장님 선택 (2026-08-27):
  · 「긴 상승」 판정 = 가격이 4H 중단선 위(LONG)/아래(SHORT) **24시간 유지**
  · 분할 = **더 깊은 이탈** (기준선 대비 -3% / -5% / -7%)
  · 손절 -10%, TP1 15% 부터 25%씩, 트레일링 -3%
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

    「긴 추세」= 4H 종가가 4H 중단선 위(LONG)/아래(SHORT)로 LONG_TREND_BARS(6봉=24h) 연속 유지.

    분할 차수 = 기준선을 **얼마나 더 벗어났는가** (SHORT 는 부호 반대):
        1차 100 : 기준선 -3%
        2차 200 : 기준선 -5%
        3차 300 : 기준선 -7%
    → 2·3차는 stage_plan.trigger_price 로 심어두고 **기존 stage_trigger_worker 가
      가격 트리거로 처리**한다. 새 진입 경로를 만들지 않는다 (헌법 6).

■ 청산 규칙

    손절   : 평단 ROI **-10%** → 전량 (1·2·3차 어느 시점이든. Fix 178 이 보장)
    익절   : TP1 **+15%** 부터 **25%씩 4회** = +15 / +20 / +25 / +30
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
#    손절가는 -10% ... tp1 15% 부터"
#
# 실측 계산 (볼밴 기준선=1.0, 2x, 1차 진입가를 0% 로 두고):
#   1차 100U @ -3%  → 평단  0.00% (진입가대비)
#   2차 200U @ -5%  → 평단 -1.38%   누적 300U
#   3차 300U @ -7%  → 평단 -2.77%   누적 600U
#   손절 ROI -10%   → 진입가대비 -7.63% = 볼밴 -10.41%  손실 60U
#   TP1 15%         → 진입가대비 +4.52% (3차까지) / +7.50% (1차만)
#
# ⚠️ 왜 손절이 ROI 인가: 시스템 force SL 은 ROI 기준이다(risk_service).
#    ROI -10% 를 넣으면 3차까지 물렸을 때 볼밴 -10.41% 에서 잘려
#    사장님이 지정한 「-10%」와 사실상 일치하고, 2·3차 트리거보다 항상 뒤에 온다
#    (1차보유 손절 -7.85% / 2차보유 -9.13% → 3차 트리거 -7% 가 먼저).
#    = 어느 차수도 「죽은 단계」가 되지 않는다. 이 정합성은 검증 테스트로 고정한다.
CAPITALS = [Decimal("100"), Decimal("200"), Decimal("300")]   # 총 600
SPLIT_STEP_PCT = [Decimal("3"), Decimal("5"), Decimal("7")]   # 기준선 대비 이탈 심도
FORCE_SL_ROI = Decimal("10")       # 평단 ROI -10% 전량 청산
TP_PERCENTS = [15, 20, 25, 30]     # TP1 +15% 부터
TP_QTY_RATIOS = [25, 25, 25, 25]   # 25% 씩
TRAILING_RETRACE_PCT = Decimal("3")  # 익절 회귀 -3% (짧게)
LEVERAGE = 2

# ── 대상 선정 ──────────────────────────────────────────────────────────
MIN_ABS_24H_CHANGE = 15.0   # 급등락 = |24h 변동| 이상
MAX_CANDIDATES = 40
LONG_TREND_TF = "4h"
LONG_TREND_BARS = 6         # 4H 6봉 = 24시간
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


def _load_config(db) -> tuple[list[Decimal], int, str]:
    """(자본 3칸, 이 전략 전용 상한, 설명) — 설정 손상 시 기본값으로 fail-SAFE."""
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
    return caps, cap_n, src


def _fmt(v) -> str:
    return f"{float(v):.6f}"


def _is_long_trend(a4: dict, side: str) -> tuple[bool, str]:
    """4H 종가가 4H 중단선 위(LONG)/아래(SHORT)로 LONG_TREND_BARS 연속 유지했는가.

    사장님 선택: 「긴 상승 = 가격이 4H 중단선 위 24시간 유지」
    ⚠️ analyze_timeframe 은 마지막 봉의 밴드값만 준다. 과거 봉마다의 중단선을
       다시 계산하는 대신, 20MA(=중단선) 를 직접 산출해 봉별로 비교한다.
    """
    closes = a4.get("closes") or []
    n = len(closes)
    if n < 20 + LONG_TREND_BARS:
        return False, f"4H 봉 부족({n})"
    ok = 0
    # i=1 이 마지막 봉. 각 봉의 20MA 는 **그 봉을 포함한** 직전 20봉 평균이다
    # (볼린저 중단선 정의와 동일). 음수 슬라이스는 i=1 에서 빈 배열이 되므로
    # 양수 인덱스로 계산한다.
    for i in range(1, LONG_TREND_BARS + 1):
        end = n - i + 1          # exclusive
        start = end - 20
        if start < 0:
            return False, "4H 20MA 창 부족"
        window = closes[start:end]
        mb = sum(float(x) for x in window) / 20.0
        c = float(closes[n - i])
        if (side == "LONG" and c > mb) or (side == "SHORT" and c < mb):
            ok += 1
        else:
            break
    return (ok >= LONG_TREND_BARS,
            f"4H 중단선 {'위' if side == 'LONG' else '아래'} 연속 {ok}/{LONG_TREND_BARS}봉")


def _entry_plan(a15: dict, side: str, long_trend: bool) -> tuple[Decimal | None, str]:
    """기준선(base)과 사유를 반환. 1차 진입 조건 미충족이면 (None, 사유).

    ⚠️ 1차는 「기준선 이탈 즉시」가 아니라 **기준선 대비 SPLIT_STEP_PCT[0](-3%)
       까지 밀렸을 때** 진입한다 (사장님 확정: "볼밴 하단 -3% 이탈하면 100 진입").
       기준선을 스치고 바로 되돌리는 가짜 이탈을 걸러내기 위함이다.
    """
    up, mid, lo = a15.get("bb_up_last"), a15.get("bb_mid_last"), a15.get("bb_lo_last")
    closes = a15.get("closes") or []
    if not closes or up is None or mid is None or lo is None:
        return None, "15m 밴드/종가 없음"
    close = Decimal(str(closes[-1]))
    step1 = SPLIT_STEP_PCT[0] / Decimal("100")
    if side == "LONG":
        base = Decimal(str(mid)) if long_trend else Decimal(str(lo))
        label = "중단" if long_trend else "하단"
        need = base * (Decimal("1") - step1)          # 기준선 -3%
        if close > need:
            return None, (
                f"{label} -{SPLIT_STEP_PCT[0]}% 미도달 "
                f"(close {_fmt(close)} > 목표 {_fmt(need)} / {label} {_fmt(base)})"
            )
    else:
        base = Decimal(str(mid)) if long_trend else Decimal(str(up))
        label = "중단" if long_trend else "상단"
        need = base * (Decimal("1") + step1)          # 기준선 +3%
        if close < need:
            return None, (
                f"{label} +{SPLIT_STEP_PCT[0]}% 미도달 "
                f"(close {_fmt(close)} < 목표 {_fmt(need)} / {label} {_fmt(base)})"
            )
    return base, (
        f"{label} {SPLIT_STEP_PCT[0]}% 이탈 확인 "
        f"(close {_fmt(close)} / {label} {_fmt(base)} / 목표 {_fmt(need)})"
    )


def _build_template(
    db, symbol: str, side: str, base: Decimal, caps: list[Decimal],
) -> StrategyTemplate:
    """3단계 분할 + TP 25%×4 + 트레일링 -3% 템플릿. caps 는 설정에서 온 자본 3칸."""
    now = datetime.now(timezone.utc)
    # 2·3차 트리거 = 기준선 대비 -1%, -2% (SHORT 는 반대)
    trig = [None, float(SPLIT_STEP_PCT[1]), float(SPLIT_STEP_PCT[2])]
    tpl = StrategyTemplate(
        name=f"PUMPSPLIT_{symbol}_{side}_{now.strftime('%Y%m%d_%H%M%S')}",
        strategy_type=STRATEGY_TYPE,
        side=side,
        leverage=LEVERAGE,
        total_capital=sum(caps),
        stages_config={
            "capitals": [float(c) for c in caps],
            "trigger_percents": trig,
            "stages_count": 3,
            "base_price": float(base),
            "split_entry": True,
        },
        stage1_capital=caps[0],
        stage2_capital=caps[1],
        stage3_capital=caps[2],
        stage4_capital=None,
        # 기준선 대비 이탈 심도 = 가격 트리거 % (stage_trigger_worker 가 처리)
        stage2_trigger_percent=SPLIT_STEP_PCT[1],
        stage3_trigger_percent=SPLIT_STEP_PCT[2],
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
        caps, max_concurrent, cfg_src = _load_config(db)
        if max_concurrent <= 0:
            logger.info("[pump_split] ⏹️ %s=0 = 이 전략 OFF", MAX_CONCURRENT_KEY)
            return {"note": "전용 상한 0", **stat}
        _ok, _why = check_no_dead_stage(caps, SPLIT_STEP_PCT, FORCE_SL_ROI, LEVERAGE)
        if not _ok:
            # 죽은 단계가 생기는 설정으로는 **진입하지 않는다**.
            # 조용히 죽는 단계를 만드는 것이 가장 위험하다 (헌법 130).
            logger.error(
                "[pump_split] ⛔ 자본 설정 정합성 실패 → 진입 중단: %s "
                "| 자본=%s 심도=%s SL=-%s%% | %s 를 조정하세요",
                _why, [str(c) for c in caps], [str(s) for s in SPLIT_STEP_PCT],
                FORCE_SL_ROI, CAPITALS_KEY,
            )
            return {"note": f"정합성 실패: {_why}", **stat}
        logger.info(
            "[pump_split] 설정: 자본 %s (%s) | 전용 상한 %d | %s",
            "/".join(str(c) for c in caps), cfg_src, max_concurrent, _why,
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
                a4 = ChartAnalyzer.analyze_timeframe(bc, sym, LONG_TREND_TF, limit=40)
            except Exception as e:
                logger.warning("[pump_split] %s 분석 실패: %s", sym, e)
                _skip("analyze_error")
                continue
            if not a15 or not a4:
                _skip("no_analysis")
                continue

            long_trend, trend_why = _is_long_trend(a4, side)
            base, why = _entry_plan(a15, side, long_trend)
            if base is None:
                _skip("no_break")
                continue

            logger.info(
                "[pump_split] 🎯 %s %s 24h=%+.1f%% | %s | %s | 기준선=%s",
                sym, side, chg, trend_why, why, _fmt(base),
            )

            # 3) 전략 생성 — 1차는 MARKET 즉시, 2·3차는 가격 트리거로 대기
            try:
                tpl = _build_template(db, sym, side, base, caps)
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
                strategy.force_sl_roi_override = FORCE_SL_ROI
                strategy.trailing_retrace_pct = TRAILING_RETRACE_PCT
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
                    "[pump_split] ✅ 진입! #%s %s %s 1차 %s USDT "
                    "(2차 %s@-%s%% / 3차 %s@-%s%%) SL -%s%% TP %s%% 25%%×4 트레일 -%s%%",
                    strategy.id, sym, side, caps[0], caps[1], SPLIT_STEP_PCT[1],
                    caps[2], SPLIT_STEP_PCT[2], FORCE_SL_ROI, TP_PERCENTS[0],
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

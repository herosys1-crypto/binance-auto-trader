"""🪜 분할 진입 실행기 — 1차 시장가 + 2·3차 가격 트리거 (볼밴 분할 split_entry 경로) — 2026-09-15.

사장님 (2026-09-15): "10 100 200 이렇게 진입하는 전략을 고려해서 만들어주고 … 언제든지 자동매매 할수 있게 준비해줘"

볼밴 스윙(bb_swing_worker)과 규칙 가족(rule_family_worker)이 **같은 코드**로 연다 — 둘이 따로 만들면 갈라진다.
capital_management_mode=split_entry 라서 기존 안전장치가 그대로 붙는다:
  손절(risk_service 평단 ROI) · 2·3차 실체결가 재앵커(stage_trigger_worker Fix 209) · 피라미딩 제외 · 단계 정리 제외 · 반전 워커 제외.
진입 방식 근거 (2026-09-15 실측, docs/spec/AUTO_ENTRY_READY_2026-09-15.md): 가상매매 실시간 20,583건 × 15분봉 재생에서
  분할 10/100/200 · TP1 5 · 손절 ROI 10 이 분할 변형 중 가장 안정적 (TP1 15 + 손절 10 이 가장 나쁨, 「이기면 추가」는 대부분 더 나쁨).
⚠️ 재생은 「가격이 닿으면 2·3차 체결」로 계산했다. 실코드의 2·3차는 볼밴 분할 추가 게이트(정점-주춤 split_peak_stall ·
   Fix 218 조정 신호)를 통과해야 들어가므로, **1차 10 만 든 채 손절(≈ −1 USDT)되는 거래가 재생보다 많다** (반박 검증 9/15 H2).
   손절가 자체는 가격상 2·3차 트리거보다 뒤에 있다 (check_no_dead_stage) — 「게이트가 막지 않으면」 3차까지 들어간 뒤 손절이다.

반박 검증(2026-09-15) 반영:
  · H1 — split_entry 는 아직 안 들어간 2·3차 자본까지 130% 예약으로 센다 (capital_calculator). 이 실행기를 쓰는 가족을 여럿 켜면
    예약이 한도를 넘어 **다른 가족(기존 방식·OBV 자동)의 2단계를 막는다** (9/13 LSKUSDT 모양) → 전체 동시 보유 상한
    auto_split_max_concurrent_total (기본 3 × 310 = 930 USDT 예약) 을 호출자가 먼저 본다 (split_total_full).
  · L1 — 1차 주문을 보낸 뒤 후처리가 실패하면 보관하지 않는다 (거래소 포지션이 관리 없이 남지 않게 — 대사 워커가 맞춘다).
가드(킬스위치·ban·잔액·같은 심볼 방향·전용 슬롯)는 **호출자**가 먼저 본다 (surge_ladder_entry._guards_ok).
생성 게이트 2개(Fix 371 자동매매 중단 · 가족별 하루 최대)는 StrategyService / ExecutionService 안에서 다시 막는다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

logger = logging.getLogger(__name__)

FIX = "SPLIT"
LEVERAGE = 2
DEFAULT_CAPS = "10,100,200"         # 사장님 2026-09-15
DEFAULT_STEPS = "3,5,7"             # 볼밴 분할과 같음 (2·3차 = 1차 체결가 대비 약 2%씩)
DEFAULT_SL_ROI = "10"               # 볼밴 분할과 같음 — 가격상 2·3차 트리거보다 뒤 (단 2·3차 게이트가 막으면 1차만 든 채 손절)
DEFAULT_TP1 = "5"                   # 실측 최선 (TP2~4 = 2·3·4배, 25%씩)
DEFAULT_TRAIL = "3"
SPLIT_TOTAL_KEY = "auto_split_max_concurrent_total"
SPLIT_TOTAL_DEFAULT = 3             # Claude가 정함 — 3 × 310 = 930 USDT 예약 (지갑 3,890 × 130% ≈ 5,057 의 18%)


def parse_config(caps_raw: str | None, steps_raw: str | None, sl_raw: str | None) -> tuple[list[Decimal], list[Decimal], Decimal, str]:
    """볼밴 분할 파서로 검증. 반환 (자본 3칸, 심도 3칸, 손절 ROI, 메모). 메모 != "설정 OK" = 손상·정합성 실패 → 기본값이 들어 있다.
    호출자는 메모가 "설정 OK" 가 아니면 **진입하지 않는다** (사장님 설정과 다른 값으로 거래하지 않게 — 반박 검증 9/15 L2)."""
    from app.workers import pump_split_entry_worker as PS
    notes: list[str] = []

    def _p(raw, default, parser, name):
        try:
            return parser(raw if raw not in (None, "") else default)
        except Exception as e:  # noqa: BLE001
            notes.append(f"{name} 손상→기본 ({e})")
            return parser(default)

    caps = _p(caps_raw, DEFAULT_CAPS, PS._parse_capitals, "자본")
    steps = _p(steps_raw, DEFAULT_STEPS, PS._parse_steps, "심도")
    sl = _p(sl_raw, DEFAULT_SL_ROI, PS._parse_sl_roi, "손절")
    ok, why = PS.check_no_dead_stage(caps, steps, sl, LEVERAGE)
    if not ok:
        notes.append(f"정합성 실패 → 기본값 ({why})")
        caps, steps, sl = PS._parse_capitals(DEFAULT_CAPS), PS._parse_steps(DEFAULT_STEPS), PS._parse_sl_roi(DEFAULT_SL_ROI)
    return caps, steps, sl, " / ".join(notes) or "설정 OK"


def uses_executor(strategy_type: str | None) -> bool:
    """이 실행기로 여는 전략 종류 (전체 상한 집계 대상)."""
    st = str(strategy_type or "")
    return st.startswith("rf_") or st == "bb_swing"


def split_total_cap(db) -> int:
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, SPLIT_TOTAL_KEY)
        if row is None or row.value is None or not str(row.value).strip():
            return SPLIT_TOTAL_DEFAULT
        n = int(float(str(row.value).strip()))
        return n if 0 <= n <= 100 else SPLIT_TOTAL_DEFAULT
    except Exception:  # noqa: BLE001
        return SPLIT_TOTAL_DEFAULT


def split_total_full(db) -> tuple[bool, str]:
    """이 실행기를 쓰는 분할 전략(규칙 가족 · 볼밴 스윙) 전체 동시 보유가 상한인가. 조회 실패 = 찼다고 본다 (fail-closed)."""
    cap = split_total_cap(db)
    try:
        from app.core.strategy_status import ACTIVE_LIKE, SPLIT_ENTRY_MODE
        from app.models.strategy_instance import StrategyInstance as SI
        from app.models.strategy_template import StrategyTemplate as T
        rows = db.execute(
            select(T.strategy_type)
            .join(SI, SI.strategy_template_id == T.id)
            .where(SI.capital_management_mode == SPLIT_ENTRY_MODE, SI.is_archived.is_(False),
                   SI.status.in_(tuple(ACTIVE_LIKE) + ("WAITING",)))
        ).scalars().all()
        n = sum(1 for st in rows if uses_executor(st))
    except Exception as e:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        return True, f"분할 자동 전략 수 조회 실패 = 막음 ({e})"
    return n >= cap, f"분할 자동 전략 동시 {n}/{cap} ({SPLIT_TOTAL_KEY})"


def anchor_base(price: float, side: str, steps: list[Decimal]) -> Decimal:
    """계산기는 1차 체결가를 기준선 × (1 ∓ 1차 심도) 로 본다 → 예상 체결가에서 거꾸로 푼다 (저장 트리거·검산이 실제와 맞게)."""
    s1 = Decimal(str(steps[0])) / Decimal("100")
    px = Decimal(str(price))
    return px / (Decimal("1") - s1) if str(side).upper() == "LONG" else px / (Decimal("1") + s1)


def tp_percents(tp1: float) -> list[float]:
    return [float(tp1) * k for k in (1, 2, 3, 4)]


def build_template(db, *, symbol: str, side: str, base: Decimal, caps: list[Decimal], steps: list[Decimal],
                   tp1: float, strategy_type: str, name_prefix: str, label: str):
    from app.models.strategy_template import StrategyTemplate
    from app.workers.pump_split_entry_worker import compounded_trigger_pcts
    pcts = compounded_trigger_pcts(side, steps)          # Fix 195: 계산기 복리 앵커 기준으로 환산
    tps = tp_percents(tp1)
    tpl = StrategyTemplate(
        name=f"{name_prefix}{symbol}_{side}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        strategy_type=strategy_type,
        side=side,
        leverage=LEVERAGE,
        total_capital=sum(caps),
        stages_config={
            "capitals": [float(c) for c in caps],
            "trigger_percents": [None] + [float(p) for p in pcts[1:]],
            "last_stage_trigger_mode": "PRICE_DOWN_PCT" if side == "LONG" else "PRICE_UP_PCT",
            "last_stage_trigger_percent": float(pcts[-1]),
            "stages_count": 3,
            "base_price": float(base),
            "split_entry": True,
            "steps": [float(s) for s in steps],           # Fix 209 재앵커가 읽는다
            "family_label": label,                        # 화면·기록에서 어느 전략인지
            "entry_plan": "/".join(f"{c:g}" for c in caps),
        },
        stage1_capital=caps[0], stage2_capital=caps[1], stage3_capital=caps[2], stage4_capital=None,
        stage2_trigger_percent=steps[1], stage3_trigger_percent=steps[2], stage4_trigger_percent=None,
        tp1_percent=Decimal(str(tps[0])), tp2_percent=Decimal(str(tps[1])),
        tp3_percent=Decimal(str(tps[2])), tp4_percent=Decimal(str(tps[3])),
        tp1_qty_ratio=Decimal("25"), tp2_qty_ratio=Decimal("25"), tp3_qty_ratio=Decimal("25"), tp4_qty_ratio=Decimal("25"),
        stop_loss_percent_of_capital=Decimal("90"),
        is_active=True,
    )
    db.add(tpl)
    db.flush()
    return tpl


def _archive(db, si: Any, code: str, msg: str) -> None:
    try:
        si.status = "STOPPED"
        si.is_archived = True
        si.last_error_code = code
        si.last_error_message = str(msg)[:500]
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        logger.error("[%s] #%s 보관 처리 실패: %s", FIX, getattr(si, "id", "?"), e)


def _order_sent(db, strategy_id: int) -> bool:
    """이 전략으로 거래소 주문 기록이 하나라도 있는가. 조회 실패 = 있다고 본다 (살아 있을지 모르는 포지션을 보관으로 숨기지 않게)."""
    try:
        from app.models.order import Order
        return (db.execute(select(func.count()).select_from(Order).where(Order.strategy_instance_id == strategy_id)).scalar() or 0) > 0
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] #%s 주문 기록 조회 실패 = 주문 있음으로 간주: %s", FIX, strategy_id, e)
        return True


def _exec(db, account):
    from app.core.crypto import decrypt_text
    from app.services.execution_service import ExecutionService
    return ExecutionService(db, api_key=decrypt_text(account.api_key_enc),
                            api_secret=decrypt_text(account.api_secret_enc), is_testnet=account.is_testnet)


def open_split_position(db, account, *, symbol: str, side: str, price: float, strategy_type: str, name_prefix: str,
                        label: str, caps: list[Decimal], steps: list[Decimal], sl_roi: Decimal, tp1: float,
                        trail: float) -> tuple[Any | None, str, str]:
    """(인스턴스 | None, 결과코드, 사유). 결과코드: entered · create_blocked · dead_stage · start_failed · start_unconfirmed.
    가드·전체 상한은 호출자가 먼저 본다. 1차 주문 전 실패 = 인스턴스 보관 처리(모든 가족의 같은 심볼·방향을 막지 않게).
    1차 주문 뒤 실패(start_unconfirmed) = 보관하지 않는다 (거래소 포지션이 남았을 수 있다 — 대사 워커가 맞춘다)."""
    from app.core.strategy_status import SPLIT_ENTRY_MODE
    from app.models.strategy_stage_plan import StrategyStagePlan
    from app.services.strategy_service import StrategyService
    from app.workers.pump_split_entry_worker import verify_stage_plans

    base = anchor_base(price, side, steps)
    try:
        tpl = build_template(db, symbol=symbol, side=side, base=base, caps=caps, steps=steps, tp1=tp1,
                             strategy_type=strategy_type, name_prefix=name_prefix, label=label)
        si = StrategyService(db).create_strategy_instance(
            user_id=1, exchange_account_id=account.id, strategy_template_id=tpl.id, symbol=symbol, side=side,
            start_price=base, leverage_override=LEVERAGE, capital_management_mode=SPLIT_ENTRY_MODE,
        )
    except ValueError as e:                     # Fix 371 자동매매 중단 · 가족별 하루 최대 · 마진 위험 등 생성 게이트
        db.rollback()
        return None, "create_blocked", str(e)
    si.force_sl_enabled_override = True         # 물타기 = 손절이 반드시 살아 있어야 한다
    si.force_sl_roi_override = sl_roi
    si.trailing_retrace_pct = Decimal(str(trail))
    si.tp1_pct_override = Decimal(str(tp1))     # 생성 기본 TP1 override(15) 가 템플릿을 덮지 않게 (Fix 205)
    db.commit()

    s1 = db.execute(
        select(StrategyStagePlan).where(StrategyStagePlan.strategy_instance_id == si.id, StrategyStagePlan.stage_no == 1)
    ).scalar_one_or_none()
    if s1 is not None:
        s1.trigger_price = None                 # 1차 = 시장가 즉시
        db.commit()

    plans = db.execute(select(StrategyStagePlan).where(StrategyStagePlan.strategy_instance_id == si.id)).scalars().all()
    ok, vwhy = verify_stage_plans(plans, base, side, caps, steps, sl_roi, LEVERAGE)
    if not ok:
        _archive(db, si, "SPLIT_DEAD_STAGE", vwhy)
        logger.error("[%s] ⛔ #%s %s %s %s 주문 전 취소 — %s", FIX, si.id, label, symbol, side, vwhy)
        return None, "dead_stage", vwhy

    try:
        _exec(db, account).start_stage1(si.id)
    except Exception as e:  # noqa: BLE001 — 24h 순위·지지선 게이트·하루 최대·레버리지 설정 실패 등
        db.rollback()
        if _order_sent(db, si.id):
            logger.error("[%s] 🚨 #%s %s %s %s 1차 주문 기록이 있는데 후처리 실패 — 보관하지 않음 (대사 워커 확인 필요): %s",
                         FIX, si.id, label, symbol, side, e)
            return None, "start_unconfirmed", str(e)
        _archive(db, si, "SPLIT_START_FAILED", str(e))
        logger.warning("[%s] ⛔ #%s %s %s %s 1차 주문 실패 → 보관: %s", FIX, si.id, label, symbol, side, e)
        return None, "start_failed", str(e)
    logger.warning("[%s] ✅ #%s [%s] %s %s 진입 | 기준선 %s (가격 %s) | 자본 %s 심도 %s%% | 손절 ROI -%s%% TP1 %g%% 25%%×4 트레일 %g%%",
                   FIX, si.id, label, symbol, side, base, price, "/".join(str(c) for c in caps),
                   "/".join(str(s) for s in steps), sl_roi, tp1, trail)
    return si, "entered", ""

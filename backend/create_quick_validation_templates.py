"""testnet stages 2~5 + TP/SL 풀 사이클 검증용 빠른 트리거 템플릿 생성.

자연 시세 변동으로 stages 2~5 가 트리거되려면 BTC 5%+ 변동이 필요해
며칠 걸린다. 이 스크립트는 0.5%/1.0%/1.5%/2.0% 의 매우 타이트한 트리거를
가진 _quick_ 프리픽스 템플릿을 SHORT/LONG 양방향으로 만들어준다.

이름이 _quick_ 으로 시작하므로 운영 종료 후 admin UI 의
"QUICK 정리" 버튼으로 일괄 삭제 가능 (Bug #14 수정 완료).

사용:
    docker compose exec api python /app/create_quick_validation_templates.py

만들어지는 템플릿:
    1. _quick_5stage_short_validation  (SHORT, 750 USDT 총 자본)
    2. _quick_5stage_long_validation   (LONG,  750 USDT 총 자본)

전략 시작 시 추천 심볼: BTCUSDT (testnet)
- testnet BTC 일일 변동성 1~5% 라 30분~수시간 안에 모든 단계 트리거 가능.
- start_price 는 SHORT 면 현재가 -0.1%, LONG 이면 현재가 +0.1% 로 즉시 체결 유도.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.strategy_template import StrategyTemplate


def _build_stages_config(
    capitals: list[int],
    trigger_percents: list[float | None],
    *,
    last_stage_trigger_mode: str | None = None,
    last_stage_trigger_percent: float | None = None,
) -> dict:
    """admin.py 의 create endpoint 와 동일한 형식으로 stages_config 빌드."""
    cfg: dict = {
        "capitals": [str(c) for c in capitals],
        "trigger_percents": [str(p) if p is not None else None for p in trigger_percents],
    }
    if last_stage_trigger_mode:
        cfg["last_stage_trigger_mode"] = last_stage_trigger_mode
    if last_stage_trigger_percent is not None:
        cfg["last_stage_trigger_percent"] = str(last_stage_trigger_percent)
    return cfg


# ---------------------------------------------------------------------------
# 두 개 템플릿 정의 — SHORT 와 LONG 양방향
# ---------------------------------------------------------------------------
TEMPLATES = [
    {
        "name": "_quick_5stage_short_validation",
        "strategy_type": "DYNAMIC_SHORT",
        "side": "SHORT",
        "leverage": 10,
        # Bug #15 fix (2026-04-29): BTCUSDT min_notional=50, step_size 반올림으로
        # capital 50 USDT 가 50 미만으로 떨어져 -4164 거절. 모든 단계 100 이상으로 상향.
        "capitals": [100, 150, 200, 250, 300],   # 총 1000 USDT (notional safe margin)
        # 중간 단계 (2~4) 의 trigger_percent. stage1 은 None (시작가 즉시).
        "trigger_percents": [None, 0.5, 1.0, 1.5, None],
        # 마지막 단계 (5) 도 가격 % 기반으로 명시 — SHORT 기본값은 LIQUIDATION_BUFFER 라
        # 청산가 근처에서만 트리거 → 검증 불가능. 그래서 PRICE_UP_PCT 로 강제.
        "last_stage_trigger_mode": "PRICE_UP_PCT",
        "last_stage_trigger_percent": 2.0,
        # TP 는 profit % (SHORT 면 가격 ↓ 시 익절). 검증용 매우 작은 값.
        "tp_percents": [0.5, 1.0, 1.5, 2.0, 3.0],
        # qty_ratio 는 정수 % (admin.py Field gt=0, le=100). 합이 100 이어야 풀청산.
        "tp_qty_ratios": [20, 20, 20, 20, 20],  # 균등 분배 (20% × 5 = 100%)
        "stop_loss_percent_of_capital": 50,     # SL: 자본 -50%
    },
    {
        "name": "_quick_5stage_long_validation",
        "strategy_type": "DYNAMIC_LONG",
        "side": "LONG",
        "leverage": 10,
        # Bug #15 fix: BTCUSDT min_notional 안전 여유 위해 100+
        "capitals": [100, 150, 200, 250, 300],   # 총 1000 USDT
        "trigger_percents": [None, 0.5, 1.0, 1.5, None],
        # LONG 의 마지막 단계 기본값은 PRICE_DOWN_PCT 지만 명시해서 일관성 확보.
        "last_stage_trigger_mode": "PRICE_DOWN_PCT",
        "last_stage_trigger_percent": 2.0,
        "tp_percents": [0.5, 1.0, 1.5, 2.0, 3.0],
        "tp_qty_ratios": [20, 20, 20, 20, 20],
        "stop_loss_percent_of_capital": 50,
    },
]


def _upsert_template(db, spec: dict) -> tuple[str, str]:
    """이름이 같은 템플릿이 있으면 업데이트, 없으면 생성. (action, name) 반환."""
    existing = db.execute(
        select(StrategyTemplate).where(StrategyTemplate.name == spec["name"])
    ).scalars().first()

    capitals = [Decimal(str(c)) for c in spec["capitals"]]
    total_capital = sum(capitals)
    stages_config = _build_stages_config(spec["capitals"], spec["trigger_percents"])
    tp_p = spec["tp_percents"]
    tp_q = spec["tp_qty_ratios"]

    fields = dict(
        strategy_type=spec["strategy_type"],
        side=spec["side"],
        leverage=spec["leverage"],
        total_capital=total_capital,
        stages_config=stages_config,
        # 구 4단계 컬럼도 호환 위해 채움
        stage1_capital=capitals[0],
        stage2_capital=capitals[1] if len(capitals) >= 2 else None,
        stage3_capital=capitals[2] if len(capitals) >= 3 else None,
        stage4_capital=capitals[3] if len(capitals) >= 4 else None,
        tp1_percent=Decimal(str(tp_p[0])),
        tp2_percent=Decimal(str(tp_p[1])),
        tp3_percent=Decimal(str(tp_p[2])),
        tp4_percent=Decimal(str(tp_p[3])),
        tp5_percent=Decimal(str(tp_p[4])),
        tp1_qty_ratio=Decimal(str(tp_q[0])),
        tp2_qty_ratio=Decimal(str(tp_q[1])),
        tp3_qty_ratio=Decimal(str(tp_q[2])),
        tp4_qty_ratio=Decimal(str(tp_q[3])),
        tp5_qty_ratio=Decimal(str(tp_q[4])),
        stop_loss_percent_of_capital=Decimal(str(spec["stop_loss_percent_of_capital"])),
        reentry_policy="manual_ready",
        reentry_delay_seconds=600,
        reentry_offset_pct=Decimal("1.0"),
        is_active=True,
    )

    if existing:
        for k, v in fields.items():
            setattr(existing, k, v)
        return ("updated", spec["name"])
    else:
        new = StrategyTemplate(name=spec["name"], **fields)
        db.add(new)
        return ("created", spec["name"])


def main() -> None:
    db = SessionLocal()
    try:
        results: list[tuple[str, str]] = []
        for spec in TEMPLATES:
            results.append(_upsert_template(db, spec))
        db.commit()
        print("=" * 60)
        print("Quick validation templates ready:")
        for action, name in results:
            mark = "+" if action == "created" else "~"
            print(f"  {mark} [{action}] {name}")
        print("=" * 60)
        print()
        print("다음 단계:")
        print("  1) admin UI 에서 전략 생성 → 템플릿 '_quick_5stage_short_validation' 선택")
        print("  2) 심볼: BTCUSDT")
        print("  3) 시작가: 현재가 -0.1% (SHORT 즉시 체결 유도)")
        print("  4) 거래소 계정: testnet 계정 (#1)")
        print("  5) 시작 후 텔레그램 '전략 시작' 알림 확인")
        print("  6) BTC 시세 변동 모니터링 → stages 2~5 트리거 검증")
        print("  7) 최종 정리: admin UI 'QUICK 정리' 버튼")
    finally:
        db.close()


if __name__ == "__main__":
    main()

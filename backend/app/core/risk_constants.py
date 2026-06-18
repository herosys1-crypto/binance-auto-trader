"""Risk / TP / SL / Crisis 정책 상수 — single source of truth.

배경 (2026-05-14 Phase 2):
- Decimal magic number 가 13 파일에 74 occurrences 분산
- 같은 의미 상수가 각자 표현 (예 Decimal("100") for percentage 의 35+ 곳)
- 5-14 SL 90% 버그의 직접 원인: risk_service.py:79 의 hardcoded Decimal("0.50")
  이 template.stop_loss_percent_of_capital 를 무시 — 의미상 default 값이었지만
  명명되지 않은 magic number 라 사용자 입력 적용을 빼먹음
- 정책 변경 시 (ex: 트레일링 임계 5% → 7%) 여러 파일 동시 수정 필요 → drift 위험

Phase 2 centralize:
- 의미있는 모든 임계/비율/한도 상수를 이 파일 1곳에서 정의
- risk_service.py / tp_sl_orchestrator.py 등은 import + re-export (backward compat)
- 새 코드는 이 모듈 직접 import 권장

규칙:
- 의미가 분명한 정책 상수만 (정밀도 magic 은 별개)
- 사용자 정의 가능한 default 값은 명시적 _DEFAULT suffix
- 단위 (PCT, USDT, RATIO) 명확히
"""
from __future__ import annotations

from decimal import Decimal
from typing import Final


# ===== 일반 산술 / 변환 =====
# 퍼센트 → ratio 변환 분모. ratio = pct / PERCENT_DENOMINATOR.
PERCENT_DENOMINATOR: Final[Decimal] = Decimal("100")
# 레버리지 fallback (strategy.leverage NULL 인 가드 — 사실상 발생 안 함).
LEVERAGE_FALLBACK: Final[Decimal] = Decimal("1")
# 청산 비율 100% (전량) — close_qty = current_qty * FULL_CLOSE_RATIO.
FULL_CLOSE_RATIO: Final[Decimal] = Decimal("1.00")


# ===== 정밀도 (quantize) =====
# USDT 금액 quantize — 소수 2자리 (cent).
USDT_PRICE_PRECISION: Final[Decimal] = Decimal("0.01")
# Quantity quantize — 8자리 (Binance 일반 max precision).
QTY_PRECISION: Final[Decimal] = Decimal("0.00000001")
# Symbol step_size 미설정 시 fallback (대부분 0.001).
DEFAULT_STEP_SIZE_FALLBACK: Final[Decimal] = Decimal("0.001")


# ===== Stop Loss (SL) =====
# template.stop_loss_percent_of_capital 가 NULL/0 일 때 default.
# 🚨 2026-06-19 사장님 critical 변경: 100% → 90% (= 사장님 SYNUSDT Liquidation 사건!)
# SYNUSDT = 가격 +49% 상승 → Liquidation 먼저! SL -100% = 발동 X = 사장님 -585 USDT 손실!
# 신 v5 = SL 90% = Liquidation 안전 마진 + 사장님 자본 보호!
DEFAULT_SL_PCT_OF_CAPITAL: Final[Decimal] = Decimal("90")

# 강제 청산 알림 임계 — max_loss_pct 가 처음 이 값 이하로 내려가는 사이클에 1회 알림.
LOSS_ALERT_THRESHOLD_PCT: Final[Decimal] = Decimal("-50")


# ===== Take Profit (TP) — 정상 모드 =====
# TP1~9 default qty ratio (잔량의 %). v6 정책 (2026-05-12): 균일 25%.
# TP10 만 100% (마지막 안전망 — trailing 미발동 + 가격 계속 상승 케이스).
DEFAULT_TP_QTY_RATIO_PCT: Final[Decimal] = Decimal("25")
TP_FINAL_QTY_RATIO_PCT: Final[Decimal] = Decimal("100")  # TP10 default


# ===== Trailing TP =====
# 피크가 이 % 이상 도달했어야 trailing armed.
TRAILING_PEAK_THRESHOLD_PCT: Final[Decimal] = Decimal("5")
# 피크 대비 이 % 회귀 시 전량 청산.
# 🌟 2026-06-10 v36 사장님 결정: default 5 → 10 (더 큰 익절 잠재력!)
# 사장님: "tp3단계 익절후 최고가 대비 -5% 하락하면 청산을 하는데
#          기본을 10%으로 해주고 상황에 따라 설정할수 있게"
# = default 10% 변경 + 옵션 5/10/15/20 그대로 (= 사장님 자율)
TRAILING_RETRACE_PCT: Final[Decimal] = Decimal("10")
# Trailing 발동 최소 TP index (TP3 이상부터 활성).
TRAILING_MIN_TP_INDEX: Final[int] = 3
# 🌟 2026-06-09 v8 사장님 BEATUSDT 사례로 완화 (= 1단계만 진입해도 트레일링 발동):
# 사장님 의도: 'tp3 정상 익절후 계속 유지하고 tp4를 못가도 최고가 대비 -15% 빠져야 익절청산'
# = stage<3 인 strategy 도 트레일링 작동해야 함
# (= v5 옛 의도 「stage>=3 만 trailing」 폐기, v7 단축 익절 폐기와 함께)
TRAILING_MIN_STAGE: Final[int] = 1
# Redis peak 키 TTL (30일).
PEAK_REDIS_TTL_SECONDS: Final[int] = 60 * 60 * 24 * 30


# ===== Crisis 복구 모드 =====
# template.crisis_max_loss_threshold NULL 시 default.
# 의미: 누적 최대 손실 % 가 이 값 이하 도달 시 Crisis 모드 진입.
CRISIS_MAX_LOSS_THRESHOLD_DEFAULT: Final[Decimal] = Decimal("-50")

# Sentinel 값 — template.crisis_max_loss_threshold = -100 이면 Crisis 비활성.
# 사용자 결정 (2026-05-14): 새 strategy 는 자동으로 이 값 주입 → 손절만 작동.
CRISIS_DISABLED_SENTINEL: Final[Decimal] = Decimal("-100")

# Crisis 모드 첫 TP 임계 (+5% 도달 시 첫 청산).
CRISIS_TP1_THRESHOLD_PCT: Final[Decimal] = Decimal("5")
# Crisis 첫 TP 후 피크 대비 이 % 회귀 시 전량 청산.
CRISIS_TRAILING_DROP_PCT: Final[Decimal] = Decimal("5")
# Crisis 첫 TP 후 PnL 이 이 % 이하 시 전량 손절.
CRISIS_HARD_SL_THRESHOLD_PCT: Final[Decimal] = Decimal("-1")

# Crisis 모드 qty ratio default (사용자 spec, 2026-04-30 이후 고정).
# template.crisis_qty_ratios JSONB override 가능 (alembic 0009).
# TP1=25%, TP2=25%, TP3=50% of remaining, TP4=100% of remaining.
CRISIS_QTY_RATIO_DEFAULT: Final[dict[str, Decimal]] = {
    "TP1": Decimal("25"),
    "TP2": Decimal("25"),
    "TP3": Decimal("50"),
    "TP4": Decimal("100"),
}
# Override 검사 시 허용 키 (TP5+ 등 알 수 없는 키는 무시).
CRISIS_RATIO_KEYS: Final[tuple[str, ...]] = ("TP1", "TP2", "TP3", "TP4")


__all__ = [
    # 일반
    "PERCENT_DENOMINATOR",
    "LEVERAGE_FALLBACK",
    "FULL_CLOSE_RATIO",
    # 정밀도
    "USDT_PRICE_PRECISION",
    "QTY_PRECISION",
    "DEFAULT_STEP_SIZE_FALLBACK",
    # SL
    "DEFAULT_SL_PCT_OF_CAPITAL",
    "LOSS_ALERT_THRESHOLD_PCT",
    # TP
    "DEFAULT_TP_QTY_RATIO_PCT",
    "TP_FINAL_QTY_RATIO_PCT",
    # Trailing
    "TRAILING_PEAK_THRESHOLD_PCT",
    "TRAILING_RETRACE_PCT",
    "TRAILING_MIN_TP_INDEX",
    "TRAILING_MIN_STAGE",
    "PEAK_REDIS_TTL_SECONDS",
    # Crisis
    "CRISIS_MAX_LOSS_THRESHOLD_DEFAULT",
    "CRISIS_DISABLED_SENTINEL",
    "CRISIS_TP1_THRESHOLD_PCT",
    "CRISIS_TRAILING_DROP_PCT",
    "CRISIS_HARD_SL_THRESHOLD_PCT",
    "CRISIS_QTY_RATIO_DEFAULT",
    "CRISIS_RATIO_KEYS",
]

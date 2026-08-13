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
# = 마진(사장님 자금) 대비 몇 % 손실에서 손절할 것인가.
#
# 이력:
#   2026-06-19 v5  : 100 → 90
#       🚨 SYNUSDT Liquidation 사건! 가격 +49% 상승 → Liquidation 이 SL 보다 먼저 발동
#          (SL -100% = 청산 뒤라 무의미) = 사장님 -585 USDT 손실.
#          → 90% 로 낮춰 **청산 전에 손절**되도록 안전 마진 확보.
#   2026-08-14 v147: 90 → **50** (사장님 지시)
#       = 청산 회피를 넘어 **손실 자체를 절반에서 끊는** 방향.
#       v139 백테스트 근거와도 일치: 깊은 물타기 8건이 전체 손실의 43% 였음
#       (일찍 끊었다면 그 대형 손실이 크게 줄었을 구간).
# ⚠️ 효과: 손절이 **더 일찍** 발동합니다 = 건당 손실 감소 / 되돌아올 자리에서도 끊길 수 있음.
DEFAULT_SL_PCT_OF_CAPITAL: Final[Decimal] = Decimal("50")

# 강제 청산 알림 임계 — max_loss_pct 가 처음 이 값 이하로 내려가는 사이클에 1회 알림.
LOSS_ALERT_THRESHOLD_PCT: Final[Decimal] = Decimal("-50")


# ===== 손실 한도 강제 청산 (Force Stop-Loss / Loss-Limit Close) =====
# 2026-06-24 사장님 사상 — docs/spec/FORCE_SL_LOSS_LIMIT_SPEC_2026-06-24.md.
# ROI 기준 전역 강제 손절. 기존 SL(-80~90%)보다 빡빡한 추가 안전망 (공존).
# 롱 기본 ON(-10%), 숏 기본 OFF. 아무 단계에서나 발동. 가격 없으면 청산 금지.
# 전역 설정 키 (system_settings 테이블, side별 독립):
FORCE_SL_LONG_ENABLED_KEY: Final[str] = "force_sl_long_enabled"
FORCE_SL_LONG_ROI_KEY: Final[str] = "force_sl_long_roi"
FORCE_SL_SHORT_ENABLED_KEY: Final[str] = "force_sl_short_enabled"
FORCE_SL_SHORT_ROI_KEY: Final[str] = "force_sl_short_roi"
# 기본값 (사장님 확정 2026-06-24 원상태 복원 2026-08-08):
#   롱 ON / 숏 OFF (원상태!)
#   default = -10% (모든 단계 진입 후에만 발동 = risk_service v130 사장님 사상!)
FORCE_SL_LONG_ENABLED_DEFAULT: Final[bool] = True
FORCE_SL_SHORT_ENABLED_DEFAULT: Final[bool] = False  # 원상태 복원!
# 양수로 저장 (예: 10 = ROI <= -10% 시 발동, 모든 단계 진입 후에만!).
FORCE_SL_ROI_DEFAULT: Final[Decimal] = Decimal("10")
# 허용 ROI 한도 (사장님 선택지). 그 외 값은 API 400.
# 🌟 2026-08-09 v131 사장님 확장: 0 (끔!) + 5 ~ 100 (5% 간격)!
FORCE_SL_ALLOWED_ROI: Final[tuple[Decimal, ...]] = (
    Decimal("0"),   # 끔! (강제 SL 미사용)
    Decimal("5"), Decimal("10"), Decimal("15"), Decimal("20"),
    Decimal("25"), Decimal("30"), Decimal("35"), Decimal("40"),
    Decimal("45"), Decimal("50"), Decimal("60"), Decimal("70"),
    Decimal("80"), Decimal("90"), Decimal("100"),
)


# ===== Take Profit (TP) — 정상 모드 =====
# TP1~9 default qty ratio (잔량의 %). v6 정책 (2026-05-12): 균일 25%.
# TP10 만 100% (마지막 안전망 — trailing 미발동 + 가격 계속 상승 케이스).
DEFAULT_TP_QTY_RATIO_PCT: Final[Decimal] = Decimal("25")
TP_FINAL_QTY_RATIO_PCT: Final[Decimal] = Decimal("100")  # TP10 default


# ===== TP1 임계 =====
# 신규 전략 생성 시 tp1_pct_override 에 넣는 기본값 (= TP1 이 발동하는 ROI %).
# 이력:
#   2026-08-08 v130 : 25 (사장님 "새로 정한건 모두 유효해")
#   2026-08-14 v147 : 25 → **15** (사장님 지시 — "tp1 단계 시작도 15%로")
# ⚠️ 낮추면 **더 일찍 1차 익절**합니다. 기존 전략은 저장된 값을 유지하며,
#    목록의 「TP1」 드롭다운으로 전략별 변경 가능 (0=TP 끔 / 10~30).
TP1_PCT_DEFAULT: Final[Decimal] = Decimal("15")

# ===== Trailing TP =====
# 피크가 이 % 이상 도달했어야 trailing armed.
TRAILING_PEAK_THRESHOLD_PCT: Final[Decimal] = Decimal("5")
# 피크 대비 이 % 회귀 시 전량 청산.
# 이력:
#   2026-06-10 v36 : 5 → 10 (사장님 "기본을 10%으로 해주고 상황에 따라 설정")
#   2026-08-14 v147: 10 → **5** (사장님 지시 — 전략 인스턴스 목록의
#                    「PNL / ROI 액션」 드롭다운 기본을 -5% 로)
# ⚠️ 이 값을 낮추면 피크 후 **더 빨리 청산**됩니다 (익절을 짧게 가져감).
#    옵션 5/10/15/20 은 그대로 = 전략별로 사장님이 개별 변경 가능.
TRAILING_RETRACE_PCT: Final[Decimal] = Decimal("5")
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


# ── 손익 액션 기준 (v147, 사장님 지시 2026-08-14) ─────────────────────
#   "pnl/roi 액션 기본을 -5%로 해줘"
#   기존엔 분석 판단(-20/-50)과 TP/SL 어드바이저(-20)에 **흩어져** 있었습니다.
#   → 여기 한 곳으로 모읍니다 (헌법 6번 단일 진실).
#
#   ACTION_PNL_PCT_DEFAULT = 사장님이 지정한 **기본 액션 임계**.
#     ROI 가 이 값 이하로 내려가면 화면에 「조치 검토」를 띄웁니다.
ACTION_PNL_PCT_DEFAULT = -5.0      # 사장님 지정 기본
ACTION_PNL_REVIEW_PCT = -20.0      # 주의 단계
ACTION_PNL_URGENT_PCT = -50.0      # 긴급 청산 검토

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
    # 손실 한도 강제 청산 (Force SL)
    "FORCE_SL_LONG_ENABLED_KEY",
    "FORCE_SL_LONG_ROI_KEY",
    "FORCE_SL_SHORT_ENABLED_KEY",
    "FORCE_SL_SHORT_ROI_KEY",
    "FORCE_SL_LONG_ENABLED_DEFAULT",
    "FORCE_SL_SHORT_ENABLED_DEFAULT",
    "FORCE_SL_ROI_DEFAULT",
    "FORCE_SL_ALLOWED_ROI",
    # TP
    "TP1_PCT_DEFAULT",
    "DEFAULT_TP_QTY_RATIO_PCT",
    "TP_FINAL_QTY_RATIO_PCT",
    # Trailing
    "TRAILING_PEAK_THRESHOLD_PCT",
    "TRAILING_RETRACE_PCT",
    "TRAILING_MIN_TP_INDEX",
    "TRAILING_MIN_STAGE",
    "PEAK_REDIS_TTL_SECONDS",
    # 손익 액션 기준 (v147)
    "ACTION_PNL_PCT_DEFAULT",
    "ACTION_PNL_REVIEW_PCT",
    "ACTION_PNL_URGENT_PCT",
    # Crisis
    "CRISIS_MAX_LOSS_THRESHOLD_DEFAULT",
    "CRISIS_DISABLED_SENTINEL",
    "CRISIS_TP1_THRESHOLD_PCT",
    "CRISIS_TRAILING_DROP_PCT",
    "CRISIS_HARD_SL_THRESHOLD_PCT",
    "CRISIS_QTY_RATIO_DEFAULT",
    "CRISIS_RATIO_KEYS",
]

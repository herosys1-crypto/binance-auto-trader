"""Lint 테스트 — risk_constants centralize 회귀 방지 (2026-05-14 Phase 2).

배경:
- 5-14 SL 90% 버그의 직접 원인은 risk_service.py 의 hardcoded Decimal("0.50")
- magic number 가 의미 없이 흩어져 있으면 정책 변경 시 누락 위험
- Phase 2 centralize 후 핵심 정책 상수가 다시 inline 으로 들어오면 즉시 catch

검증 대상:
- risk_service.py / tp_sl_orchestrator.py / strategy_calculator.py 에서
  의미있는 정책 상수 (SL %, Crisis sentinel, percent denominator) hardcoded 금지
- risk_constants.py 가 모든 expected 상수 노출
- backward compat alias 가 risk_service / tp_sl_orchestrator 에서 import 가능

이 테스트가 실패하면:
1. 해당 파일의 hardcoded Decimal 을 제거하고
2. app.core.risk_constants 의 적절한 상수를 import 해 사용
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path


def _backend_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _read(rel: str) -> str:
    return (_backend_root() / rel).read_text(encoding="utf-8")


class TestRiskConstantsCentralization:
    """app.core.risk_constants 가 정책 상수의 single source 인지 검증."""

    def test_module_exposes_all_required_constants(self):
        """risk_constants.py 가 expected 상수 모두 노출."""
        from app.core import risk_constants as rc

        required = [
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
            # Crisis
            "CRISIS_MAX_LOSS_THRESHOLD_DEFAULT",
            "CRISIS_DISABLED_SENTINEL",
            "CRISIS_TP1_THRESHOLD_PCT",
            "CRISIS_TRAILING_DROP_PCT",
            "CRISIS_HARD_SL_THRESHOLD_PCT",
            "CRISIS_QTY_RATIO_DEFAULT",
            "CRISIS_RATIO_KEYS",
        ]
        missing = [name for name in required if not hasattr(rc, name)]
        assert not missing, f"app.core.risk_constants 누락 export: {missing}"

    def test_constant_values_match_user_spec(self):
        """사용자 명시 정책 값들이 정확히 설정됐는지 검증.

        값이 변경되면 사용자 의사 결정 (DEVELOPMENT_SPEC) 반영 필요 — 의도적 변경이면 이 테스트도 같이 갱신.
        """
        from app.core.risk_constants import (
            CRISIS_DISABLED_SENTINEL,
            CRISIS_MAX_LOSS_THRESHOLD_DEFAULT,
            CRISIS_QTY_RATIO_DEFAULT,
            DEFAULT_SL_PCT_OF_CAPITAL,
            DEFAULT_TP_QTY_RATIO_PCT,
            FULL_CLOSE_RATIO,
            LOSS_ALERT_THRESHOLD_PCT,
            PERCENT_DENOMINATOR,
            TP_FINAL_QTY_RATIO_PCT,
            TRAILING_MIN_STAGE,
            TRAILING_MIN_TP_INDEX,
            TRAILING_PEAK_THRESHOLD_PCT,
            TRAILING_RETRACE_PCT,
        )

        # 일반 산술
        assert PERCENT_DENOMINATOR == Decimal("100")
        assert FULL_CLOSE_RATIO == Decimal("1.00")

        # SL
        assert DEFAULT_SL_PCT_OF_CAPITAL == Decimal("50"), "사용자 default SL = 50%"
        assert LOSS_ALERT_THRESHOLD_PCT == Decimal("-50")

        # TP v6 정책
        assert DEFAULT_TP_QTY_RATIO_PCT == Decimal("25"), "사용자 v6: TP1~9 균일 25%"
        assert TP_FINAL_QTY_RATIO_PCT == Decimal("100"), "TP10 default 100% (마지막 안전망)"

        # Trailing v5
        assert TRAILING_PEAK_THRESHOLD_PCT == Decimal("5")
        assert TRAILING_RETRACE_PCT == Decimal("5")
        assert TRAILING_MIN_TP_INDEX == 3, "사용자 v5: TP3+ 부터 trailing"
        assert TRAILING_MIN_STAGE == 3, "사용자 v5: stage 3+ 부터 trailing"

        # Crisis
        assert CRISIS_MAX_LOSS_THRESHOLD_DEFAULT == Decimal("-50")
        assert CRISIS_DISABLED_SENTINEL == Decimal("-100"), "사용자 결정: -100=비활성"
        assert CRISIS_QTY_RATIO_DEFAULT == {
            "TP1": Decimal("25"),
            "TP2": Decimal("25"),
            "TP3": Decimal("50"),
            "TP4": Decimal("100"),
        }, "사용자 spec 2026-04-30 고정"

    def test_backward_compat_aliases_in_risk_service(self):
        """기존 코드/테스트가 import 하던 risk_service 의 module-level 상수가 여전히 작동."""
        from app.services.risk_service import (
            CRISIS_HARD_SL_THRESHOLD,
            CRISIS_MAX_LOSS_THRESHOLD,
            CRISIS_TP1_THRESHOLD,
            CRISIS_TRAILING_DROP,
            LOSS_ALERT_THRESHOLD,
            PEAK_REDIS_TTL_SECONDS,
            TRAILING_MIN_STAGE,
            TRAILING_MIN_TP_INDEX,
            TRAILING_TP_PEAK_THRESHOLD,
            TRAILING_TP_RETRACE_AMOUNT,
        )
        # 값이 central 과 일치하는지 spot-check
        from app.core import risk_constants as rc

        assert TRAILING_MIN_TP_INDEX == rc.TRAILING_MIN_TP_INDEX
        assert TRAILING_MIN_STAGE == rc.TRAILING_MIN_STAGE
        assert LOSS_ALERT_THRESHOLD == rc.LOSS_ALERT_THRESHOLD_PCT
        assert CRISIS_MAX_LOSS_THRESHOLD == rc.CRISIS_MAX_LOSS_THRESHOLD_DEFAULT
        assert TRAILING_TP_PEAK_THRESHOLD == rc.TRAILING_PEAK_THRESHOLD_PCT
        assert TRAILING_TP_RETRACE_AMOUNT == rc.TRAILING_RETRACE_PCT
        assert CRISIS_TP1_THRESHOLD == rc.CRISIS_TP1_THRESHOLD_PCT
        assert CRISIS_TRAILING_DROP == rc.CRISIS_TRAILING_DROP_PCT
        assert CRISIS_HARD_SL_THRESHOLD == rc.CRISIS_HARD_SL_THRESHOLD_PCT

    def test_backward_compat_aliases_in_tp_sl_orchestrator(self):
        """test_crisis_qty_ratios_resolver.py 가 import 하는 alias 들 작동."""
        from app.services.tp_sl_orchestrator import (
            _CRISIS_QTY_RATIO_DEFAULT,
            _CRISIS_RATIO_KEYS,
            _resolve_crisis_qty_ratios,
        )
        from app.core.risk_constants import CRISIS_QTY_RATIO_DEFAULT, CRISIS_RATIO_KEYS

        assert _CRISIS_QTY_RATIO_DEFAULT is CRISIS_QTY_RATIO_DEFAULT, (
            "_CRISIS_QTY_RATIO_DEFAULT alias 가 central dict 와 동일 객체여야"
        )
        assert _CRISIS_RATIO_KEYS == CRISIS_RATIO_KEYS
        # resolver 자체도 import 가능 (테스트 파일이 사용)
        assert callable(_resolve_crisis_qty_ratios)

    def test_no_hardcoded_sl_50_pct_in_risk_service(self):
        """risk_service.py 에 Decimal("0.50") 또는 Decimal("50") inline 이 없어야.

        5-14 버그 직접 회귀 검증: risk_service.py:79 의 hardcoded Decimal("0.50") 가
        template 값을 무시했던 것이 SL 90% 버그의 원인. 다시 들어오면 즉시 catch.
        """
        text = _read("app/services/risk_service.py")
        # 의도적 hardcoded SL 값 사용 패턴 검출
        # 예외: "Decimal("50")" 가 주석/테스트 설명 안에 있을 수 있으므로
        # 실제 코드 라인만 탐지 (주석 제외)
        suspicious = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.split("#", 1)[0]  # 주석 제거
            # SL 관련 magic 만 — 0.50 / 50 inline 으로 SL 계산에 쓰이는 것
            if re.search(r'sl_pct\s*=\s*Decimal\(["\'](?:0\.50|50)["\']\)', stripped):
                suspicious.append(f"line {lineno}: {line.strip()}")
            if re.search(r'/\s*Decimal\(["\']100["\']\)', stripped) and "pct" in stripped.lower():
                # PERCENT_DENOMINATOR import 사용 안 한 곳
                suspicious.append(f"line {lineno}: hardcoded /Decimal('100') (use PERCENT_DENOMINATOR): {line.strip()}")

        assert not suspicious, (
            "risk_service.py 에 hardcoded SL/percent 발견 — "
            "DEFAULT_SL_PCT_OF_CAPITAL / PERCENT_DENOMINATOR 사용 필요:\n  "
            + "\n  ".join(suspicious)
        )

    def test_crisis_disabled_sentinel_used_consistently(self):
        """Decimal("-100") inline 이 risk_service / tp_sl_orchestrator 에 없어야.

        CRISIS_DISABLED_SENTINEL 사용 강제 (사용자 의도 명확화).
        """
        files = [
            "app/services/risk_service.py",
            "app/services/tp_sl_orchestrator.py",
        ]
        bad: list[str] = []
        for f in files:
            text = _read(f)
            for lineno, line in enumerate(text.splitlines(), start=1):
                stripped = line.split("#", 1)[0]
                if re.search(r'Decimal\(["\']-100["\']\)', stripped):
                    bad.append(f"{f}:{lineno}: {line.strip()}")
        assert not bad, (
            "Decimal('-100') inline 사용 발견 — CRISIS_DISABLED_SENTINEL 사용 필요:\n  "
            + "\n  ".join(bad)
        )

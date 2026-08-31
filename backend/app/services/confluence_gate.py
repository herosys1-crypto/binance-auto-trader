"""🚫 합의(confluence) 진입 게이트 — 두 번 측정된 신호를 드디어 쓴다 (Fix 247).

## 두 번의 실측이 같은 것을 말한다

**① v139 백테스트** (`strategy_confluence.py:105-131` 주석에 이미 적혀 있다):

    AVOID      227건  →  총 **-19,207 USDT** = 전체 손실 -22,068 의 **87%**
    CONFLICT    67건  →  4h 적중률 **16.4%** / 평균 **-1.86%**  ← 금지보다도 나쁨
    AGREE       40건  →  57.5% / +2.00%

**② 2026-08-31 실측** (자동매매 4일, 진입 스냅샷 112건, 승 23 / 패 89):

    지표                        승 중앙값   패 중앙값   효과크기
    confluence.blocked            0.000      1.000      -2.06
    sar_ichimoku.cloud_15m_ok     1.000      0.000      +2.09
    ema_vcp.trend_ok              1.000      0.000      +2.02
    sar_ichimoku.cloud_4h_ok      1.000      0.000      +2.01
    confluence.score             50.000      0.000      +1.49

효과크기 2.0 = **거의 완벽한 분리**. 64개 필드 중 상위 전부가 이 한 신호다
(추세 정렬을 6가지 방식으로 본 것이라 독립 발견 6개가 아니라 **하나**다).

## 그런데 이 판정은 진입에 쓰이지 않았다

`strategy_confluence.evaluate` 호출자는 단 둘 —
`api/v1/analysis.py`(화면 표시) 와 `learning_sync_worker.py`(학습 저장).
**진입 경로에는 한 번도 불리지 않는다.** 즉 시스템은 「하지 마라」를 계산해 놓고
그대로 들어갔다.

## 왜 진입 직전에만 부르나

EMA/SAR 판정에는 4h/1h/15m 캔들 3회 조회가 필요하다. 후보 40~100개마다 돌리면
IP ban(418) 위험이 크다 — 이 프로젝트가 실제로 겪은 사고다(Fix 117/122).
→ 다른 게이트를 **전부 통과한 뒤 생성 직전**에만 부른다. 사이클당 몇 건뿐이다.

⚠️ 기본 **OFF**. 이 게이트는 진입을 **막는** 쪽이라 안전하지만, 얼마나 막는지는
   사장님이 먼저 보셔야 한다. OFF 여도 「막았을 것」 로그는 남긴다.
   켜기: SystemSetting `confluence_gate_enabled` = 1
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["check_confluence_gate", "confluence_gate_enabled", "SETTING_KEY"]

SETTING_KEY = "confluence_gate_enabled"


def confluence_gate_enabled(db) -> bool:
    """기본 OFF — 얼마나 막는지 확인한 뒤 사장님이 켠다."""
    try:
        from app.services.system_settings_service import SystemSettingsService

        return SystemSettingsService(db).get_bool(SETTING_KEY, False)
    except Exception:
        return False


def check_confluence_gate(bc, symbol: str, side: str) -> tuple[bool, str, dict[str, Any]]:
    """진입해도 되는가.

    Returns:
        (allow, reason, detail)
        allow=False 면 두 전략이 「금지」 또는 「충돌」로 판정한 자리다.

    ⚠️ **fail-open**: 판정을 못 하면 통과시킨다.
       조회 실패로 자동매매가 통째로 멈추는 것이 더 위험하다.
       (막는 게이트이므로 fail-open 이 안전한 방향이다 — obv_gate 와 같은 원칙.)
    """
    detail: dict[str, Any] = {}
    if bc is None:
        return True, "client_none_pass", detail
    try:
        from app.services import strategy_confluence
        from app.services.ema_vcp_analyzer import EMAVCPAnalyzer
        from app.services.sar_ichimoku_analyzer import SARIchimokuAnalyzer

        kl: dict[str, Any] = {}
        for iv, lim in (("4h", 120), ("1h", 120), ("15m", 200)):
            try:
                r = bc.get_klines(symbol=symbol, interval=iv, limit=lim)
                kl[iv] = r if isinstance(r, list) else None
            except Exception:
                kl[iv] = None
        if not kl.get("4h") or not kl.get("15m"):
            return True, "klines_missing_pass", detail

        ema = EMAVCPAnalyzer(bc).analyze(
            symbol, side, klines_4h=kl["4h"], klines_1h=kl["1h"], klines_15m=kl["15m"],
        )
        sar = SARIchimokuAnalyzer(bc).analyze(
            symbol, side, klines_4h=kl["4h"], klines_1h=kl["1h"], klines_15m=kl["15m"],
        )
        conf = strategy_confluence.evaluate(ema, sar, side)
        if not conf:
            return True, "no_verdict_pass", detail

        blocked = bool(conf.get("blocked"))
        level = str(conf.get("level") or "?")
        score = conf.get("score")
        detail = {"blocked": blocked, "level": level, "score": score}
        if blocked:
            return (
                False,
                f"합의 판정 {level} (score={score}) "
                f"[Fix247 실측: 이 구간이 손실의 87%, CONFLICT 적중률 16.4%]",
                detail,
            )
        return True, f"합의 {level} (score={score})", detail
    except Exception as e:  # noqa: BLE001 — 게이트 실패로 매매를 멈추지 않는다
        logger.warning("[Fix247] %s %s 합의 게이트 판정 실패 = 통과: %s", symbol, side, e)
        return True, f"error_pass: {e}", detail

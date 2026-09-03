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

__all__ = [
    "check_confluence_gate", "confluence_gate_enabled", "SETTING_KEY",
    "SETTING_REVERSAL_EXEMPT", "reversal_exempt_enabled",
]

SETTING_KEY = "confluence_gate_enabled"
SETTING_REVERSAL_EXEMPT = "confluence_reversal_exempt"   # Fix 331 — 기본 ON


def reversal_exempt_enabled(db) -> bool:
    """반전 전략에서 합의 판정을 참고로만 쓸 것인가 (기본 ON).

    사장님 정정: "15분이 기준이고 4시간을 참고" — 추세추종 지표 두 개의 합의로
    반전 진입을 막으면 사장님 사상 ①(급등 정점 SHORT)이 실행되지 않는다.
    """
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, SETTING_REVERSAL_EXEMPT)
        if row is None or row.value is None or not str(row.value).strip():
            return True
        return str(row.value).strip().lower() in ("1", "true", "on", "yes")
    except Exception as e:
        logger.warning("[Fix331] %s 조회 실패 → 기본 ON: %s", SETTING_REVERSAL_EXEMPT, e)
        return True



def confluence_gate_enabled(db) -> bool:
    """기본 OFF — 얼마나 막는지 확인한 뒤 사장님이 켠다."""
    try:
        from app.services.system_settings_service import SystemSettingsService

        return SystemSettingsService(db).get_bool(SETTING_KEY, False)
    except Exception:
        return False


def check_confluence_gate(bc, symbol: str, side: str, *,
                         db=None, strategy_kind: object = None,
                         ) -> tuple[bool, str, dict[str, Any]]:
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

        # ═══════════════════════════════════════════════════════════════
        # 🚨 Fix 331 (2026-09-03) — 반전 전략에는 「참고」로만 쓴다
        #
        # 합의 판정은 **EMA/VCP(돌파형)** 와 **SAR/구름대(추세추종)** 두 개를 합친다.
        # 🚨 **둘 다 추세추종 계열**이다. 정점에서는 가격이 아직 상승 추세이므로
        #    SHORT 에 대해 둘 다 D등급이 나오는 것이 **당연**하다 → AVOID.
        #    즉 정점 반전 전략은 **구조적으로 이 게이트를 통과할 수 없다.**
        #    (Fix 270 4H 게이트와 정확히 같은 충돌이다 — Fix 330 참조)
        #
        # 실측 — 게이트 도입(2026-08-31) 전후:
        #     v219 정점SHORT  이전 280건 승률 29.6% 건당 **+1.65**
        #                     이후  35건 승률  2.9% 건당   +0.62
        #     v219 저점LONG   이전 126건 건당 -4.99
        #                     이후  30건 건당 **-14.01**
        #   → 켠 뒤 **두 전략 모두 나빠졌다.** 24시간에 SHORT 801건을 막고 있었다.
        #
        # ⚠️ 표본이 작고(35/30건) 그 사이 다른 Fix 가 많이 들어가 교란이 있다.
        #    그래서 「게이트가 나쁘다」고 단정하지 않고 **반전 전략에만** 내린다.
        #    AVOID 227건 = 손실의 87% 라는 원 근거는 **전략 제안(추천 761건)**
        #    표본에서 나온 것이고, v219 정점 진입과는 다른 모집단이다.
        #
        # 🚨 되돌리기: `confluence_reversal_exempt = 0`
        # ═══════════════════════════════════════════════════════════════
        _exempt = False
        if blocked and db is not None and strategy_kind is not None:
            try:
                from app.services.trend_4h_gate import is_reversal_strategy
                _exempt = is_reversal_strategy(strategy_kind) and reversal_exempt_enabled(db)
            except Exception as _ee:      # 판정 실패가 매매를 막으면 안 된다
                logger.debug("[Fix331] 반전 판정 실패 (무시): %s", _ee)
                _exempt = False
        detail["reversal_exempt"] = _exempt

        if blocked and not _exempt:
            return (
                False,
                f"합의 판정 {level} (score={score}) "
                f"[Fix247 실측: 이 구간이 손실의 87%, CONFLICT 적중률 16.4%]",
                detail,
            )
        if blocked and _exempt:
            # 참고만 — 「합의는 반대였다」를 기록으로 남긴다 (나중에 재려고)
            detail["ref_note"] = f"합의 {level} (score={score})"
            return (
                True,
                f"합의 참고: {level} (score={score}) — 반전 전략이라 막지 않음 (Fix 331)",
                detail,
            )
        return True, f"합의 {level} (score={score})", detail
    except Exception as e:  # noqa: BLE001 — 게이트 실패로 매매를 멈추지 않는다
        logger.warning("[Fix247] %s %s 합의 게이트 판정 실패 = 통과: %s", symbol, side, e)
        return True, f"error_pass: {e}", detail

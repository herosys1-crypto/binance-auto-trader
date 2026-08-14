"""🚀 Live Pump/Dump API — 급등락 실시간 진입 (v133d → **v147 실측 로직 전환**)

사장님 요구 (2026-08-13): "급등 급락 중 진입 별도 메뉴!"
사장님 결정 (2026-08-14): "급등락 실시간 진입은 **15분봉 20% 전후** 급등락으로 해줘"
사장님 결정 (2026-08-14 v147d): 상한 확대 — "**27.5**로 해줘"

🚨 v147 이전(v133c)의 문제 — 실측과 정면으로 어긋났습니다:
    · 5분 ±1.5% / 1시간 ±3% 만 보고 **무조건 추격** (급등=LONG, 급락=SHORT)
    · 실제로 이런 화면이 나왔습니다:
        AKEUSDT → 1시간 **-7.01%** 인데 5분 +3.45% 라고 **LONG 추천**
        = 하락 추세 속 5분 반등을 추격 = 칼날 잡기
    · 실측 근거 (scripts/study_pump_dump_20pct.py, 181심볼 5m 7,200봉):
        - 급락은 양방향 모두 기대값 없음 (역추세 6셀 vs 추격 5셀 = 동전던지기)
        - 작은 임계(1.5~3%)는 노이즈 — 수수료(왕복 0.08%)도 못 넘김

✅ v147 = PumpDumpLiveAnalyzer 단일 경로로 통일:
    · **15m 17.5~27.5% 밴드** 에서만 신호 (5m 신호는 OFF)
      단, 하위 밴드별로 TP/SL 이 다릅니다 (v147d 재측정 — 합치면 기대값이 나빠져서):
        17.5~22.5% → +5%/-5% 짧게 / 22.5~27.5% → +15%/-7% 길게
    · **급등 → 추격 LONG** (실측 양의 기대값 54셀 중 37셀이 여기)
    · **급락 → 진입 비권장** (side=None, 화면에 이유 표시)
    · TP/SL·기대값·표본 수를 신호와 함께 반환 = 사장님이 근거를 보고 판단

spec: docs/PUMP_DUMP_LIVE_STRATEGY_SPEC.md
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.core.crypto import decrypt_text
from app.integrations.binance.client import BinanceClient
from app.models.exchange_account import ExchangeAccount
from app.services.pump_dump_live_analyzer import PumpDumpLiveAnalyzer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/live-pump-dump", tags=["live-pump-dump"])


@router.get("/scan")
def scan_live_pump_dump(
    max_symbols: int = Query(default=60, ge=10, le=150),
    include_dump: bool = Query(
        default=True,
        description="급락도 목록에 표시할지 (표시하되 진입 비권장으로 표기)",
    ),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> dict[str, Any]:
    """🚀 15분봉 17.5~27.5% 급등락 실시간 스캔 (v147d 실측 로직).

    반환 alert 는 **근거를 함께** 실어 보냅니다:
      side / tp_pct / sl_pct / expected_value_pct / tp_first_rate / sample_n
    급락은 side=None + 「진입 비권장」 사유가 담깁니다.
    """
    account = db.execute(
        select(ExchangeAccount).where(ExchangeAccount.is_testnet.is_(False))
    ).scalar_one_or_none()
    if not account:
        return {"alerts": [], "error": "no mainnet account"}

    bc = BinanceClient(
        api_key=decrypt_text(account.api_key_enc),
        api_secret=decrypt_text(account.api_secret_enc),
        is_testnet=False,
    )

    try:
        tickers = bc.get_24hr_ticker()
        if not isinstance(tickers, list):
            return {"alerts": [], "error": "invalid ticker response"}
    except Exception as e:
        logger.warning("[live_pump_dump] ticker 실패: %s", e)
        return {"alerts": [], "error": str(e)}

    # 1차 후보 = 24h 변동이 큰 순 (15m 20% 급등은 대개 24h 도 크게 움직임)
    usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
    try:
        usdt.sort(key=lambda x: abs(float(x.get("priceChangePercent", 0) or 0)), reverse=True)
    except Exception:
        pass
    candidates = usdt[:max_symbols]

    analyzer = PumpDumpLiveAnalyzer(bc)
    alerts: list[dict[str, Any]] = []
    band_lo, band_hi = PumpDumpLiveAnalyzer.BAND_15M

    for t in candidates:
        symbol = str(t.get("symbol", ""))
        if not symbol.endswith("USDT"):
            continue
        try:
            k15 = bc.get_klines(
                symbol=symbol, interval="15m",
                limit=PumpDumpLiveAnalyzer.KLINE_LIMIT,
            )
            if not isinstance(k15, list):
                continue
            # 5m 은 화면 참고용으로만 사용 (신호는 15m 전용 = v141b)
            res = analyzer.analyze(symbol, klines_5m=[], klines_15m=k15)
        except Exception as e:
            logger.debug("[live_pump_dump] %s 분석 실패: %s", symbol, e)
            continue

        ev = res.get("event") or {}
        if not ev:
            # 🌟 v147i 사장님 지시: "결정은 내가 해"
            #   밴드 밖이라고 **목록에서 빼지 않습니다.** 10%+ 움직임이면 보여드리고,
            #   실측 근거가 없다는 사실만 함께 적어 사장님이 판단하시게 합니다.
            oob = PumpDumpLiveAnalyzer.out_of_band_15m(res.get("m15") or {})
            if oob is None:
                continue                  # 10% 미만 = 표시할 움직임 자체가 없음
            if oob < 0 and not include_dump:
                continue
            alerts.append({
                "symbol": symbol,
                "side": None,             # 추천 방향 없음 = 사장님이 고르십니다
                "type": "out_of_band_15m",
                "grade": "D",
                "window": (res.get("m15") or {}).get("window_of_biggest"),
                "change_pct": round(oob, 2),
                "confidence": 0.0,
                "verdict": f"15m {oob:+.1f}% — 실측 밴드({band_lo:g}~{band_hi:g}%) 밖",
                "reason": (
                    f"실측 플레이북이 다루는 구간이 아닙니다 "
                    f"(밴드 {band_lo:g}~{band_hi:g}%). 기대값·표본 근거가 없으니 "
                    f"진입하실 경우 사장님 판단으로만 하세요."
                ),
                "signals": res.get("signals") or [],
                "tp_pct": None, "sl_pct": None,
                "expected_value_pct": None, "expected_value_after_fee_pct": None,
                "tp_first_rate": None, "sample_n": None,
                "price": float(t.get("lastPrice", 0) or 0),
                "volume_24h": float(t.get("quoteVolume", 0) or 0),
                "change_24h": float(t.get("priceChangePercent", 0) or 0),
            })
            continue

        is_dump = ev.get("kind") == "DUMP"
        if is_dump and not include_dump:
            continue

        lv = res.get("levels") or {}
        alerts.append({
            "symbol": symbol,
            "side": res.get("side"),                    # 급락이면 None!
            "type": "pump_15m" if not is_dump else "dump_15m_avoid",
            "grade": res.get("grade"),
            "window": ev.get("window"),
            "change_pct": ev.get("change_pct"),
            "confidence": round(min(0.55 + (res.get("score") or 0) / 200, 0.9), 3),
            "verdict": res.get("verdict"),
            "reason": " | ".join((res.get("signals") or [])[:2]),
            "signals": res.get("signals") or [],
            "tp_pct": lv.get("tp_pct"),
            "sl_pct": lv.get("sl_pct"),
            "expected_value_pct": lv.get("expected_value_pct"),
            "expected_value_after_fee_pct": lv.get("expected_value_after_fee_pct"),
            "tp_first_rate": lv.get("tp_first_rate"),
            "sample_n": lv.get("sample_n"),
            "price": float(t.get("lastPrice", 0) or 0),
            "volume_24h": float(t.get("quoteVolume", 0) or 0),
            "change_24h": float(t.get("priceChangePercent", 0) or 0),
        })

    # 진입 가능(급등) 먼저, 그 다음 신뢰도 순
    alerts.sort(key=lambda a: (a["side"] is None, -(a.get("confidence") or 0)))

    return {
        "alerts": alerts,
        "total": len(alerts),
        "band": {"low": band_lo, "high": band_hi},
        "scanned": len(candidates),
        "policy": (
            f"v147i — 실측 밴드({band_lo:g}~{band_hi:g}%) 급등은 추격 LONG 을 「추천」하고, "
            "급락·밴드 밖은 근거가 없다고 「표시」만 합니다. "
            "**막지는 않습니다 — 최종 결정은 사장님** (사장님 지시 2026-08-14)."
        ),
    }

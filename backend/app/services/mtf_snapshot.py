"""🎯 Fix 132 (2026-08-26): 15m / 1h / 4h 통합 진입 스냅샷 (학습 원재료)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 verbatim (2026-08-26):
  "성공과 실패의 15분 1시간 4시간 차트와 보조지표들의 정확한 수치들을
   정확하게 설정해서 신뢰도를 만들어 활용하면 매우 훌륭한 시스템이 될꺼야"
  "실패만 봐도 학습을 잘했으면 좋은 포지션 진입이 가능한데"
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 왜 필요한가 (실측 근거)

7일 자동진입 실적:
  LONG  성공 2 / 실패 96   (승률 2.0%)
  SHORT 성공 9 / 실패 192  (승률 4.5%)

그런데 진입 시점에 기록되는 entry_snapshot 은 워커마다 제각각이고,
1h / 4h 지표는 「한 건도」 기록되지 않고 있었다:

  sajangnim_top_short : bb_*_15m, cci_15m, macd_15m_hist, change_24h   ← 15m 만
  bb4h_auto_entry     : bb_lower/mid/upper, cci, divergence            ← timeframe 표기조차 없음
  공통 누락            : RSI, OBV, 볼륨, 1h 전체, 4h 전체

= 성공/실패로 신뢰도를 학습하려 해도 「학습할 데이터 자체가 없다」.
  이 모듈이 그 원재료를 만든다 (헌법 6 = 모든 진입 경로가 같은 함수를 쓴다).

## 설계 원칙

- 절대 예외를 올리지 않는다. 실패해도 부분 dict 를 돌려준다 (진입을 막으면 안 됨).
- ChartAnalyzer.analyze_timeframe 을 쓰므로 Redis kline 캐시를 그대로 탄다
  (15m 60s / 4h 300s + Fix 122 클라이언트 캐시) = 추가 API 부하 최소.
- 스키마 버전(schema)을 박아 나중에 필드가 늘어도 학습 쿼리가 구분할 수 있게 한다.
- 파생값(bb_pos, obv_slope_pct, vol_ratio)까지 미리 계산해 저장한다.
  나중에 원본 봉 없이도 학습이 가능해야 하기 때문.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "mtf_v1"
TIMEFRAMES = ("15m", "1h", "4h")
KLINE_LIMIT = {"15m": 80, "1h": 80, "4h": 60}

OBV_SLOPE_LOOKBACK = 20     # OBV 기울기 산출 봉수
VOL_LOOKBACK = 20           # 볼륨 평균 대비 배수 산출 봉수


def _slope_pct(series: list[float], lookback: int) -> float | None:
    """선형회귀 기울기를 「창 내 진폭 대비 %」로 환산.

    절대값은 심볼마다 스케일이 달라 학습에 못 쓴다 → 정규화한 값을 쓴다.
    """
    try:
        if not series or len(series) < 3:
            return None
        w = [float(x) for x in series[-lookback:]]
        n = len(w)
        if n < 3:
            return None
        mean_x = (n - 1) / 2.0
        mean_y = sum(w) / n
        num = sum((i - mean_x) * (w[i] - mean_y) for i in range(n))
        den = sum((i - mean_x) ** 2 for i in range(n))
        if den == 0:
            return None
        slope = num / den
        base = max(abs(max(w)), abs(min(w)), 1.0)
        return round(slope / base * 100.0, 6)
    except Exception:
        return None


def _bb_pos(close: float | None, lo: float | None, up: float | None) -> float | None:
    """BB 내 위치 0~1 (0=하단, 0.5=중단, 1=상단). 밴드 밖이면 0 미만/1 초과.

    사장님 사상의 「BB 하단 지지 / 중단 지지 / 상단 돌파」를 하나의 수치로 표현한다.
    """
    try:
        if close is None or lo is None or up is None:
            return None
        width = float(up) - float(lo)
        if width <= 0:
            return None
        return round((float(close) - float(lo)) / width, 4)
    except Exception:
        return None


def _vol_ratio(volumes: list[float]) -> float | None:
    """마지막 봉 볼륨 / 직전 N봉 평균."""
    try:
        if not volumes or len(volumes) < 5:
            return None
        prev = [float(v) for v in volumes[-(VOL_LOOKBACK + 1):-1]]
        if not prev:
            return None
        avg = sum(prev) / len(prev)
        if avg <= 0:
            return None
        return round(float(volumes[-1]) / avg, 4)
    except Exception:
        return None


def _tf_block(a: dict) -> dict[str, Any]:
    """analyze_timeframe 결과 → 학습용 평탄 dict."""
    closes = a.get("closes") or []
    hist = a.get("macd_hist") or []
    close = float(closes[-1]) if closes else None
    up, mid, lo = a.get("bb_up_last"), a.get("bb_mid_last"), a.get("bb_lo_last")
    return {
        "close": close,
        "rsi": a.get("rsi_now"),
        "rsi_prev": a.get("rsi_prev"),
        "macd_hist": float(hist[-1]) if hist else None,
        "macd_hist_prev": float(hist[-2]) if len(hist) >= 2 else None,
        "macd_hist_prev2": float(hist[-3]) if len(hist) >= 3 else None,
        "cci": a.get("cci_now"),
        "cci_prev": a.get("cci_prev"),
        "bb_up": float(up) if up is not None else None,
        "bb_mid": float(mid) if mid is not None else None,
        "bb_lo": float(lo) if lo is not None else None,
        "bb_pos": _bb_pos(close, lo, up),
        "obv_slope_pct": _slope_pct(a.get("obv") or [], OBV_SLOPE_LOOKBACK),
        "vol_ratio": _vol_ratio(a.get("volumes") or []),
        "bars": a.get("kl_count"),
    }


def capture(bc, symbol: str, side: str, *, extra: dict | None = None) -> dict[str, Any]:
    """🎯 15m / 1h / 4h 전 지표 스냅샷.

    Args:
        bc: BinanceClient
        symbol / side: 진입 대상
        extra: 워커별 부가 정보 (source, confidence, 기존 키 등) — 그대로 병합

    Returns:
        학습에 바로 쓸 수 있는 평탄한 dict. 실패해도 예외 없이 부분 결과 반환.
    """
    snap: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "side": side,
        "symbol": symbol,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "tf": {},
    }
    try:
        from app.services.chart_analyzer import ChartAnalyzer
        for tf in TIMEFRAMES:
            try:
                a = ChartAnalyzer.analyze_timeframe(bc, symbol, tf, limit=KLINE_LIMIT[tf])
                snap["tf"][tf] = _tf_block(a) if a else {"error": "empty"}
            except Exception as e:      # 한 timeframe 실패가 전체를 막지 않게
                snap["tf"][tf] = {"error": str(e)[:120]}
    except Exception as e:
        snap["error"] = str(e)[:200]

    # 24h 변동 (전 심볼 티커는 Fix 117 캐시를 타므로 사실상 무료)
    try:
        rows = bc.get_24hr_ticker()
        if isinstance(rows, list):
            for t in rows:
                if t.get("symbol") == symbol:
                    snap["change_24h"] = float(t.get("priceChangePercent") or 0)
                    snap["quote_volume_24h"] = float(t.get("quoteVolume") or 0)
                    break
    except Exception:
        pass

    # 15m 반복 상승/하락 횟수 (사장님 "2-3번 반복" 판정의 원수치)
    try:
        from app.services.peak_confirmation import count_swing_peaks, count_swing_valleys
        c15 = (snap.get("tf", {}).get("15m") or {})
        if not c15.get("error"):
            from app.services.chart_analyzer import ChartAnalyzer as _CA
            a15 = _CA.analyze_timeframe(bc, symbol, "15m", limit=KLINE_LIMIT["15m"])
            closes = (a15 or {}).get("closes") or []
            snap["swings_15m_peaks"] = count_swing_peaks(closes)
            snap["swings_15m_valleys"] = count_swing_valleys(closes)
    except Exception:
        pass

    if extra:
        try:
            snap.update({k: v for k, v in extra.items() if k not in ("tf",)})
        except Exception:
            pass
    return snap


_default_client = None


def _get_default_client():
    """mainnet 클라이언트 lazy 싱글턴.

    워커마다 bc 를 손에 들고 있지 않은 지점(예: auto_bb_breakdown 의 진입 루프)에서도
    스냅샷을 남길 수 있어야 한다. 없으면 그 경로만 학습 데이터가 비게 되고,
    그러면 「어떤 조건이 실패했는지」를 영영 알 수 없다.
    """
    global _default_client
    if _default_client is not None:
        return _default_client
    try:
        from app.core.database import SessionLocal
        from app.core.crypto import decrypt_text
        from app.integrations.binance.client import BinanceClient
        from app.models.exchange_account import ExchangeAccount
        from sqlalchemy import select
        db = SessionLocal()
        try:
            acc = db.execute(
                select(ExchangeAccount)
                .where(ExchangeAccount.is_testnet.is_(False))
                .where(ExchangeAccount.is_active.is_(True))
            ).scalars().first()
            if acc is None:
                return None
            _default_client = BinanceClient(
                api_key=decrypt_text(acc.api_key_enc),
                api_secret=decrypt_text(acc.api_secret_enc),
                is_testnet=False,
            )
            return _default_client
        finally:
            db.close()
    except Exception as e:
        logger.warning("[Fix132/mtf] 기본 클라이언트 확보 실패: %s", e)
        return None


def merge_into(existing: dict | None, bc, symbol: str, side: str) -> dict[str, Any]:
    """기존 워커의 entry_snapshot 에 MTF 블록을 「덧붙인다」.

    기존 키는 절대 덮어쓰지 않는다 = 하위 호환 100%
    (기존 학습/화면 코드가 그대로 동작해야 하므로).
    """
    base = dict(existing or {})
    try:
        if bc is None:
            bc = _get_default_client()
        if bc is None:
            base.setdefault("mtf_error", "no_client")
            return base
        mtf = capture(bc, symbol, side)
        for k, v in mtf.items():
            if k not in base:
                base[k] = v
    except Exception as e:
        logger.warning("[Fix132/mtf] %s %s 스냅샷 실패 (진입은 계속): %s", symbol, side, e)
        base.setdefault("mtf_error", str(e)[:120])
    return base

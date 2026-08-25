"""🌟 Fix 74 (2026-08-25): MACD 15m 변곡점 + 4H 방향 필터 = LONG/SHORT 대칭 감지!

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
사장님 verbatim (헌법 77!):
  "macd 15분 하락 후 반등 시작점과 반등후 하락 위치를 참고해줘
   15분과 4시간의 움직임을"

= 15m MACD 히스토그램 「변곡점」을 두 방향으로 감지:
    (a) 반등 시작점 = hist[-3] > hist[-2] AND hist[-2] < hist[-1] AND hist[-2] < 0
        → LONG 후보 (저점 반전 상승!)
    (b) 반등후 하락 = hist[-3] < hist[-2] AND hist[-2] > hist[-1] AND hist[-2] > 0
        → SHORT 후보 (고점 반전 하락!)
  + 4시간봉 MACD 방향 일치 = 사장님 verbatim "15분과 4시간의 움직임을"
  + 볼륨 30%+ 증가 = 실 변곡점 확인 (false-positive 억제!)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

다운스트림:
  - SHORT 알람 → "pump_top:alert:{symbol}:SHORT" → auto_short_at_top_worker 처리!
  - LONG 알람  → "sajangnim:bottom_long:{symbol}"  → auto_long_at_bottom_worker 처리!

Fix 65 (OBV gate) + Fix 66 (regime gate) 통합 = 사장님 사상 필터 완전 준수!
Fix 72 대칭 = entry_snapshot 학습 데이터 완전 저장!
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.exchange_account import ExchangeAccount

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# spec header (Fix 74!)
# ═══════════════════════════════════════════════════════════════════
SPEC_VERSION = "macd_reversal_15m_v1_fix74_2026-08-25"
INTERVAL_SEC = 180        # 3분 (15m 봉 완성 감지!)
MAX_SYMBOLS = 100         # 상위 100 심볼 스캔!
ALERT_TTL_SEC = 1800      # 30분
MIN_CONFIDENCE = 0.85

# 사장님 사상 v3: MACD 15m 변곡점 + 4H 필터!
MACD_HIST_MIN_MAGNITUDE = 0.00001  # 미미한 변곡 skip!
VOLUME_INCREASE_RATIO = 1.3        # 볼륨 30%+ 증가 확인!

# 헌법 64 = 급등/급락 극단 (±15%) = 반대매매 위험 → skip!
EXTREME_CHG_ABS = 15.0

# 4H 필터: 방향 판정용
MACD_4H_FLAT_ABS = 0.00001         # 방향 판정 zero-band (평평 = "flat")

# 15m 볼륨 비교: 최근 3봉 vs 이전 6봉 평균
VOL_RECENT_BARS = 3
VOL_PRIOR_BARS = 6


# ═══════════════════════════════════════════════════════════════════
# 헬퍼: MACD line + signal 재계산 (analyze_timeframe이 hist만 반환!)
# ═══════════════════════════════════════════════════════════════════
def _compute_macd_triplet(closes: list[float]) -> tuple[list[float], list[float], list[float]]:
    """closes → (macd_line, signal_line, hist) 튜플 반환.

    ChartAnalyzer.analyze_timeframe은 hist만 반환하므로 line/signal도 필요할 때 직접 계산.

    Returns:
        (macd_line, signal_line, hist) — 계산 실패 시 ([], [], [])
    """
    try:
        from app.services.bb_4h_band_analyzer import BB4HBandAnalyzer
        if len(closes) < 35:
            return [], [], []
        ema12 = BB4HBandAnalyzer._calc_ema(closes, 12)
        ema26 = BB4HBandAnalyzer._calc_ema(closes, 26)
        offset = 26 - 12
        macd_line = [a - b for a, b in zip(ema12[offset:], ema26)]
        if len(macd_line) < 10:
            return [], [], []
        signal_line = BB4HBandAnalyzer._calc_ema(macd_line, 9)
        if not signal_line:
            return [], [], []
        # macd_line trim = signal_line 길이만큼!
        macd_trim = macd_line[-len(signal_line):]
        hist = [m - s for m, s in zip(macd_trim, signal_line)]
        return macd_trim, signal_line, hist
    except Exception as e:
        logger.warning("[Fix74/_compute_macd_triplet] 실패: %s", e)
        return [], [], []


# ═══════════════════════════════════════════════════════════════════
# 함수 (a): 15m MACD 변곡점 감지 (사장님 verbatim = 두 방향!)
# ═══════════════════════════════════════════════════════════════════
def _check_15m_macd_reversal(bc, symbol: str) -> tuple[str | None, dict | None]:
    """15m MACD 히스토그램 변곡점 감지 (사장님 verbatim = 반등 시작점 or 반등후 하락!).

    감지 조건 (chart_analyzer.compute_reversal_score 라인 331-332/347-348 동일 로직):
      - LONG 후보 (반등 시작점) = hist[-3] > hist[-2] AND hist[-2] < hist[-1] AND hist[-2] < 0
      - SHORT 후보 (반등후 하락) = hist[-3] < hist[-2] AND hist[-2] > hist[-1] AND hist[-2] > 0

    Args:
        bc: BinanceClient
        symbol: 심볼

    Returns:
        (reversal_type, snapshot) or (None, None):
          reversal_type: "long" | "short"
          snapshot: dict = 15m 지표 (MACD/RSI/CCI/BB/OBV/close)
    """
    try:
        from app.services.chart_analyzer import ChartAnalyzer

        a15 = ChartAnalyzer.analyze_timeframe(bc, symbol, "15m", limit=60)
        if not a15:
            return None, None

        hist = a15.get("macd_hist") or []
        if len(hist) < 3:
            return None, None

        h_prev2 = float(hist[-3])
        h_prev = float(hist[-2])
        h_now = float(hist[-1])

        # 미미한 변곡 skip (양쪽 변화량이 모두 미미하면 노이즈!)
        delta_prev = abs(h_prev - h_prev2)
        delta_now = abs(h_now - h_prev)
        if delta_prev < MACD_HIST_MIN_MAGNITUDE and delta_now < MACD_HIST_MIN_MAGNITUDE:
            return None, None

        reversal_type: str | None = None

        # LONG 후보 = 저점 변곡 (반등 시작점!)
        # 사장님 verbatim: "macd 15분 하락 후 반등 시작점"
        if h_prev2 > h_prev and h_prev < h_now and h_prev < 0:
            reversal_type = "long"

        # SHORT 후보 = 고점 변곡 (반등후 하락!)
        # 사장님 verbatim: "반등후 하락 위치"
        elif h_prev2 < h_prev and h_prev > h_now and h_prev > 0:
            reversal_type = "short"

        if reversal_type is None:
            return None, None

        # MACD line/signal 재계산 (analyze_timeframe은 hist만!)
        closes = a15.get("closes") or []
        macd_line, sig_line, _hist_local = _compute_macd_triplet(closes)
        macd_line_now = macd_line[-1] if macd_line else None
        macd_signal_now = sig_line[-1] if sig_line else None

        # OBV slope (최근 5봉 vs 이전 5봉 = 방향 계산!)
        obv = a15.get("obv") or []
        obv_slope: float | None = None
        if len(obv) >= 10:
            try:
                obv_slope = float(obv[-1]) - float(obv[-6])
            except Exception:
                obv_slope = None

        snapshot = {
            "close_15m": closes[-1] if closes else None,
            "rsi_15m": a15.get("rsi_now"),
            "rsi_prev_15m": a15.get("rsi_prev"),
            "cci_15m": a15.get("cci_now"),
            "cci_prev_15m": a15.get("cci_prev"),
            "obv_15m": float(obv[-1]) if obv else None,
            "obv_slope_15m": obv_slope,
            "bb_up_15m": a15.get("bb_up_last"),
            "bb_lo_15m": a15.get("bb_lo_last"),
            "macd_15m_hist_now": h_now,
            "macd_15m_hist_prev": h_prev,
            "macd_15m_hist_prev2": h_prev2,
            "macd_15m_line_now": macd_line_now,
            "macd_15m_signal_now": macd_signal_now,
            "kl_count_15m": a15.get("kl_count"),
        }
        return reversal_type, snapshot
    except Exception as e:
        logger.warning("[Fix74/_check_15m_macd_reversal] %s: %s", symbol, e)
        return None, None


# ═══════════════════════════════════════════════════════════════════
# 함수 (b): 4H 방향 필터 (사장님 verbatim = "4시간의 움직임"!)
# ═══════════════════════════════════════════════════════════════════
def _check_4h_direction_filter(bc, symbol: str, side: str) -> tuple[bool, str, dict]:
    """4H MACD 방향 확인 = 15m 변곡과 일치 여부!

    사장님 verbatim: "15분과 4시간의 움직임을"
      → 두 시간대 방향 일치 시만 진입!

    LONG 조건: 4H MACD Hist 상승 중 (hist[-1] >= hist[-2]) OR hist[-1] >= 0
    SHORT 조건: 4H MACD Hist 하락 중 (hist[-1] <= hist[-2]) OR hist[-1] <= 0

    Args:
        bc: BinanceClient
        symbol: 심볼
        side: "long" or "short" (lowercase!)

    Returns:
        (ok, reason, snapshot_4h)
    """
    try:
        from app.services.chart_analyzer import ChartAnalyzer

        side_l = (side or "").lower()
        a4 = ChartAnalyzer.analyze_timeframe(bc, symbol, "4h", limit=120)
        if not a4:
            return False, "4h 데이터 없음", {}

        hist_4h_list = a4.get("macd_hist") or []
        if len(hist_4h_list) < 2:
            return False, "4h macd_hist 데이터 부족", {}

        hist_4h_now = float(hist_4h_list[-1])
        hist_4h_prev = float(hist_4h_list[-2])

        # 4H 방향 판정 (평평 zone 존재!)
        if abs(hist_4h_now - hist_4h_prev) < MACD_4H_FLAT_ABS:
            direction_4h = "flat"
        elif hist_4h_now > hist_4h_prev:
            direction_4h = "up"
        else:
            direction_4h = "down"

        snapshot = {
            "macd_4h_hist": hist_4h_now,
            "macd_4h_hist_prev": hist_4h_prev,
            "macd_4h_direction": direction_4h,
            "rsi_4h": a4.get("rsi_now"),
            "cci_4h": a4.get("cci_now"),
            "bb_up_4h": a4.get("bb_up_last"),
            "bb_lo_4h": a4.get("bb_lo_last"),
        }

        # 사장님 사상: 두 시간대 방향 일치 요구!
        if side_l == "long":
            # 4H MACD Hist 상승 중 or 이미 양수 = 상승 우호!
            ok = (hist_4h_now >= hist_4h_prev) or (hist_4h_now >= 0)
            reason = (
                f"4h dir={direction_4h} hist={hist_4h_now:+.5f} (LONG ok)"
                if ok else
                f"4h dir={direction_4h} hist={hist_4h_now:+.5f} (LONG 역방향)"
            )
        elif side_l == "short":
            # 4H MACD Hist 하락 중 or 이미 음수 = 하락 우호!
            ok = (hist_4h_now <= hist_4h_prev) or (hist_4h_now <= 0)
            reason = (
                f"4h dir={direction_4h} hist={hist_4h_now:+.5f} (SHORT ok)"
                if ok else
                f"4h dir={direction_4h} hist={hist_4h_now:+.5f} (SHORT 역방향)"
            )
        else:
            return False, f"unknown side {side}", snapshot

        return ok, reason, snapshot
    except Exception as e:
        logger.warning("[Fix74/_check_4h_direction_filter] %s: %s", symbol, e)
        return False, f"예외: {e}", {}


# ═══════════════════════════════════════════════════════════════════
# 함수 (c): 15m 볼륨 증가 확인 (실 변곡점 확인 = false-positive 억제!)
# ═══════════════════════════════════════════════════════════════════
def _check_volume_increase(bc, symbol: str) -> tuple[bool, float | None]:
    """최근 3봉 평균 vs 이전 6봉 평균 = 30%+ 증가?

    Args:
        bc: BinanceClient
        symbol: 심볼

    Returns:
        (ok, ratio) — ratio = recent_avg / prior_avg (실패 시 None)
    """
    try:
        klines = bc.get_klines(
            symbol=symbol,
            interval="15m",
            limit=VOL_RECENT_BARS + VOL_PRIOR_BARS,
        )
        if not isinstance(klines, list) or len(klines) < (VOL_RECENT_BARS + VOL_PRIOR_BARS):
            return False, None
        volumes = [float(k[5]) for k in klines]
        recent = sum(volumes[-VOL_RECENT_BARS:]) / VOL_RECENT_BARS
        prior_bars = volumes[:VOL_PRIOR_BARS]
        prior = sum(prior_bars) / len(prior_bars)
        if prior <= 0:
            return False, None
        ratio = recent / prior
        return (ratio >= VOLUME_INCREASE_RATIO), ratio
    except Exception as e:
        logger.warning("[Fix74/_check_volume_increase] %s: %s", symbol, e)
        return False, None


# ═══════════════════════════════════════════════════════════════════
# 헬퍼: KST 시간 (entry_snapshot 학습용!)
# ═══════════════════════════════════════════════════════════════════
def _kst_hour() -> int:
    """현재 KST 시각 (0~23)."""
    try:
        from datetime import timedelta
        return (datetime.now(timezone.utc) + timedelta(hours=9)).hour
    except Exception:
        return -1


# ═══════════════════════════════════════════════════════════════════
# 헬퍼: Redis alert 저장 (다운스트림 auto_short_at_top / auto_long_at_bottom 호환!)
# ═══════════════════════════════════════════════════════════════════
def _save_alert_redis(
    r,
    symbol: str,
    reversal_type: str,
    confidence: float,
    chg_24h: float,
    snap_15m: dict,
    snap_4h: dict,
    volume_ratio: float | None,
    signals_passed: list[str],
) -> tuple[bool, str]:
    """Fix 72 대칭 = entry_snapshot 완전 저장!

    SHORT → "pump_top:alert:{symbol}:SHORT" (auto_short_at_top ALERT_PATTERN 일치!)
    LONG  → "sajangnim:bottom_long:{symbol}"  (auto_long_at_bottom 호환!)
    """
    try:
        side_upper = "SHORT" if reversal_type == "short" else "LONG"
        regime = (
            "MACD_15M_REVERSAL_SHORT"
            if reversal_type == "short"
            else "MACD_15M_REVERSAL_LONG"
        )

        # Fix 72: rich entry_snapshot (auto_short_at_top / auto_long_at_bottom 우선 소비!)
        entry_snapshot = {
            "source": "macd_reversal_15m",
            "spec_version": SPEC_VERSION,
            "regime": regime,
            "kst_hour": _kst_hour(),
            "confidence": confidence,
            "reversal_type": reversal_type,
            # MACD 15m
            "macd_15m_hist_now": snap_15m.get("macd_15m_hist_now"),
            "macd_15m_hist_prev": snap_15m.get("macd_15m_hist_prev"),
            "macd_15m_hist_prev2": snap_15m.get("macd_15m_hist_prev2"),
            "macd_15m_line_now": snap_15m.get("macd_15m_line_now"),
            "macd_15m_signal_now": snap_15m.get("macd_15m_signal_now"),
            # MACD 4h
            "macd_4h_hist": snap_4h.get("macd_4h_hist"),
            "macd_4h_direction": snap_4h.get("macd_4h_direction"),
            # 15m 지표
            "rsi_15m": snap_15m.get("rsi_15m"),
            "cci_15m": snap_15m.get("cci_15m"),
            "obv_15m": snap_15m.get("obv_15m"),
            "obv_slope_15m": snap_15m.get("obv_slope_15m"),
            "volume_ratio": volume_ratio,
            # BB
            "bb_up_15m": snap_15m.get("bb_up_15m"),
            "bb_lo_15m": snap_15m.get("bb_lo_15m"),
            "bb_mb_15m": None,  # analyze_timeframe이 mb 미반환 (up/lo만!)
            # 가격/변동
            "close_15m": snap_15m.get("close_15m"),
            "change_24h": chg_24h,
            # 진단
            "signals_passed": signals_passed,
            "signals_passed_count": len(signals_passed),
            "detected_at": datetime.now(timezone.utc).isoformat(),
        }

        # 다운스트림 alert payload (하위 호환 필드 함께!)
        alert_data = {
            "symbol": symbol,
            "side": side_upper,
            "confidence": confidence,
            "chg_24h": chg_24h,
            "change_24h": chg_24h,  # auto_short_at_top이 change_24h로 읽음!
            "source": "macd_reversal_15m",
            "spec_version": SPEC_VERSION,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            # Fix 72 하위 호환 = top-level rsi/cci_last (auto_short_at_top 옛 fallback!)
            "rsi": snap_15m.get("rsi_15m"),
            "cci_last": snap_15m.get("cci_15m"),
            # rich snapshot (다운스트림 우선 소비!)
            "entry_snapshot": entry_snapshot,
        }

        if side_upper == "SHORT":
            alert_key = f"pump_top:alert:{symbol}:SHORT"
        else:
            alert_key = f"sajangnim:bottom_long:{symbol}"

        r.setex(alert_key, ALERT_TTL_SEC, json.dumps(alert_data, default=str))
        return True, alert_key
    except Exception as e:
        logger.warning("[Fix74/_save_alert_redis] %s: %s", symbol, e)
        return False, ""


# ═══════════════════════════════════════════════════════════════════
# 메인 함수: 매 3분 실행
# ═══════════════════════════════════════════════════════════════════
def run_macd_reversal_15m() -> dict:
    """Fix 74: 15m MACD 변곡점 + 4H 방향 필터 = LONG/SHORT 대칭 감지!

    사장님 verbatim (헌법 77):
      "macd 15분 하락 후 반등 시작점과 반등후 하락 위치를 참고해줘
       15분과 4시간의 움직임을"

    필터 순서 (사장님 사상 완전 준수!):
      a. 24h 극단 (±15%) 제외 (헌법 64 = 급등/급락 반대매매 금지!)
      b. 15m MACD 변곡점 감지 (반등 시작점 / 반등후 하락!)
      c. 4H MACD 방향 필터 (사장님 "4시간의 움직임" 일치 확인!)
      d. 볼륨 30%+ 증가 확인 (실 변곡 확인 = false-positive 억제!)
      e. Fix 65 OBV gate (사장님 사상!)
      f. Fix 66 regime gate (SHORT/LONG 사이드별!)
      g. Redis alert 저장 (다운스트림 auto_short_at_top / auto_long_at_bottom!)
    """
    from app.core.api_backoff import is_account_banned
    from app.core.crypto import decrypt_text
    from app.core.redis_client import get_redis_client
    from app.integrations.binance.client import BinanceClient
    from app.services.notification_service import NotificationService

    db: Session = SessionLocal()
    detected_short = 0
    detected_long = 0
    scanned = 0
    skipped_extreme = 0
    skipped_4h_direction = 0
    skipped_volume = 0
    skipped_obv_gate = 0
    skipped_regime = 0

    try:
        # 1. mainnet 계정!
        acc = db.execute(
            select(ExchangeAccount)
            .where(ExchangeAccount.is_testnet == False)
            .where(ExchangeAccount.is_active == True)
            .limit(1)
        ).scalar_one_or_none()
        if not acc:
            return {
                "error": "no mainnet account",
                "detected": 0,
                "spec_version": SPEC_VERSION,
            }

        if is_account_banned(acc.id):
            return {
                "error": "account banned",
                "detected": 0,
                "spec_version": SPEC_VERSION,
            }

        # 2. BinanceClient
        bc = BinanceClient(
            api_key=decrypt_text(acc.api_key_enc),
            api_secret=decrypt_text(acc.api_secret_enc),
            is_testnet=False,
        )

        r = get_redis_client()

        # 3. 24h ticker
        tickers = bc.get_24hr_ticker()
        if not isinstance(tickers, list):
            return {
                "error": "ticker failed",
                "detected": 0,
                "spec_version": SPEC_VERSION,
            }

        # USDT 심볼 + 거래대금 정렬 (상위 100!)
        usdt = [t for t in tickers if str(t.get("symbol", "")).endswith("USDT")]
        try:
            usdt.sort(key=lambda x: float(x.get("quoteVolume", 0) or 0), reverse=True)
        except Exception:
            pass
        candidates = usdt[:MAX_SYMBOLS]

        for t in candidates:
            symbol = str(t.get("symbol", ""))
            if not symbol:
                continue
            try:
                scanned += 1
                chg_24h = float(t.get("priceChangePercent", 0) or 0)

                # ────────────────────────────────────────────────────
                # 필터 (a): 24h 극단 (±15%) 제외 (헌법 64!)
                # ────────────────────────────────────────────────────
                if abs(chg_24h) >= EXTREME_CHG_ABS:
                    skipped_extreme += 1
                    logger.info(
                        "[Fix74/skip] %s: 24h %+.1f%% 극단 (헌법 64 반대매매 방지!)",
                        symbol, chg_24h,
                    )
                    continue

                # ────────────────────────────────────────────────────
                # 필터 (b): 15m MACD 변곡점 감지 (사장님 verbatim!)
                # ────────────────────────────────────────────────────
                reversal_type, snap_15m = _check_15m_macd_reversal(bc, symbol)
                if not reversal_type or not snap_15m:
                    continue

                # ────────────────────────────────────────────────────
                # 필터 (c): 4H 방향 필터 (사장님 "4시간의 움직임"!)
                # ────────────────────────────────────────────────────
                dir_ok, dir_reason, snap_4h = _check_4h_direction_filter(
                    bc, symbol, reversal_type,
                )
                if not dir_ok:
                    skipped_4h_direction += 1
                    logger.info("[Fix74/skip] %s: %s", symbol, dir_reason)
                    continue

                # ────────────────────────────────────────────────────
                # 필터 (d): 볼륨 증가 확인 (실 변곡점 확인!)
                # ────────────────────────────────────────────────────
                vol_ok, vol_ratio = _check_volume_increase(bc, symbol)
                if not vol_ok:
                    skipped_volume += 1
                    logger.info(
                        "[Fix74/skip] %s: 볼륨 증가 미확인 (ratio=%s)",
                        symbol,
                        f"{vol_ratio:.2f}" if vol_ratio is not None else "None",
                    )
                    continue

                # ────────────────────────────────────────────────────
                # 필터 (e): Fix 65 OBV gate (사장님 사상!)
                # ────────────────────────────────────────────────────
                side_upper = "SHORT" if reversal_type == "short" else "LONG"
                try:
                    from app.services.obv_gate import check_obv_gate
                    obv_pass, obv_reason = check_obv_gate(bc, symbol, side_upper)
                    if not obv_pass:
                        skipped_obv_gate += 1
                        logger.info(
                            "[Fix74+Fix65] %s skip: %s", symbol, obv_reason,
                        )
                        continue
                except Exception as _obv_exc:
                    logger.warning(
                        "[Fix74+Fix65] %s obv_gate error: %s", symbol, _obv_exc,
                    )

                # ────────────────────────────────────────────────────
                # 필터 (f): Fix 66 regime gate (사이드별!)
                # ────────────────────────────────────────────────────
                try:
                    from app.services.bidirectional_blocklist import is_bidirectional_blocked
                    from app.core.database import SessionLocal as _SL
                    db_bl = _SL()
                    try:
                        blocked, block_reason = is_bidirectional_blocked(db_bl, symbol)
                        if blocked:
                            skipped_regime += 1
                            logger.info(
                                "[Fix74+Fix66] %s skip: %s", symbol, block_reason,
                            )
                            continue
                    finally:
                        db_bl.close()

                    if reversal_type == "short":
                        from app.services.pump_dump_regime import is_regime_blocked_for_short
                        regime_blocked, regime_reason = is_regime_blocked_for_short(
                            bc, symbol,
                        )
                    else:
                        from app.services.pump_dump_regime import is_regime_blocked_for_long
                        regime_blocked, regime_reason = is_regime_blocked_for_long(
                            bc, symbol,
                        )
                    if regime_blocked:
                        skipped_regime += 1
                        logger.info(
                            "[Fix74+Fix66] %s skip: %s", symbol, regime_reason,
                        )
                        continue
                except Exception as _f66_exc:
                    logger.warning("[Fix74+Fix66] %s error: %s", symbol, _f66_exc)

                # ────────────────────────────────────────────────────
                # confidence 계산 (기본 0.85 + 4H 방향 강도 bonus!)
                # ────────────────────────────────────────────────────
                confidence = MIN_CONFIDENCE
                # 4H 방향이 name-match ("up" for LONG, "down" for SHORT) 시 bonus!
                dir_4h = snap_4h.get("macd_4h_direction")
                if (reversal_type == "long" and dir_4h == "up") or (
                    reversal_type == "short" and dir_4h == "down"
                ):
                    confidence = min(confidence + 0.05, 0.95)
                # 볼륨 강한 증가 시 (2배+) 추가 bonus!
                if vol_ratio is not None and vol_ratio >= 2.0:
                    confidence = min(confidence + 0.02, 0.95)

                confidence = round(confidence, 4)

                # ────────────────────────────────────────────────────
                # 통과한 signal 리스트 (학습용!)
                # ────────────────────────────────────────────────────
                signals_passed = [
                    "macd_15m_reversal",
                    "macd_4h_direction",
                    "volume_increase",
                    "obv_gate",
                    "regime_ok",
                ]

                # ────────────────────────────────────────────────────
                # Redis alert 저장 (다운스트림 auto_short_at_top / auto_long_at_bottom!)
                # ────────────────────────────────────────────────────
                saved, alert_key = _save_alert_redis(
                    r=r,
                    symbol=symbol,
                    reversal_type=reversal_type,
                    confidence=confidence,
                    chg_24h=chg_24h,
                    snap_15m=snap_15m,
                    snap_4h=snap_4h,
                    volume_ratio=vol_ratio,
                    signals_passed=signals_passed,
                )
                if not saved:
                    continue

                if reversal_type == "short":
                    detected_short += 1
                else:
                    detected_long += 1

                h_prev = snap_15m.get("macd_15m_hist_prev")
                h_now = snap_15m.get("macd_15m_hist_now")
                dir_4h_str = snap_4h.get("macd_4h_direction")
                logger.warning(
                    "[Fix74/detected] %s: side=%s hist_prev=%.5f→now=%.5f 4h=%s conf=%.2f vol=%s key=%s",
                    symbol,
                    side_upper,
                    float(h_prev) if h_prev is not None else 0.0,
                    float(h_now) if h_now is not None else 0.0,
                    dir_4h_str,
                    confidence,
                    f"{vol_ratio:.2f}x" if vol_ratio is not None else "?",
                    alert_key,
                )

                # 텔레그램 알림!
                try:
                    _db_n = SessionLocal()
                    try:
                        _ns = NotificationService(_db_n)
                        _title = f"🎯 Fix74 MACD 15m 변곡 {side_upper}: {symbol}"
                        _body = (
                            f"reversal={reversal_type} conf={confidence*100:.0f}%\n"
                            f"15m hist: {float(h_prev) if h_prev is not None else 0:+.5f}"
                            f"→{float(h_now) if h_now is not None else 0:+.5f}\n"
                            f"4h MACD 방향: {dir_4h_str}\n"
                            f"볼륨: "
                            f"{f'{vol_ratio:.2f}x' if vol_ratio is not None else '?'}\n"
                            f"24h: {chg_24h:+.1f}%\n"
                            f"사장님 verbatim (헌법 77):\n"
                            f"「macd 15분 하락 후 반등 시작점과 반등후 하락 위치」"
                        )
                        _ns.send_system_alert(title=_title, body=_body)
                    finally:
                        _db_n.close()
                except Exception as _te:
                    logger.warning("[Fix74/telegram] %s 실패: %s", symbol, _te)
            except Exception as e:
                logger.warning("[Fix74] %s error: %s", symbol, e)
                continue

        detected_total = detected_short + detected_long
        logger.warning(
            "[Fix74] 완료: scanned=%d detected=%d (SHORT=%d, LONG=%d) "
            "skip_extreme=%d skip_4h=%d skip_vol=%d skip_obv=%d skip_regime=%d spec=%s",
            scanned, detected_total, detected_short, detected_long,
            skipped_extreme, skipped_4h_direction, skipped_volume,
            skipped_obv_gate, skipped_regime, SPEC_VERSION,
        )
        return {
            "scanned": scanned,
            "detected": detected_total,
            "detected_short": detected_short,
            "detected_long": detected_long,
            "skipped_extreme": skipped_extreme,
            "skipped_4h_direction": skipped_4h_direction,
            "skipped_volume": skipped_volume,
            "skipped_obv_gate": skipped_obv_gate,
            "skipped_regime": skipped_regime,
            "spec_version": SPEC_VERSION,
        }
    except Exception as e:
        logger.exception("[Fix74] 실행 실패: %s", e)
        return {"error": str(e), "detected": 0, "spec_version": SPEC_VERSION}
    finally:
        db.close()

"""🔀 20% 급등 후 「지속 상승 vs 하락 전환」 판별기 (v146 신!)

spec: docs/PUMP_CONTINUATION_SPEC.md
사장님 전략 2026-08-14:
  "20% 이상 급등하는 심볼을 1분 5분 차트를 보고 1차 진입을 결정해야 해.
   20% 급등 후 지속 상승하는 경우 진입시점을 잡고 최대 3단계 안에서 고점을 잡아야 해."
  "롱과 숏을 동시에 생각하고 하는 거. **급등 후 하락할 경우 숏, 지속 상승은 롱 짧게**"

= 같은 20% 시점에 서서 **두 갈래를 가르는 판별기**입니다.

🔬 실측 (scripts/study_pump_continuation.py — 181심볼 5m 25일, 20%+ 급등 282건)

  [기저] 20% 급등 후 6시간 내 ±10% 선착:
        지속(UP) **41.1%** / 전환(DOWN) **48.9%** / 미결 9.9%
        → 그냥은 거의 동전던지기입니다. 오히려 전환이 약간 우세.

  [사장님이 보신 「20%→100%」] 282건 중 **1건 (0.4%)**
        +30% 이상 = 13.5% / +50% 이상 = 5.0% / +100% 이상 = **0.4%**
        → 실재하지만 **극히 드뭅니다.** 그것만 노리면 안 됩니다.

  [판별] 단독 특징은 전부 무력했습니다 (최대 1.18배).
        **조합**해야 갈라집니다:

        🚀 지속 신호 = **거래량 4배+ AND 종가가 봉 상단 70%+**
              n=57 → 지속 52.6% / 전환 35.1% / +30% 도달 19.3%
        📉 전환 신호 = **가속도 둔화(<0) AND 거래량 마름(1배 미만)**
              n=41 → 지속 31.7% / 전환 48.8%

  → 41:49 였던 기저가 **53:35** (지속) 또는 **32:49** (전환) 로 벌어집니다.

⚠️ 표본이 41~57건뿐입니다. 방향은 잡혔지만 **확정된 우위는 아닙니다.**

헌법 v146:
  '20% 급등 후 계속 갈지 꺾일지는 기본적으로 동전던지기다 (41:49)'
  '단독 지표로는 못 가른다 — 거래량과 종가 위치를 **조합**해야 갈라진다'
  '20%→100%는 0.4%다. 그 하나를 노리다 나머지 99.6%에서 잃지 마라'
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PumpContinuationAnalyzer:
    """20% 급등 시점에서 지속(LONG 짧게) / 전환(SHORT) 을 가릅니다."""

    MIN_MOVE = 20.0
    WINDOW = 24            # 5m 24봉 = 2시간 (v144에서 유효했던 창)

    # --- 판별 임계 (실측 조합) ---
    VOL_STRONG = 4.0       # 거래량 4배+ = 지속 신호
    VOL_DRY = 1.0          # 거래량 1배 미만 = 전환 신호
    CLOSE_POS_HIGH = 0.7   # 종가가 봉 상단 70%+
    CLOSE_POS_LOW = 0.4
    ACCEL_STRONG = 15.0
    ACCEL_WEAK = 0.0

    # --- 실측 성적 (사장님께 그대로 노출) ---
    BASE_CONTINUE = 41.1
    BASE_REVERSE = 48.9
    CONTINUE_STATS = {"n": 57, "cont": 52.6, "rev": 35.1, "big30": 19.3}
    REVERSE_STATS = {"n": 41, "cont": 31.7, "rev": 48.8}
    BIG_MOVE_RATES = {30: 13.5, 50: 5.0, 100: 0.4}

    # --- 사장님 지시: 최대 3단계 ---
    MAX_STAGES = 3
    # 지속(LONG)은 「짧게」 = TP 를 작게
    LONG_TP, LONG_SL = 5.0, 5.0
    SHORT_TP, SHORT_SL = 10.0, 10.0

    KLINE_LIMIT = 60       # 5m 60봉 = 5시간 (창 24 + 특징 계산 여유)

    def __init__(self, binance_client=None):
        self.client = binance_client

    # ------------------------------------------------------------------
    @staticmethod
    def split(klines: list) -> dict[str, list[float]]:
        return {
            "opens": [float(k[1]) for k in klines],
            "highs": [float(k[2]) for k in klines],
            "lows": [float(k[3]) for k in klines],
            "closes": [float(k[4]) for k in klines],
            "volumes": [float(k[5]) for k in klines],
        }

    @classmethod
    def measure(cls, klines_5m: list) -> dict[str, Any]:
        """5m 캔들 → 20% 급등 여부 + 판별 특징 (전부 현재까지의 데이터만)."""
        out: dict[str, Any] = {
            "available": False, "note": None, "is_pump": False,
            "move_pct": None, "vol_ratio": None, "accel": None,
            "streak": 0, "close_pos": None, "straight": None, "price": None,
        }
        need = cls.WINDOW + 30
        if not klines_5m or len(klines_5m) < need:
            out["note"] = f"5m 캔들 부족 ({len(klines_5m or [])}/{need})"
            return out

        d = cls.split(klines_5m)
        o, h, l, c, v = d["opens"], d["highs"], d["lows"], d["closes"], d["volumes"]
        i = len(c) - 1
        base = c[i - cls.WINDOW]
        if base <= 0:
            out["note"] = "기준가 오류"
            return out

        move = (c[i] - base) / base * 100

        v_recent = sum(v[i - 5:i + 1]) / 6
        prev = v[max(0, i - 29):i - 5]
        v_prev = sum(prev) / len(prev) if prev else 0.0
        vol_ratio = (v_recent / v_prev) if v_prev > 0 else 0.0

        r_recent = (c[i] - c[i - 6]) / c[i - 6] * 100 if c[i - 6] else 0.0
        r_prev = (c[i - 6] - c[i - 12]) / c[i - 12] * 100 if c[i - 12] else 0.0
        accel = r_recent - r_prev

        streak = 0
        for j in range(i, max(i - cls.WINDOW, 0), -1):
            if c[j] > o[j]:
                streak += 1
            else:
                break

        peak, max_pb = base, 0.0
        for j in range(i - cls.WINDOW, i + 1):
            peak = max(peak, h[j])
            max_pb = min(max_pb, (l[j] - peak) / peak * 100)

        rng = h[i] - l[i]
        close_pos = ((c[i] - l[i]) / rng) if rng > 0 else 0.5

        out.update({
            "available": True,
            "is_pump": move >= cls.MIN_MOVE,
            "move_pct": round(move, 2),
            "vol_ratio": round(vol_ratio, 2),
            "accel": round(accel, 2),
            "streak": streak,
            "close_pos": round(close_pos, 3),
            "straight": round(max_pb, 2),
            "price": round(c[i], 8),
        })
        return out

    # ------------------------------------------------------------------
    @classmethod
    def classify(cls, m: dict) -> str:
        """지속(CONTINUE) / 전환(REVERSE) / 중립(NEUTRAL) 판정."""
        if not m.get("available") or not m.get("is_pump"):
            return "NONE"
        vol = m.get("vol_ratio") or 0.0
        pos = m.get("close_pos") or 0.5
        acc = m.get("accel") or 0.0

        # 🚀 지속: 거래량 폭발 + 고가 마감 (실측 53:35)
        if vol >= cls.VOL_STRONG and pos >= cls.CLOSE_POS_HIGH:
            return "CONTINUE"
        # 📉 전환: 가속 둔화 + 거래량 마름 (실측 32:49)
        if acc < cls.ACCEL_WEAK and vol < cls.VOL_DRY:
            return "REVERSE"
        return "NEUTRAL"

    # ------------------------------------------------------------------
    @classmethod
    def combine(cls, symbol: str, m: dict) -> dict[str, Any]:
        signals: list[str] = []
        if not m.get("available"):
            return {
                "available": False, "symbol": symbol, "grade": "D", "stage": "UNKNOWN",
                "side": None, "verdict": "➖ 판정 불가", "color": "#94a3b8", "score": 0,
                "signals": [f"➖ {m.get('note')}"], "measure": m, "levels": {},
            }

        if not m.get("is_pump"):
            return {
                "available": True, "symbol": symbol, "grade": "D", "stage": "NONE",
                "side": None,
                "verdict": f"➖ 20% 급등 아님 (2시간 {m['move_pct']:+.1f}%)",
                "color": "#64748b", "score": 0,
                "signals": [f"➖ 2시간 변동 {m['move_pct']:+.1f}% = 20% 미만 = 대상 아님"],
                "measure": m, "levels": {},
            }

        kind = cls.classify(m)
        signals.append(
            f"🚀 2시간 동안 {m['move_pct']:+.1f}% 급등! "
            f"(거래량 {m['vol_ratio']}배 / 가속 {m['accel']:+.1f} / "
            f"연속양봉 {m['streak']} / 종가위치 {m['close_pos']*100:.0f}%)"
        )
        signals.append(
            f"📊 기저: 20% 급등 후 지속 {cls.BASE_CONTINUE}% vs 전환 {cls.BASE_REVERSE}% "
            "= 그냥은 거의 동전던지기입니다!"
        )

        price = m["price"]
        if kind == "CONTINUE":
            s = cls.CONTINUE_STATS
            grade, side, stage = "A", "LONG", "TRIGGER"
            verdict = f"🚀 지속 신호 → LONG (짧게!) — 실측 지속 {s['cont']}% vs 전환 {s['rev']}%"
            tp, sl = cls.LONG_TP, cls.LONG_SL
            signals.append(
                f"✅ 거래량 {m['vol_ratio']}배(4배+) AND 종가 상단 {m['close_pos']*100:.0f}%(70%+) "
                f"= 지속 신호! (표본 {s['n']}건, +30% 도달 {s['big30']}%)"
            )
            signals.append(
                f"⏱ 사장님 지시대로 **짧게** — TP +{tp:.0f}% / SL -{sl:.0f}%, "
                f"최대 {cls.MAX_STAGES}단계"
            )
            score = 70
        elif kind == "REVERSE":
            s = cls.REVERSE_STATS
            grade, side, stage = "A", "SHORT", "TRIGGER"
            verdict = f"📉 전환 신호 → SHORT — 실측 전환 {s['rev']}% vs 지속 {s['cont']}%"
            tp, sl = cls.SHORT_TP, cls.SHORT_SL
            signals.append(
                f"✅ 가속 둔화({m['accel']:+.1f}) AND 거래량 마름({m['vol_ratio']}배) "
                f"= 전환 신호! (표본 {s['n']}건)"
            )
            signals.append(f"⏱ TP +{tp:.0f}% / SL -{sl:.0f}%, 최대 {cls.MAX_STAGES}단계")
            score = 60
        else:
            grade, side, stage = "C", None, "WATCH"
            verdict = "👀 중립 — 지속·전환 신호 모두 불충분 = 진입 근거 없음"
            tp = sl = None
            signals.append(
                "➖ 거래량/종가위치/가속도 조합이 어느 쪽 신호도 만족하지 않습니다. "
                "이 상태로 들어가면 41:49 동전던지기입니다."
            )
            score = 20

        # 사장님이 보신 「20%→100%」의 실제 빈도
        signals.append(
            f"📌 참고: 20% 급등 후 +30% 도달 {cls.BIG_MOVE_RATES[30]}% / "
            f"+50% {cls.BIG_MOVE_RATES[50]}% / **+100% {cls.BIG_MOVE_RATES[100]}%** "
            "= 큰 건은 극히 드뭅니다."
        )
        signals.append(
            f"⚠️ 표본이 {cls.CONTINUE_STATS['n']}~{cls.REVERSE_STATS['n']}건뿐입니다. "
            "방향은 잡혔지만 확정된 우위는 아닙니다!"
        )

        levels = {}
        if side and price:
            if side == "LONG":
                levels = {
                    "entry_ref": price,
                    "tp_pct": tp, "sl_pct": sl,
                    "tp_price": round(price * (1 + tp / 100), 8),
                    "sl_price": round(price * (1 - sl / 100), 8),
                    "max_stages": cls.MAX_STAGES,
                }
            else:
                levels = {
                    "entry_ref": price,
                    "tp_pct": tp, "sl_pct": sl,
                    "tp_price": round(price * (1 - tp / 100), 8),
                    "sl_price": round(price * (1 + sl / 100), 8),
                    "max_stages": cls.MAX_STAGES,
                }

        color = {"A": "#22c55e", "C": "#94a3b8", "D": "#64748b"}[grade]
        return {
            "available": True, "symbol": symbol, "kind": kind,
            "grade": grade, "stage": stage, "side": side,
            "verdict": verdict, "color": color, "score": score,
            "signals": signals, "measure": m, "levels": levels,
        }

    # ------------------------------------------------------------------
    def analyze(self, symbol: str, klines_5m: list | None = None) -> dict[str, Any]:
        symbol = (symbol or "").upper()
        try:
            k5 = klines_5m if klines_5m is not None else (
                self.client.get_klines(symbol=symbol, interval="5m", limit=self.KLINE_LIMIT)
                if self.client else None)
            if k5 is None:
                raise RuntimeError("binance_client 없음 (캔들을 직접 넘기세요!)")
        except Exception as e:
            logger.warning("[pump_cont] 캔들 조회 실패 %s: %s", symbol, e)
            return {
                "available": False, "symbol": symbol, "grade": "D", "stage": "UNKNOWN",
                "side": None, "verdict": "➖ 판정 불가", "color": "#94a3b8", "score": 0,
                "signals": [f"➖ 캔들 조회 실패: {e}"], "error": str(e),
            }
        try:
            return self.combine(symbol, self.measure(k5))
        except Exception as e:
            logger.warning("[pump_cont] 계산 실패 %s: %s", symbol, e)
            return {
                "available": False, "symbol": symbol, "grade": "D", "stage": "UNKNOWN",
                "side": None, "verdict": "➖ 판정 불가", "color": "#94a3b8", "score": 0,
                "signals": [f"➖ 계산 실패: {e}"], "error": str(e),
            }


def to_learning_context(result: dict | None) -> dict[str, Any]:
    if not result:
        return {}
    m = result.get("measure") or {}
    return {
        "available": bool(result.get("available")),
        "kind": result.get("kind"),
        "grade": result.get("grade"),
        "side": result.get("side"),
        "move_pct": m.get("move_pct"),
        "vol_ratio": m.get("vol_ratio"),
        "accel": m.get("accel"),
        "streak": m.get("streak"),
        "close_pos": m.get("close_pos"),
        "levels": result.get("levels") or {},
    }

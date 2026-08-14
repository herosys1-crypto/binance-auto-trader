"""⚡ 5분·15분봉 급등락 실시간 진입 분석 (v141 신!)

spec: docs/PUMP_DUMP_LIVE_STRATEGY_SPEC.md
사장님 지시 2026-08-14:
  "5분봉과 15분봉에서 20% 정도의 급등락을 급등락 실시간 진입 전략으로 해줘"

핵심 질문은 **방향**이었습니다:
  기존 v133c = 「5분 +3% = 즉시 LONG 추격 / -3% = 즉시 SHORT 추격」
  20%대 급등락에서도 같은가? → **과거 캔들에서 직접 셌습니다.**

🔬 실측 (scripts/study_pump_dump_20pct.py):
  181심볼 × 5m 7,200봉(25일) + 15m 2,400봉 = 롤링 창 누적변동이 임계% 를
  처음 넘는 순간을 이벤트로 잡고, 이후 4시간 동안 **TP와 SL 중 무엇이 먼저 닿는지** 측정.
  (같은 봉에서 둘 다 닿으면 SL 우선 = 보수적)

  ▶ 양의 기대값 셀 54개의 분포 (표본 100건 이상만):
        급등 → **추격 LONG  : 37개 (69%)**   ← 압도적
        급등 → 역추세 SHORT :  6개
        급락 → 역추세 LONG  :  6개
        급락 → 추격 SHORT   :  5개           ← 급락은 방향성 없음!

  ▶ 대표 결과:
        15m 20% 1시간 급등 → 추격 LONG +10%/-5% : TP선착 38.1%, 기대값 **+0.76%** (218건)
        15m 15% 4시간 급등 → 추격 LONG  +5%/-5% : TP선착 50.9%, 기대값 **+0.44%** (782건)
        5m  15% 1시간 급등 → 추격 LONG  +5%/-3% : TP선착 42.7%, 기대값 **+0.42%** (375건)
        5m  20% 1시간 급등 → 추격 LONG +10%/-5% : TP선착 35.1%, 기대값 **+0.32%** (185건)

  ▶ 작은 TP(+3%)는 대부분 **마이너스**입니다.
     변동성이 커서 TP 전에 SL을 먼저 맞기 때문 → **큰 TP + 짧은 SL(비대칭)** 만 통합니다.

⚠️ 반드시 알고 쓰셔야 하는 한계 (숨기지 않습니다):
  1. 기대값 +0.2~0.76% 는 **왕복 수수료(taker 약 0.08%)를 빼기 전** 값입니다.
  2. 20% 급등 중인 알트는 **호가 스프레드가 벌어져 슬리피지가 큽니다** (0.1~0.5%+).
     → 실제 기대값은 **0에 가깝거나 마이너스일 수 있습니다.**
  3. 승률이 30~38%로 낮습니다 = **연속 손실이 길게 이어집니다** (10연패도 정상 범위).
  4. 표본 기간 25일 = 단일 시장 국면일 수 있습니다.

헌법 v141:
  '급등은 추격, 급락은 건드리지 마라 (실측: 급락은 양방향 모두 기대값 없음!)'
  '변동성이 큰 종목일수록 작은 TP는 독이다 — 큰 TP + 짧은 SL 만 살아남는다'
  '기대값은 수수료·슬리피지 전 값이다. 그 사실을 반드시 함께 표시하라!'
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class PumpDumpLiveAnalyzer:
    """5m/15m 롤링 창 급등락 감지 + 실측 기대값 기반 진입 권고."""

    # (라벨, 봉수) — 롤링 창
    WINDOWS = {
        "5m": [("30분", 6), ("1시간", 12), ("2시간", 24)],
        "15m": [("1시간", 4), ("2시간", 8), ("4시간", 16)],
    }

    # 임계값 (사장님 요청 20% + 실측상 더 안정적인 15%)
    TH_STRONG = 20.0     # 사장님 지정
    TH_BASE = 15.0       # 실측상 표본·기대값이 가장 안정적
    TH_WATCH = 10.0      # 관찰 시작 (5m 전용)

    # 🎯 v141a 사장님 지시 2026-08-14:
    #   "15분봉 급등락은 20% 전후만 흐름을 급등락 실시간 진입 전략으로 알려줘"
    #   → 15m 은 이 밴드 **밖이면 신호를 내지 않습니다** (5m 은 기존대로 10%+)
    # 🌟 사장님 결정 (2026-08-14 v147d): 상한 22.5% → **27.5%** 확대
    BAND_15M = (17.5, 27.5)
    # 🌟 v148 사장님 최종 결정 (2026-08-14):
    #   "급등락 실시간 진입은 5분과 15분 차트의 20% 전후 상승과하락일때 할수 있게 해주고"
    #   = 5분봉도 = 15분봉 동일 밴드 (17.5~27.5%)로 신호!
    #   (v141b에서 5m 신호 껐던 것 = 사장님 재요청으로 복원 + 20% 밴드 통일!)
    BAND_5M = (17.5, 27.5)

    # 15m 밴드 플레이북 (scripts/study_15m_pump_bands.py, 181심볼 15m 25일치)
    #   같은 20%대 급등이라도 ①얼마 만에 갔느냐(창) ②얼마나 갔느냐(하위 밴드)
    #   두 축으로 결과가 갈립니다. 그래서 **하위 밴드를 합치지 않고 따로** 씁니다.
    #
    #   ⚠️ 합치면 오히려 나빠집니다 (v147d 재측정):
    #       17.5~27.5% 통합 → 1시간 +0.23% / 2시간 -0.07% / 4시간 +0.16%
    #       하위 밴드 분리 → 1시간 +0.18%·+1.59% / 4시간 +0.23%
    #     하위 밴드마다 최적 TP/SL 이 달라서(+5% vs +15%) 하나로 묶으면
    #     절충된 TP/SL 이 양쪽 모두에 안 맞기 때문입니다.
    #
    #   구조: {(하한, 상한): {창: (등급, TP%, SL%, 기대값%, 표본, TP선착%) | None}}
    #   None = 실측상 신호 없음 → 진입하지 않습니다.
    PLAYBOOK_15M_BAND = {
        # ── 20% 전후 (기존) = 작은 TP 로 짧게 ────────────────────────
        (17.5, 22.5): {
            "1시간": ("B", 5.0, 5.0, 0.18, 255, 51.4),
            "2시간": None,                      # 기대값 0.00% (416건) = 무의미
            "4시간": ("B", 5.0, 5.0, 0.23, 546, 49.1),
        },
        # ── 22.5~27.5% (v147d 신설) = 큰 TP 로 길게 ──────────────────
        #   이 밴드는 **작은 TP 가 오히려 손해**인 구간입니다.
        #   1시간 창 전 조합 실측: +3/-3 -1.11% → +10/-7 +1.12% → +15/-7 +1.59%
        #   = TP 를 키울수록 좋아지는 우측 꼬리형. LONG 이 9개 조합 중 6개 양수,
        #     SHORT 는 0개 양수 = 방향은 확실히 LONG.
        (22.5, 27.5): {
            "1시간": ("B", 15.0, 7.0, 1.59, 114, 36.0),
            "2시간": None,                      # LONG 1/9·SHORT 2/9 양수 = 노이즈
            "4시간": None,                      # 양방향 0/9 양수 = 신호 없음
        },
    }

    @classmethod
    def _band_15m_play(cls, abs_chg: float, window: str):
        """15m 변동폭이 속한 하위 밴드와 그 창의 플레이 → ((lo,hi), play).

        밴드 밖이면 (None, None), 밴드 안이지만 그 창에 신호가 없으면 ((lo,hi), None).
        """
        for bounds, plays in cls.PLAYBOOK_15M_BAND.items():
            lo, hi = bounds
            if lo <= abs_chg < hi:
                return bounds, plays.get(window)
        return None, None

    # 실측 기대값 테이블 = (등급, TP%, SL%, 기대값%, 표본, TP선착%)
    # ⚠️ 전부 수수료/슬리피지 **차감 전** 값!
    PUMP_PLAYBOOK = {
        # (타임프레임, 임계 구간, 창 라벨)
        ("15m", "20", "1시간"): ("A", 10.0, 5.0, 0.76, 218, 38.1),
        ("5m", "20", "1시간"): ("A", 10.0, 5.0, 0.32, 185, 35.1),
        ("15m", "15", "4시간"): ("B", 5.0, 5.0, 0.44, 782, 50.9),
        ("5m", "15", "30분"): ("B", 5.0, 3.0, 0.43, 247, 42.9),
        ("5m", "15", "1시간"): ("B", 5.0, 3.0, 0.42, 375, 42.7),
        ("5m", "15", "2시간"): ("B", 5.0, 3.0, 0.40, 511, 41.9),
        ("15m", "15", "1시간"): ("B", 10.0, 5.0, 0.27, 447, 33.8),
        ("15m", "15", "2시간"): ("B", 5.0, 5.0, 0.21, 645, 50.7),
    }

    # 기본 TP/SL (플레이북에 없는 조합에 사용 — 실측상 가장 무난한 비대칭 조합)
    DEFAULT_TP = 10.0
    DEFAULT_SL = 5.0

    # 왕복 수수료 추정 (taker 0.04% × 2) — 기대값에서 차감해 보여줍니다
    ROUND_TRIP_FEE = 0.08

    # ── v142: 급등 고점 후 「되돌림 깊이 → 고점 회복률」 실측표 ──────────
    #   scripts/study_15m_reversal_pattern.py (181심볼, 15m 20% 전후 급등)
    #   ⚠️ 이건 **진입 신호가 아니라 보유 판단용**입니다.
    #      되돌림 깊이로 진입 타점을 잡는 규칙은 3가지 다 기대값 마이너스였습니다
    #      (아래 REVERSAL_ENTRY_VERDICT 참조). 반면 「지금 몇 % 되돌렸나」로
    #      앞으로 고점을 회복할 확률을 보는 것은 실측 근거가 뚜렷합니다.
    #   (되돌림 상한%, 고점 회복률%, 표본)  — 4시간 창 기준
    RETRACE_RECOVERY = [
        (5.0, 80.0, 20),      # 3~5%   되돌림 → 고점 회복 80.0%
        (8.0, 58.7, 63),      # 5~8%            → 58.7%
        (12.0, 40.7, 108),    # 8~12%           → 40.7%
        (20.0, 24.9, 197),    # 12~20%          → 24.9%
        (999.0, 12.0, 158),   # 20%+            → 12.0%
    ]
    # 급등의 65%가 12% 이상 되돌립니다 (355/546) = 얕은 되돌림은 15%뿐 = 「가끔」!
    DEEP_RETRACE_RATE = 65.0
    SHALLOW_RETRACE_RATE = 15.2
    RETRACE_LOOKBACK = 16     # 최근 16봉(4시간) 내 고점 기준

    REVERSAL_ENTRY_VERDICT = (
        "되돌림을 진입 타점으로 쓰는 규칙 3종(첫 양봉 / 직전봉 돌파+TP=고점 / "
        "SL 고정)은 실측 기대값이 전부 마이너스였습니다 (-0.49% ~ -2.09%)."
    )

    KLINE_LIMIT = 60     # 5m 60봉=5시간 / 15m 60봉=15시간 (최장 창 16봉 커버)

    def __init__(self, binance_client=None):
        self.client = binance_client

    # ------------------------------------------------------------------
    # 변동률 측정
    # ------------------------------------------------------------------
    @classmethod
    def measure(cls, klines: list, tf: str) -> dict[str, Any]:
        """각 롤링 창의 누적 변동률 (%) — 진행 중 봉 포함 = 실시간!"""
        out: dict[str, Any] = {"available": False, "tf": tf, "changes": {}, "note": None}
        wins = cls.WINDOWS.get(tf)
        if not wins:
            out["note"] = f"지원하지 않는 타임프레임: {tf}"
            return out
        need = max(w for _, w in wins) + 1
        if not klines or len(klines) < need:
            out["note"] = f"{tf} 캔들 부족 ({len(klines or [])}/{need})"
            return out

        closes = [float(k[4]) for k in klines]
        highs = [float(k[2]) for k in klines]
        lows = [float(k[3]) for k in klines]
        price = closes[-1]

        changes: dict[str, float] = {}
        for label, bars in wins:
            base = closes[-1 - bars]
            if base > 0:
                changes[label] = round((price - base) / base * 100, 3)

        # 창 내 최고/최저 = 급등 정점 대비 현재 위치 (추격 시 중요!)
        longest = max(w for _, w in wins)
        seg_hi = max(highs[-longest:])
        seg_lo = min(lows[-longest:])
        out.update({
            "available": True,
            "price": round(price, 8),
            "changes": changes,
            "window_high": round(seg_hi, 8),
            "window_low": round(seg_lo, 8),
            "from_high_pct": round((price - seg_hi) / seg_hi * 100, 3) if seg_hi else None,
            "from_low_pct": round((price - seg_lo) / seg_lo * 100, 3) if seg_lo else None,
        })
        return out

    # ------------------------------------------------------------------
    # v142: 되돌림 상태 = **보유 판단** 도구 (진입 신호 아님!)
    # ------------------------------------------------------------------
    @classmethod
    def retrace_state(cls, klines_15m: list) -> dict[str, Any]:
        """최근 고점 대비 현재 되돌림 깊이 → 실측 고점 회복 확률.

        사장님 지시(2026-08-14)로 「급등→고점→하락→재상승」 V자 패턴을 연구한 결과:
          · 되돌림이 **얕을수록** 고점 회복률이 뚜렷하게 높습니다 (3~5% → 80%)
          · 그러나 **진입 타점**으로 쓰는 규칙은 3종 모두 기대값 마이너스였습니다
        → 그래서 **이미 들고 있는 포지션의 홀드/청산 판단**에만 씁니다.
        """
        out: dict[str, Any] = {
            "available": False, "note": None,
            "recent_high": None, "price": None, "retrace_pct": None,
            "recovery_rate": None, "sample_n": None, "advice": None,
        }
        need = cls.RETRACE_LOOKBACK + 2
        if not klines_15m or len(klines_15m) < need:
            out["note"] = f"15m 캔들 부족 ({len(klines_15m or [])}/{need})"
            return out

        highs = [float(k[2]) for k in klines_15m]
        closes = [float(k[4]) for k in klines_15m]
        price = closes[-1]
        recent_high = max(highs[-cls.RETRACE_LOOKBACK:])
        if recent_high <= 0:
            out["note"] = "고점 계산 불가"
            return out

        retrace = (price - recent_high) / recent_high * 100   # 음수 = 되돌림
        depth = abs(retrace)
        rate = n = None
        for limit, r, sample in cls.RETRACE_RECOVERY:
            if depth < limit:
                rate, n = r, sample
                break

        if depth < 1.0:
            advice = "고점 부근 = 되돌림 판정 전 (아직 흐름 진행 중)"
        elif rate is not None and rate >= 55:
            advice = (f"얕은 되돌림 = 실측 고점 회복률 {rate:.0f}% → 홀드 근거 있음 "
                      f"(단 이런 얕은 되돌림은 전체의 {cls.SHALLOW_RETRACE_RATE:.0f}%뿐!)")
        elif rate is not None and rate >= 35:
            advice = f"중간 되돌림 = 회복률 {rate:.0f}% = 반반 → 분할 청산 검토"
        else:
            advice = (f"깊은 되돌림 = 회복률 {rate:.0f}%뿐 → 고점 회복 기대는 낮습니다 "
                      f"(급등의 {cls.DEEP_RETRACE_RATE:.0f}%가 12% 이상 되돌림)")

        out.update({
            "available": True,
            "recent_high": round(recent_high, 8),
            "price": round(price, 8),
            "retrace_pct": round(retrace, 3),
            "recovery_rate": rate,
            "sample_n": n,
            "advice": advice,
        })
        return out

    # ------------------------------------------------------------------
    # 이벤트 판정
    # ------------------------------------------------------------------
    # 🌟 v148 사장님 최종 결정 (2026-08-14):
    #   "급등락 실시간 진입은 5분과 15분 차트의 20% 전후 상승과하락일때 할수 있게 해주고"
    #   → 5m 신호 = **ON!** (BAND_5M = BAND_15M 동일 = 17.5~27.5%!)
    ENABLE_5M_SIGNAL = True

    @classmethod
    def _qualifies(cls, tf: str, abs_chg: float) -> bool:
        """타임프레임별 신호 자격.

        · 15m = 20% 전후 밴드 (BAND_15M = 17.5~27.5%) 안에서만!
        · 5m  = 20% 전후 밴드 (BAND_5M = 17.5~27.5%) 안에서만! (v148 사장님!)
        """
        if tf == "15m":
            lo, hi = cls.BAND_15M
            return lo <= abs_chg < hi
        if tf == "5m":
            if not cls.ENABLE_5M_SIGNAL:
                return False
            lo, hi = cls.BAND_5M
            return lo <= abs_chg < hi
        return False

    @classmethod
    def detect(cls, m5: dict, m15: dict) -> dict[str, Any]:
        """자격을 갖춘 신호 중 가장 강한 것 하나 (절대 변동폭 기준)."""
        best: dict[str, Any] | None = None
        for tf, m in (("5m", m5), ("15m", m15)):
            if not m.get("available"):
                continue
            for label, chg in (m.get("changes") or {}).items():
                if not cls._qualifies(tf, abs(chg)):
                    continue
                cand = {"tf": tf, "window": label, "change_pct": chg,
                        "kind": "PUMP" if chg > 0 else "DUMP", "abs": abs(chg)}
                if best is None or cand["abs"] > best["abs"]:
                    best = cand
        return best or {}

    @classmethod
    def out_of_band_15m(cls, m15: dict) -> float | None:
        """15m 변동이 밴드 밖일 때 그 크기 (사장님께 「왜 신호가 없는지」 설명용)."""
        if not m15.get("available"):
            return None
        biggest = None
        for chg in (m15.get("changes") or {}).values():
            if cls._qualifies("15m", abs(chg)):
                return None          # 밴드 안 신호가 있으면 설명 불필요
            if biggest is None or abs(chg) > abs(biggest):
                biggest = chg
        return biggest if biggest is not None and abs(biggest) >= cls.TH_WATCH else None

    @classmethod
    def _band(cls, abs_chg: float) -> str | None:
        if abs_chg >= cls.TH_STRONG:
            return "20"
        if abs_chg >= cls.TH_BASE:
            return "15"
        return None

    # ------------------------------------------------------------------
    # 종합 권고
    # ------------------------------------------------------------------
    @classmethod
    def combine(cls, symbol: str, m5: dict, m15: dict,
                retrace: dict | None = None) -> dict[str, Any]:
        signals: list[str] = []
        event = cls.detect(m5, m15)
        retrace = retrace or {}

        if not event:
            lo, hi = cls.BAND_15M
            oob = cls.out_of_band_15m(m15)
            msgs = [
                f"➖ 급등락 진입 신호는 「15m {lo:g}~{hi:g}% 밴드」 하나만 씁니다 "
                "(사장님 결정 = 5m 신호는 사용 안 함)"
            ]
            if oob is not None:
                # 왜 15m 신호가 없는지 = 사장님이 헷갈리지 않게 명시!
                msgs.append(
                    f"➖ 15m 변동 {oob:+.1f}% 는 「20% 전후 밴드({lo:g}~{hi:g}%) 밖」 "
                    "= 사장님 지시대로 신호를 내지 않습니다."
                )
            return {
                "available": bool(m5.get("available") or m15.get("available")),
                "symbol": symbol, "grade": "D", "stage": "NONE",
                "event": None, "side": None,
                "verdict": f"➖ 급등락 신호 없음 (15m 은 {lo:g}~{hi:g}% 밴드만 사용)",
                "color": "#64748b", "score": 0,
                "signals": msgs,
                "m5": m5, "m15": m15, "retrace": retrace, "levels": {},
            }

        tf, window = event["tf"], event["window"]
        chg, kind = event["change_pct"], event["kind"]
        is_pump = kind == "PUMP"
        band = cls._band(event["abs"])

        signals.append(
            f"{'🚀' if is_pump else '📉'} {tf} {window} 동안 {chg:+.1f}% "
            f"{'급등' if is_pump else '급락'} 진행 중!"
        )

        # --- 🚫 급락은 진입 비권장 (실측: 양방향 모두 기대값 없음) ---
        if not is_pump:
            signals.append(
                "🚫 실측상 「급락은 방향성이 없습니다」 — 양의 기대값 셀 54개 중 "
                "급락 역추세 6개 / 급락 추격 5개로 사실상 동전던지기입니다."
            )
            signals.append(
                "💡 급락 반등을 노리시려면 v140(15m 바닥 다이버전스) 신호가 함께 뜰 때만 하세요."
            )
            return {
                "available": True, "symbol": symbol, "grade": "D", "stage": "AVOID",
                "event": event, "side": None,
                "verdict": f"🚫 {tf} {window} {chg:.1f}% 급락 — 진입 비권장 (기대값 없음)",
                "color": "#ef4444", "score": 0, "signals": signals,
                "m5": m5, "m15": m15, "retrace": retrace, "levels": {},
            }

        # --- 🚀 급등 = 추격 LONG (실측 69%가 여기) ---
        sub_band = None
        if tf == "15m":
            # 사장님 지시 = 밴드 전용 플레이북 (창별·하위 밴드별로 결과가 다름!)
            sub_band, play = cls._band_15m_play(event["abs"], window)
            if play is None:
                sb_txt = (f"{sub_band[0]:g}~{sub_band[1]:g}%" if sub_band
                          else f"{cls.BAND_15M[0]:g}~{cls.BAND_15M[1]:g}%")
                signals.append(
                    f"➖ 15m {sb_txt} 급등은 {window} 창에서 「실측 신호가 없습니다」 "
                    "— 진입하지 않습니다."
                )
                signals.append(
                    "💡 같은 20%대라도 「얼마 만에 갔느냐(창)」와 「얼마나 갔느냐(밴드)」로 "
                    "결과가 갈립니다. 유효한 조합은 "
                    "17.5~22.5%(1시간·4시간) / 22.5~27.5%(1시간) 뿐입니다."
                )
                return {
                    "available": True, "symbol": symbol, "grade": "D", "stage": "NONE",
                    "event": event, "side": None,
                    "verdict": f"➖ 15m {sb_txt} {window} = 실측 신호 없음 (진입 비권장)",
                    "color": "#64748b", "score": 0, "signals": signals,
                    "m5": m5, "m15": m15, "retrace": retrace, "levels": {},
                }
        else:
            play = cls.PUMP_PLAYBOOK.get((tf, band, window)) if band else None

        if play:
            grade, tp, sl, ev, n, tp_rate = play
            band_txt = (f"{sub_band[0]:g}~{sub_band[1]:g}%"
                        if (tf == "15m" and sub_band) else f"{band}%")
            signals.append(
                f"📊 실측 플레이북 적중: {tf} {band_txt} {window} 급등 → 추격 LONG "
                f"+{tp:.0f}%/-{sl:.0f}% = TP선착 {tp_rate:.1f}%, 기대값 {ev:+.2f}% (표본 {n}건)"
            )
            # 🚨 큰 TP 밴드는 「자주 지고 가끔 크게 이기는」 구조 = 미리 알려드립니다
            if tp_rate is not None and tp_rate < 45:
                loss_rate = 100 - tp_rate
                signals.append(
                    f"🚨 이 밴드는 「자주 지고 가끔 크게 이기는」 형태입니다 — "
                    f"TP 도달은 {tp_rate:.0f}%뿐이고 나머지 {loss_rate:.0f}% 는 "
                    f"-{sl:.0f}% 손절/시간초과입니다. 기대값이 +인 이유는 "
                    f"이기는 판이 +{tp:.0f}% 로 크기 때문 = 연패를 견딜 수 있는 "
                    f"자본으로만 하세요."
                )
        elif band:
            grade, tp, sl = "C", cls.DEFAULT_TP, cls.DEFAULT_SL
            ev = n = tp_rate = None
            signals.append(
                f"➖ {tf} {band}% {window} 조합은 실측 플레이북에 없음 "
                f"= 기본값 +{tp:.0f}%/-{sl:.0f}% 적용 (근거 약함!)"
            )
        else:
            grade, tp, sl = "C", cls.DEFAULT_TP, cls.DEFAULT_SL
            ev = n = tp_rate = None
            signals.append(
                f"👀 변동 {chg:+.1f}% = 관찰 구간 ({cls.TH_BASE:.0f}% 미만) — 신호 약함!"
            )

        signals.append("✅ 방향 = 「추격 LONG」 (실측: 양의 기대값 54셀 중 37개(69%)가 급등 추격!)")
        signals.append(
            f"⚠️ 작은 TP는 독입니다 — +3%/-3% 조합은 대부분 마이너스였습니다 "
            f"(변동성이 커서 TP 전에 SL을 먼저 맞음)"
        )

        # 정점 대비 위치 = 추격 진입의 핵심 리스크
        m = m15 if tf == "15m" else m5
        from_high = m.get("from_high_pct")
        if from_high is not None and from_high < -3:
            signals.append(
                f"⚠️ 이미 정점 대비 {from_high:.1f}% 밀린 상태 = 추격 진입 시 불리! "
                "(급등 「진행 중」이 아니라 「끝난 뒤」일 수 있습니다)"
            )

        # 수수료/슬리피지 경고 = 반드시!
        if ev is not None:
            net = ev - cls.ROUND_TRIP_FEE
            signals.append(
                f"💸 수수료 차감 후 기대값 ≈ {net:+.2f}% "
                f"(왕복 {cls.ROUND_TRIP_FEE:.2f}% 가정, 「슬리피지 별도」). "
                "급등 중 알트는 스프레드가 벌어져 실제로는 더 낮습니다!"
            )
        signals.append(
            f"📉 승률 {tp_rate:.0f}% 수준 = 연속 손실이 깁니다. 자본 관리 없이는 위험합니다!"
            if tp_rate else
            "📉 승률이 30~40%대인 전략입니다 = 연속 손실을 견딜 자본 관리가 필수!"
        )

        price = m.get("price")
        levels = {
            "entry_ref": price,
            "tp_pct": tp,
            "sl_pct": sl,
            "tp_price": round(price * (1 + tp / 100), 8) if price else None,
            "sl_price": round(price * (1 - sl / 100), 8) if price else None,
            "window_high": m.get("window_high"),
            "window_low": m.get("window_low"),
            "expected_value_pct": ev,
            "expected_value_after_fee_pct": round(ev - cls.ROUND_TRIP_FEE, 3) if ev is not None else None,
            "tp_first_rate": tp_rate,
            "sample_n": n,
        }
        color = {"A": "#22c55e", "B": "#f59e0b", "C": "#94a3b8", "D": "#64748b"}[grade]
        verdict = (
            f"🚀 {grade}등급 급등 추격 LONG — {tf} {window} {chg:+.1f}%"
            + (f" (기대값 {ev:+.2f}%)" if ev is not None else "")
        )
        score = {"A": 80, "B": 60, "C": 35}[grade]

        return {
            "available": True, "symbol": symbol, "grade": grade, "stage": "TRIGGER",
            "event": event, "side": "LONG",
            "verdict": verdict, "color": color, "score": score, "signals": signals,
            "m5": m5, "m15": m15, "retrace": retrace, "levels": levels,
        }

    # ------------------------------------------------------------------
    # 진입점
    # ------------------------------------------------------------------
    def _fetch(self, symbol: str, interval: str) -> list:
        if self.client is None:
            raise RuntimeError("binance_client 없음 (캔들을 직접 넘기세요!)")
        return self.client.get_klines(symbol=symbol, interval=interval, limit=self.KLINE_LIMIT)

    def analyze(
        self,
        symbol: str,
        klines_5m: list | None = None,
        klines_15m: list | None = None,
    ) -> dict[str, Any]:
        """급등락 실시간 판정 (읽기 전용!). 예외 = available=False."""
        symbol = (symbol or "").upper()
        try:
            k5 = klines_5m if klines_5m is not None else self._fetch(symbol, "5m")
            k15 = klines_15m if klines_15m is not None else self._fetch(symbol, "15m")
        except Exception as e:
            logger.warning("[pump_live] 캔들 조회 실패 %s: %s", symbol, e)
            return {
                "available": False, "symbol": symbol, "grade": "D", "stage": "UNKNOWN",
                "verdict": "➖ 판정 불가", "color": "#94a3b8", "score": 0,
                "signals": [f"➖ 캔들 조회 실패: {e}"], "error": str(e),
            }
        try:
            return self.combine(
                symbol, self.measure(k5, "5m"), self.measure(k15, "15m"),
                retrace=self.retrace_state(k15),
            )
        except Exception as e:
            logger.warning("[pump_live] 계산 실패 %s: %s", symbol, e)
            return {
                "available": False, "symbol": symbol, "grade": "D", "stage": "UNKNOWN",
                "verdict": "➖ 판정 불가", "color": "#94a3b8", "score": 0,
                "signals": [f"➖ 계산 실패: {e}"], "error": str(e),
            }


def to_learning_context(result: dict | None) -> dict[str, Any]:
    """학습 저장용 압축 스냅샷."""
    if not result:
        return {}
    ev = result.get("event") or {}
    lv = result.get("levels") or {}
    return {
        "available": bool(result.get("available")),
        "grade": result.get("grade"),
        "stage": result.get("stage"),
        "side": result.get("side"),
        "kind": ev.get("kind"),
        "tf": ev.get("tf"),
        "window": ev.get("window"),
        "change_pct": ev.get("change_pct"),
        "tp_pct": lv.get("tp_pct"),
        "sl_pct": lv.get("sl_pct"),
        "expected_value_pct": lv.get("expected_value_pct"),
        "tp_first_rate": lv.get("tp_first_rate"),
        "retrace_pct": (result.get("retrace") or {}).get("retrace_pct"),
        "retrace_recovery_rate": (result.get("retrace") or {}).get("recovery_rate"),
    }

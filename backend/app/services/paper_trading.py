"""🧪 Fix 361 (2026-09-08) — 가상 매매 학습 (paper trading): 실시간 자동을 끈 동안 **가상으로 진입·추가·청산**을 기록하고
「꼭 이기는 롱·숏 자리」와 「익절 중 추가로 수익이 나는 자리」를 같은 잣대로 학습한다. 실 운영을 다시 켤 때 설정으로 옮긴다.

사장님 (2026-09-08 verbatim): "지금부터 실시간 자동은 종료했어 가상으로 포지션 진입해서 성공과 실패를 기록저장 학습해서
다시 실시간 운영시작 하면 그때 적용할 수 있게 학습해줘 꼭 성리할수 있는 롱과숏 포지션 진입하고 익절중에 포지션 추가해서
수익을 만들 자리를 찾아줘"

무엇을 하나 (주문 0건 — 이 모듈과 워커는 바이낸스에 **읽기만** 한다):
  * 15분마다(봉 마감 직후) 감시 대상(당일 상승/하락 50 + 3·5일 순위)의 **완성봉**에서 규칙 레지스트리(chart_learning.RULES
    12종 = 실매매 판정식 + 후보) 를 평가해 발동하면 **가상 진입**(그 봉 종가). 같은 심볼·규칙은 한 번에 하나만.
  * 열린 가상 포지션은 매 사이클 진입 뒤 봉으로 두 엔진을 돌린다:
      - house  = 9/3 이후 모든 측정의 잣대 (SL −5% ROI 우선 → TP +15% → 12h)
      - live   = 실매매 청산 규칙 근사 (SL = 새 전략 기본 **−25% ROI**(Fix 362) · TP1 = 24h 변동 연동 3/15% 에서 25% 부분익절 ·
                 그 뒤 트레일링 5%p · 48h 시간 만료). 봉 고가/저가로 판정 = 15초 마크가격 샘플러의 상한 근사 (M4 측정의 E1).
  * **추가(피라미딩) 변형**을 같은 포지션 위에 병렬로 기록한다 — 각 변형은 300 USDT lot, 자기 손절 = 같은 −25% ROI, 최대 2회:
      live(현행: SHORT · ROI≥5 · 유리이동≥3% · 15m hist 3봉 가속 · 정점 되돌림≤2.5%) / live_both(LONG 허용) /
      after_tp1(익절 뒤에만, 양방향) / body(캔들 몸통 G3A 추가 조건) / noind(지표 조건 없음).
  * 기준선 = 3시간마다 무작위 진입(baseline_LONG/SHORT) 을 같은 엔진으로 — 규칙의 Δ 는 기준선 대비.
  * 학습 = 규칙×방향×자리(태그 그룹)×엔진 별 n·평균·승률·CV 4조각(심볼 홀짝 × 시간 반쪽) → 채택 문턱
    (CV 4/4 양수 · n≥100 · 기준선 초과) 을 넘는 것만 「실 운영 재개 시 켤 설정」으로 제안.
  * 부트스트랩 = 학습 일지(chart_learning_days)의 3주 봉으로 같은 엔진을 되돌려(source=backfill) 첫날부터 표본이 있게.

원칙: 완성봉만 · 미래참조 없음(진입 봉 이후 봉만 청산에 쓴다) · 숫자는 설정키(paper_*) · 실 주문 경로와 import 관계 없음.
"""
from __future__ import annotations

import bisect
import logging
import statistics
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from app.services.chart_learning import (
    HORIZON, LEV, MS_15M, MS_1H, MS_4H, RULES, SL_PRICE, TP_PRICE, Rule, RuleCtx, aggregate, macd_hist, obv, rsi,
    sim, snapshot_indicators,
)

logger = logging.getLogger(__name__)

FIX = "Fix361"
VERSION = 1

# ── 숫자 (Claude 가 정함 — 설정키로 덮을 수 있다) ──────────────────────────────
S_ENABLED = "paper_trading_enabled"            # 기본 ON
S_TOP_N = "paper_trading_top_n"                # 감시 상승/하락 N (기본 50 = 사장님)
S_BACKFILL = "paper_trading_backfill_enabled"  # 일지에서 부트스트랩 (기본 ON)
S_LOT_USDT = "paper_add_lot_usdt"              # 추가 lot (기본 300 = sajangnim_pyramid_capital)
S_BASE_USDT = "paper_base_usdt"                # 첫 진입 (기본 10 = 사다리 1단계)

LOT_USDT = 300.0
BASE_USDT = 10.0
LIVE_SL_ROI = 25.0          # Fix 362 (2026-09-08 사장님): 새 전략 강제손절 기본 −25% ROI — live 엔진(본 포지션·추가 lot)에 적용
LIVE_HORIZON = 192          # 48h — live 엔진 시간 만료
TP1_CLOSE_RATIO = 0.25      # TP1 에서 25% 부분익절 (risk_constants TP1=25)
TRAIL_RETRACE = 5.0         # 트레일링 되돌림 %p (TRAILING_RETRACE_PCT)
TP1_SURGE_CHG = 15.0        # |24h| ≥ 15% → TP1 15 (adaptive_tp 기본)
TP1_SURGE = 15.0
TP1_CALM = 3.0
ADD_TRIGGER_ROI = 5.0       # sajangnim_pyramid_trigger_roi (2026-09-07 사장님 적용값)
ADD_MIN_MOVE = 3.0          # pyramid_min_move_pct
ADD_MAX = 2                 # MAX_PYRAMID_COUNT
ADD_MAX_RETRACE = 2.5       # 정점 되돌림 허용 (가격 %)
ADD_COOLDOWN_BARS = 1
BASELINE_EVERY = 12         # 3h 마다 기준선 진입
VARIANTS = ("live", "live_both", "after_tp1", "body", "noind")
BASELINE_KEYS = {"baseline_LONG": "LONG", "baseline_SHORT": "SHORT"}
GROUP_KEYS = ("ALL", "UP24", "DOWN24", "UP35_DOWN24")
ADOPT_MIN_N = 100


def group_of(tags: Sequence[str]) -> list[str]:
    t = set(tags or [])
    g = ["ALL"]
    if "UP" in t:
        g.append("UP24")
    if "DOWN" in t:
        g.append("DOWN24")
    if "DOWN" in t and (t & {"UP3D", "UP5D"}):
        g.append("UP35_DOWN24")
    return g


# ══════════════════════════════════════════════════════════════════════
# 수치 도구
# ══════════════════════════════════════════════════════════════════════

def roi_of(side: str, entry: float, price: float) -> float:
    """ROI% = 가격변동률 × 레버리지 (실매매 success_pyramiding/risk 와 같은 자)."""
    if entry <= 0:
        return 0.0
    r = (price / entry - 1.0) if side == "LONG" else (1.0 - price / entry)
    return r * 100.0 * LEV


def price_at_roi(side: str, entry: float, roi_pct: float) -> float:
    r = roi_pct / 100.0 / LEV
    return entry * (1.0 + r) if side == "LONG" else entry * (1.0 - r)


def tp1_for(chg_24h: float | None) -> float:
    """adaptive_tp.pick_tp1 기본값 재현: |24h| ≥ 15 → 15, 아니면 3. 24h 없음 = 15 (fail-safe 쪽)."""
    if chg_24h is None:
        return TP1_SURGE
    return TP1_SURGE if abs(float(chg_24h)) >= TP1_SURGE_CHG else TP1_CALM


def _accel3(hist: Sequence[float], idx: int, side: str) -> bool:
    """15m MACD hist 가 내 편 부호로 3봉 연속 커짐 (Fix 348 = check_hist_rising min_bars=3, 완성봉)."""
    if idx < 3 or idx >= len(hist):
        return False
    s = 1.0 if side == "LONG" else -1.0
    return all(s * (hist[k] - hist[k - 1]) > 0 for k in (idx - 2, idx - 1, idx))


# ══════════════════════════════════════════════════════════════════════
# 엔진 1: house (chart_learning.sim 과 동일) — 미완이면 done=False
# ══════════════════════════════════════════════════════════════════════

def run_house(side: str, entry: float, bars: Sequence[Sequence[float]]) -> dict[str, Any]:
    r = sim(side, entry, bars, horizon=HORIZON)
    done = r["hit"] in ("SL", "TP") or len(bars) >= HORIZON
    if not done:
        r["hit"] = "OPEN"
    r["done"] = done
    return r


# ══════════════════════════════════════════════════════════════════════
# 엔진 2: live-like (SL → TP1 25% → 트레일링 5%p → 48h) + 추가 변형 lots
# ══════════════════════════════════════════════════════════════════════

@dataclass
class _Lot:
    variant: str
    seq: int
    bar: int
    price: float
    roi_at_add: float
    exit_bar: int | None = None
    exit_price: float | None = None
    exit_kind: str | None = None

    def roi(self, side: str) -> float | None:
        return None if self.exit_price is None else roi_of(side, self.price, self.exit_price)


@dataclass
class _Variant:
    name: str
    lots: list[_Lot] = field(default_factory=list)
    last_add_bar: int = -99

    def open_lots(self) -> list[_Lot]:
        return [x for x in self.lots if x.exit_kind is None]


def _variant_allows(name: str, side: str, *, roi_c: float, move: float, accel: bool, tp1_hit: bool,
                    body_ok: bool | None, retrace_ok: bool) -> bool:
    if roi_c < ADD_TRIGGER_ROI or move < ADD_MIN_MOVE or not retrace_ok:
        return False
    if name == "live":
        return side == "SHORT" and accel
    if name == "live_both":
        return accel
    if name == "after_tp1":
        return tp1_hit and accel
    if name == "body":
        return accel and bool(body_ok)
    if name == "noind":
        return True
    return False


def run_live_like(side: str, entry: float, bars: Sequence[Sequence[float]], *, tp1_pct: float,
                  hist: Sequence[float] | None = None, hist_off: int = 0,
                  body_fn: Callable[[int], bool | None] | None = None,
                  horizon: int = LIVE_HORIZON, variants: Sequence[str] = VARIANTS,
                  sl_roi: float = LIVE_SL_ROI) -> dict[str, Any]:
    """진입 뒤 완성봉 `bars` 로 실매매 청산 규칙을 근사한다. 판정 순서(한 봉 안): 손절 → TP1 → 트레일링(직전 봉까지의 최고 기준)
    → 시간 만료. 추가 lot 은 봉 **종가**에서 열고, 자기 손절(−5% ROI) 또는 본 포지션 청산과 함께 닫힌다.
    `hist[hist_off + i]` = i 번째 봉의 MACD hist. `body_fn(i)` = i 번째 봉까지의 몸통 성장 판정. 봉이 모자라면 done=False."""
    long = side == "LONG"
    sl_price = price_at_roi(side, entry, -abs(float(sl_roi)))
    tp1_price = price_at_roi(side, entry, tp1_pct)
    realized = 0.0                   # 청산된 비율의 ROI 합 (비율 가중)
    remaining = 1.0
    tp1_hit = False
    tp1_bar: int | None = None
    max_roi = roi_of(side, entry, entry)
    best_fav_price = entry
    mfe = mae = 0.0
    exit_kind: str | None = None
    exit_bar: int | None = None
    exit_price: float | None = None
    vs = {name: _Variant(name) for name in variants}
    n = 0

    def _close_lots(i: int, price: float, kind: str) -> None:
        for v in vs.values():
            for lot in v.open_lots():
                lot.exit_bar, lot.exit_price, lot.exit_kind = i, price, kind

    for i, b in enumerate(bars[:horizon]):
        n = i + 1
        h, l, c = float(b[2]), float(b[3]), float(b[4])
        fav_px = h if long else l
        adv_px = l if long else h
        mfe = max(mfe, roi_of(side, entry, fav_px))
        mae = max(mae, -roi_of(side, entry, adv_px))
        # lot 자기 손절 (본 포지션보다 먼저 — 각 lot 은 자기 진입가 기준 −5% ROI)
        for v in vs.values():
            for lot in v.open_lots():
                lsl = price_at_roi(side, lot.price, -abs(float(sl_roi)))
                if (long and l <= lsl) or (not long and h >= lsl):
                    lot.exit_bar, lot.exit_price, lot.exit_kind = i, lsl, "SL"
        # 본 포지션 손절 (SL 우선)
        if (long and l <= sl_price) or (not long and h >= sl_price):
            realized += remaining * roi_of(side, entry, sl_price)
            exit_kind, exit_bar, exit_price = ("SL" if not tp1_hit else "SL_AFTER_TP1"), i, sl_price
            remaining = 0.0
            _close_lots(i, sl_price, "BASE_SL")
            break
        # TP1 부분익절
        if not tp1_hit and ((long and h >= tp1_price) or (not long and l <= tp1_price)):
            tp1_hit, tp1_bar = True, i
            realized += TP1_CLOSE_RATIO * tp1_pct
            remaining -= TP1_CLOSE_RATIO
            max_roi = max(max_roi, tp1_pct)
        # 트레일링 (TP1 뒤, 직전 봉까지의 최고 ROI 기준 — 같은 봉의 신고점은 다음 봉부터)
        if tp1_hit and i > (tp1_bar or 0):
            trail_roi = max_roi - TRAIL_RETRACE
            adv_roi = roi_of(side, entry, adv_px)
            if adv_roi <= trail_roi:
                px = price_at_roi(side, entry, trail_roi)
                realized += remaining * trail_roi
                exit_kind, exit_bar, exit_price = "TRAIL", i, px
                remaining = 0.0
                _close_lots(i, px, "BASE_TRAIL")
                break
        max_roi = max(max_roi, roi_of(side, entry, fav_px))
        # 추가 판정 (봉 종가)
        roi_c = roi_of(side, entry, c)
        move = ((c / entry - 1.0) if long else (1.0 - c / entry)) * 100.0
        if (long and c > best_fav_price) or (not long and c < best_fav_price):
            best_fav_price = c
        retrace = abs(c / best_fav_price - 1.0) * 100.0
        accel = _accel3(hist, hist_off + i, side) if hist is not None else False
        body_ok = None
        if body_fn is not None and "body" in vs:
            try:
                body_ok = body_fn(i)
            except Exception:  # noqa: BLE001
                body_ok = None
        for v in vs.values():
            if len(v.lots) >= ADD_MAX or i - v.last_add_bar <= ADD_COOLDOWN_BARS:
                continue
            if _variant_allows(v.name, side, roi_c=roi_c, move=move, accel=accel, tp1_hit=tp1_hit,
                               body_ok=body_ok, retrace_ok=retrace <= ADD_MAX_RETRACE):
                v.lots.append(_Lot(v.name, len(v.lots) + 1, i, c, roi_c))
                v.last_add_bar = i
        if i == horizon - 1:
            realized += remaining * roi_c
            exit_kind, exit_bar, exit_price = "TIME", i, c
            remaining = 0.0
            _close_lots(i, c, "BASE_TIME")
            break

    done = exit_kind is not None
    last_c = float(bars[min(n, len(bars)) - 1][4]) if bars else entry
    unreal = remaining * roi_of(side, entry, last_c)
    out: dict[str, Any] = {
        "done": done, "hit": exit_kind or "OPEN", "bars": n, "tp1_pct": tp1_pct, "sl_roi": sl_roi, "tp1_hit": tp1_hit,
        "tp1_bar": tp1_bar, "max_roi": round(max_roi, 4), "mfe": round(mfe, 4), "mae": round(mae, 4),
        "roi": round(realized + unreal, 4), "realized": round(realized, 4), "exit_bar": exit_bar,
        "exit_price": exit_price,
    }
    adds: dict[str, list[dict[str, Any]]] = {}
    for v in vs.values():
        rows = []
        for lot in v.lots:
            r = lot.roi(side)
            rows.append({"seq": lot.seq, "bar": lot.bar, "price": lot.price, "roi_at_add": round(lot.roi_at_add, 4),
                         "exit_bar": lot.exit_bar, "exit_kind": lot.exit_kind,
                         "roi": (round(r, 4) if r is not None else None),
                         "pnl_usdt": (round(LOT_USDT * r / 100.0, 4) if r is not None else None)})
        adds[v.name] = rows
    out["adds"] = adds
    return out


# ══════════════════════════════════════════════════════════════════════
# 규칙 평가 (chart_learning.label_row 와 같은 재료로 한 봉 j 에서)
# ══════════════════════════════════════════════════════════════════════

@dataclass
class Series:
    """한 심볼의 15m 완성봉 전체 + 인과 지표 (한 사이클에 한 번 계산)."""
    allk: list[list[float]]
    k4h: list[list[float]]
    c: list[float]
    h: list[float]
    l: list[float]
    v: list[float]
    hist: list[float]
    rsi14: list[float | None]
    obv: list[float]
    k1h: list[list[float]]
    close1h: list[int]
    close4h: list[int]

    @classmethod
    def build(cls, allk: Sequence[Sequence[float]], k4h: Sequence[Sequence[float]]) -> "Series":
        allk = [list(map(float, b[:6])) for b in allk]
        k4h = [list(map(float, b[:6])) for b in k4h]
        c = [b[4] for b in allk]
        k1h = aggregate(allk, MS_1H)
        return cls(allk=allk, k4h=k4h, c=c, h=[b[2] for b in allk], l=[b[3] for b in allk], v=[b[5] for b in allk],
                   hist=macd_hist(c), rsi14=rsi(c), obv=obv(c, [b[5] for b in allk]), k1h=k1h,
                   close1h=[int(b[0]) + MS_1H for b in k1h], close4h=[int(b[0]) + MS_4H for b in k4h])

    def ctx(self, j: int) -> RuleCtx:
        close_ms = int(self.allk[j][0]) + MS_15M
        n1 = bisect.bisect_right(self.close1h, close_ms)
        n4 = bisect.bisect_right(self.close4h, close_ms)
        return RuleCtx(j=j, c=self.c, h=self.h, l=self.l, v=self.v, hist=self.hist, rsi14=self.rsi14, obv=self.obv,
                       kl15=self.allk[max(0, j - 259):j + 1], kl1h=self.k1h[max(0, n1 - 60):n1],
                       kl4h=self.k4h[max(0, n4 - 60):n4])


def evaluate_rules(series: Series, j: int, *, rules: Sequence[Rule] = RULES) -> dict[str, bool]:
    ctx = series.ctx(j)
    out: dict[str, bool] = {}
    for r in rules:
        try:
            out[r.key] = bool(r.fn(ctx))
        except Exception as e:  # noqa: BLE001
            logger.debug("[%s] 규칙 %s 실패 (j=%d): %s", FIX, r.key, j, e)
            out[r.key] = False
    ts = int(series.allk[j][0])
    is_base = (ts // MS_15M) % BASELINE_EVERY == 0
    for k in BASELINE_KEYS:
        out[k] = is_base
    return out


def entry_snapshot(series: Series, j: int, side: str, *, chg_24h: float | None, tags: Sequence[str],
                   fired: Mapping[str, bool]) -> dict[str, Any]:
    """진입 근거 기록 — 나중에 「어떤 상태에서 이기나」를 가르는 축. 전부 j 봉까지의 값."""
    pre15 = series.allk[max(0, j - 259):j + 1]
    n4 = bisect.bisect_right(series.close4h, int(series.allk[j][0]) + MS_15M)
    snap: dict[str, Any] = {"tags": list(tags), "chg_24h": chg_24h,
                            "rules_fired": sorted(k for k, v in fired.items() if v and k not in BASELINE_KEYS)}
    try:
        snap.update(snapshot_indicators(pre15, series.k4h[max(0, n4 - 61):n4]))
    except Exception as e:  # noqa: BLE001
        snap["indicator_error"] = str(e)[:120]
    try:
        from app.services import candle_battle as CB
        cfg = CB.DEFAULT_CFG
        ok_w, why_w, _ = CB.recent_wick_bar(pre15, "SHORT", cfg)
        ok_h, why_h, _ = CB.reversal_signal(pre15, "LONG", cfg)
        snap["candle"] = {"wick_addon_short": bool(ok_w), "hammer_long": bool(ok_h)}
    except Exception as e:  # noqa: BLE001
        snap["candle"] = {"error": str(e)[:120]}
    snap["accel3"] = _accel3(series.hist, j, side)
    return snap


# ══════════════════════════════════════════════════════════════════════
# 가상 포지션 dict (DB 행과 1:1) — 열기 / 관리
# ══════════════════════════════════════════════════════════════════════

def open_trade(*, symbol: str, side: str, rule: str, series: Series, j: int, tags: Sequence[str],
               chg_24h: float | None, chg_3d: float | None, chg_5d: float | None, source: str,
               fired: Mapping[str, bool]) -> dict[str, Any]:
    bar = series.allk[j]
    entry = float(bar[4])
    return {
        "source": source, "symbol": symbol, "side": side, "rule": rule, "tags": list(tags),
        "chg_24h": chg_24h, "chg_3d": chg_3d, "chg_5d": chg_5d,
        "entry_bar_ts": int(bar[0]), "entry_price": entry, "tp1_pct": tp1_for(chg_24h),
        "snapshot": entry_snapshot(series, j, side, chg_24h=chg_24h, tags=tags, fired=fired),
        "status": "OPEN", "version": VERSION,
    }


def manage_trade(trade: Mapping[str, Any], series: Series) -> dict[str, Any]:
    """진입 봉 **이후** 완성봉으로 두 엔진을 처음부터 다시 돌린다(상태 없음 = 백필과 같은 코드 경로).
    반환: {"status", "engines", "adds", "bars_seen", "mfe", "mae", "close_reason"}."""
    side = str(trade["side"])
    entry = float(trade["entry_price"])
    ets = int(trade["entry_bar_ts"])
    j = bisect.bisect_right([int(b[0]) for b in series.allk], ets) - 1     # 진입 봉 인덱스 (없으면 -1)
    if j < 0 or int(series.allk[j][0]) != ets:
        after = [b for b in series.allk if int(b[0]) > ets]
        j = None
        # Fix 361b: 진입 봉이 조회 창 밖이면(오래 열린 포지션 + 워커 중단) 진입 직후 봉이 빠져 손절·시간 만료를 잘못 판정한다
        #   → 닫지 않고 OPEN 유지 + gap 표시 (호출자가 로그). 창이 진입 다음 봉부터 이어질 때만 계산한다.
        if not after or int(after[0][0]) > ets + MS_15M:
            gap = (int(after[0][0]) - ets) // MS_15M - 1 if after else None
            return {"status": "OPEN", "engines": None, "adds": None, "bars_seen": 0, "mfe": 0.0, "mae": 0.0,
                    "close_reason": None, "exit_bars": 0, "gap_bars": gap}
    else:
        after = series.allk[j + 1:]
    house = run_house(side, entry, after)
    tp1 = float(trade.get("tp1_pct") or tp1_for(trade.get("chg_24h")))
    body_fn = None
    if j is not None:
        from app.services import candle_battle as CB

        def body_fn(i: int, _j: int = j) -> bool | None:      # i 번째 후속 봉까지의 몸통 성장
            return bool(CB.body_growth(series.allk[:_j + 2 + i], side, CB.DEFAULT_CFG)[0])
    live = run_live_like(side, entry, after, tp1_pct=tp1, hist=series.hist if j is not None else None,
                         hist_off=(j + 1) if j is not None else 0, body_fn=body_fn)
    adds = live.pop("adds")
    done = house["done"] and live["done"]
    exit_bars = max(int(house.get("bars") or 0) if house["done"] else 0,
                    (int(live["exit_bar"]) + 1) if live["done"] and live.get("exit_bar") is not None else 0)
    return {
        "status": "CLOSED" if done else "OPEN",
        "engines": {"house": house, "live": live},
        "adds": adds,
        "bars_seen": len(after),
        "exit_bars": exit_bars,                  # Fix 361b: 마지막 엔진이 끝난 봉(진입 뒤 n 번째) → closed_at 산정
        "mfe": max(float(house.get("mfe") or 0), float(live.get("mfe") or 0)),
        "mae": max(float(house.get("mae") or 0), float(live.get("mae") or 0)),
        "close_reason": (f"house={house['hit']} live={live['hit']}" if done else None),
    }


# ══════════════════════════════════════════════════════════════════════
# 백필: 학습 일지 한 행(pre15 200 + fwd 144 + 4h) 위에서 창 안 첫 발동 + 기준선을 같은 엔진으로
# ══════════════════════════════════════════════════════════════════════

def backfill_row(*, symbol: str, pre15: Sequence[Sequence[float]], pre4h: Sequence[Sequence[float]],
                 fwd15: Sequence[Sequence[float]], tags: Sequence[str], chg_24h: float | None,
                 chg_3d: float | None, chg_5d: float | None, window: int = 96,
                 rules: Sequence[Rule] = RULES) -> list[dict[str, Any]]:
    """한 심볼-일 → 가상 포지션 dict 목록(CLOSED, source=backfill). 규칙은 창 안 **첫 발동**만(일지와 동일), 기준선은 3h 마다."""
    if not pre15 or not fwd15:
        return []
    allk = [list(map(float, b[:6])) for b in pre15] + [list(map(float, b[:6])) for b in fwd15]
    k4h = [list(map(float, b[:6])) for b in pre4h] + aggregate([list(map(float, b[:6])) for b in fwd15], MS_4H)
    series = Series.build(allk, k4h)
    off = len(pre15)
    pending = {r.key: r.side for r in rules}
    out: list[dict[str, Any]] = []
    for i in range(min(window, len(fwd15) - 1)):
        j = off + i
        fired = evaluate_rules(series, j, rules=[r for r in rules if r.key in pending])
        for key, hit in fired.items():
            if not hit:
                continue
            side = BASELINE_KEYS.get(key) or pending.get(key)
            if side is None:
                continue
            t = open_trade(symbol=symbol, side=side, rule=key, series=series, j=j, tags=tags, chg_24h=chg_24h,
                           chg_3d=chg_3d, chg_5d=chg_5d, source="backfill", fired=fired)
            t.update(manage_trade(t, series))
            if t["status"] == "OPEN":                       # 봉이 모자라 미완 = 마지막 봉 종가로 마감 표시
                t["status"] = "CLOSED"
                t["close_reason"] = "END_OF_DATA"
                # Fix 361b: live 엔진(48h)은 일지 창(144봉)에 못 담긴다 → **검열(censored)** 표식. 보고서는 live 통계에서 뺀다.
                if t.get("engines") and not t["engines"]["live"].get("done"):
                    t["engines"]["live"]["hit"] = "END_OF_DATA"
            out.append(t)
            if key in pending:
                del pending[key]
    return out


# ══════════════════════════════════════════════════════════════════════
# 보고서 — 규칙×방향×자리×엔진 + 추가 변형 + CV + 채택 제안
# ══════════════════════════════════════════════════════════════════════

def _stat(rois: Sequence[float]) -> dict[str, Any]:
    if not rois:
        return {"n": 0, "mean": None, "win": None}
    return {"n": len(rois), "mean": round(statistics.fmean(rois), 3),
            "win": round(100 * sum(1 for x in rois if x > 0) / len(rois), 1)}


def _parity(sym: str) -> int:
    return sum(ord(ch) for ch in sym) % 2


def _cv(items: Sequence[tuple[str, str, float]], base: Sequence[tuple[str, str, float]]) -> dict[str, Any]:
    """items/base = (symbol, opened_iso, roi). 심볼 홀짝 × 시간 반쪽(전체 items 의 중앙 시각) 4조각의 Δ."""
    if not items:
        return {"all_positive": False}
    times = sorted(t for _, t, _ in items)
    mid = times[len(times) // 2]
    cv: dict[str, Any] = {}
    for name, pred in (("sym_even", lambda s, t: _parity(s) == 0), ("sym_odd", lambda s, t: _parity(s) == 1),
                       ("time_early", lambda s, t: t < mid), ("time_late", lambda s, t: t >= mid)):
        sub = [r for s, t, r in items if pred(s, t)]
        bsub = [r for s, t, r in base if pred(s, t)]
        st = _stat(sub)
        b = statistics.fmean(bsub) if bsub else None
        st["delta"] = round(st["mean"] - b, 3) if st["mean"] is not None and b is not None else None
        cv[name] = st
    deltas = [cv[k]["delta"] for k in ("sym_even", "sym_odd", "time_early", "time_late")]
    cv["all_positive"] = all(d is not None and d > 0 for d in deltas)
    return cv


def build_report(trades: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """trades = CLOSED 가상 포지션 dict 목록 (source 혼합 가능; 보고서는 source 별로도 나눈다)."""
    closed = [t for t in trades if t.get("status") == "CLOSED" and t.get("engines")]
    rep: dict[str, Any] = {"version": VERSION, "n": len(closed),
                           "sources": {s: sum(1 for t in closed if t.get("source") == s) for s in ("live", "backfill")},
                           "rules": {}, "adds": {}, "recommend": {"entries": [], "adds": []}}
    if not closed:
        return rep
    times = sorted(str(t.get("opened_at") or t.get("entry_bar_ts")) for t in closed)
    rep["period"] = {"from": times[0], "to": times[-1]}
    rule_side = {r.key: r.side for r in RULES}
    rule_side.update(BASELINE_KEYS)

    def _items(pred, engine):
        # Fix 361b: 끝까지 간 결과만 (live 엔진의 END_OF_DATA 검열 표본은 제외 — 백필/실시간 비교 가능성)
        return [(t["symbol"], str(t.get("opened_at") or t.get("entry_bar_ts")), float(t["engines"][engine]["roi"]))
                for t in closed if pred(t) and t["engines"].get(engine) and t["engines"][engine].get("roi") is not None
                and t["engines"][engine].get("done", True)]
    rep["censored_live"] = sum(1 for t in closed if t["engines"].get("live") and not t["engines"]["live"].get("done", True))

    for key in list(rule_side):
        side = rule_side[key]
        rep["rules"][key] = {"side": side, "groups": {}}
        for g in GROUP_KEYS:
            gg: dict[str, Any] = {}
            for eng in ("house", "live"):
                it = _items(lambda t: t["rule"] == key and g in group_of(t.get("tags") or []), eng)
                bs = _items(lambda t: t["rule"] == f"baseline_{side}" and g in group_of(t.get("tags") or []), eng)
                st = _stat([r for _, _, r in it])
                b = statistics.fmean([r for _, _, r in bs]) if bs else None
                st["baseline"] = round(b, 3) if b is not None else None
                st["delta"] = round(st["mean"] - b, 3) if st["mean"] is not None and b is not None else None
                st["cv"] = _cv(it, bs)
                st["hits"] = {}
                for t in closed:
                    if t["rule"] == key and g in group_of(t.get("tags") or []):
                        hk = str(t["engines"].get(eng, {}).get("hit"))
                        st["hits"][hk] = st["hits"].get(hk, 0) + 1
                gg[eng] = st
                if (key not in BASELINE_KEYS and st["n"] >= ADOPT_MIN_N and st["delta"] is not None
                        and st["delta"] > 0 and st["cv"].get("all_positive")):
                    rep["recommend"]["entries"].append({"rule": key, "side": side, "group": g, "engine": eng,
                                                        "n": st["n"], "mean": st["mean"], "delta": st["delta"]})
            rep["rules"][key]["groups"][g] = gg

    # 추가 변형: lot 단위 (실매매 추가 188건 포렌식과 같은 귀속 = lot 자체의 ROI/USDT)
    for var in VARIANTS:
        rep["adds"][var] = {}
        for side in ("LONG", "SHORT"):
            lots = []
            for t in closed:
                if t["side"] != side or t["rule"] in BASELINE_KEYS:
                    continue
                for lot in (t.get("adds") or {}).get(var, []):
                    if lot.get("roi") is not None:
                        lots.append((t["symbol"], str(t.get("opened_at") or t.get("entry_bar_ts")), float(lot["roi"]),
                                     float(lot.get("pnl_usdt") or 0), t["rule"]))
            st = _stat([r for _, _, r, _, _ in lots])
            st["pnl_usdt"] = round(sum(p for _, _, _, p, _ in lots), 2)
            st["cv"] = _cv([(s, tm, r) for s, tm, r, _, _ in lots], [(s, tm, 0.0) for s, tm, r, _, _ in lots])
            st["by_rule"] = {}
            for rk in sorted({x[4] for x in lots}):
                sub = [r for s, tm, r, p, r2 in lots if r2 == rk]
                st["by_rule"][rk] = _stat(sub)
            rep["adds"][var][side] = st
            if st["n"] >= ADOPT_MIN_N and st["mean"] is not None and st["mean"] > 0 and st["cv"].get("all_positive"):
                rep["recommend"]["adds"].append({"variant": var, "side": side, "n": st["n"], "mean": st["mean"],
                                                 "pnl_usdt": st["pnl_usdt"]})
    return rep


def _f(x: Any, nd: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x:+.{nd}f}" if isinstance(x, float) else str(x)


def render_markdown(rep: Mapping[str, Any], *, min_n: int = 15) -> str:
    L: list[str] = []
    L.append(f"# 가상 매매 학습 보고서 (Fix 361) — 가상 포지션 {rep.get('n')}건 "
             f"(실시간 {rep.get('sources', {}).get('live', 0)} / 백필 {rep.get('sources', {}).get('backfill', 0)})")
    p = rep.get("period") or {}
    L.append(f"기간 {p.get('from')} ~ {p.get('to')}. 잣대: 레버 2 · house = SL −5%/TP +15%/12h · live = SL −{LIVE_SL_ROI:g}% → TP1(3/15%) 25% → "
             f"트레일링 5%p → 48h. 추가 lot 300 USDT, 자기 손절 −{LIVE_SL_ROI:g}%. CV = 심볼 홀짝 × 시간 반쪽. 채택 = CV 4/4 · n≥{ADOPT_MIN_N} · Δ>0.")
    L.append("")
    if rep.get("censored_live"):
        L.append(f"⚠️ live 엔진 검열 표본 {rep['censored_live']}건(백필 창 144봉 < 48h) 은 live 통계·채택에서 제외. house 엔진은 전부 완결.")
        L.append("")
    rec = rep.get("recommend") or {}
    L.append("## 0. 지금 채택 문턱을 넘는 것 (실 운영 재개 시 켤 후보)")
    if rec.get("entries"):
        for e in rec["entries"]:
            L.append(f"- 진입 **{e['rule']}** {e['side']} · {e['group']} · {e['engine']}: n={e['n']} 평균 {_f(e['mean'])} Δ{_f(e['delta'])}")
    else:
        L.append("- 진입: 아직 없음")
    if rec.get("adds"):
        for a in rec["adds"]:
            L.append(f"- 추가 **{a['variant']}** {a['side']}: lot n={a['n']} 평균 {_f(a['mean'])} 합 {_f(a['pnl_usdt'])} USDT")
    else:
        L.append("- 추가: 아직 없음")
    L.append("")
    for eng in ("house", "live"):
        L.append(f"## 진입 규칙 — {eng} 엔진 (자리별 · n≥{min_n}만 표시)")
        L.append("| 규칙 | 방향 | 자리 | n | 평균 ROI | 승률 | 기준선 | Δ | CV(짝/홀/전/후) | 종료 |")
        L.append("|---|---|---|---:|---:|---:|---:|---:|---|---|")
        for key, rd in (rep.get("rules") or {}).items():
            for g, gg in rd["groups"].items():
                st = gg.get(eng) or {}
                if (st.get("n") or 0) < min_n:
                    continue
                cv = st.get("cv") or {}
                cvs = "/".join(_f((cv.get(k) or {}).get("delta")) for k in ("sym_even", "sym_odd", "time_early", "time_late"))
                mark = " ✅" if cv.get("all_positive") and (st.get("delta") or 0) > 0 else ""
                hits = " ".join(f"{k}{v}" for k, v in sorted((st.get("hits") or {}).items()))
                L.append(f"| {key} | {rd['side']} | {g} | {st['n']} | {_f(st['mean'])} | {_f(st.get('win'), 1)}% | "
                         f"{_f(st.get('baseline'))} | {_f(st.get('delta'))}{mark} | {cvs} | {hits} |")
        L.append("")
    L.append("## 추가(피라미딩) 변형 — lot 단위 (live 엔진 위)")
    L.append("| 변형 | 방향 | lot n | 평균 lot ROI | 승률 | 합 USDT | CV(짝/홀/전/후) | 규칙별 |")
    L.append("|---|---|---:|---:|---:|---:|---|---|")
    for var, vd in (rep.get("adds") or {}).items():
        for side, st in vd.items():
            if not st.get("n"):
                continue
            cv = st.get("cv") or {}
            cvs = "/".join(_f((cv.get(k) or {}).get("mean")) for k in ("sym_even", "sym_odd", "time_early", "time_late"))
            br = ", ".join(f"{k} {v['n']}:{_f(v['mean'])}" for k, v in (st.get("by_rule") or {}).items() if v.get("n"))
            L.append(f"| {var} | {side} | {st['n']} | {_f(st['mean'])} | {_f(st.get('win'), 1)}% | {_f(st.get('pnl_usdt'))} | {cvs} | {br} |")
    L.append("")
    L.append("변형: live = 현행(SHORT·ROI≥5·이동≥3%·15m hist 3봉 가속) / live_both = LONG 허용 / after_tp1 = 익절 뒤에만 / "
             "body = +캔들 몸통(G3A) / noind = 지표 조건 없음.")
    return "\n".join(L)

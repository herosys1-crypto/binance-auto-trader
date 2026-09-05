"""📚 차트 학습 일지 — 상승 50위·하락 50위(+3·5일 순위) 차트를 매일 저장하고 결과를 라벨링한다 (Fix 353).

## 사장님 지시 (2026-09-05)

  "상승 50위 하락 50위 심볼을 차트를 우리가 필요한 시스템로직을 위해서 분석학습 할 수 있을까?
   상세하게 분석해서 적용할수 있게 한번에 어려우면 할수 있는 만큼씩 매일 매일 나눠서 학습을 해줘"

  "시스템로직은 첫번째 진입이 실패했을때 좋은 자리에서 포지션 진입부터 승부를 하고
   처음부터 승리하면 포지션 추가로 수익을 만들어 가는거야
   실패했을 손실을 최소화하고 다시 포지션 진입하는 로직이야"

## 왜 이 모듈이 필요한가

지금까지의 학습은 전부 「**지금** 급등락 중인 종목의 최근 5일 15m 을 다시 받아 한 번에 재는」 방식이었다.
한계 두 가지:
  ① 감시 대상이 **지금** 기준으로 뽑혀 과거 봉에 미래가 붙는다 (9/3 에 같은 함정을 4번 잡았다).
  ② 15m 은 500봉(5일)뿐이라 표본이 매번 같은 며칠이다. 9/3 판정식(`chart_events.py`)은
     그래서 호출처 0곳으로 남아 있다 — 검증할 새 표본이 없었다.
→ 매일 감시 대상(당일·3일·5일 순위)이 **그 시각 기준으로** 저장되고 36시간 뒤 결과가 라벨링되면,
  표본이 매일 200~300 심볼-일씩 쌓이고 미래참조가 **구조적으로** 불가능하다.

## 세 결정점 (사장님 사상) — 학습이 답해야 하는 질문

  ① 첫 진입 자리        : 어느 규칙이 기준선(같은 창의 무작위 봉)보다 낫나
  ② 이겼을 때 추가 자리 : 첫 진입이 이기고 있을 때 어디서 얹으면 이어지나
  ③ 졌을 때 손실 최소화 → 다시 진입 자리 : 첫 진입이 손절된 뒤 진짜 자리는 어디였나

Day 1 은 ① 과 「자리의 값」(정점·저점까지 시간, 정점 뒤 낙폭)을 잰다. ②③ 은 라벨이 쌓이면
(docs/learning/CHART_LEARNING_CURRICULUM.md). **규칙 채택은 사람이 한다** — 이 모듈은 재기만 한다.

## 숫자 (Claude 가 정함 — 전부 상수/설정키)

  레버 2 / SL −5% ROI / TP +15% ROI / 12h 지평 = 9/3 이후 모든 측정과 같은 잣대.
  창 24h(96봉) / 스냅샷 전 15m 200봉(50h, 1h 파생용) + 4h 61봉 / 원시 봉 보존 45일.
"""
from __future__ import annotations

import bisect
import logging
import statistics
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable, Mapping, Sequence

logger = logging.getLogger(__name__)

FIX = "Fix353"

# ── 설정키 ──────────────────────────────────────────────────────────────
SETTING_ENABLED = "chart_learning_enabled"               # 기본 ON
SETTING_SNAPSHOT_HOURS = "chart_learning_snapshot_hours"  # 기본 "0" (UTC 시각, 쉼표 구분). 스케줄은 0·12시에 깨어나 이 값을 본다
SETTING_TOP_N = "chart_learning_top_n"                   # 기본 50 (사장님 「50위」)
SETTING_KEEP_DAYS = "chart_learning_keep_days"           # 원시 봉 보존 일수, 기본 45 (라벨은 영구)
SETTING_OUTCOME_BATCH = "chart_learning_outcome_batch"   # 시간당 라벨링 상한, 기본 400

# ── 측정 잣대 ────────────────────────────────────────────────────────────
LEV = 2.0
SL_PRICE = 0.025          # 가격 −2.5% = ROI −5%
TP_PRICE = 0.075          # 가격 +7.5% = ROI +15%
HORIZON = 48              # 12h (15m 봉)
WINDOW = 96               # 24h — 규칙 첫 충족을 찾는 창
FWD_BARS = WINDOW + HORIZON   # 144 = 36h
PRE_15M = 200
PRE_4H = 61
BASELINE_STEP = 12        # 창 안 3시간마다 1봉 = 심볼-일당 8개 기준선 진입
MS_15M = 900_000
MS_1H = 3_600_000
MS_4H = 14_400_000
MS_DAY = 86_400_000
LABEL_VERSION = 1


# ══════════════════════════════════════════════════════════════════════
# 설정
# ══════════════════════════════════════════════════════════════════════

def _setting(db: Any, key: str) -> str | None:
    if db is None:
        return None
    try:
        from app.models.system_setting import SystemSetting
        row = db.get(SystemSetting, key)
        if row is None or row.value is None:
            return None
        v = str(row.value).strip()
        return v or None
    except Exception as e:  # noqa: BLE001
        logger.warning("[%s] %s 조회 실패 → 기본값: %s", FIX, key, e)
        return None


def enabled(db: Any) -> bool:
    v = _setting(db, SETTING_ENABLED)
    return True if v is None else v.lower() in ("1", "true", "on", "yes")


def _int(db: Any, key: str, default: int, lo: int, hi: int) -> int:
    v = _setting(db, key)
    try:
        return max(lo, min(hi, int(float(v)))) if v is not None else default
    except (TypeError, ValueError):
        return default


def top_n(db: Any) -> int:
    return _int(db, SETTING_TOP_N, 50, 5, 200)


def keep_days(db: Any) -> int:
    return _int(db, SETTING_KEEP_DAYS, 45, 7, 3650)


def outcome_batch(db: Any) -> int:
    return _int(db, SETTING_OUTCOME_BATCH, 400, 10, 20000)


def snapshot_hours(db: Any) -> set[int]:
    v = _setting(db, SETTING_SNAPSHOT_HOURS) or "0"
    out: set[int] = set()
    for tok in v.replace(";", ",").split(","):
        tok = tok.strip()
        if tok.isdigit() and 0 <= int(tok) <= 23:
            out.add(int(tok))
    return out or {0}


# ══════════════════════════════════════════════════════════════════════
# 캔들 처리 — 6필드 [open_time, o, h, l, c, v] 로 통일
# ══════════════════════════════════════════════════════════════════════

def compact(kl: Sequence[Sequence[Any]] | None, *, now_ms: int | None = None,
            interval_ms: int = MS_15M) -> list[list[float]]:
    """바이낸스 12필드/6필드 → 6필드 float. `now_ms` 를 주면 그 시각에 **아직 안 닫힌 봉을 뺀다**."""
    out: list[list[float]] = []
    for k in kl or []:
        try:
            t = int(k[0])
            o, h, l, c, v = float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])
        except (TypeError, ValueError, IndexError):
            continue
        if now_ms is not None and t + interval_ms > now_ms:
            continue
        out.append([t, o, h, l, c, v])
    return out


def aggregate(kl: Sequence[Sequence[float]], step_ms: int, *, src_ms: int = MS_15M) -> list[list[float]]:
    """15m 6필드 → 상위 주기(1h/4h) 6필드. **완전한 그룹만**(봉 수가 정확히 맞는 것) 돌려준다."""
    need = step_ms // src_ms
    groups: dict[int, list[float]] = {}
    order: list[int] = []
    for t, o, h, l, c, v in kl:
        g = (int(t) // step_ms) * step_ms
        a = groups.get(g)
        if a is None:
            groups[g] = [g, o, h, l, c, v, 1]
            order.append(g)
        else:
            a[2] = max(a[2], h)
            a[3] = min(a[3], l)
            a[4] = c
            a[5] += v
            a[6] += 1
    return [groups[g][:6] for g in order if groups[g][6] == need]


# ══════════════════════════════════════════════════════════════════════
# 지표 (전부 인과적 — i 번째 값은 i 까지의 봉만 쓴다)
# ══════════════════════════════════════════════════════════════════════

def ema(v: Sequence[float], n: int) -> list[float]:
    if not v:
        return []
    k = 2.0 / (n + 1)
    out = [float(v[0])]
    for x in v[1:]:
        out.append(out[-1] + k * (float(x) - out[-1]))
    return out


def macd_hist(c: Sequence[float]) -> list[float]:
    if len(c) < 35:
        return [0.0] * len(c)
    m = [a - b for a, b in zip(ema(c, 12), ema(c, 26))]
    s = ema(m, 9)
    return [a - b for a, b in zip(m, s)]


def rsi(c: Sequence[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(c)
    if len(c) <= n:
        return out
    g = l = 0.0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]
        g += max(d, 0.0)
        l += max(-d, 0.0)
    ag, al = g / n, l / n
    out[n] = 100.0 - 100.0 / (1.0 + (ag / al if al else 1e9))
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        ag = (ag * (n - 1) + max(d, 0.0)) / n
        al = (al * (n - 1) + max(-d, 0.0)) / n
        out[i] = 100.0 - 100.0 / (1.0 + (ag / al if al else 1e9))
    return out


def obv(c: Sequence[float], v: Sequence[float]) -> list[float]:
    out = [0.0]
    for i in range(1, len(c)):
        out.append(out[-1] + (v[i] if c[i] > c[i - 1] else -v[i] if c[i] < c[i - 1] else 0.0))
    return out


def pctb(c: Sequence[float], i: int, n: int = 20) -> float | None:
    if i + 1 < n:
        return None
    w = c[i - n + 1:i + 1]
    m = sum(w) / n
    sd = (sum((x - m) ** 2 for x in w) / n) ** 0.5
    return (c[i] - (m - 2 * sd)) / (4 * sd) if sd else 0.5


# ══════════════════════════════════════════════════════════════════════
# 결과 시뮬 — 9/3 이후 모든 측정과 같은 잣대
# ══════════════════════════════════════════════════════════════════════

def sim(side: str, entry: float, bars: Sequence[Sequence[float]], *, horizon: int = HORIZON) -> dict[str, Any]:
    """진입가 `entry`, 그 다음 봉부터 `bars` 를 훑어 SL(−5% ROI) → TP(+15% ROI) → 시간 만료 순으로 판정.
    SL 을 먼저 보는 것은 보수적 가정(같은 봉에서 둘 다 닿으면 손절로 친다)."""
    if entry <= 0:
        return {"roi": 0.0, "hit": "NA", "bars": 0, "mfe": 0.0, "mae": 0.0}
    long = side == "LONG"
    sl = entry * (1 - SL_PRICE) if long else entry * (1 + SL_PRICE)
    tp = entry * (1 + TP_PRICE) if long else entry * (1 - TP_PRICE)
    mfe = mae = 0.0
    n = 0
    last = entry
    for b in bars[:horizon]:
        n += 1
        h, l, last = b[2], b[3], b[4]
        fav = (h / entry - 1) if long else (1 - l / entry)
        adv = (1 - l / entry) if long else (h / entry - 1)
        mfe = max(mfe, fav)
        mae = max(mae, adv)
        if (long and l <= sl) or (not long and h >= sl):
            return {"roi": round(-SL_PRICE * 100 * LEV, 4), "hit": "SL", "bars": n,
                    "mfe": round(mfe * 100, 4), "mae": round(mae * 100, 4)}
        if (long and h >= tp) or (not long and l <= tp):
            return {"roi": round(TP_PRICE * 100 * LEV, 4), "hit": "TP", "bars": n,
                    "mfe": round(mfe * 100, 4), "mae": round(mae * 100, 4)}
    roi = (last / entry - 1) * 100 * LEV * (1 if long else -1)
    return {"roi": round(roi, 4), "hit": "TIME" if n else "NA", "bars": n,
            "mfe": round(mfe * 100, 4), "mae": round(mae * 100, 4)}


# ══════════════════════════════════════════════════════════════════════
# 규칙 레지스트리 — ① 첫 진입 자리 후보. 시스템 규칙 + 후보 규칙
# ══════════════════════════════════════════════════════════════════════

@dataclass
class RuleCtx:
    """창 안 i 번째 완성봉에서의 판정 재료. 전부 그 봉까지의 데이터만 담는다."""
    j: int                              # 전체 15m 배열에서의 인덱스
    c: Sequence[float]
    h: Sequence[float]
    l: Sequence[float]
    v: Sequence[float]
    hist: Sequence[float]
    rsi14: Sequence[float | None]
    obv: Sequence[float]
    kl15: list[list[float]]             # j 까지 (꼬리 260봉)
    kl1h: list[list[float]]             # j 봉 마감 시각까지 닫힌 1h (꼬리 60)
    kl4h: list[list[float]]             # j 봉 마감 시각까지 닫힌 4h (꼬리 60)


@dataclass(frozen=True)
class Rule:
    key: str
    side: str
    label: str
    origin: str                          # "system" = 지금 코드에 있는 판정 / "candidate" = 후보
    fn: Callable[[RuleCtx], bool]


_CFG = None


def _cfg():
    global _CFG
    if _CFG is None:
        from app.services.chart_events import Thresholds
        _CFG = Thresholds()
    return _CFG


def _r_toprev_331(ctx: RuleCtx) -> bool:
    from app.services.chart_events import is_top_reversal
    ok, _, d = is_top_reversal(ctx.kl15, ctx.kl4h, kl_1h=ctx.kl1h, trim=False, cfg=_cfg())
    return bool(ok and d.get("decided"))


def _r_pullback_331(ctx: RuleCtx) -> bool:
    from app.services.chart_events import is_pullback_entry
    ok, _, d = is_pullback_entry(ctx.kl15, ctx.kl4h, trim=False, cfg=_cfg())
    return bool(ok and d.get("decided"))


def _r_bottom_331(ctx: RuleCtx) -> bool:
    from app.services.chart_events import is_bottom_reversal
    ok, _, d = is_bottom_reversal(ctx.kl15, ctx.kl4h, trim=False, cfg=_cfg())
    return bool(ok and d.get("decided"))


def _r_surge_start_346(ctx: RuleCtx) -> bool:
    from app.services.momentum_phase import classify_surge_start
    j = ctx.j
    ok, _ = classify_surge_start(list(ctx.c[max(0, j - 119):j + 1]), list(ctx.v[max(0, j - 119):j + 1]))
    return bool(ok)


def _r_multiday_rebound_352(ctx: RuleCtx) -> bool:
    from app.services.multiday_movers import is_pullback_rebound
    j = ctx.j
    ok, _ = is_pullback_rebound(list(ctx.c[max(0, j - 39):j + 1]))
    return bool(ok)


def _r_l1_hist_turn_up(ctx: RuleCtx) -> bool:
    H, j = ctx.hist, ctx.j
    return j >= 2 and H[j] > H[j - 1] > H[j - 2] and H[j - 2] < 0


def _r_s2_hist_turn_down(ctx: RuleCtx) -> bool:
    H, j, c, h = ctx.hist, ctx.j, ctx.c, ctx.h
    return j >= 8 and H[j - 1] > 0 and H[j] < H[j - 1] < H[j - 2] and c[j] < max(h[j - 8:j])


def _r_s1_breakdown(ctx: RuleCtx) -> bool:
    H, j, c = ctx.hist, ctx.j, ctx.c
    return j >= 19 and H[j] < H[j - 1] < H[j - 2] and c[j] <= min(c[j - 19:j + 1])


RULES: tuple[Rule, ...] = (
    Rule("toprev_331", "SHORT", "정점 반전 (chart_events 9/3, 미배선)", "system", _r_toprev_331),
    Rule("s2_hist_turn_down", "SHORT", "반등 뒤 hist 꺾임 + 신고점 실패", "candidate", _r_s2_hist_turn_down),
    Rule("s1_breakdown", "SHORT", "hist 2봉 하락 + 20봉 신저점", "candidate", _r_s1_breakdown),
    Rule("pullback_331", "LONG", "상승 중 조정 (chart_events 9/3, 미배선)", "system", _r_pullback_331),
    Rule("bottom_331", "LONG", "저점 반전 (chart_events 9/3, 미배선)", "system", _r_bottom_331),
    Rule("surge_start_346", "LONG", "상승 초입 (Fix 346 배선됨)", "system", _r_surge_start_346),
    Rule("multiday_rebound_352", "LONG", "RSI14<35 뒤 첫 상승 마감 (Fix 352 배선됨)", "system", _r_multiday_rebound_352),
    Rule("l1_hist_turn_up", "LONG", "hist 2봉 상승 전환 (0 아래)", "candidate", _r_l1_hist_turn_up),
)


# ══════════════════════════════════════════════════════════════════════
# 라벨링 — 스냅샷 전 봉 + 그 뒤 36h 봉 → 「자리의 값」 + 규칙 첫 충족 결과
# ══════════════════════════════════════════════════════════════════════

def _stats_from(entry: float, bars: Sequence[Sequence[float]]) -> tuple[float, int, float, int]:
    hi = max((b[2] for b in bars), default=entry)
    lo = min((b[3] for b in bars), default=entry)
    hi_i = next((i for i, b in enumerate(bars) if b[2] == hi), 0)
    lo_i = next((i for i, b in enumerate(bars) if b[3] == lo), 0)
    return hi, hi_i, lo, lo_i


def label_row(pre15: Sequence[Sequence[float]], pre4h: Sequence[Sequence[float]],
              fwd15: Sequence[Sequence[float]], *, rules: Sequence[Rule] = RULES) -> dict[str, Any]:
    """한 심볼-일의 라벨. 모든 값은 완성봉만 쓰고, 규칙은 창(24h) 안 첫 충족 봉의 종가 진입으로 잰다."""
    pre15 = [list(b) for b in pre15]
    fwd15 = [list(b) for b in fwd15]
    if not pre15 or not fwd15:
        return {"version": LABEL_VERSION, "error": "봉 없음"}
    entry = float(pre15[-1][4])
    win = fwd15[:WINDOW]
    out: dict[str, Any] = {"version": LABEL_VERSION, "entry_price": entry,
                           "n_fwd": len(fwd15), "window_bars": len(win)}

    # 자리의 값 — 창 안 정점/저점과 그 뒤 12h 의 낙폭/반등폭
    hi, hi_i, lo, lo_i = _stats_from(entry, win)
    after_peak = fwd15[hi_i + 1:hi_i + 1 + HORIZON]
    after_trough = fwd15[lo_i + 1:lo_i + 1 + HORIZON]
    out["peak"] = {"bar": hi_i, "hours": round((hi_i + 1) * 0.25, 2), "pct": round((hi / entry - 1) * 100, 4),
                   "drop_after_pct": round((min((b[3] for b in after_peak), default=hi) / hi - 1) * 100, 4)}
    out["trough"] = {"bar": lo_i, "hours": round((lo_i + 1) * 0.25, 2), "pct": round((lo / entry - 1) * 100, 4),
                     "rise_after_pct": round((max((b[2] for b in after_trough), default=lo) / lo - 1) * 100, 4)}
    out["at_snapshot"] = {"LONG": sim("LONG", entry, fwd15), "SHORT": sim("SHORT", entry, fwd15)}
    base: dict[str, list[float]] = {"LONG": [], "SHORT": []}
    for i in range(0, len(win), BASELINE_STEP):
        e = float(win[i][4])
        base["LONG"].append(sim("LONG", e, fwd15[i + 1:])["roi"])
        base["SHORT"].append(sim("SHORT", e, fwd15[i + 1:])["roi"])
    out["baseline"] = base

    # 규칙 — 전체 15m 배열 위에서 인과 지표를 한 번만 계산
    allk = pre15 + fwd15
    c = [b[4] for b in allk]
    h = [b[2] for b in allk]
    l = [b[3] for b in allk]
    v = [b[5] for b in allk]
    H = macd_hist(c)
    R = rsi(c)
    O = obv(c, v)
    k1h = aggregate(allk, MS_1H)
    k4h = list(pre4h) + aggregate(fwd15, MS_4H)
    close1h = [int(b[0]) + MS_1H for b in k1h]
    close4h = [int(b[0]) + MS_4H for b in k4h]
    off = len(pre15)
    pending = {r.key: r for r in rules}
    fired: dict[str, Any] = {r.key: None for r in rules}
    for i in range(len(win)):
        if not pending:
            break
        j = off + i
        close_ms = int(allk[j][0]) + MS_15M
        n1 = bisect.bisect_right(close1h, close_ms)
        n4 = bisect.bisect_right(close4h, close_ms)
        ctx = RuleCtx(j=j, c=c, h=h, l=l, v=v, hist=H, rsi14=R, obv=O,
                      kl15=allk[max(0, j - 259):j + 1], kl1h=k1h[max(0, n1 - 60):n1], kl4h=k4h[max(0, n4 - 60):n4])
        for key, rule in list(pending.items()):
            try:
                hit = bool(rule.fn(ctx))
            except Exception as e:  # noqa: BLE001
                logger.debug("[%s] 규칙 %s 실패 (bar %d): %s", FIX, key, i, e)
                hit = False
            if hit:
                e = float(c[j])
                res = sim(rule.side, e, fwd15[i + 1:])
                fired[key] = {"bar": i, "hours": round((i + 1) * 0.25, 2), "price": e,
                              "move_pct": round((e / entry - 1) * 100, 4), **res}
                del pending[key]
    out["rules"] = fired
    return out


# ══════════════════════════════════════════════════════════════════════
# 스냅샷 시점 지표 (기록용 — 나중에 「어떤 상태의 종목이 이기나」를 가르는 축)
# ══════════════════════════════════════════════════════════════════════

def snapshot_indicators(pre15: Sequence[Sequence[float]], pre4h: Sequence[Sequence[float]]) -> dict[str, Any]:
    d: dict[str, Any] = {}
    try:
        c = [b[4] for b in pre15]
        v = [b[5] for b in pre15]
        if len(c) >= 40:
            H = macd_hist(c)
            R = rsi(c)
            d["hist_15m"] = [round(x, 8) for x in H[-3:]]
            d["rsi14_15m"] = round(R[-1], 2) if R[-1] is not None else None
            pb = pctb(c, len(c) - 1)
            d["pctb_15m"] = round(pb, 4) if pb is not None else None
            m20 = sum(v[-21:-1]) / 20 if len(v) >= 21 else None
            d["vol_ratio_15m"] = round(v[-1] / m20, 3) if m20 else None
            hi24 = max(b[2] for b in pre15[-96:])
            lo24 = min(b[3] for b in pre15[-96:])
            d["dist_high24_pct"] = round((c[-1] / hi24 - 1) * 100, 4)
            d["dist_low24_pct"] = round((c[-1] / lo24 - 1) * 100, 4)
        c4 = [b[4] for b in pre4h]
        if len(c4) >= 40:
            H4 = macd_hist(c4)
            d["hist_4h"] = [round(x, 8) for x in H4[-2:]]
            e20 = ema(c4, 20)[-1]
            e50 = ema(c4, 50)[-1] if len(c4) >= 50 else None
            d["ema_4h_bull"] = bool(e20 > e50) if e50 is not None else None
            hi5d = max(b[2] for b in pre4h[-30:])
            lo5d = min(b[3] for b in pre4h[-30:])
            d["dist_high5d_pct"] = round((c4[-1] / hi5d - 1) * 100, 4)
            d["dist_low5d_pct"] = round((c4[-1] / lo5d - 1) * 100, 4)
    except Exception as e:  # noqa: BLE001
        d["error"] = str(e)[:120]
    return d


# ══════════════════════════════════════════════════════════════════════
# 감시 대상 태그 — 당일 UP/DOWN + 3·5일 UP3D/UP5D/DOWN3D/DOWN5D (한 심볼에 여러 태그)
# ══════════════════════════════════════════════════════════════════════

def tag_universe(chg24: Mapping[str, float], qvol: Mapping[str, float],
                 rets: Mapping[str, tuple[float | None, float | None]], *, n: int,
                 min_quote_volume: float) -> dict[str, dict[str, Any]]:
    """{symbol: {"tags": [...], "ranks": {...}}} — 당일 상승/하락 N위 ∪ 3·5일 상승/하락 N위.
    `chg24` 는 % 단위. 거래대금 하한은 당일 순위에만 건다(다일 순위는 multiday_movers 와 같은 규칙)."""
    from app.services.multiday_movers import rank_symbols
    pool = [s for s in chg24 if qvol.get(s, 0.0) >= min_quote_volume]
    ranked = sorted(pool, key=lambda s: chg24[s], reverse=True)
    out: dict[str, dict[str, Any]] = {}

    def _add(sym: str, tag: str, rank: int) -> None:
        e = out.setdefault(sym, {"tags": [], "ranks": {}})
        if tag not in e["tags"]:
            e["tags"].append(tag)
        e["ranks"][tag] = rank

    for i, s in enumerate(ranked[:n], start=1):
        _add(s, "UP", i)
    for i, s in enumerate(list(reversed(ranked[-n:])) if ranked else [], start=1):
        if "UP" not in out.get(s, {}).get("tags", []):      # 심볼이 적어 양쪽에 걸리면 상승 쪽만
            _add(s, "DOWN", i)
    md = rank_symbols({s: r for s, r in rets.items() if qvol.get(s, 0.0) >= min_quote_volume}, n)
    for s, info in md.items():
        for tag in ("UP3D", "UP5D", "DOWN3D", "DOWN5D"):
            if info.get(tag):
                _add(s, tag, int(info[tag]))
    return out


# ══════════════════════════════════════════════════════════════════════
# 보고서 — 자리(태그 그룹)별 기준선 + 규칙별 결과 + 교차검증
# ══════════════════════════════════════════════════════════════════════

GROUPS: tuple[tuple[str, str, Callable[[set[str]], bool]], ...] = (
    ("ALL", "전체", lambda t: True),
    ("UP24", "당일 상승 50", lambda t: "UP" in t),
    ("DOWN24", "당일 하락 50", lambda t: "DOWN" in t),
    ("UP35", "3·5일 상승 50", lambda t: bool(t & {"UP3D", "UP5D"})),
    ("DOWN35", "3·5일 하락 50", lambda t: bool(t & {"DOWN3D", "DOWN5D"})),
    ("UP35_DOWN24", "며칠 상승 + 당일 하락 (조정)", lambda t: bool(t & {"UP3D", "UP5D"}) and "DOWN" in t),
    ("UP35_UP24", "며칠 상승 + 당일 상승 (연장)", lambda t: bool(t & {"UP3D", "UP5D"}) and "UP" in t),
    ("DOWN35_DOWN24", "며칠 하락 + 당일 하락 (연속 급락)", lambda t: bool(t & {"DOWN3D", "DOWN5D"}) and "DOWN" in t),
)


def _stat(rois: Sequence[float]) -> dict[str, Any]:
    if not rois:
        return {"n": 0, "mean": None, "win": None, "tp": None, "sl": None}
    n = len(rois)
    return {"n": n, "mean": round(statistics.fmean(rois), 3),
            "win": round(100 * sum(1 for x in rois if x > 0) / n, 1),
            "tp": round(100 * sum(1 for x in rois if x >= TP_PRICE * 100 * LEV - 0.01) / n, 1),
            "sl": round(100 * sum(1 for x in rois if x <= -SL_PRICE * 100 * LEV + 0.01) / n, 1)}


def _median(xs: Sequence[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def _mean(xs: Sequence[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 3) if xs else None


def _parity(symbol: str) -> int:
    return sum(ord(ch) for ch in symbol) % 2


def build_report(rows: Sequence[Mapping[str, Any]], *, rules: Sequence[Rule] = RULES) -> dict[str, Any]:
    """rows: {symbol, snap_date, tags, source, outcome}. outcome 이 없는 행은 뺀다."""
    done = [r for r in rows if isinstance(r.get("outcome"), Mapping) and r["outcome"].get("rules") is not None]
    dates = sorted({str(r["snap_date"]) for r in done})
    half = dates[len(dates) // 2] if dates else None
    rep: dict[str, Any] = {"version": LABEL_VERSION, "rows": len(done), "rows_total": len(rows),
                           "dates": {"from": dates[0] if dates else None, "to": dates[-1] if dates else None,
                                     "n": len(dates)},
                           "sources": {}, "groups": {}, "rules": {}, "cv": {}}
    for r in done:
        rep["sources"][str(r.get("source") or "?")] = rep["sources"].get(str(r.get("source") or "?"), 0) + 1
    rule_by_key = {r.key: r for r in rules}

    for gkey, glabel, pred in GROUPS:
        grp = [r for r in done if pred(set(r.get("tags") or []))]
        if not grp:
            continue
        base = {"LONG": [], "SHORT": []}
        snap = {"LONG": [], "SHORT": []}
        for r in grp:
            o = r["outcome"]
            for s in ("LONG", "SHORT"):
                base[s].extend(o.get("baseline", {}).get(s, []))
                snap[s].append(o.get("at_snapshot", {}).get(s, {}).get("roi"))
        g: dict[str, Any] = {
            "label": glabel, "n": len(grp), "symbols": len({r["symbol"] for r in grp}),
            "baseline": {s: _stat(base[s]) for s in base},
            "at_snapshot": {s: _stat([x for x in snap[s] if x is not None]) for s in snap},
            "peak_hours_med": _median([r["outcome"]["peak"]["hours"] for r in grp]),
            "peak_pct_mean": _mean([r["outcome"]["peak"]["pct"] for r in grp]),
            "drop_after_peak_mean": _mean([r["outcome"]["peak"]["drop_after_pct"] for r in grp]),
            "trough_hours_med": _median([r["outcome"]["trough"]["hours"] for r in grp]),
            "trough_pct_mean": _mean([r["outcome"]["trough"]["pct"] for r in grp]),
            "rise_after_trough_mean": _mean([r["outcome"]["trough"]["rise_after_pct"] for r in grp]),
            "rules": {},
        }
        for key, rule in rule_by_key.items():
            fired = [r["outcome"]["rules"].get(key) for r in grp]
            fired = [f for f in fired if f]
            st = _stat([f["roi"] for f in fired])
            b = g["baseline"][rule.side]["mean"]
            st.update(side=rule.side, fire_rate=round(100 * len(fired) / len(grp), 1),
                      hours_med=_median([f["hours"] for f in fired]),
                      delta=(round(st["mean"] - b, 3) if st["mean"] is not None and b is not None else None))
            g["rules"][key] = st
        rep["groups"][gkey] = g

    for key, rule in rule_by_key.items():
        rep["rules"][key] = {"side": rule.side, "label": rule.label, "origin": rule.origin}
        cv: dict[str, Any] = {}
        for name, pred in (("sym_even", lambda r: _parity(r["symbol"]) == 0),
                           ("sym_odd", lambda r: _parity(r["symbol"]) == 1),
                           ("date_early", lambda r: half is not None and str(r["snap_date"]) < half),
                           ("date_late", lambda r: half is not None and str(r["snap_date"]) >= half)):
            sub = [r for r in done if pred(r)]
            fired = [r["outcome"]["rules"].get(key) for r in sub]
            fired = [f for f in fired if f]
            st = _stat([f["roi"] for f in fired])
            b = _stat([x for r in sub for x in r["outcome"].get("baseline", {}).get(rule.side, [])])["mean"]
            st["delta"] = round(st["mean"] - b, 3) if st["mean"] is not None and b is not None else None
            cv[name] = st
        deltas = [cv[k]["delta"] for k in cv]
        cv["all_positive"] = bool(deltas) and all(d is not None and d > 0 for d in deltas)
        rep["cv"][key] = cv
    return rep


def _f(x: Any, nd: int = 2) -> str:
    if x is None:
        return "—"
    return f"{x:+.{nd}f}" if isinstance(x, float) and nd else str(x)


def render_markdown(rep: Mapping[str, Any], *, min_n: int = 15) -> str:
    L: list[str] = []
    d = rep.get("dates", {})
    L.append(f"# 차트 학습 일지 보고서 — {d.get('from')} ~ {d.get('to')} ({d.get('n')}일, 심볼-일 {rep.get('rows')}건, "
             f"출처 {rep.get('sources')})")
    L.append("")
    L.append("잣대: 레버 2 · SL −5% ROI · TP +15% ROI · 12h. 기준선 = 같은 24h 창 안 3시간마다 1봉(무작위 진입). "
             "규칙 = 창 안 첫 충족 완성봉 종가 진입.")
    L.append("")
    L.append("## 1. 자리별 기준선 (그 자리에 아무 때나 들어가면)")
    L.append("")
    L.append("| 자리 | n (심볼) | LONG 기준선 (승률) | SHORT 기준선 (승률) | 스냅샷 즉시 L / S | 정점까지(중앙 h) · 정점 % · 정점 뒤 12h 낙폭 | 저점까지 · 저점 % · 저점 뒤 12h 반등 |")
    L.append("|---|---|---|---|---|---|---|")
    for gkey, g in rep.get("groups", {}).items():
        bl, bs = g["baseline"]["LONG"], g["baseline"]["SHORT"]
        al, as_ = g["at_snapshot"]["LONG"], g["at_snapshot"]["SHORT"]
        L.append(f"| {g['label']} `{gkey}` | {g['n']} ({g['symbols']}) | {_f(bl['mean'])} ({bl['win']}%) | "
                 f"{_f(bs['mean'])} ({bs['win']}%) | {_f(al['mean'])} / {_f(as_['mean'])} | "
                 f"{g['peak_hours_med']}h · {_f(g['peak_pct_mean'])}% · {_f(g['drop_after_peak_mean'])}% | "
                 f"{g['trough_hours_med']}h · {_f(g['trough_pct_mean'])}% · {_f(g['rise_after_trough_mean'])}% |")
    L.append("")
    L.append("## 2. 규칙별 — ① 첫 진입 자리 (기준선 대비 Δ)")
    L.append("")
    for gkey, g in rep.get("groups", {}).items():
        if g["n"] < min_n:
            continue
        L.append(f"### {g['label']} `{gkey}` (n={g['n']})")
        L.append("")
        L.append("| 규칙 | 방향 | 발동 n (율) | 평균 ROI | Δ기준선 | 승률 | TP | SL | 발동까지(중앙 h) |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for key, st in g["rules"].items():
            meta = rep["rules"].get(key, {})
            L.append(f"| {meta.get('label', key)} `{key}` | {st['side']} | {st['n']} ({st['fire_rate']}%) | "
                     f"{_f(st['mean'])} | {_f(st['delta'])} | {st['win'] if st['win'] is not None else '—'}% | "
                     f"{st['tp'] if st['tp'] is not None else '—'}% | {st['sl'] if st['sl'] is not None else '—'}% | {st['hours_med']} |")
        L.append("")
    L.append("## 3. 교차검증 (전체, Δ기준선) — 네 조각 전부 양수여야 채택 후보")
    L.append("")
    L.append("| 규칙 | 심볼 짝 | 심볼 홀 | 날짜 전반 | 날짜 후반 | 전부 양수 |")
    L.append("|---|---|---|---|---|---|")
    for key, cv in rep.get("cv", {}).items():
        meta = rep["rules"].get(key, {})
        cell = lambda k: f"{_f(cv[k]['delta'])} (n={cv[k]['n']})"  # noqa: E731
        L.append(f"| {meta.get('label', key)} `{key}` | {cell('sym_even')} | {cell('sym_odd')} | {cell('date_early')} | "
                 f"{cell('date_late')} | {'✅' if cv.get('all_positive') else '✗'} |")
    L.append("")
    return "\n".join(L)


def row_to_report_input(row: Any) -> dict[str, Any]:
    """ORM 행 → build_report 입력."""
    sd = row.snap_date
    return {"symbol": row.symbol, "snap_date": sd.isoformat() if isinstance(sd, (date, datetime)) else str(sd),
            "tags": list(row.tags or []), "source": row.source, "outcome": row.outcome}

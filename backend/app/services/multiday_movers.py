"""📅 1일·3일·5일 순위 감시 대상 (Fix 351).

## 사장님 지시 (2026-09-05)
  "1일에서 5일 사이 이렇게 조정받는 심볼을 찾아서 숏과 롱으로 수익을 만들어야 하는게 우리 시스템"
  "최근 1일에서 5일 상승 50위까지 하락 50위까지의 차트를 분석해서 지금 당일 급등락과 같이 활용할 수 있게
   1일에서 5일 순위를 기준으로 당일 급등락을 같이 공유해서 활용해줘"
  (예시 차트 SKDD·ZEST·TAKE·HEMI·CLO = 며칠 오른 뒤 당일 −13~−19% 조정)

## 실측 (2026-09-05, 전 USDT 무기한 524종목 일봉 60일, 순위 = 전일 종가 기준, 미래참조 없음)
    자리                                   n     LONG(당일 종가 진입, 3일)   SHORT
    3·5일 상승50 + 당일 −8%↓ (조정)         146   −1.90 (승률 16%)          −3.10
    3·5일 상승50 + 당일 하락50               316   −1.24                      −2.46
    5일 상승50 + 당일 상승50 + 신고가         193   −2.59                      −1.76
    기준선                                 4703   −0.13                      −1.83
  → 며칠 순위는 **진입 신호가 아니다**(당일 종가 진입은 롱·숏 모두 음수). **감시 대상(어디를 볼지)** 이다.
    진입 타이밍은 기존 15분 로직(정점-주춤·상승 초입·지지선)이 정한다. 사장님 예시 5개 중 4개(HEMI·TAKE·CLO·ZEST)가
    「3·5일 상승50 + 당일 하락50」 목록에 실제로 잡혔다(SKDD 는 거래대금 하한 미달).

## 이 모듈이 하는 것
  - 24h 티커에 **3일·5일 수익률 순위**(전일 종가 기준, 진행중 일봉 제외)를 붙인다.
  - `rank_map_multiday` = 기존 `market_movers.rank_map`(당일 상승/하락 N위) 뒤에
    UP3D/UP5D/DOWN3D/DOWN5D 순위를 이어 붙인다(중복 제거). 정점·저점 감지 워커의 감시 대상이 넓어진다.
  - `multiday_hit` = 진입 관문(chg24_entry_gate)에서 「당일 순위 밖이어도 3·5일 순위 안이면 통과」.
  - 일봉 조회(심볼당 1회)는 무거우므로 Redis 에 30분 캐시 + 갱신 잠금. 캐시·조회 실패 = 24h 만 (fail-open).
  숫자(top_n 50, 캐시 30분)는 사장님 「50위」 + Claude 운영값. 설정키로 바꿀 수 있다.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterable

from app.services.market_movers import DEFAULT_TOP_N, MIN_QUOTE_VOLUME, quote_volume, rank_map

logger = logging.getLogger(__name__)

SETTING_ENABLED = "multiday_universe_enabled"        # 감시 대상 확장 (기본 ON)
SETTING_GATE_ENABLED = "entry_rank_multiday_enabled"   # 진입 관문에서도 인정 (기본 ON)
SETTING_TOP_N = "multiday_rank_top_n"                  # 기본 50
SETTING_CACHE_SEC = "multiday_cache_seconds"           # 기본 1800

CACHE_KEY = "multiday_ranks:v1"
LOCK_KEY = "multiday_ranks:lock"
CACHE_SEC_DEFAULT = 1800
LOCK_SEC = 600
TAGS = ("UP3D", "UP5D", "DOWN3D", "DOWN5D")


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
        logger.warning("[Fix351] %s 조회 실패 → 기본값: %s", key, e)
        return None


def _bool(db: Any, key: str, default: bool) -> bool:
    v = _setting(db, key)
    return default if v is None else v.lower() in ("1", "true", "on", "yes")


def multiday_enabled(db: Any) -> bool:
    return _bool(db, SETTING_ENABLED, True)


def gate_multiday_enabled(db: Any) -> bool:
    return _bool(db, SETTING_GATE_ENABLED, True)


def top_n(db: Any) -> int:
    v = _setting(db, SETTING_TOP_N)
    try:
        n = int(float(v)) if v else DEFAULT_TOP_N
    except Exception:
        return DEFAULT_TOP_N
    return n if 1 <= n <= 500 else DEFAULT_TOP_N


def cache_seconds(db: Any) -> int:
    v = _setting(db, SETTING_CACHE_SEC)
    try:
        n = int(float(v)) if v else CACHE_SEC_DEFAULT
    except Exception:
        return CACHE_SEC_DEFAULT
    return n if 60 <= n <= 86400 else CACHE_SEC_DEFAULT


# ── 순수 계산 ────────────────────────────────────────────────────────────

def returns_from_daily(closes: list[float]) -> tuple[float | None, float | None]:
    """완성 일봉 종가 리스트(오래된 → 최근, 진행중 봉 제외)에서 (r3, r5).
    r3 = 어제 종가 / 4일 전 종가 − 1, r5 = 어제 종가 / 6일 전 종가 − 1  (전일 종가 기준 = 미래참조 없음)."""
    if len(closes) < 7:
        return None, None
    y = closes[-1]
    try:
        return y / closes[-4] - 1.0, y / closes[-6] - 1.0
    except ZeroDivisionError:
        return None, None


def rank_symbols(rets: dict[str, tuple[float | None, float | None]], n: int) -> dict[str, dict[str, Any]]:
    """{sym: (r3, r5)} → {sym: {"r3", "r5", "UP3D", "UP5D", "DOWN3D", "DOWN5D"}} (순위는 1부터, 없으면 None)."""
    out: dict[str, dict[str, Any]] = {s: {"r3": r3, "r5": r5, "UP3D": None, "UP5D": None, "DOWN3D": None, "DOWN5D": None}
                                      for s, (r3, r5) in rets.items()}
    for key, tag_up, tag_dn in (("r3", "UP3D", "DOWN3D"), ("r5", "UP5D", "DOWN5D")):
        valid = [(s, v[key]) for s, v in out.items() if v[key] is not None]
        for i, (s, _) in enumerate(sorted(valid, key=lambda x: -x[1])[:n], start=1):
            out[s][tag_up] = i
        for i, (s, _) in enumerate(sorted(valid, key=lambda x: x[1])[:n], start=1):
            out[s][tag_dn] = i
    return out


def rsi14(closes: list[float], n: int = 14) -> list[float | None]:
    """Wilder RSI. 완성봉 종가 리스트 → 같은 길이(초반 None)."""
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    g = l = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        g += max(d, 0.0); l += max(-d, 0.0)
    ag, al = g / n, l / n
    out[n] = 100.0 - 100.0 / (1.0 + (ag / al if al else 1e9))
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0.0)) / n
        al = (al * (n - 1) + max(-d, 0.0)) / n
        out[i] = 100.0 - 100.0 / (1.0 + (ag / al if al else 1e9))
    return out


# ── 「며칠 상승 뒤 조정 → 반등 시작」 롱 (Fix 352) ─────────────────────────────
# 실측 (2026-09-05, 3·5일 상승50 ∩ 당일 하락50 심볼-일 263건, 최근 12일, 조정일 다음 15m 48봉 안 첫 충족, 2x, 12h):
#     기준선 LONG −0.73 (승률 31%) / SHORT −0.02
#     L3 RSI14 < 35 뒤 첫 상승 마감 LONG   **+0.63** (n=173, 승률 43%, TP 14%)
#     L2 상승 초입 LONG                    +0.48 (n=99)
#     숏 추가하락 규칙 S1/S2               −0.82 / −0.24  → 이 자리는 롱이다 (사장님 사상 ② 「급등 후 큰 조정 → 롱」)
# 숫자(당일 −8%, RSI 35)는 Claude 가 정함 — 설정키. 자본은 v219 사다리 1단계 10 USDT (탐색).
SETTING_PB_ENABLED = "multiday_pullback_long_enabled"
SETTING_PB_MIN_DROP = "multiday_pullback_min_drop_pct"     # 당일 하락 최소 % (기본 8)
SETTING_PB_RSI_MAX = "multiday_pullback_rsi_max"           # 직전 완성봉 RSI14 상한 (기본 35)
PATTERN_PULLBACK = "MULTIDAY_PULLBACK"


def pullback_enabled(db: Any) -> bool:
    return _bool(db, SETTING_PB_ENABLED, True)


def pullback_params(db: Any) -> tuple[float, float]:
    d = _setting(db, SETTING_PB_MIN_DROP); r = _setting(db, SETTING_PB_RSI_MAX)
    try:
        drop = float(d) if d else 8.0
    except Exception:
        drop = 8.0
    try:
        rmax = float(r) if r else 35.0
    except Exception:
        rmax = 35.0
    return (drop if 1.0 <= drop <= 60.0 else 8.0), (rmax if 10.0 <= rmax <= 60.0 else 35.0)


def is_pullback_rebound(closes: list[float], *, rsi_max: float = 35.0) -> tuple[bool, dict[str, Any]]:
    """완성봉 종가(오래된→최근)에서 「직전 봉 RSI14 < rsi_max 이고 마지막 봉이 상승 마감」."""
    d: dict[str, Any] = {"decided": False}
    if len(closes) < 20:
        d["reason"] = "봉 부족"
        return False, d
    r = rsi14(closes)
    prev, last = r[-2], r[-1]
    if prev is None:
        d["reason"] = "RSI 계산 불가"
        return False, d
    ok = prev < rsi_max and closes[-1] > closes[-2]
    d.update(decided=True, rsi_prev=round(prev, 2), rsi_last=round(last, 2) if last is not None else None,
             up_close=closes[-1] > closes[-2], rsi_max=rsi_max)
    return ok, d


def best_tag(info: dict[str, Any] | None) -> tuple[str, int] | None:
    """심볼의 다일 순위 중 가장 좋은 (태그, 순위). 없으면 None."""
    if not info:
        return None
    hits = [(t, info.get(t)) for t in TAGS if info.get(t)]
    if not hits:
        return None
    return min(hits, key=lambda x: x[1])


# ── 조회 + 캐시 ──────────────────────────────────────────────────────────

def _redis():
    try:
        from app.core.redis_client import get_redis_client
        return get_redis_client()
    except Exception as e:  # noqa: BLE001
        logger.debug("[Fix351] redis 없음: %s", e)
        return None


def get_multiday_ranks(bc: Any, tickers: Iterable[dict[str, Any]], *, db: Any = None,
                       min_quote_volume: float = MIN_QUOTE_VOLUME) -> dict[str, dict[str, Any]]:
    """{symbol: {r3, r5, UP3D, UP5D, DOWN3D, DOWN5D}}. 캐시(30분) 우선, 없으면 일봉을 받아 계산.
    실패는 {} (호출자는 24h 순위만 쓴다 = fail-open)."""
    r = _redis()
    try:
        if r is not None:
            raw = r.get(CACHE_KEY)
            if raw:
                data = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
                if isinstance(data, dict) and data.get("ranks"):
                    return data["ranks"]
    except Exception as e:  # noqa: BLE001
        logger.debug("[Fix351] 캐시 읽기 실패: %s", e)
    # 갱신 잠금 — 여러 워커가 동시에 수백 번 일봉을 받지 않게
    locked = False
    try:
        if r is not None:
            locked = bool(r.set(LOCK_KEY, str(time.time()), nx=True, ex=LOCK_SEC))
            if not locked:
                return {}
    except Exception:
        locked = True
    try:
        n = top_n(db)
        pool = [t for t in (tickers or []) if str(t.get("symbol") or "").endswith("USDT")
                and (min_quote_volume <= 0 or quote_volume(t) >= min_quote_volume)]
        rets: dict[str, tuple[float | None, float | None]] = {}
        t0 = time.time()
        for t in pool:
            sym = str(t.get("symbol"))
            try:
                kl = bc.get_klines(symbol=sym, interval="1d", limit=8)
                if not kl or len(kl) < 8:
                    continue
                closes = [float(k[4]) for k in kl[:-1]]        # 진행중 일봉 제외
                rets[sym] = returns_from_daily(closes)
            except Exception as e:  # noqa: BLE001
                logger.debug("[Fix351] %s 일봉 실패: %s", sym, e)
        ranks = rank_symbols(rets, n)
        logger.info("[Fix351] 다일 순위 갱신: 후보 %d, 계산 %d, top_n %d, %.1fs", len(pool), len(rets), n, time.time() - t0)
        if r is not None:
            try:
                r.setex(CACHE_KEY, cache_seconds(db), json.dumps({"ts": time.time(), "ranks": ranks}))
            except Exception as e:  # noqa: BLE001
                logger.debug("[Fix351] 캐시 저장 실패: %s", e)
        return ranks
    except Exception as e:  # noqa: BLE001
        logger.warning("[Fix351] 다일 순위 계산 실패 → 24h 만 사용: %s", e)
        return {}
    finally:
        if locked and r is not None:
            try:
                r.delete(LOCK_KEY)
            except Exception:
                pass


def rank_map_multiday(tickers: Iterable[dict[str, Any]], top_n_24h: int, *, bc: Any = None, db: Any = None,
                      min_quote_volume: float = MIN_QUOTE_VOLUME) -> list[tuple[dict[str, Any], str, int]]:
    """감시 대상 = 당일 상승/하락 N위 ∪ 3일·5일 상승/하락 N위. `(ticker, 태그, 순위)`.
    당일 순위가 먼저(기존 순서 그대로), 그 뒤에 UP3D/UP5D/DOWN3D/DOWN5D. 같은 심볼은 먼저 나온 쪽만."""
    tickers = list(tickers or [])
    base = rank_map(tickers, top_n_24h, min_quote_volume=min_quote_volume)
    if bc is None or not multiday_enabled(db):
        return base
    ranks = get_multiday_ranks(bc, tickers, db=db, min_quote_volume=min_quote_volume)
    if not ranks:
        return base
    seen = {str(t.get("symbol") or "") for t, _, _ in base}
    by_sym = {str(t.get("symbol") or ""): t for t in tickers}
    out = list(base)
    for tag in TAGS:
        for sym, info in sorted(((s, i) for s, i in ranks.items() if i.get(tag)), key=lambda x: x[1][tag]):
            if sym in seen or sym not in by_sym:
                continue
            seen.add(sym)
            out.append((by_sym[sym], tag, int(info[tag])))
    return out


def multiday_hit(symbol: str, bc: Any, tickers: Iterable[dict[str, Any]], *, db: Any = None) -> tuple[str, int] | None:
    """진입 관문용: 이 심볼이 3일·5일 순위 안이면 (「5일 상승」, 순위). 아니면 None. 실패는 None."""
    if not gate_multiday_enabled(db):
        return None
    try:
        ranks = get_multiday_ranks(bc, tickers, db=db)
        hit = best_tag(ranks.get(symbol))
        if not hit:
            return None
        tag, rank = hit
        label = {"UP3D": "3일 상승", "UP5D": "5일 상승", "DOWN3D": "3일 하락", "DOWN5D": "5일 하락"}[tag]
        return label, rank
    except Exception as e:  # noqa: BLE001
        logger.debug("[Fix351] multiday_hit 실패 (무시): %s", e)
        return None

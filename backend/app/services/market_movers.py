"""📊 당일 변동률 순위 — 「상승 N위 + 하락 N위」 감시 대상 선정.

사장님 지시 (2026-08-30):
  "v219 감시와 자동매매는 당일 급등 50위까지도 모니터링해서 자동매매해줘"
  → 확인: "당일 상승 50위와 하락 50위로 해줘"

## 왜 필요한가 — 지금은 「거래대금 순」이다

    pump_top_detector_worker:388     usdt.sort(key=quoteVolume, reverse=True)
    long_bottom_detector_worker:537  동일

거래대금 상위 100~150개 **안에서만** 급등락을 골랐다. 그래서 오늘 +80% 급등해도
거래대금이 작으면 감시 대상에 **아예 들어오지 못했다**. 「당일 급등 50위」와는
완전히 다른 기준이다.

## 이 모듈이 하는 일

24h 변동률로 정렬해 **상승 N위 ∪ 하락 N위** 를 돌려준다. 두 워커가 같은 함수를
쓰게 해서 「한쪽만 고쳐 어긋나는」 상습 실패를 막는다 (헌법 101).

⚠️ 감시 대상 수는 **API weight 와 직결**된다 (2026-08-26 IP ban 418 사고).
   심볼당 kline 호출이 그대로 곱해지므로, 상한은 호출부에서 반드시 통제할 것.
"""
from __future__ import annotations

from typing import Any, Iterable

__all__ = ["change_pct", "quote_volume", "top_movers", "rank_map", "MIN_QUOTE_VOLUME"]

# 사장님 확정 기본값 — 상승 50 / 하락 50 (합쳐서 최대 100 심볼)
DEFAULT_TOP_N: int = 50

# 🚨 Fix 220 (2026-08-30): 24h 거래대금 하한 (USDT).
#
#   옛 코드는 **거래대금 순으로 정렬**해 상위 100~150개만 봤다. 그 자체는 사장님이
#   요구한 적 없는 기준이라 Fix 217 로 없앴는데, 없애고 나니 **부작용**이 생겼다:
#   거래대금 정렬이 사실상 **유동성 필터** 노릇을 하고 있었다.
#   이제 거래대금 500위 잡코인도 +80% 면 자동매매 대상이 된다
#   → 슬리피지 / 부분 체결 / 청산가 왜곡. 2026-08-21 급등 SHORT -849 USDT 사고와
#     같은 계열의 노출이다 (헌법 64).
#
#   그래서 **순위는 변동률로 매기되, 죽은 시장만 걷어내는 최소 하한**을 둔다.
#   5,000,000 USDT 는 바이낸스 USD-M 영구선물에서 「거래가 실제로 되는」 최소선이고,
#   급등한 종목은 그날 거래대금이 이보다 훨씬 크므로 사장님이 잡고 싶어 하는
#   급등 종목을 걸러내지 않는다.
#   ⚠️ 감으로 정한 값이다. 몇 개가 이 하한에 걸리는지 호출부가 로그로 남기므로,
#      하루 데이터를 보고 조정할 것. 끄려면 0 으로 두면 된다.
MIN_QUOTE_VOLUME: float = 5_000_000.0


def change_pct(ticker: dict[str, Any]) -> float:
    """24h 변동률(%). 파싱 실패는 0.0 — 정렬에서 가운데로 밀려 자연히 제외된다."""
    try:
        return float(ticker.get("priceChangePercent") or 0)
    except (TypeError, ValueError):
        return 0.0


def quote_volume(ticker: dict[str, Any]) -> float:
    """24h 거래대금(USDT). 파싱 실패는 0.0 = 하한에 걸려 제외된다 (안전측)."""
    try:
        return float(ticker.get("quoteVolume") or 0)
    except (TypeError, ValueError):
        return 0.0


def top_movers(
    tickers: Iterable[dict[str, Any]],
    top_n: int = DEFAULT_TOP_N,
    *,
    quote: str = "USDT",
    min_quote_volume: float = MIN_QUOTE_VOLUME,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(상승 top_n, 하락 top_n) 을 24h 변동률 순으로 돌려준다.

    - 상승은 1위(가장 많이 오른 것)부터, 하락도 1위(가장 많이 내린 것)부터.
    - 심볼이 top_n*2 보다 적으면 겹칠 수 있으므로 **호출부에서 합칠 때 중복을 제거**한다
      (`rank_map` 이 그 일을 한다).
    - 정렬 키가 없거나 깨진 티커는 0% 로 취급된다.
    """
    if top_n <= 0:
        return [], []
    pool = [
        t for t in (tickers or [])
        if str(t.get("symbol") or "").endswith(quote)
        # Fix 220: 순위는 변동률로 매기되 **죽은 시장만** 걷어낸다 (유동성 하한).
        and (min_quote_volume <= 0 or quote_volume(t) >= min_quote_volume)
    ]
    ranked = sorted(pool, key=change_pct, reverse=True)
    gainers = ranked[:top_n]
    losers = list(reversed(ranked[-top_n:])) if ranked else []
    return gainers, losers


def rank_map(
    tickers: Iterable[dict[str, Any]],
    top_n: int = DEFAULT_TOP_N,
    *,
    quote: str = "USDT",
    min_quote_volume: float = MIN_QUOTE_VOLUME,
) -> list[tuple[dict[str, Any], str, int]]:
    """감시 대상 = 상승 N위 ∪ 하락 N위. `(ticker, "UP"|"DOWN", 순위)` 로 돌려준다.

    - **중복 제거**: 같은 심볼이 양쪽에 들어오면(심볼 수가 적을 때) 먼저 나온 쪽만 남는다.
    - 순서: 상승 1위 → 상승 N위 → 하락 1위 → 하락 N위.
      호출부가 상한을 걸어 자를 때 **가장 많이 오른/내린 것부터** 살아남게 하기 위함이다.
    - 순위(1부터)를 같이 주므로 로그·화면에 「상승 3위」처럼 남길 수 있다
      (차단 사유를 화면에 보여줄 것 — 헌법 161).
    """
    gainers, losers = top_movers(
        tickers, top_n, quote=quote, min_quote_volume=min_quote_volume,
    )
    out: list[tuple[dict[str, Any], str, int]] = []
    seen: set[str] = set()
    for side, group in (("UP", gainers), ("DOWN", losers)):
        for i, t in enumerate(group, start=1):
            sym = str(t.get("symbol") or "")
            if not sym or sym in seen:
                continue
            seen.add(sym)
            out.append((t, side, i))
    return out

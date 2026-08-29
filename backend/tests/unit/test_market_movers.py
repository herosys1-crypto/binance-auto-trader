"""📊 당일 상승 50위 / 하락 50위 — 감시 대상 선정 (사장님 2026-08-30 지시).

사장님: "당일 상승 50위와 하락 50위로 해줘"

지금 코드는 **거래대금(quoteVolume) 순**으로 정렬해 상위 100~150개 안에서만
급등락을 고른다 (pump_top_detector:388 / long_bottom_detector:537).
사장님이 요구한 적 없는 기준이고, 그래서 **오늘 +80% 급등해도 거래대금이 작으면
감시 대상에 아예 못 들어온다.** 이 파일은 그 기준을 「변동률 순위」로 고정한다.
"""
from __future__ import annotations

from app.services.market_movers import DEFAULT_TOP_N, change_pct, rank_map, top_movers


def _t(sym, chg, vol=1.0):
    return {"symbol": sym, "priceChangePercent": str(chg), "quoteVolume": str(vol)}


def _universe(n=200):
    """변동률 -100.. +99 로 흩어진 심볼 n개. 거래대금은 변동률과 **반대**로 준다.

    거래대금 순으로 고르면 가장 많이 오른 종목이 **꼴찌**가 되도록 만들어,
    옛 기준과 새 기준을 확실히 갈라 놓는다.
    """
    return [_t(f"S{i}USDT", i - n // 2, vol=n - i) for i in range(n)]


def test_gainers_and_losers_are_ranked_by_change():
    ups, downs = top_movers(_universe(200), 50)
    assert len(ups) == 50 and len(downs) == 50
    assert change_pct(ups[0]) > change_pct(ups[-1]), "상승은 1위부터"
    assert change_pct(downs[0]) < change_pct(downs[-1]), "하락도 1위(가장 많이 내린 것)부터"
    assert change_pct(ups[0]) == 99
    assert change_pct(downs[0]) == -100


def test_volume_does_not_decide_anything():
    """🚨 핵심 계약 — 거래대금이 선정에 끼어들면 안 된다.

    이 시험 데이터는 「가장 많이 오른 종목의 거래대금이 가장 작다」로 만들어져 있다.
    옛 기준(거래대금 순)이면 상승 1위가 절대 안 뽑힌다.
    """
    ups, _ = top_movers(_universe(200), 50)
    assert ups[0]["symbol"] == "S199USDT", "변동률 1위가 뽑히지 않았다 = 거래대금이 개입했다"
    assert float(ups[0]["quoteVolume"]) == 1.0, "대조군 무효 — 거래대금이 최소가 아니다"


def test_rank_map_is_up_first_then_down_and_deduped():
    rows = rank_map(_universe(200), 50)
    assert len(rows) == 100
    assert [s for _, s, _ in rows[:50]] == ["UP"] * 50
    assert [s for _, s, _ in rows[50:]] == ["DOWN"] * 50
    assert rows[0][2] == 1 and rows[50][2] == 1, "각 방향 순위는 1부터"
    syms = [t["symbol"] for t, _, _ in rows]
    assert len(syms) == len(set(syms)), "중복 심볼이 있다"


def test_small_universe_does_not_duplicate():
    """심볼이 적으면 상승·하락 목록이 겹친다 — 그때도 중복이 나오면 안 된다."""
    rows = rank_map([_t("AUSDT", 5), _t("BUSDT", -5), _t("CUSDT", 1)], 50)
    syms = [t["symbol"] for t, _, _ in rows]
    assert sorted(syms) == ["AUSDT", "BUSDT", "CUSDT"]
    assert len(syms) == len(set(syms))


def test_non_usdt_and_broken_tickers_are_safe():
    """USDT 아닌 것 제외 / 값이 깨져도 죽지 않는다 (워커가 여기서 멈추면 안 된다)."""
    rows = rank_map(
        [_t("AUSDT", 10), _t("BBTC", 99), {"symbol": "CUSDT"},
         {"symbol": "DUSDT", "priceChangePercent": "없음"}],
        50,
    )
    syms = [t["symbol"] for t, _, _ in rows]
    assert "BBTC" not in syms, "USDT 아닌 심볼이 들어왔다"
    assert set(syms) == {"AUSDT", "CUSDT", "DUSDT"}
    assert change_pct({"priceChangePercent": "없음"}) == 0.0


def test_zero_top_n_is_empty_not_everything():
    """상한 0 = 감시 안 함. 실수로 전 종목을 스캔하면 API weight 가 폭발한다."""
    assert top_movers(_universe(50), 0) == ([], [])
    assert rank_map(_universe(50), 0) == []


def test_default_is_50_as_instructed():
    assert DEFAULT_TOP_N == 50, "사장님 지시 = 상승 50위 / 하락 50위"

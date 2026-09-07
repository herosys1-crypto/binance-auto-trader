"""🧪 Fix 361 — 가상 매매 학습 (paper trading). 실시간 자동을 끈 동안 가상으로 진입·추가·청산을 기록해
「꼭 이기는 롱·숏 자리」와 「익절 중 추가로 수익이 나는 자리」를 학습한다. 실 주문 0건(klines/ticker 만 읽는다).

사장님 (2026-09-08 verbatim): "지금부터 실시간 자동은 종료했어 가상으로 포지션 진입해서 성공과 실패를 기록저장
학습해서 다시 실시간 운영시작 하면 그때 적용할 수 있게 학습해줘 꼭 성리할수 있는 롱과숏 포지션 진입하고
익절중에 포지션 추가해서 수익을 만들 자리를 찾아줘"

## 이 파일의 범위 (A4 — 매매 판정이 아닌 코드: 테스트 + 문서)

이 저장소는 Fix 361 을 4조각(A1 모델/마이그레이션, A2 워커/스케줄러, A3 API, A4 테스트/문서)으로 나눠 병렬로
작업한다. **엔진(app/services/paper_trading.py)은 이미 작성돼 있고 이 파일이 수정 대상이 아니다** — 아래
엔진 테스트는 지금(A4 작성 시점) 그대로 pytest 로 통과해야 한다.

작성 착수 시점 기준 배선 상태(정적 테스트 결과가 갈리는 이유를 여기 적어둔다 — 「왜 실패하는지 몰라서
테스트를 지웠다」를 막기 위해). A4 작업을 시작한 시점엔 A1(모델/마이그레이션)만 배선돼 있었고 A2(워커/
스케줄러)·A3(API)는 미착수라 `test_A2_*`/`test_A3_*` 는 **그때는 FAIL 이 정상**이었다 — 파일 존재를 먼저
확인하도록 짜서 assertion 실패로 떨어지게(모듈 없어서 import 에러로 collection 자체가 죽지 않게) 했다.
이 PR 을 마무리하는 시점엔 A1~A3 가 전부 병렬로 먼저 머지돼 아래 28개 테스트가 **전부 PASS** 한다(실행
확인 완료, 2026-09-08). `test_A2_*`/`test_A3_*` 를 지우지 않고 남겨두는 이유: 이후 리팩터로 잡 id·크론
표현식·라우트 경로가 바뀌면 이 파일이 바로 잡아야 하기 때문(정적 배선은 엔진 로직처럼 실행 경로로
검증되지 않는다 — chart_learning 계열 테스트 관례와 동일).

엔진 수치 재검증 방법 요약(왜 이 값들인지):
  - live 엔진 청산 순서는 **손절 → TP1 25% 부분익절 → 트레일링(직전 봉까지 최고 ROI 기준 −5%p) → 48h 시간
    만료**이고, 손절 판정이 먼저이므로 한 봉 안에서 SL·TP1 가격을 동시에 건드리면 **손절로 확정**한다
    (보수적 가정 — chart_learning.sim 과 같은 원칙).
  - 트레일링 청산 시 실현 ROI = `TP1_CLOSE_RATIO * tp1_pct + (1 - TP1_CLOSE_RATIO) * (max_roi - TRAIL_RETRACE)`
    = `0.25*tp1 + 0.75*(max_roi-5)` (ASSIGNMENT 명세와 동일).
  - 추가(피라미딩) lot 은 ROI≥5·이동≥3%·정점 되돌림≤2.5%·(변형별 지표 조건) 을 봉 **종가**에서 판정하고
    최대 2회·쿨다운 1봉이다. `live` 변형은 SHORT + 15m MACD hist 3봉 가속만 허용한다.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.services import chart_learning as CL
from app.services import paper_trading as PT

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


# ══════════════════════════════════════════════════════════════════════
# 도우미
# ══════════════════════════════════════════════════════════════════════

def _bar(ts: int, o: float, h: float, l: float, c: float, v: float = 100.0) -> list[float]:
    return [float(ts), float(o), float(h), float(l), float(c), float(v)]


def _flat15(n: int, *, start_ms: int = 0, base: float = 100.0, step: float = 1.0) -> list[list[float]]:
    """평범한(SL/TP1 근처에 안 닿는) 15m 완성봉 n개 — 스냅샷/생명주기 스모크용."""
    out = []
    price = base
    for i in range(n):
        price += step
        out.append(_bar(start_ms + i * CL.MS_15M, price - 0.5, price + 0.5, price - 1.0, price, 100.0))
    return out


def _closed_trade(symbol: str, side: str, rule: str, roi: float, opened_at: str, tags=None) -> dict:
    return {"status": "CLOSED", "symbol": symbol, "side": side, "rule": rule, "tags": list(tags or []),
            "source": "backfill", "opened_at": opened_at,
            "engines": {"house": {"roi": roi, "hit": "TP"}, "live": {"roi": roi, "hit": "TP"}}, "adds": {}}


def _t(i: int) -> str:
    return (datetime(2026, 1, 1) + timedelta(minutes=i)).isoformat()


def _balanced_symbols(prefix: str, n: int) -> list[str]:
    """심볼 홀짝(PT._parity)이 정확히 절반씩 되도록 — build_report 의 CV 4조각 중 심볼 축을 결정적으로 채운다."""
    want_even, want_odd = -(-n // 2), n // 2
    evens: list[str] = []
    odds: list[str] = []
    i = 0
    while len(evens) < want_even or len(odds) < want_odd:
        s = f"{prefix}{i:05d}USDT"
        i += 1
        if PT._parity(s) == 0 and len(evens) < want_even:
            evens.append(s)
        elif PT._parity(s) == 1 and len(odds) < want_odd:
            odds.append(s)
    return evens + odds


# ══════════════════════════════════════════════════════════════════════
# live 엔진 — 청산 순서 · TP1/트레일링 수식 · 시간만료
# ══════════════════════════════════════════════════════════════════════

def test_SL_이_TP1과_한_봉에서_동시에_닿으면_손절이_우선한다():
    entry = 100.0
    bars = [_bar(0, 100.0, 105.0, 80.0, 90.0)]           # h=105 → TP1(101.5) 도달, l=80 → SL(87.5) 도달
    r = PT.run_live_like("LONG", entry, bars, tp1_pct=3.0, variants=())
    assert r["hit"] == "SL" and r["tp1_hit"] is False and r["done"] is True
    assert r["roi"] == pytest.approx(-PT.LIVE_SL_ROI)
    assert r["exit_bar"] == 0 and r["exit_price"] == pytest.approx(87.5)


def test_SHORT_손절도_동시_도달이면_손절_우선(): # 대칭 확인
    entry = 100.0
    sl_price = PT.price_at_roi("SHORT", entry, -PT.LIVE_SL_ROI)
    tp1_price = PT.price_at_roi("SHORT", entry, 3.0)
    bars = [_bar(0, 100.0, sl_price + 1.0, tp1_price - 1.0, 100.0)]   # h 가 SL 위, l 이 TP1 아래
    r = PT.run_live_like("SHORT", entry, bars, tp1_pct=3.0, variants=())
    assert r["hit"] == "SL" and r["tp1_hit"] is False
    assert r["roi"] == pytest.approx(-PT.LIVE_SL_ROI)


def test_TP1_25퍼센트_부분익절_후_트레일링_청산_수식():
    entry = 100.0
    bars = [
        _bar(0, 100.0, 101.5, 99.0, 101.0),     # TP1(101.5) 도달 → 25% 부분익절, max_roi=3.0
        _bar(0, 101.0, 110.0, 100.0, 108.0),    # 신고점 → max_roi=20.0 (트레일링 기준은 "직전 봉까지")
        _bar(0, 108.0, 109.0, 107.0, 107.5),    # l=107 → roi 14.0 ≤ (max_roi 20 − 5) → 트레일링 이탈
    ]
    r = PT.run_live_like("LONG", entry, bars, tp1_pct=3.0, variants=())
    assert r["tp1_hit"] is True and r["hit"] == "TRAIL" and r["done"] is True
    assert r["max_roi"] == pytest.approx(20.0)
    expected = PT.TP1_CLOSE_RATIO * 3.0 + (1 - PT.TP1_CLOSE_RATIO) * (20.0 - PT.TRAIL_RETRACE)
    assert r["roi"] == pytest.approx(expected) and expected == pytest.approx(12.0)
    assert r["exit_bar"] == 2 and r["exit_price"] == pytest.approx(107.5)


def test_트레일링은_같은_봉의_신고점을_그_봉에서_바로_쓰지_않는다():
    """신고점 갱신은 봉 끝에 일어나고, 트레일링 판정은 그 봉이 시작할 때의(직전까지의) max_roi 를 쓴다."""
    entry = 100.0
    bars = [
        _bar(0, 100.0, 101.5, 99.0, 101.0),   # TP1 히트, max_roi → 3.0
        _bar(0, 101.0, 130.0, 96.0, 101.0),   # 같은 봉 안에서 신고점(30%)과 큰 되돌림(l=96→roi=-8)이 동시에 있어도
    ]                                          # 트레일링 기준은 아직 3.0(직전 값)이라 −8 은 (3−5=−2) 아래라 청산돼야 함
    r = PT.run_live_like("LONG", entry, bars, tp1_pct=3.0, variants=())
    assert r["hit"] == "TRAIL" and r["exit_bar"] == 1
    expected = PT.TP1_CLOSE_RATIO * 3.0 + (1 - PT.TP1_CLOSE_RATIO) * (3.0 - PT.TRAIL_RETRACE)
    assert r["roi"] == pytest.approx(expected)


def test_TIME_시간만료_청산():
    entry = 100.0
    bars = [_bar(0, 100.0, 101.0, 99.0, 100.0) for _ in range(5)]
    r = PT.run_live_like("LONG", entry, bars, tp1_pct=50.0, horizon=5, variants=())
    assert r["hit"] == "TIME" and r["bars"] == 5 and r["exit_bar"] == 4 and r["done"] is True
    assert r["roi"] == pytest.approx(0.0, abs=1e-9)
    assert r["tp1_hit"] is False


def test_봉이_모자라면_미완이다():
    entry = 100.0
    bars = [_bar(0, 100.0, 101.0, 99.0, 100.0) for _ in range(3)]
    r = PT.run_live_like("LONG", entry, bars, tp1_pct=50.0, horizon=10, variants=())
    assert r["done"] is False and r["hit"] == "OPEN" and r["bars"] == 3


# ══════════════════════════════════════════════════════════════════════
# 추가(피라미딩) lot — ROI≥5 · 이동≥3% · 가속 · 최대 2회 · 쿨다운 1봉 · 되돌림≤2.5%
# ══════════════════════════════════════════════════════════════════════

def test_추가_lot_은_ROI5_이동3_가속에서_열리고_최대2회_쿨다운1봉():
    entry = 100.0
    hist = [20.0 - 2 * i for i in range(7)]     # 단조 하락 → idx≥3 이면 항상 SHORT 가속(True)
    closes = [99.0, 97.0, 95.0, 90.0, 85.0, 80.0, 75.0]
    bars = [_bar(0, c + 0.5, c + 1.0, c - 1.0, c) for c in closes]
    r = PT.run_live_like("SHORT", entry, bars, tp1_pct=500.0, hist=hist, hist_off=0,
                         horizon=7, variants=("live",), sl_roi=PT.LIVE_SL_ROI)
    adds = r["adds"]["live"]
    assert [a["bar"] for a in adds] == [3, 5]           # i=4 는 직전 추가(3) + 1봉 쿨다운에 걸려 건너뜀
    assert [a["price"] for a in adds] == [90.0, 80.0]
    assert [a["roi_at_add"] for a in adds] == [pytest.approx(20.0), pytest.approx(40.0)]
    assert r["hit"] == "TIME" and r["exit_bar"] == 6                # SL/TP1 안 닿고 끝까지 감
    assert all(a["exit_kind"] == "BASE_TIME" and a["exit_bar"] == 6 for a in adds)   # 본 포지션 청산과 같이 닫힘


def test_추가_lot_은_idx가_3_미만이면_가속_판정_전에_열리지_않는다():
    entry = 100.0
    hist = [20.0, 15.0, 10.0, 5.0]              # idx<3 인 처음 3봉은 _accel3 이 항상 False
    closes = [90.0, 80.0, 70.0]                 # ROI·이동은 이미 문턱을 넘지만
    bars = [_bar(0, c + 0.5, c + 1.0, c - 1.0, c) for c in closes]
    r = PT.run_live_like("SHORT", entry, bars, tp1_pct=500.0, hist=hist, hist_off=0,
                         horizon=3, variants=("live",))
    assert r["adds"]["live"] == []


def test_live_변형은_LONG에서_추가하지_않는다_live_both만_허용():
    entry = 100.0
    hist = [-20.0 + 2 * i for i in range(5)]    # 단조 상승 → idx≥3 이면 LONG 가속 True
    closes = [101.0, 103.0, 106.0, 110.0, 115.0]
    bars = [_bar(0, c - 1.0, c + 1.0, c - 0.5, c) for c in closes]
    r = PT.run_live_like("LONG", entry, bars, tp1_pct=500.0, hist=hist, hist_off=0,
                         horizon=5, variants=("live", "live_both"))
    assert r["adds"]["live"] == []                       # live = SHORT 전용
    assert len(r["adds"]["live_both"]) >= 1               # live_both = 양방향 허용


def test_되돌림_2점5퍼_초과면_추가하지_않는다():
    """bar3 추가 → bar4 는 쿨다운(직전+1봉) → bar5 는 쿨다운은 풀렸지만 정점(90) 대비 되돌림 5.6% > 2.5% 로 보류
    → bar6 에서 신저점(88) 을 다시 찍어 되돌림 0%(문턱 통과)이 되면서 두 번째 추가가 열린다."""
    entry = 100.0
    hist = [20.0 - 2 * i for i in range(7)]                    # 단조 하락 → idx≥3 이면 항상 SHORT 가속
    closes = [99.0, 97.0, 95.0, 90.0, 90.5, 95.0, 88.0]
    bars = [_bar(0, c + 0.5, c + 1.0, c - 1.0, c) for c in closes]
    r = PT.run_live_like("SHORT", entry, bars, tp1_pct=500.0, hist=hist, hist_off=0,
                         horizon=7, variants=("live",))
    fired_bars = [a["bar"] for a in r["adds"]["live"]]
    assert fired_bars == [3, 6], "bar4(쿨다운)·bar5(되돌림 5.6%>2.5%) 는 막히고 bar3·bar6 만 추가돼야 한다"


# ══════════════════════════════════════════════════════════════════════
# 미래참조 없음 — 진입 스냅샷은 j 이후를, 관리(manage_trade)는 진입봉 이하를 안 본다
# ══════════════════════════════════════════════════════════════════════

def test_진입_스냅샷은_j_이후_봉을_보지_않는다():
    allk_a = _flat15(60)
    j = 25
    allk_b = [list(b) for b in allk_a]
    for k in range(j + 1, len(allk_b)):
        allk_b[k] = [allk_b[k][0], 99999.0, 99999.0, 0.0001, 99999.0, 1.0]   # 미래봉을 극단값으로 오염
    sa = PT.Series.build(allk_a, [])
    sb = PT.Series.build(allk_b, [])
    fired = PT.evaluate_rules(sa, j)
    ta = PT.open_trade(symbol="AAAUSDT", side="LONG", rule="baseline_LONG", series=sa, j=j, tags=[],
                       chg_24h=None, chg_3d=None, chg_5d=None, source="live", fired=fired)
    tb = PT.open_trade(symbol="AAAUSDT", side="LONG", rule="baseline_LONG", series=sb, j=j, tags=[],
                       chg_24h=None, chg_3d=None, chg_5d=None, source="live", fired=fired)
    assert ta["entry_price"] == tb["entry_price"] == allk_a[j][4]
    assert ta["snapshot"] == tb["snapshot"], "미래봉을 바꿔도 진입 스냅샷(j 까지의 값)은 그대로여야 한다"


def test_관리는_진입봉_이하를_보지_않는다():
    allk_a = _flat15(60)
    j = 25
    entry_ts = int(allk_a[j][0])
    entry_price = float(allk_a[j][4])
    allk_b = [list(b) for b in allk_a]
    for k in range(0, j + 1):                                     # 진입봉과 그 이전을 전부 오염
        allk_b[k] = [allk_b[k][0], 1.0, 999999.0, 0.0001, 1.0, 1.0]
    sa = PT.Series.build(allk_a, [])
    sb = PT.Series.build(allk_b, [])
    trade = {"side": "LONG", "entry_price": entry_price, "entry_bar_ts": entry_ts, "tp1_pct": 3.0, "chg_24h": None}
    ra = PT.manage_trade(trade, sa)
    rb = PT.manage_trade(trade, sb)
    assert ra["engines"]["house"] == rb["engines"]["house"]
    assert ra["engines"]["live"]["roi"] == pytest.approx(rb["engines"]["live"]["roi"])
    assert ra["engines"]["live"]["hit"] == rb["engines"]["live"]["hit"]
    assert ra["bars_seen"] == rb["bars_seen"] == len(allk_a) - j - 1


# ══════════════════════════════════════════════════════════════════════
# 백필 — 창 안 첫 발동만 · 기준선은 12봉(3h)마다
# ══════════════════════════════════════════════════════════════════════

def test_백필은_규칙당_창_안_첫_발동만_기준선은_12봉마다():
    t0 = 1_700_000_000_000 // (CL.MS_15M * PT.BASELINE_EVERY) * (CL.MS_15M * PT.BASELINE_EVERY)  # 12봉 경계 정렬
    pre15 = [_bar(t0 - (30 - i) * CL.MS_15M, 100.0, 100.5, 99.5, 100.0) for i in range(30)]
    fwd15 = [_bar(t0 + i * CL.MS_15M, 100.0, 100.5, 99.5, 100.0) for i in range(26)]
    test_rule = CL.Rule("test_mod3", "LONG", "테스트(3의 배수마다 계속 참)", "candidate", lambda ctx: ctx.j % 3 == 0)

    out = PT.backfill_row(symbol="TESTUSDT", pre15=pre15, pre4h=[], fwd15=fwd15, tags=[], chg_24h=None,
                          chg_3d=None, chg_5d=None, window=24, rules=(test_rule,))

    by_rule: dict[str, list] = {}
    for t in out:
        by_rule.setdefault(t["rule"], []).append(t)
    assert len(by_rule.get("test_mod3", [])) == 1, "조건이 8번(0,3,..,21) 참이어도 첫 발동 한 건만 열려야 한다"
    assert by_rule["test_mod3"][0]["entry_bar_ts"] == fwd15[0][0]
    assert len(by_rule.get("baseline_LONG", [])) == 2                # i=0, i=12 (window=24 → i<24)
    assert len(by_rule.get("baseline_SHORT", [])) == 2
    assert len(out) == 5
    assert all(t["status"] == "CLOSED" and t["source"] == "backfill" for t in out)


def test_백필_봉이_전혀_없으면_빈_목록():
    assert PT.backfill_row(symbol="X", pre15=[], pre4h=[], fwd15=[], tags=[], chg_24h=None, chg_3d=None,
                           chg_5d=None) == []
    pre15 = [_bar(0, 1, 1, 1, 1)]
    assert PT.backfill_row(symbol="X", pre15=pre15, pre4h=[], fwd15=[], tags=[], chg_24h=None, chg_3d=None,
                           chg_5d=None) == []


# ══════════════════════════════════════════════════════════════════════
# 보고서 — 채택 추천(n≥100 · Δ>0 · CV 4/4 양수) + markdown 스모크
# ══════════════════════════════════════════════════════════════════════

def test_build_report_추천은_n문턱과_CV_게이트를_모두_지킨다():
    baseline_syms = _balanced_symbols("BASE", 100)
    trades = [_closed_trade(baseline_syms[i], "SHORT", "baseline_SHORT", -5.0, _t(i)) for i in range(100)]

    # 규칙 A(confirm_peak_111): n=100, 모든 조각에서 Δ=15 (양수) → 채택 추천
    a_syms = _balanced_symbols("RULEA", 100)
    trades += [_closed_trade(a_syms[i], "SHORT", "confirm_peak_111", 10.0, _t(i)) for i in range(100)]

    # 규칙 B(off8_267): Δ 는 양수지만 n=20 < ADOPT_MIN_N(100) → 추천 안 됨
    b_syms = _balanced_symbols("RULEB", 20)
    trades += [_closed_trade(b_syms[i], "SHORT", "off8_267", 10.0, _t(i)) for i in range(20)]

    # 규칙 C(s1_breakdown): n=100, 전체 Δ=5(양수) 지만 홀짝 절반이 음수 → CV 4/4 아님 → 추천 안 됨
    c_syms = _balanced_symbols("RULEC", 100)
    trades += [_closed_trade(c_syms[i], "SHORT", "s1_breakdown", 20.0 if i < 50 else -20.0, _t(i)) for i in range(100)]

    rep = PT.build_report(trades)
    entries = rep["recommend"]["entries"]
    assert ("confirm_peak_111", "ALL", "live") in {(e["rule"], e["group"], e["engine"]) for e in entries}
    assert not any(e["rule"] == "off8_267" for e in entries), "n<100 인데 추천되면 문턱이 안 지켜진 것"
    assert not any(e["rule"] == "s1_breakdown" for e in entries), "CV 한 조각이 음수인데 추천되면 게이트가 없는 것"

    st_a = rep["rules"]["confirm_peak_111"]["groups"]["ALL"]["live"]
    assert st_a["n"] == 100 and st_a["delta"] == pytest.approx(15.0) and st_a["cv"]["all_positive"] is True
    st_c = rep["rules"]["s1_breakdown"]["groups"]["ALL"]["live"]
    assert st_c["n"] == 100 and st_c["delta"] == pytest.approx(5.0) and st_c["cv"]["all_positive"] is False

    md = PT.render_markdown(rep)
    assert "- 진입 **confirm_peak_111**" in md
    assert "- 진입 **off8_267**" not in md and "- 진입 **s1_breakdown**" not in md


def test_render_markdown_은_빈_보고서에서도_안_죽는다():
    rep = PT.build_report([])
    md = PT.render_markdown(rep)
    assert "가상 매매 학습 보고서" in md and "아직 없음" in md


# ══════════════════════════════════════════════════════════════════════
# 작은 수치 도구
# ══════════════════════════════════════════════════════════════════════

def test_roi_price_왕복():
    for side in ("LONG", "SHORT"):
        for roi in (-25.0, -5.0, 0.0, 15.0, 40.0):
            px = PT.price_at_roi(side, 100.0, roi)
            assert PT.roi_of(side, 100.0, px) == pytest.approx(roi)


def test_tp1_for_임계값():
    assert PT.tp1_for(None) == PT.TP1_SURGE
    assert PT.tp1_for(20.0) == PT.TP1_SURGE
    assert PT.tp1_for(-20.0) == PT.TP1_SURGE
    assert PT.tp1_for(5.0) == PT.TP1_CALM
    assert PT.tp1_for(-5.0) == PT.TP1_CALM


def test_group_of_태그_조합():
    assert PT.group_of([]) == ["ALL"]
    assert set(PT.group_of(["UP"])) == {"ALL", "UP24"}
    assert set(PT.group_of(["DOWN"])) == {"ALL", "DOWN24"}
    assert set(PT.group_of(["DOWN", "UP5D"])) == {"ALL", "DOWN24", "UP35_DOWN24"}
    assert set(PT.group_of(["UP", "UP5D"])) == {"ALL", "UP24"}          # 상승+며칠상승은 조정 자리가 아니다


# ══════════════════════════════════════════════════════════════════════
# 규칙 레지스트리 / 생명주기 스모크
# ══════════════════════════════════════════════════════════════════════

def test_evaluate_rules_는_규칙_12종과_기준선_두_개를_돌려준다():
    assert len(CL.RULES) == 12
    series = PT.Series.build(_flat15(60), [])
    fired = PT.evaluate_rules(series, 40)
    assert set(fired) >= {r.key for r in CL.RULES} | set(PT.BASELINE_KEYS)
    assert all(isinstance(v, bool) for v in fired.values())


def test_open_trade와_manage_trade_생명주기_스모크():
    allk = _flat15(60)
    series = PT.Series.build(allk, [])
    j = 20
    fired = PT.evaluate_rules(series, j)
    t = PT.open_trade(symbol="XUSDT", side="LONG", rule="baseline_LONG", series=series, j=j, tags=["UP"],
                      chg_24h=1.0, chg_3d=None, chg_5d=None, source="live", fired=fired)
    assert t["status"] == "OPEN" and t["version"] == PT.VERSION
    assert t["entry_bar_ts"] == int(allk[j][0]) and t["entry_price"] == pytest.approx(allk[j][4])
    res = PT.manage_trade(t, series)
    assert res["status"] in ("OPEN", "CLOSED")
    assert "house" in res["engines"] and "live" in res["engines"]
    assert res["bars_seen"] == len(allk) - j - 1


# ══════════════════════════════════════════════════════════════════════
# A1 배선 — 모델/마이그레이션은 이미 배선 완료 → 지금 PASS 해야 한다
# ══════════════════════════════════════════════════════════════════════

def test_A1_PaperTrade_모델_스키마():
    from app.models.paper_trade import PaperTrade
    cols = {c.name for c in PaperTrade.__table__.columns}
    assert {"id", "source", "symbol", "side", "rule", "entry_bar_ts", "entry_price", "tp1_pct", "opened_at",
            "closed_at", "status", "close_reason", "tags", "chg_24h", "chg_3d", "chg_5d", "snapshot", "engines",
            "adds", "bars_seen", "mfe", "mae", "version"} <= cols
    uniques = [c for c in PaperTrade.__table__.constraints if type(c).__name__ == "UniqueConstraint"]
    assert any({col.name for col in u.columns} == {"symbol", "rule", "entry_bar_ts"} for u in uniques)


def test_A1_alembic_0036_은_0035_뒤를_잇는다():
    m = (ROOT / "alembic" / "versions" / "0036_paper_trades.py").read_text(encoding="utf-8")
    assert "revision = '0036_paper_trades'" in m and "down_revision = '0035_chart_learning'" in m
    assert len("0036_paper_trades") <= 32


def test_A1_models_init에_등록됨():
    assert "PaperTrade" in (APP / "models" / "__init__.py").read_text(encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════
# A2 배선 — 워커 + 스케줄러. 이 파일 작성 시점엔 미착수 → 아래 두 테스트는 FAIL 이 정상이다
# (머지되면 파일이 생기고 문자열이 등장해 저절로 PASS 로 바뀌어야 한다. 통과 안 하면 스펙과 어긋난 것)
# ══════════════════════════════════════════════════════════════════════

def test_A2_paper_trading_worker_모듈이_있다():
    assert (APP / "workers" / "paper_trading_worker.py").exists(), \
        "A2(워커) 미착수 — app/workers/paper_trading_worker.py 없음. 머지 전이면 이 실패는 정상."


def test_A2_스케줄러에_paper_trading_잡이_등록된다():
    s = (APP / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    assert 'id="paper_trading"' in s, "스케줄러에 paper_trading 잡 id 가 없다 (A2 미착수/오배선)"
    assert 'CronTrigger(minute="1,16,31,46")' in s, "크론이 매 15분(:01,:16,:31,:46) 이 아니다"
    assert "run_paper_trading_once" in s


# ══════════════════════════════════════════════════════════════════════
# A3 배선 — API. 이 파일 작성 시점엔 미착수 → 아래 테스트는 FAIL 이 정상이다
# ══════════════════════════════════════════════════════════════════════

def test_A3_paper_trading_API_라우터가_있다():
    api_file = APP / "api" / "v1" / "paper_trading.py"
    assert api_file.exists(), "A3(API) 미착수 — app/api/v1/paper_trading.py 없음. 머지 전이면 이 실패는 정상."
    s = api_file.read_text(encoding="utf-8")
    assert 'prefix="/paper-trading"' in s
    for path in ("/status", "/report", "/report.md", "/trades"):
        assert path in s, f"{path} 라우트가 없다"


def test_A3_라우터에_등록된다():
    r = (APP / "api" / "router.py").read_text(encoding="utf-8")
    assert "paper_trading" in r and "include_router" in r, "app/api/router.py 에 paper_trading 라우터 등록이 없다"

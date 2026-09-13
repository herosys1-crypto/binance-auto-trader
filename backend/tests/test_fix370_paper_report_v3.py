"""🧪 Fix 370 — 가상 매매 보고서 v3 (app/services/paper_report_v3.py). 매매 판정이 아닌 순수 통계/배선 테스트.

리드의 9/14 분석이 지목한 옛 보고서(`paper_trading_worker.build_report_from_db` → `PT.build_report`) 4대 결함을
겨냥한 새 설계를 검증한다: ① 메모리 가벼운 로더(스칼라 컬럼만) ② live 만(backfill 은 참고) ③ 같은 6시간 창
무작위 대비(전기간 아님) ④ 심볼×시간 클러스터(중복 발동 1건). 여기 실린 테스트는 전부 **순수 함수**
(`build_report_v3`)에 합성 행을 먹여서 본다 — DB 를 만지지 않는다.

담당 분리: 이 파일과 app/services/paper_report_v3.py 는 매매 판정(진입/손절/자본)이 아닌 분석 보고서다.
엔진(app/services/paper_trading.py)은 리드가 관리하고 여기서는 상수(PT.ENGINES 등)만 가져다 쓴다.
"""
from __future__ import annotations

import itertools
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services import paper_report_v3 as PR3
from app.services import paper_trading as PT

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"

_EMPTY_CTX = {"backfill": {}, "open_live": {}}
_ID_SEQ = itertools.count(1)


# ══════════════════════════════════════════════════════════════════════
# 도우미
# ══════════════════════════════════════════════════════════════════════

def dt(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=timezone.utc)


def _mk(symbol: str, side: str, rule: str, roi: float, opened_at: datetime, *, live_hit: str = "TP",
       tp1: float | None = PT.TP1_FLAT, done: bool = True, tags: list[str] | None = None,
       dist: float | None = None, extra_engines: dict | None = None, row_id: int | None = None) -> dict:
    engines: dict = {"live": {"roi": roi, "hit": live_hit, "done": done, "tp1_pct": tp1, "ambig_arm": None}}
    for name, edata in (extra_engines or {}).items():
        ed = {"roi": None, "hit": None, "done": None, "tp1_pct": None, "ambig_arm": None}
        ed.update(edata)
        engines[name] = ed
    return {"id": row_id if row_id is not None else next(_ID_SEQ), "symbol": symbol, "side": side, "rule": rule,
            "opened_at": opened_at, "status": "CLOSED", "tags": list(tags or []), "dist_high5d_pct": dist,
            "engines": engines}


def _baseline(side: str, n: int, day: date, hour: int, *, roi: float = 0.0, prefix: str = "BASE") -> list[dict]:
    return [_mk(f"{prefix}{i}USDT", side, f"baseline_{side}", roi, dt(day, hour, i % 60)) for i in range(n)]


def _report(rows: list[dict], lots: list | None = None, *, prereg_at: str = "2026-01-01T00:00:00+00:00",
           now: datetime | None = None) -> dict:
    return PR3.build_report_v3(rows, lots or [], _EMPTY_CTX, prereg_at=prereg_at,
                               now=now or datetime.now(timezone.utc))


# ══════════════════════════════════════════════════════════════════════
# 기준선 조정 — 같은 버킷 → 그 날 전체 → no_base
# ══════════════════════════════════════════════════════════════════════

def test_baseline_bucket_then_day_fallback_then_no_base():
    day1, day2 = date(2026, 9, 1), date(2026, 9, 2)
    # 버킷0(0~5시): 12건 기준선 roi=0 → 버킷 표본 충분(MIN_BUCKET_BASE=10) → 그 버킷 평균(0)을 쓴다
    bucket0_base = _baseline("LONG", 12, day1, 1, roi=0.0, prefix="B0")
    rule_bucket0 = _mk("RULEB0USDT", "LONG", "myrule", 5.0, dt(day1, 1, 0))
    # 버킷1(6~11시): 기준선 3건뿐(버킷 표본 부족) → 그 날 전체(12*0 + 3*2)/15=0.4 로 물러난다
    bucket1_base = _baseline("LONG", 3, day1, 7, roi=2.0, prefix="B1")
    rule_bucket1 = _mk("RULEB1USDT", "LONG", "myrule", 5.0, dt(day1, 7, 0))
    # day2: 기준선 5건뿐 — 버킷도 그 날 전체도 MIN_BUCKET_BASE(10) 미달 → base=None → no_base
    day2_base = _baseline("LONG", 5, day2, 1, roi=1.0, prefix="B2")
    rule_no_base = _mk("RULENBUSDT", "LONG", "myrule", 5.0, dt(day2, 1, 0))

    rows = bucket0_base + [rule_bucket0] + bucket1_base + [rule_bucket1] + day2_base + [rule_no_base]
    rep = _report(rows, now=dt(day2, 12, 0))
    st = rep["blocks"]["all"]["rules"]["LONG"]["myrule"]

    assert st["n"] == 3 and st["no_base"] == 1
    assert st["mean"] == pytest.approx(5.0)          # raw 평균은 기준선 유무와 무관
    assert st["clusters"] == 3 and st["days"] == 2    # 전체(raw) 유효 행 기준 — 필터 채택 게이트와 일관
    # adj 는 기준선 있는 2건만: 버킷0(5-0=5.0) · 버킷1(5-0.4=4.6)
    assert st["adj"] == pytest.approx((5.0 + 4.6) / 2, abs=1e-6)
    assert st["half"]["first"] is None, "adj 유효 행이 전부 day1 뿐이라 앞 절반은 비어야 한다"
    assert st["half"]["second"] == pytest.approx(st["adj"])


# ══════════════════════════════════════════════════════════════════════
# 클러스터 t — 같은 심볼×시간 중복은 하나로
# ══════════════════════════════════════════════════════════════════════

def test_cluster_count_collapses_duplicates_in_same_symbol_hour():
    day = date(2026, 9, 5)
    baseline = _baseline("LONG", 12, day, 1, roi=0.0)
    # 같은 심볼 · 같은 시(1시)에 10건이 겹쳐 발동 — roi 4/6 번갈아 (평균 5, 분산 有)
    dups = [_mk("DUPUSDT", "LONG", "duprule", 4.0 if i % 2 == 0 else 6.0, dt(day, 1, i)) for i in range(10)]
    rep = _report(baseline + dups, now=dt(day, 12, 0))
    st = rep["blocks"]["all"]["rules"]["LONG"]["duprule"]
    assert st["n"] == 10
    assert st["clusters"] == 1, "같은 심볼·같은 시간 10건은 클러스터 1개로 세야 한다(결함4)"
    # t = adj평균(5.0) / (pstdev(1.0)/sqrt(clusters=1)) = 5.0 — 만약 순진하게 sqrt(n=10) 을 썼다면 훨씬 컸을 것
    assert st["t"] == pytest.approx(5.0, abs=1e-6)


def test_cluster_count_counts_distinct_symbols_separately():
    day = date(2026, 9, 6)
    baseline = _baseline("LONG", 12, day, 1, roi=0.0)
    spread = [_mk(f"SPR{i}USDT", "LONG", "spreadrule", 4.0 if i % 2 == 0 else 6.0, dt(day, 1, i)) for i in range(10)]
    rep = _report(baseline + spread, now=dt(day, 12, 0))
    st = rep["blocks"]["all"]["rules"]["LONG"]["spreadrule"]
    assert st["clusters"] == 10, "심볼이 전부 다르면 클러스터도 10개"
    assert st["t"] > 5.0, "같은 Δ·분산이라도 클러스터가 많을수록(표준오차가 작아져) t 가 커야 한다"


# ══════════════════════════════════════════════════════════════════════
# 사전등록(prereg) 분리
# ══════════════════════════════════════════════════════════════════════

def test_prereg_split_excludes_rows_before_cutoff_and_rescopes_baseline():
    day1, day2 = date(2026, 9, 3), date(2026, 9, 4)
    baseline = _baseline("LONG", 12, day1, 1, roi=0.0)          # day1(사전등록 이전)에만 있는 기준선
    before = _mk("BEFOREUSDT", "LONG", "myrule", 5.0, dt(day1, 1, 0))
    after = _mk("AFTERUSDT", "LONG", "myrule", 5.0, dt(day2, 1, 0))
    rows = baseline + [before, after]
    prereg_at = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    rep = _report(rows, prereg_at=prereg_at, now=dt(day2, 2, 0))

    assert rep["n_live"] == len(rows)
    assert rep["blocks"]["all"]["rules"]["LONG"]["myrule"]["n"] == 2
    prereg_st = rep["blocks"]["prereg"]["rules"]["LONG"]["myrule"]
    assert prereg_st["n"] == 1, "사전등록 이전(before) 행은 prereg 블록에서 빠져야 한다"
    assert prereg_st["no_base"] == 1, "prereg 블록은 기준선도 그 블록 안(사전등록 이후)만 다시 골라 — day1 기준선은 안 보인다"
    assert rep["adoption"]["n_live"] == 1


# ══════════════════════════════════════════════════════════════════════
# 엔진 유효성 — v1 적응 TP(3.0) 행 배제
# ══════════════════════════════════════════════════════════════════════

def test_is_engine_valid_excludes_old_tp1_and_missing_fields():
    assert PR3.is_engine_valid({"roi": 1.0, "done": True, "tp1_pct": 15.0}, "live") is True
    assert PR3.is_engine_valid({"roi": 1.0, "done": True, "tp1_pct": 3.0}, "live") is False, \
        "v1 적응 TP(3) 로 계산된 옛 live 행은 표본에서 빠져야 한다"
    assert PR3.is_engine_valid({"roi": 1.0, "done": True, "tp1_pct": None}, "live") is True
    assert PR3.is_engine_valid({"roi": None, "done": True, "tp1_pct": 15.0}, "live") is False
    assert PR3.is_engine_valid({"roi": 1.0, "done": False, "tp1_pct": 15.0}, "live") is False
    assert PR3.is_engine_valid(None, "live") is False
    assert PR3.is_engine_valid({"roi": 1.0, "done": True, "tp1_pct": 3.0}, "house") is True, "house 는 TP1 확인 안 함"
    assert PR3.is_engine_valid({"roi": 1.0, "done": True, "tp1_pct": 3.0}, "live_adaptive") is True, \
        "레거시 엔진(v1)은 TP1 확인 대상이 아니다"


def test_build_report_excludes_old_tp1_row_from_rule_stats():
    day = date(2026, 9, 7)
    baseline = _baseline("LONG", 12, day, 1, roi=0.0)
    good = _mk("GOODUSDT", "LONG", "myrule", 5.0, dt(day, 1, 0), tp1=15.0)
    old = _mk("OLDUSDT", "LONG", "myrule", 9.0, dt(day, 1, 1), tp1=3.0)
    rep = _report(baseline + [good, old], now=dt(day, 12, 0))
    st = rep["blocks"]["all"]["rules"]["LONG"]["myrule"]
    assert st["n"] == 1 and st["mean"] == pytest.approx(5.0)


# ══════════════════════════════════════════════════════════════════════
# 청산 변형 — 짝 비교(diff) · 채택 true/false 경계 · ambig 공유 · 승률은 참고용
# ══════════════════════════════════════════════════════════════════════

def _exit_rows(n_days: int, per_day: int, *, live_roi_fn, var_roi_fn, variant: str, side: str = "SHORT",
              hit: str = "PROTECT", tag: str = "EX") -> list[dict]:
    rows = []
    day0 = date(2026, 9, 10)
    for d in range(n_days):
        day = day0 + timedelta(days=d)
        for i in range(per_day):
            sym = f"{tag}{variant}{d}_{i}USDT"
            rows.append(_mk(sym, side, "myrule", live_roi_fn(d, i), dt(day, 1, i % 60), live_hit="TRAIL",
                            extra_engines={variant: {"roi": var_roi_fn(d, i), "hit": hit, "done": True,
                                                     "tp1_pct": PT.TP1_FLAT}}))
    return rows


def test_exit_adopt_true_when_diff_positive_significant_and_both_halves_positive():
    rows = _exit_rows(8, 40, live_roi_fn=lambda d, i: 0.0,
                      var_roi_fn=lambda d, i: 4.0 if i % 2 == 0 else 6.0, variant="live_be10", tag="OK")
    rep = _report(rows, now=datetime(2026, 9, 20, tzinfo=timezone.utc))
    st = rep["blocks"]["all"]["exits"]["SHORT"]["live_be10"]
    assert st["n"] == 320 and st["clusters"] == 320 and st["days"] == 8
    assert st["diff"] == pytest.approx(5.0)
    assert st["t"] >= PR3.ADOPT_MIN_T
    assert st["half"]["first"] is not None and st["half"]["first"] > 0
    assert st["half"]["second"] is not None and st["half"]["second"] > 0
    assert st["adopt"] is True


def test_exit_adopt_false_when_not_enough_clusters():
    rows = _exit_rows(8, 10, live_roi_fn=lambda d, i: 0.0,
                      var_roi_fn=lambda d, i: 4.0 if i % 2 == 0 else 6.0, variant="live_be10", tag="FEW")
    rep = _report(rows, now=datetime(2026, 9, 20, tzinfo=timezone.utc))
    st = rep["blocks"]["all"]["exits"]["SHORT"]["live_be10"]
    assert st["clusters"] < PR3.ADOPT_MIN_CLUSTERS
    assert st["diff"] == pytest.approx(5.0) and st["t"] >= PR3.ADOPT_MIN_T   # 나머지는 좋아도
    assert st["adopt"] is False, "클러스터 문턱을 못 채우면 diff·t 가 좋아도 채택하면 안 된다"


def test_exit_adopt_false_when_diff_negative():
    rows = _exit_rows(8, 40, live_roi_fn=lambda d, i: 0.0,
                      var_roi_fn=lambda d, i: -4.0 if i % 2 == 0 else -6.0, variant="live_lock5", tag="NEG")
    rep = _report(rows, now=datetime(2026, 9, 20, tzinfo=timezone.utc))
    st = rep["blocks"]["all"]["exits"]["SHORT"]["live_lock5"]
    assert st["diff"] == pytest.approx(-5.0)
    assert st["adopt"] is False


def test_exit_adopt_false_when_one_half_is_negative():
    def var_roi(d, i):
        base = -5.0 if d < 4 else 15.0
        return base + (1.0 if i % 2 == 0 else -1.0)
    rows = _exit_rows(8, 40, live_roi_fn=lambda d, i: 0.0, var_roi_fn=var_roi, variant="live_be10", tag="HALF")
    rep = _report(rows, now=datetime(2026, 9, 20, tzinfo=timezone.utc))
    st = rep["blocks"]["all"]["exits"]["SHORT"]["live_be10"]
    assert st["diff"] == pytest.approx(5.0)                 # 전체 평균은 양수지만
    assert st["half"]["first"] < 0 and st["half"]["second"] > 0
    assert st["adopt"] is False, "앞 절반이 음수면 전체 평균·t 가 좋아도 채택하면 안 된다"


def test_exit_adopt_false_when_t_below_threshold_due_to_high_variance():
    rows = _exit_rows(8, 40, live_roi_fn=lambda d, i: 0.0,
                      var_roi_fn=lambda d, i: 5.0 + (50.0 if i % 2 == 0 else -50.0), variant="live_be10", tag="VAR")
    rep = _report(rows, now=datetime(2026, 9, 20, tzinfo=timezone.utc))
    st = rep["blocks"]["all"]["exits"]["SHORT"]["live_be10"]
    assert st["diff"] == pytest.approx(5.0)
    assert st["t"] is not None and st["t"] < PR3.ADOPT_MIN_T
    assert st["adopt"] is False


def test_exit_win_rate_is_informational_only_not_used_for_adopt():
    # be10 본전(ROI 정확히 0.0) 청산 — 승리로 세면 안 된다. live 는 -4/-6 이라 diff(0-(-4)=4, 0-(-6)=6) 는 여전히 양수·유의.
    rows = _exit_rows(8, 40, live_roi_fn=lambda d, i: -4.0 if i % 2 == 0 else -6.0,
                      var_roi_fn=lambda d, i: 0.0, variant="live_be10", tag="WIN")
    rep = _report(rows, now=datetime(2026, 9, 20, tzinfo=timezone.utc))
    st = rep["blocks"]["all"]["exits"]["SHORT"]["live_be10"]
    assert st["win"] == 0.0, "ROI 정확히 0.0(본전)은 승리로 세면 안 된다"
    assert st["diff"] == pytest.approx(5.0) and st["t"] >= PR3.ADOPT_MIN_T
    assert st["adopt"] is True, "승률이 0% 여도 diff·t·클러스터·반쪽 조건을 채우면 채택돼야 한다(승률은 참고용)"


def test_exit_ambig_share_computed_only_for_protect_exits():
    day = date(2026, 9, 15)
    rows = []
    for i in range(5):
        rows.append(_mk(f"AMB{i}USDT", "SHORT", "myrule", -5.0, dt(day, 1, i), live_hit="TRAIL",
                        extra_engines={"live_be10": {"roi": 0.0, "hit": "PROTECT", "done": True,
                                                     "tp1_pct": PT.TP1_FLAT, "ambig_arm": i < 2}}))
    # 승리 청산(TP1)행 하나 추가 — PROTECT 가 아니므로 ambig 분모(protect_n)에 안 들어간다
    rows.append(_mk("WINUSDT", "SHORT", "myrule", -5.0, dt(day, 1, 9), live_hit="TRAIL",
                    extra_engines={"live_be10": {"roi": 8.0, "hit": "TP", "done": True,
                                                 "tp1_pct": PT.TP1_FLAT, "ambig_arm": False}}))
    rep = _report(rows, now=dt(day, 12, 0))
    st = rep["blocks"]["all"]["exits"]["SHORT"]["live_be10"]
    assert st["hits"]["PROTECT"] == 5
    assert st["ambig_n"] == 2
    assert st["ambig_share"] == pytest.approx(0.4)


# ══════════════════════════════════════════════════════════════════════
# 진입 필터 — P1~P4 kept/excluded
# ══════════════════════════════════════════════════════════════════════

def test_filter_P1_drops_pre_registered_weak_rules():
    day = date(2026, 9, 20)
    weak = [_mk(f"W{i}USDT", "SHORT", "s1_breakdown", 3.0, dt(day, 1, i)) for i in range(4)]
    ok = [_mk(f"O{i}USDT", "SHORT", "confirm_peak_111", 3.0, dt(day, 1, i)) for i in range(4)]
    rep = _report(weak + ok, now=dt(day, 12, 0))
    f = rep["blocks"]["all"]["filters"]["SHORT"]["P1_drop_weak_rules"]
    assert f["universe"]["n"] == 8 and f["kept"]["n"] == 4 and f["excluded"]["n"] == 4


def test_filter_P2_ignores_rows_without_any_mkt_tag():
    day = date(2026, 9, 21)
    no_tag = [_mk(f"NT{i}USDT", "SHORT", "confirm_peak_111", 3.0, dt(day, 1, i), tags=[]) for i in range(5)]
    mkt_up = [_mk(f"UP{i}USDT", "SHORT", "confirm_peak_111", 3.0, dt(day, 1, i), tags=["MKT_UP"]) for i in range(3)]
    mkt_down = [_mk(f"DN{i}USDT", "SHORT", "confirm_peak_111", 3.0, dt(day, 1, i), tags=["MKT_DOWN"]) for i in range(2)]
    rep = _report(no_tag + mkt_up + mkt_down, now=dt(day, 12, 0))
    f = rep["blocks"]["all"]["filters"]["SHORT"]["P2_short_skip_mkt_down"]
    assert f["universe"]["n"] == 5, "MKT_* 태그가 아예 없는(9/10 이전) 행은 universe 밖이어야 한다"
    assert f["kept"]["n"] == 3 and f["excluded"]["n"] == 2


def test_filter_P3_long_deep_pullback_uses_numeric_dist_only():
    day = date(2026, 9, 22)
    none_dist = [_mk(f"ND{i}USDT", "LONG", "myrule", 3.0, dt(day, 1, i), dist=None) for i in range(2)]
    shallow = [_mk(f"SH{i}USDT", "LONG", "myrule", 3.0, dt(day, 1, i), dist=-5.0) for i in range(3)]
    deep = [_mk(f"DP{i}USDT", "LONG", "myrule", 3.0, dt(day, 1, i), dist=-15.0) for i in range(4)]
    rep = _report(none_dist + shallow + deep, now=dt(day, 12, 0))
    f = rep["blocks"]["all"]["filters"]["LONG"]["P3_long_deep_pullback"]
    assert f["universe"]["n"] == 7 and f["kept"]["n"] == 4 and f["excluded"]["n"] == 3


def test_filter_P4_first_rule_per_hour_orders_by_opened_at_then_id():
    day = date(2026, 9, 23)
    hour_ts = dt(day, 1, 0)
    r1 = _mk("SAMEUSDT", "LONG", "ruleA", 3.0, hour_ts + timedelta(minutes=5), row_id=10)
    r2 = _mk("SAMEUSDT", "LONG", "ruleB", 4.0, hour_ts + timedelta(minutes=2), row_id=5)
    r3 = _mk("SAMEUSDT", "LONG", "ruleC", 5.0, hour_ts + timedelta(minutes=2), row_id=1)   # 같은 opened_at, id 더 작음
    other_hour = _mk("SAMEUSDT", "LONG", "ruleD", 6.0, hour_ts + timedelta(hours=1), row_id=20)
    rep = _report([r1, r2, r3, other_hour], now=dt(day, 12, 0))
    f = rep["blocks"]["all"]["filters"]["LONG"]["P4_first_rule_per_hour"]
    assert f["kept"]["n"] == 2 and f["excluded"]["n"] == 2
    assert f["kept"]["mean"] == pytest.approx((5.0 + 6.0) / 2), \
        "같은 (opened_at, id) 동률에서 id 가 더 작은 r3 가 남아야 한다"
    assert f["excluded"]["mean"] == pytest.approx((4.0 + 3.0) / 2)


def test_filter_P1_adopt_true_when_kept_clearly_beats_excluded_across_days():
    day0 = date(2026, 9, 26)
    rows = []
    for d in range(8):
        day = day0 + timedelta(days=d)
        for i in range(40):
            rows.append(_mk(f"KP{d}_{i}USDT", "SHORT", "confirm_peak_111", 5.0, dt(day, 1, i % 60)))
            rows.append(_mk(f"EX{d}_{i}USDT", "SHORT", "s1_breakdown", -5.0, dt(day, 1, i % 60)))
    rep = _report(rows, now=dt(day0 + timedelta(days=8), 0, 0))
    f = rep["blocks"]["all"]["filters"]["SHORT"]["P1_drop_weak_rules"]
    assert f["kept"]["clusters"] >= PR3.ADOPT_MIN_CLUSTERS
    assert f["day_edge"]["days_with_both"] >= PR3.ADOPT_MIN_DAYS
    assert f["kept"]["mean"] > f["excluded"]["mean"]
    assert f["adopt"] is True


# ══════════════════════════════════════════════════════════════════════
# weak_flag — 관측된 「지금 나쁜」 신호(사전 등록 WEAK_RULES 와 별개)
# ══════════════════════════════════════════════════════════════════════

def test_weak_flag_when_adj_negative_and_t_below_negative_threshold():
    day = date(2026, 9, 25)
    baseline = _baseline("SHORT", 12, day, 1, roi=0.0)
    bad = [_mk(f"WF{i}USDT", "SHORT", "s1_breakdown", -4.0 if i % 2 == 0 else -6.0, dt(day, 1, i)) for i in range(6)]
    rep = _report(baseline + bad, now=dt(day, 12, 0))
    st = rep["blocks"]["all"]["rules"]["SHORT"]["s1_breakdown"]
    assert st["adj"] == pytest.approx(-5.0)
    assert st["t"] is not None and st["t"] <= -PR3.ADOPT_MIN_T
    assert st["weak_flag"] is True
    assert st["adopt"] is False
    assert st["pre_flagged_weak"] is True, "s1_breakdown 은 WEAK_RULES[SHORT] 사전 등록 목록에 있다"


def test_weak_rules_constant_matches_spec():
    assert PR3.WEAK_RULES["LONG"] == {"surge_start_346", "mach7_trap_long"}
    assert PR3.WEAK_RULES["SHORT"] == {"s1_breakdown", "off8_267", "fujimoto_s1_rsi", "mach7_trap_short"}


# ══════════════════════════════════════════════════════════════════════
# 렌더링 — 빈 보고서에서도 안 죽는다
# ══════════════════════════════════════════════════════════════════════

def test_render_markdown_v3_smoke_on_empty_report():
    rep = _report([], now=datetime(2026, 9, 14, tzinfo=timezone.utc))
    md = PR3.render_markdown_v3(rep)
    assert "가상 매매 보고서 v3" in md and "아직 없음" in md


# ══════════════════════════════════════════════════════════════════════
# 정적 배선 — 메모리 가벼운 쿼리 · 신구 함수 공존 · API 라우트 · 사전등록 스탬프
# ══════════════════════════════════════════════════════════════════════

def _code_only(src: str) -> str:
    """맨 앞 모듈 docstring(산문 설명)은 빼고 본다 — 「이렇게 하면 안 된다」는 설명 문구 자체가 오탐을 낼 수 있다."""
    if src.startswith('"""'):
        end = src.find('"""', 3)
        if end != -1:
            return src[end + 3:]
    return src


def test_no_full_orm_or_whole_jsonb_column_selects():
    raw = (APP / "services" / "paper_report_v3.py").read_text(encoding="utf-8")
    src = _code_only(raw)
    assert "select(PaperTrade)" not in src, "ORM 전체 로딩 금지(1.8GB 사고 재발 방지)"
    assert "PaperTrade.engines," not in src, "engines 전체 컬럼 select 금지"
    assert "PaperTrade.snapshot," not in src, "snapshot 전체 컬럼 select 금지"
    assert ".astext" in src
    assert "yield_per" in src


def test_worker_keeps_old_report_and_adds_v3():
    src = (APP / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    assert "def build_report_from_db(" in src, "옛 함수는 고정 테스트가 있어 그대로 둬야 한다"
    assert "def build_report_v3_from_db(" in src
    assert '"--v3"' in src


def test_worker_stamps_prereg_at_once_and_never_overwrites():
    src = (APP / "workers" / "paper_trading_worker.py").read_text(encoding="utf-8")
    assert "if not _setting(db, PR3.PREREG_SETTING_KEY):" in src, \
        "이미 값이 있으면 절대 덮지 않는 가드가 있어야 한다"
    assert "_set_setting(db, PR3.PREREG_SETTING_KEY, _prereg_now)" in src
    assert "사전등록 시각 기록" in src
    # 가드 if 문 안에서만 스탬프가 나오는지(들여쓰기로 확인) — 무조건 스탬프하면 재배포마다 밀려 사전등록이 무의미해진다
    i = src.find("if not _setting(db, PR3.PREREG_SETTING_KEY):")
    block = src[i:i + 400]
    assert "_set_setting(db, PR3.PREREG_SETTING_KEY" in block


def test_api_routes_exist_for_v3_and_legacy():
    src = (APP / "api" / "v1" / "paper_trading.py").read_text(encoding="utf-8")
    assert 'prefix="/paper-trading"' in src
    for path in ('"/status"', '"/report"', '"/report.md"', '"/report/legacy"', '"/report/legacy.md"', '"/trades"'):
        assert path in src, f"{path} 라우트가 없다"

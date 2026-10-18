"""🏁 Fix 471 — 일목 실험실 승격 관문 (사장님 10/18 「가상매매를 통해서 확실하게 성공하는 전략을 만들어줘」)."""
from __future__ import annotations

import ast
import pathlib
import random

from app.services import ichikijun_promo as PR

DAY = PR.DAY
P = PR.params_from(None)
P_FAST = {**P, "ichipromo_boot": 400}


def _rows(days, per_day, sig_fn, rand_fn=lambda d, i: 0.0, var="4h_src_pb_r15", side="SHORT", btc=lambda d: d % 2 == 0):
    out = []
    for d in range(days):
        for i in range(per_day):
            key = f"{var}|{side}|S{i}|{d * DAY}"
            out.append({"kind": "sig", "variant": var, "side": side, "symbol": f"S{i}", "entry_bar_ts": d * DAY,
                        "r_net": sig_fn(d, i), "pair_key": key, "btc_up": btc(d)})
            out.append({"kind": "rand", "variant": var, "side": side, "symbol": "R", "entry_bar_ts": d * DAY,
                        "r_net": rand_fn(d, i), "pair_key": key, "btc_up": btc(d)})
    return out


def _one(rows, applied=(), p=P_FAST):
    return next(iter(PR.evaluate_all(rows, list(applied), p).values()))


def test_clear_edge_passes_all_gates():
    rng = random.Random(1)
    g = _one(_rows(70, 2, lambda d, i: 0.3 + rng.gauss(0, 0.2)))
    assert g["status"] == PR.PASS and all(g["gates"][k] for k in ("G1", "G2", "G3", "G4", "G5", "G6"))
    assert g["gates"]["G7"] is None


def test_small_sample_is_watch_not_fail():
    g = _one(_rows(30, 2, lambda d, i: 1.0))
    assert g["status"] == PR.WATCH and g["gates"]["G1"] is False and g["gates"]["G2"] is None


def test_beating_random_but_losing_fails_g3():
    g = _one(_rows(70, 2, lambda d, i: -0.1, rand_fn=lambda d, i: -0.6))
    assert g["status"] == PR.FAIL and g["gates"]["G3"] is False and g["gates"]["G2"] is True


def test_month_consistency_g6():
    # 70일 = 3개 달(1월 31 · 2월 28 · 3월 11). 1월만 + 이고 나머지 달은 무작위보다 못하면 G6 실패
    g = _one(_rows(70, 2, lambda d, i: 1.5 if d < 31 else -0.05))
    assert g["detail"]["months"]["counted"] == 3 and g["detail"]["months"]["positive"] == 1
    assert g["gates"]["G6"] is False and g["status"] == PR.FAIL                      # 상태까지 고정 (교차 감사)


def test_btc_one_sided_does_not_block():
    # 🗾 이 전략은 BTC 장세 한쪽에서만 거래한다 — 장세 관문으로 막지 않는다(10/18 교체 이유)
    g = _one(_rows(70, 2, lambda d, i: 0.3, btc=lambda d: True))
    assert g["gates"]["G6"] is True and g["status"] == PR.PASS


def test_top_days_dependency_fails_g5():
    g = _one(_rows(70, 2, lambda d, i: 30.0 if d < 3 else -0.05))
    assert g["gates"]["G5"] is False and g["status"] == PR.FAIL


def test_second_half_negative_fails_g4():
    g = _one(_rows(70, 2, lambda d, i: 0.6 if d < 35 else -0.1))
    assert g["gates"]["G4"] is False


def test_multiple_comparison_quantile_flips_g2():
    """같은 줄이 95% 기준이면 G2 통과, 72줄 보정 99.9% 기준이면 실패 (교차 감사: 「자명한 비교」 대신 판정이 뒤집히는 경우)."""
    rng = random.Random(0)
    rows = _rows(70, 2, lambda d, i: 0.07 + rng.gauss(0, 0.35))           # 약한 우위
    loose = _one(rows, p={**P_FAST, "ichipromo_q": 0.025})
    strict = _one(rows, p=P_FAST)
    assert loose["gates"]["G2"] is True and strict["gates"]["G2"] is False
    assert strict["status"] == PR.FAIL


def test_mostly_unpaired_is_not_a_sample():
    rows = _rows(70, 2, lambda d, i: 0.5)
    rows = [r for r in rows if not (r["kind"] == "rand" and (r["entry_bar_ts"] // DAY) % 2 == 1)]   # 절반의 날 짝 없음
    g = _one(rows)
    assert g["gates"]["G1"] is False and g["status"] == PR.WATCH


def test_live_gap_gate():
    rows = _rows(70, 2, lambda d, i: 0.4)
    bad = [{"variant": "4h_src_pb_r15", "side": "SHORT", "live_r": -0.5, "lab_r": 0.4}] * 10
    ok = [{"variant": "4h_src_pb_r15", "side": "SHORT", "live_r": 0.3, "lab_r": 0.4}] * 10
    assert _one(rows, bad)["gates"]["G7"] is False and _one(rows, bad)["status"] == PR.FAIL
    assert _one(rows, ok)["gates"]["G7"] is True and _one(rows, ok)["status"] == PR.PASS
    assert _one(rows, ok[:9])["gates"]["G7"] is None                      # 10건 미만 = 아직 적용 안 함


def test_deterministic():
    rng = random.Random(3)
    rows = _rows(70, 2, lambda d, i: 0.2 + rng.gauss(0, 0.3))
    assert _one(rows) == _one(list(reversed(rows)))


def test_transitions():
    assert PR.transitions({"a|LONG"}, {"a|LONG", "b|SHORT"}) == (["b|SHORT"], [])
    assert PR.transitions({"a|LONG"}, set()) == ([], ["a|LONG"])


def test_params_bounds():
    p = PR.params_from(lambda k: {"ichipromo_q": "0.5", "ichipromo_min_days": "30", "ichipromo_live_gap": "1",
                                  "ichipromo_month_share": "0.2"}.get(k))
    assert p["ichipromo_month_share"] == 0.667
    assert p["ichipromo_q"] == 0.001 and p["ichipromo_min_days"] == 30 and p["ichipromo_live_gap"] == -0.3


def test_no_order_imports():
    src = pathlib.Path(PR.__file__).read_text(encoding="utf-8")
    mods = {n.module or "" for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)}
    assert not any(b in m for m in mods for b in ("execution", "order", "database"))

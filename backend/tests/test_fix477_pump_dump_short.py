"""Fix 477 세력 펌프·덤프 SHORT 마틴게일 — 신호·두 안 숫자·그림자 기록·사후 채점."""
from __future__ import annotations

import json
import math

from app.services import pump_dump_short as P

DAY = 86_400_000


def _kl(closes, qv=None, highs=None):
    out = []
    for i, c in enumerate(closes):
        hi = highs[i] if highs else c * 1.01
        out.append([i * DAY, str(c), str(hi), str(c * 0.99), str(c), "1", (i + 1) * DAY - 1, str((qv[i] if qv else 1000.0))])
    return out


def _signal_kl(next_close=12.0):
    closes = [5.0] * 60 + [6.0, 10.0, next_close]          # 60일 바닥 5 → 전날 6 → 급등 10(+67%) → 다음 날
    qv = [1000.0] * 61 + [20000.0, 5000.0]                 # 급등 날 거래대금 ×20
    return _kl(closes, qv)


def test_plan_numbers_match_owner_answers():
    a = P.PLANS["a"].numbers()
    b = P.PLANS["b"].numbers()
    assert a["total"] == 2910 and b["total"] == 1400
    assert math.isclose(a["mults"][-1], 1.15 ** 3) and math.isclose(b["mults"][-1], 1.44)
    assert round(b["loss_last"]) == 104                    # 사장님과 확인한 「3단계 진입 때 −104」
    assert round(b["stop_loss_usdt"]) == 560 and round(a["stop_loss_usdt"]) == 873
    assert round((b["stop"] - 1) * 100) == 88 and round((a["stop"] - 1) * 100) == 85
    assert b["liq"] > b["stop"] and a["liq"] > a["stop"]  # 손절이 청산보다 안쪽(레버 1)


def test_detect_signal_and_rejects():
    k = _signal_kl(next_close=9.0)                        # 다음 날 음봉
    s = P.detect(k)
    assert s and s["entry_ref"] == 9.0 and s["surge_close"] == 10.0 and math.isclose(s["half"], 8.0)
    assert P.detect(_signal_kl(next_close=11.0)) is None   # 다음 날 양봉 = 신호 아님
    low_vol = _signal_kl(9.0)
    low_vol[-2][7] = "5000"                                # ×5
    assert P.detect(low_vol) is None
    small = _kl([5.0] * 60 + [9.0, 12.0, 11.0], [1000.0] * 61 + [20000.0, 1.0])   # +33% 이지만 랠리 12/4.95 < +100%? → +142% 라 신호
    assert P.detect(small) is not None
    no_rally = _kl([8.0] * 60 + [9.0, 12.0, 11.0], [1000.0] * 61 + [20000.0, 1.0])  # 60일 최저 7.92 → 12.12/7.92 = +53%
    assert P.detect(no_rally) is None
    assert P.detect([]) is None and P.detect(_kl([1.0] * 10)) is None
    bad = _signal_kl(9.0)
    bad[-5][4] = "nan"
    assert P.detect(bad) is None


def test_params_bounds():
    p = P.params_from(lambda k: "garbage")
    assert p["mode"] == "shadow" and p["plan"] == "a" and p["lev"] == 1 and p["max_concurrent"] == 3 and math.isclose(p["surge"], 0.30)
    p2 = P.params_from(lambda k: {"pds_mode": "ON", "pds_plan": "B", "pds_leverage": "9"}.get(k, P.SETTINGS[k][0]))
    assert p2["mode"] == "on" and p2["plan"] == "b" and p2["lev"] == 1   # 레버 범위 밖 = 기본 1
    assert P.SETTINGS["pds_mode"][0] == "shadow"


class _R:
    def __init__(self):
        self.d = {}

    def set(self, k, v, nx=False, ex=None):
        if nx and k in self.d:
            return None
        self.d[k] = v
        return True


def test_record_shadow_once():
    r = _R()
    s = P.detect(_signal_kl(9.0))
    assert P.record_shadow(r, "XUSDT", s, {"whale": True}) and not P.record_shadow(r, "XUSDT", s)
    rec = json.loads(next(iter(r.d.values())))
    assert rec["symbol"] == "XUSDT" and rec["whale"] is True and set(rec["plans"]) == {"a", "b"}


def test_simulate_tp_stop_and_stage_counts():
    # 1단계만 들어가고 바로 절반 반납 → 익절 · 이김
    h = [10.0, 10.2, 10.0]
    lw = [9.0, 7.5, 7.0]
    c = [10.0, 8.0, 7.5]
    r = P.simulate(h, lw, c, 0, half=8.0, plan=P.PLANS["b"])
    assert r["why"] == "익절" and r["stages"] == 1 and r["pnl"] > 0
    # 계속 올라 3단계 다 들어간 뒤 손절(+88%)
    h2 = [10.0, 13.0, 15.0, 19.5]
    lw2 = [9.9, 10.5, 12.5, 15.0]
    c2 = [10.0, 12.5, 14.8, 19.0]
    r2 = P.simulate(h2, lw2, c2, 0, half=8.0, plan=P.PLANS["b"])
    assert r2["why"] == "손절" and r2["stages"] == 3 and round(r2["pnl"]) < -555
    # 끝나지 않은 신호 = None
    assert P.simulate([10.0, 10.1], [9.9, 9.8], [10.0, 10.0], 0, half=1.0, plan=P.PLANS["a"]) is None


def test_daily_hook_modes():
    k = _signal_kl(9.0)
    for mode, want_rec, want_cand in (("off", 0, 0), ("shadow", 1, 0), ("on", 1, 1)):
        r, st = _R(), {}
        p = {**P.params_from(), "mode": mode}
        P.make_daily_hook(r, p, st)("XUSDT", k, {"mcap": 5e7, "float": 0.3})
        assert len(r.d) == want_rec and len(st.get("candidates") or []) == want_cand, mode
    r, st = _R(), {}
    P.make_daily_hook(r, {**P.params_from(), "mode": "on", "whale_only": True}, st)("YUSDT", k, {"mcap": 5e9, "float": 0.9})
    assert len(r.d) == 1 and st["candidates"] == []             # 🐋 만 실주문 후보 — 그림자는 그래도 기록


def test_control_room_panel_and_scheduler_hook():
    from app.services import auto_control as AC
    assert any(p.fam == "pds" and p.job == "pump_profile" for p in AC._external_panels())
    import pathlib
    src = (pathlib.Path(AC.__file__).resolve().parents[1] / "workers" / "scheduler_runner.py").read_text(encoding="utf-8")
    assert "on_kl=PDS.make_daily_hook(r_, pds_p, pds_stat)" in src

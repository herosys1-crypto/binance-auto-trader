"""🕯 Fix 360 — v2.20 캔들 세력 공방 수치화 (몸통·꼬리) 단위 테스트 + 배선 정적 검사.

합성 봉으로 정의 자체를 고정한다: LONG 단일봉 해머(기본) / 두 봉(꼬리봉→확인봉) 형태, SHORT 윗꼬리봉→음봉,
도지 제외, confirm_peak 필터(직전 4봉), 몸통 성장 판정(G3A 기본 / 엄격 옵션), 설정 파싱·범위 가드, 배선 순서.
"""
from pathlib import Path

from app.services import candle_battle as CB

ROOT = Path(__file__).resolve().parents[1] / "app"
CFG = CB.CandleCfg()      # = 측정 기본값


def _flat(n=120, px=100.0, rng=1.0):
    return [[i * 900000.0, px, px + rng / 2, px - rng / 2, px, 10.0] for i in range(n)]


def _with(**kv):
    return CB.CandleCfg(**{**CFG.__dict__, **kv})


def test_metrics_and_atr():
    m = CB.metrics([0, 100, 104, 96, 99.8])
    assert m and abs(m["range"] - 8) < 1e-9 and abs(m["body"] - 0.2) < 1e-9
    assert abs(m["lower_wick"] - 3.8) < 1e-9 and abs(m["upper_wick"] - 4.0) < 1e-9
    assert m["bearish"] and not m["bullish"]
    assert CB.metrics([0, 100, 100, 100, 100]) is None
    assert abs(CB.atr_range(_flat(20), 14) - 1.0) < 1e-9 and CB.atr_range(_flat(5), 14) is None


def test_long_hammer_default_form():
    """기본 LONG 형태 = 단일봉 해머: 양봉 + 아래꼬리 ≥ 0.5 + 범위 ≥ 0.8×ATR + 저가가 24h 최저 3% 안."""
    bars = _flat()
    bars.append([0, 99.8, 100.2, 96.0, 100.1, 10])     # 아래꼬리 3.8/4.2=0.90, 양봉, 신저가
    ok, why, d = CB.reversal_signal(bars, "LONG")
    assert ok and d["form"] == "hammer" and d["zone"] == "extreme24h", why
    bars[-1] = [0, 100.1, 100.2, 96.0, 99.8, 10]       # 같은 꼬리인데 음봉 → 해머 아님
    assert not CB.reversal_signal(bars, "LONG")[0]
    # 구역 밖: 저가 104.5 > 24h 최저 99.5×1.03
    bars2 = _flat()
    bars2.append([0, 107.8, 108.2, 104.5, 108.1, 10])
    ok2, why2, _ = CB.reversal_signal(bars2, "LONG")
    assert not ok2 and "구역" in why2
    assert CB.reversal_signal(bars2, "LONG", _with(zone_long="none"))[0]


def test_long_two_bar_form_option():
    bars = _flat()
    bars.append([0, 100.0, 100.2, 96.0, 99.8, 10])     # 꼬리봉(음봉이어도 됨)
    bars.append([0, 99.8, 101.0, 99.5, 100.9, 10])     # 양봉 확인, 몸통 0.73, 종가 > 꼬리봉 중간(98.1)
    cfg = _with(form_long="two_bar")
    ok, why, d = CB.reversal_signal(bars, "LONG", cfg)
    assert ok and d["form"] == "two_bar", why
    bars[-1] = [0, 99.8, 100.0, 97.0, 97.5, 10]        # 확인봉이 음봉
    ok2, why2, _ = CB.reversal_signal(bars, "LONG", cfg)
    assert not ok2 and "확인봉" in why2


def test_doji_is_not_a_signal():
    bars = _flat(rng=4.0)                               # ATR 4 → 범위 0.42 짜리 봉은 도지
    bars.append([0, 99.6, 100.02, 99.6, 99.98, 10])    # 양봉, 아래꼬리 0/… → 꼬리 자체가 없음; 꼬리 있는 도지도 검사
    bars[-1] = [0, 99.98, 100.02, 99.6, 100.0, 10]     # 아래꼬리 0.38/0.42=0.90, 양봉, 범위 0.42 < 0.8×4
    ok, why, _ = CB.reversal_signal(bars, "LONG")
    assert not ok and "도지" in why


def test_short_two_bar_default_with_bb_zone():
    bars = _flat()
    bars.append([0, 100.0, 104.0, 99.8, 100.2, 10])    # 윗꼬리 3.8/4.2, 종가 100.2 → %B ≫ 0.85 (평탄 뒤 튐)
    bars.append([0, 100.2, 100.4, 98.8, 99.0, 10])     # 음봉, 몸통 0.75, 종가 < 중간(101.9)
    ok, why, d = CB.reversal_signal(bars, "SHORT")
    assert ok and d["form"] == "two_bar" and d["zone"] == "bb", why
    assert CB.reversal_signal(bars, "SHORT", _with(confirm_mode="extreme"))[0]        # 99.0 < 저가 99.8
    bars[-1] = [0, 100.2, 100.4, 99.6, 99.9, 10]       # 종가 99.9 > 저가 99.8 → extreme ✗, mid ✓
    assert not CB.reversal_signal(bars, "SHORT", _with(confirm_mode="extreme"))[0]
    assert CB.reversal_signal(bars, "SHORT")[0]
    assert not CB.reversal_signal(bars, "LONG")[0]


def test_recent_wick_bar_addon_for_confirm_peak():
    """측정 셀 = 「loose」 꼬리봉(꼬리 ≥ 0.4) 이 발동 봉 포함 5봉 안에 (반박 검증이 0.5·4봉 배선을 잡아 고침)."""
    bars = _flat()
    bars.append([0, 100.0, 104.0, 99.8, 100.2, 10])    # 꼬리봉 + 구역 (발동 봉에서 4봉 전 = 창의 끝)
    for _ in range(3):
        bars.append([0, 100.2, 100.6, 99.9, 100.3, 10])
    bars.append([0, 100.3, 100.5, 99.7, 99.9, 10])     # confirm_peak 발동 봉
    ok, why, d = CB.recent_wick_bar(bars, "SHORT")
    assert ok and d["bars_ago"] == 4 and d["lookback"] == 5, why
    assert not CB.recent_wick_bar(bars, "SHORT", lookback=4)[0]        # 4봉 창이면 놓친다
    assert not CB.recent_wick_bar(_flat(), "SHORT")[0]
    ok0, _, d0 = CB.recent_wick_bar(bars[:10], "SHORT")
    assert not ok0 and d0["checked"] == 0                              # 봉 부족 = 판정 불가 (gate 는 fail-open)
    # 애드온은 꼬리 0.4 부터, 두 봉 규칙은 0.5 부터
    loose = _flat() + [[0, 100.3, 102.0, 99.9, 101.1, 10]]             # 윗꼬리 0.9/2.1 = 0.43 ≥ 몸통 0.8 → 애드온(0.4)만 통과
    assert CB.recent_wick_bar(loose, "SHORT")[0]
    assert not CB.wick_bar_ok(loose[-1], "SHORT", CFG, CB.atr_range(loose[:-1]))[0]


def test_zone_needs_full_24h_and_flat_atr_rejects():
    short_hist = _flat(50) + [[0, 99.8, 100.2, 96.0, 100.1, 10]]       # 24h 봉이 96개 안 됨
    ok, why, _ = CB.reversal_signal(short_hist, "LONG")
    assert not ok and "구역" in why and "봉 부족" in why
    flat0 = [[i * 900000.0, 100.0, 100.0, 100.0, 100.0, 1.0] for i in range(120)] + [[0, 99.8, 100.2, 96.0, 100.1, 10]]
    ok2, why2, _ = CB.reversal_signal(flat0, "LONG")
    assert not ok2 and "ATR" in why2


def test_body_growth_for_pyramiding():
    # 기본(G3A): 마지막 완성봉 추세 방향, 몸통/범위 ≥ 0.5, 몸통 ≥ 0.5×ATR(이전 14봉), 반대 꼬리 ≤ 0.3
    bars = _flat(rng=1.0) + [[0, 100.0, 100.1, 98.9, 99.0, 1]]      # 음봉 몸통 1.0/1.2=0.83, 아래꼬리 0.1/1.2
    ok, why, d = CB.body_growth(bars, "SHORT")
    assert ok and abs(d["body_ratio"] - 0.8333) < 1e-3, why
    assert not CB.body_growth(bars, "LONG")[0]
    # 반대(아래) 꼬리가 크면 ✗
    bars[-1] = [0, 100.0, 100.05, 97.0, 98.4, 1]                      # 몸통 1.6/3.05=0.52 ✓, 아래꼬리 1.4/3.05=0.46 > 0.3
    ok2, why2, _ = CB.body_growth(bars, "SHORT")
    assert not ok2 and "반대 꼬리" in why2
    # 몸통이 ATR 대비 작으면 ✗ (ATR 1.0, 몸통 0.2 < 0.5)
    bars[-1] = [0, 100.0, 100.05, 99.75, 99.8, 1]
    ok3, why3, _ = CB.body_growth(bars, "SHORT")
    assert not ok3 and ("ATR" in why3 or "몸통" in why3)
    # 엄격(기획서 원문): 3봉 연속 커져야
    strict = _with(growth_bars=3, growth_strict=True)
    grow = _flat() + [[0, 100, 100.1, 99.4, 99.5, 1], [0, 99.5, 99.6, 98.7, 98.8, 1], [0, 98.8, 98.9, 97.7, 97.8, 1]]
    assert CB.body_growth(grow, "SHORT", strict)[0]
    shrink = grow[:-1] + [[0, 98.8, 98.9, 98.2, 98.3, 1]]
    ok4, why4, _ = CB.body_growth(shrink, "SHORT", strict)
    assert not ok4 and "커지지" in why4


class _DB:
    def __init__(self, **kv):
        self.kv = kv

    def get(self, _m, key):
        return type("R", (), {"value": self.kv[key]})() if key in self.kv else None


def test_settings_parsing_and_guards():
    assert CB.cfg_from_db(None) == CB.DEFAULT_CFG
    c = CB.cfg_from_db(_DB(candle_battle_wick_ratio_min="0.6", candle_battle_zone_short="extreme24h",
                           candle_battle_growth_bars="3", candle_battle_confirm_mode="EXTREME",
                           candle_battle_range_atr_mult_min="99", candle_battle_form_long="two_bar",
                           candle_battle_growth_strict="1"))
    assert c.wick_ratio_min == 0.6 and c.zone_short == "extreme24h" and c.growth_bars == 3
    assert c.confirm_mode == "extreme" and c.form_long == "two_bar" and c.growth_strict is True
    assert c.range_atr_mult_min == CB.DEFAULT_CFG.range_atr_mult_min        # 범위 밖 → 기본
    assert CB.mode(_DB(), CB.S_MODE_SHORT) == "shadow"
    assert CB.mode(_DB(candle_battle_mode_short="gate"), CB.S_MODE_SHORT) == "gate"
    assert CB.mode(_DB(candle_battle_mode_short="on"), CB.S_MODE_SHORT) == "shadow"   # 허용값 아님 → 기본
    assert CB.mode(_DB(pyramid_body_growth_mode="off"), CB.S_MODE_PYRAMID) == "off"


def test_completed_only_drops_open_bar():
    now = 10_000_000
    kl = [[now - 1_800_000, "1", "2", "0.5", "1.5", "9", now - 900_001], [now - 900_000, "1", "2", "0.5", "1.5", "9", now + 899_999]]
    out = CB.completed_only(kl, now)
    assert len(out) == 1 and out[0][1] == 1.0
    assert len(CB.completed_only(kl)) == 2


def test_compact_is_small_and_json_safe():
    ok, why, d = CB.reversal_signal(_flat() + [[0, 99.8, 100.2, 96.0, 100.1, 10]], "LONG")
    c = CB.compact(ok, why, d)
    assert c["ok"] is True and c["form"] == "hammer" and "wick" in c and set(c["wick"]) <= {"body_ratio", "uwick_ratio", "lwick_ratio", "bullish"}
    import json
    json.dumps(c)


# ── 배선 정적 검사 ──────────────────────────────────────────────────────────────

def test_journal_rules_registered_and_label_version_bumped():
    from app.services import chart_learning as CL
    keys = {r.key: r for r in CL.RULES}
    assert "wick_rev_short_v220" in keys and keys["wick_rev_short_v220"].side == "SHORT"
    assert "wick_rev_long_v220" in keys and keys["wick_rev_long_v220"].side == "LONG"
    assert keys["wick_rev_long_v220"].origin == "candidate" and keys["wick_rev_short_v220"].origin == "candidate"
    assert CL.LABEL_VERSION >= 3, "규칙을 더했으면 LABEL_VERSION 을 올려 옛 행이 재라벨되게"


def test_short_worker_wiring_order_and_fail_open():
    s = (ROOT / "workers" / "auto_short_at_top_worker.py").read_text(encoding="utf-8")
    i_111 = s.find('logger.info("[auto_short_top+Fix111]')
    i_346 = s.find("Fix 346 (2026-09-04 사장님, MINIMAXUSDT")
    i_350 = s.find('logger.warning("[Fix350] %s 1h 판정 오류')
    i_360 = s.find("_cb360.recent_wick_bar(_cb_bars, \"SHORT\"")
    i_go = s.find("# 7. 자동 진입!")
    assert 0 < i_111 < i_346 < i_350 < i_360 < i_go, "confirm_peak → Fix 346(LONG 인계) → Fix 350 → Fix 360 필터 → 진입 순서"
    blk = s[i_360 - 1500:i_360 + 1400]
    assert 'elif _cb_mode == "gate" and _cb_bars and int(_cb_det.get("checked", 0)) > 0:' in blk, \
        "gate 는 봉이 있고 판정을 실제로 했을 때만 막는다 (봉 부족·조회 실패 = fail-open)"
    assert "skipped += 1" in blk and "fail-open" in blk and "except Exception as _e360" in blk
    assert 'entry_snapshot["candle_battle"] = _cb_snap' in s, "판정은 strategy_config.entry_snapshot 에 저장돼야 실적을 잴 수 있다 (cfg 는 저장 안 됨)"
    i_snap = s.find('entry_snapshot["candle_battle"] = _cb_snap')
    i_sugg = s.find("sugg = StrategySuggestion(")
    assert 0 < i_snap < i_sugg


def test_pyramid_worker_wiring_shadow_default():
    s = (ROOT / "workers" / "success_pyramiding_worker.py").read_text(encoding="utf-8")
    i_273 = s.find('logger.info("[Fix273] ✅ %s %s — %s"')
    i_360 = s.find("_cb360.body_growth(")
    i_add = s.find("_add_order = _exec.add_position_now(")
    assert 0 < i_273 < i_360 < i_add, "지표 게이트 통과 → 몸통 판정 → 추가 주문 순서"
    blk = s[i_360 - 900:i_360 + 1200]
    assert '_bump("body_not_growing")' in blk
    assert 'if not _bg_ok and _bg_mode == "gate" and len(_bg_bars) >= 15:' in blk, "봉 조회 실패/부족은 gate 에서도 fail-open"
    assert '"body_growth": _bg_snap' in s, "추가 스냅샷에 몸통 판정 기록"
    assert "_bg_snap = None" in s


def test_journal_relabel_catchup_and_report_denominators():
    """반박 검증이 잡은 것: LABEL_VERSION 을 올려도 매시 잡은 PENDING 만 봐서 옛 행이 재라벨되지 않았다."""
    w = (ROOT / "workers" / "chart_learning_worker.py").read_text(encoding="utf-8")
    i_prune = w.find("pruned = _prune(db)")
    i_re = w.find("relabel(days=CL.keep_days(db), limit=max(int(batch), 500), only_old_version=True)")
    assert 0 < i_prune < i_re < i_prune + 1200, "매시 라벨링 잡 끝에 옛 버전 재라벨"
    assert "cast(_ver, Integer) < CL.LABEL_VERSION" in w, "relabel 의 limit 이 옛 행에만 쓰이게 SQL 에서 거른다"
    c = (ROOT / "services" / "chart_learning.py").read_text(encoding="utf-8")
    assert "evald = [r for r in grp if key in (r[\"outcome\"].get(\"rules\") or {})]" in c
    assert 'rep["versions"]' in c and "라벨 버전 혼재" in c

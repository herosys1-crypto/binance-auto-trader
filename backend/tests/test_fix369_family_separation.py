"""🔀 Fix 369 — 「➕ 새 전략 (기존 방식)」 / 「새 전략 (OBV 자동)」 분리.

사장님 2026-09-13: "새 전략기존방식 과 새전략 obv 자동 둘을 완전 다르게 둘로 분리해서 개발을해줘 두개가 계속 겹치는것 같아"
S1 (사장님 결정 9/13 「기존 방식 미진입 단계 예약 제외」): 기존 방식 전략의 단계 진입 판정에서만 기존 방식 미진입 단계를 130% 예약에서 빼고,
    발주 직전 가용 잔고(실제 주문 크기 · 조회 실패 = 보류)로 막는다. 공용 합계·생성 검사·화면·다른 가족 판정은 그대로 (반박 검증).
    실측: 예약 7,159 중 기존 방식 7건 = 6,509 → 한도 ≈5,058 초과로 기존 방식 2단계 전부 차단 (#4496·#4506 LSKUSDT).
S2 (워커 분리): 가족 판정 단일 권한 strategy_family.family_of + 반전 워커·진입 누락 알림의 가족 제한 + OBV 생성 표식.
    수익 추가는 기존 방식도 그대로 대상 (Fix 185 사장님 「모든 전략 — 수동/모달 전략도 수익 나면 추가 진입」).
"""
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS

from app.services import capital_calculator as CC
from app.services import strategy_family as F

ROOT = Path(__file__).resolve().parents[1] / "app"


class _DB:
    def __init__(self, **kv):
        self.kv = kv
        self.executed = 0

    def get(self, _m, key):
        v = self.kv.get(key)
        return None if v is None else type("R", (), {"value": v})()

    def execute(self, *_a, **_k):
        self.executed += 1
        raise AssertionError("여기까지 오면 안 된다")


class _BoomDB(_DB):
    def get(self, _m, key):
        raise RuntimeError("db down")


class _SeqDB(_DB):
    """db.execute(...).scalars().all() 결과를 차례로 돌려준다 (계정 조회 = 전략 목록, 그다음 전략별 미진입 계획)."""

    def __init__(self, results, **kv):
        super().__init__(**kv)
        self.results = list(results)

    def execute(self, *_a, **_k):
        self.executed += 1
        rows = self.results.pop(0)
        return NS(scalars=lambda: NS(all=lambda: rows))


def _plans():
    return [NS(planned_capital=Decimal("300")), NS(planned_capital=Decimal("600"))]


def _si(profile="legacy_manual", mode="fixed", trigger="PRICE_DOWN_PCT", stype="DYNAMIC_LONG", name="_quick_20260913"):
    return NS(id=1, symbol="XUSDT", side="LONG", status="STAGE1_OPEN", entry_profile=profile, capital_management_mode=mode,
              strategy_template=NS(trigger_mode=trigger, strategy_type=stype, name=name),
              current_position_qty=Decimal("10"), avg_entry_price=Decimal("20"), leverage=2)


def _no_probe(monkeypatch):
    monkeypatch.setattr("app.services.managed_symbols.loss_ladder_disabled", lambda db, s: (False, ""))


def _src(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


# ── S1: 130% 가드 예약 ───────────────────────────────────────────────────
def test_shared_reserve_rule_still_counts_legacy(monkeypatch):
    """공용 규칙(생성 시 검사 · 화면 · 다른 가족의 단계 판정)은 기존 방식 미진입 단계도 그대로 센다 — 여기서 빼면 모두 느슨해진다."""
    _no_probe(monkeypatch)
    assert CC.ladder_reserves_untriggered(_DB(), _si()) is True
    assert CC.calc_untriggered_margin_for_strategy(_SeqDB([_plans()]), _si()) == Decimal("900")
    assert CC.calc_reserved_for_strategy(_SeqDB([_plans()]), _si()) == Decimal("1000")           # 실 마진 10 × 20 ÷ 2 = 100


def test_legacy_stage_entry_view_excludes_only_legacy(monkeypatch):
    _no_probe(monkeypatch)
    db = _DB()
    assert CC.calc_untriggered_margin_for_strategy(db, _si(), exclude_legacy_untriggered=True) == Decimal("0") and db.executed == 0
    assert CC.calc_reserved_for_strategy(_DB(), _si(), exclude_legacy_untriggered=True) == Decimal("100")   # 실 마진은 그대로
    for other in (_si(profile=None), _si(profile=None, mode="split_entry"), _si(profile="obv_auto", trigger="OBV_REVERSE")):
        assert CC.calc_untriggered_margin_for_strategy(_SeqDB([_plans()]), other, exclude_legacy_untriggered=True) == Decimal("900")
    assert CC.calc_untriggered_margin_for_strategy(_DB(), _si(profile=None, mode="stage_ladder"), exclude_legacy_untriggered=True) == 0  # Fix 344 그대로


def test_account_reserve_for_legacy_entry_still_counts_other_families(monkeypatch):
    _no_probe(monkeypatch)
    rows = [_si(), _si(profile=None)]
    assert CC.calc_reserved_for_account(_SeqDB([rows, _plans(), _plans()]), 1) == Decimal("2000")      # 기본 = 옛 합계
    assert CC.calc_reserved_for_account(_SeqDB([rows, _plans()]), 1, exclude_legacy_untriggered=True) == Decimal("1100")  # 기존 방식 900 만 빠짐


def test_rollback_setting_and_failure_direction(monkeypatch):
    _no_probe(monkeypatch)
    assert CC.legacy_manual_skips_reserve(_DB(legacy_reserve_untriggered_enabled="1"), _si()) is False   # 되돌리기 = 옛 동작
    assert CC.legacy_manual_skips_reserve(_DB(legacy_reserve_untriggered_enabled="0"), _si()) is True
    assert CC.legacy_manual_skips_reserve(_BoomDB(), _si()) is True                                      # 조회 실패 = 사장님 결정 쪽
    assert CC.legacy_manual_skips_reserve(_DB(), _si(profile=None)) is False                             # Fix 367 이전 옛 가격 전략 = 예약 유지
    assert CC.legacy_manual_skips_reserve(_DB(), _si(mode="split_entry")) is False                       # 가족 판정 단일 권한 (표식 있어도 SPLIT)
    assert CC.calc_untriggered_margin_for_strategy(
        _SeqDB([_plans()], legacy_reserve_untriggered_enabled="1"), _si(), exclude_legacy_untriggered=True) == Decimal("900")


def test_stage_order_margin_uses_real_order_cost():
    from app.workers.stage_trigger_worker import _stage_order_margin369 as M
    one = Decimal("1")

    def plan(cap="300", qty="3000", px="1.00", add=None):
        return NS(planned_capital=Decimal(cap), planned_qty=None if qty is None else Decimal(qty),
                  trigger_price=None if px is None else Decimal(px), additional_margin_usdt=add)
    short, long_ = NS(leverage=10, side="SHORT"), NS(leverage=10, side="LONG")
    # 가격이 트리거를 넘어선 뒤 LIMIT @ 트리거 = 바로 체결 → 개시 손실이 붙는다 (재검증 H1)
    assert M(short, plan(), Decimal("1.01"), one) == Decimal("333")       # 3000 × 1.01 ÷ 10 + 3000 × 0.01
    assert M(long_, plan(), Decimal("0.99"), one) == Decimal("330")       # 3000 × 1.00 ÷ 10 + 3000 × 0.01
    assert M(short, plan(), Decimal("1.00"), one) == Decimal("300")
    # 단계 수정으로 planned_qty 가 planned_capital 보다 큰 경우 = 수량 기준
    assert M(short, plan(qty="5000"), Decimal("1.00"), Decimal("1.02")) == Decimal("510")
    # 수량 없음 = planned_capital × lev ÷ 주문가 · 추가 증거금은 배율 뒤에 더한다 · mark 없음 = 트리거가
    assert M(short, plan(qty=None, add=Decimal("20")), None) == Decimal("335")
    # MARKET (trigger_price 없음) = planned_capital
    assert M(short, plan(px=None), Decimal("1.2")) == Decimal("315")
    assert M(short, NS(planned_capital="bad", planned_qty="x", trigger_price=None, additional_margin_usdt="y"), None) == Decimal("0")


def test_legacy_margin_buffer_setting():
    from app.workers.stage_trigger_worker import _legacy_margin_buffer369 as B
    assert B(_DB()) == Decimal("1.05")                                     # Claude가 정함 (MARKET preflight 와 같은 값)
    assert B(_DB(legacy_stage_margin_buffer="1.2")) == Decimal("1.2")
    assert B(_DB(legacy_stage_margin_buffer="3")) == Decimal("1.05")       # 범위 밖
    assert B(_BoomDB()) == Decimal("1.05")


def test_stage_trigger_legacy_view_fail_closed_and_labels():
    s = _src("workers", "stage_trigger_worker.py")
    i_flag = s.find("_legacy_nores369 = bool(_lmsr369(db, strategy))")
    i_calc = s.find("calc_reserved_for_account(db, account.id, exclude_legacy_untriggered=_legacy_nores369)")
    i_130 = s.find("130%% 초과 차단")
    i_bal = s.find("if _is_ladder or _legacy_nores369:")
    i_fc = s.find("if _avail is None and _legacy_nores369:")
    i_fire = s.find("exec_service.trigger_next_stage(")
    assert 0 < i_flag < i_calc < i_130 < i_bal < i_fc < i_fire
    assert s[i_fc:i_fire].find("continue") < s[i_fc:i_fire].find("if _avail is not None:"), "잔고 모름 = 보류"
    seg = s[i_bal:i_fire]
    assert "_need = _stage_order_margin369(strategy, next_plan, mark, _legacy_margin_buffer369(db))" in seg
    assert seg.count("_alert_silent_block_once(") >= 2, "기존 방식 보류 = 사장님 텔레그램 (1시간 dedup)"
    assert seg.count("_f369_log_once(") >= 2, "15초 주기 WARNING 반복 방지"
    assert 0 < s.find("mark = Decimal(str(mark))") < i_bal, "잔고 검사에 쓰는 mark 는 앞에서 확정된다"
    assert "실=%s + 예약=%s = %s" not in s and "합 (실 + 예약)" not in s, "판정값은 예약 하나 — 「실 + 예약」 라벨은 틀렸다"
    c = _src("services", "capital_calculator.py")
    i_lr = c.find("def ladder_reserves_untriggered")
    assert "legacy_manual_skips_reserve" not in c[i_lr:c.find("\ndef ", i_lr + 10)], "공용 규칙에 넣으면 다른 가족·생성 검사까지 느슨해진다"


# ── S2: 가족 판정 단일 권한 ───────────────────────────────────────────────
def test_family_of_order_and_markers():
    assert F.family_of(_si()) == F.LEGACY_MANUAL
    assert F.family_of(_si(profile=None, trigger="OBV_REVERSE", name="_quick_m20260913_LONG")) == F.OBV_AUTO   # 표식 없는 OBV (옛 인스턴스)
    assert F.family_of(_si(profile="obv_auto", trigger=None)) == F.OBV_AUTO
    assert F.family_of(_si(profile=None, mode="split_entry")) == F.SPLIT
    assert F.family_of(_si(profile=None, mode="stage_ladder")) == F.LADDER
    assert F.family_of(_si(profile=None, stype="bb_mid_line")) == F.SINGLE
    assert F.family_of(_si(profile=None, name="RF_BOTTOM_XUSDT_LONG_1_A1")) == F.SINGLE
    assert F.family_of(_si(profile=None)) == F.OTHER                                   # Fix 367 이전 수동 가격 전략 · 자동 워커
    assert F.MANUAL_FAMILIES == {F.OBV_AUTO, F.LEGACY_MANUAL}

    class _Bad:
        id = 9

        @property
        def capital_management_mode(self):
            raise RuntimeError("boom")
    assert F.family_of(_Bad()) == F.UNKNOWN


def test_drop_families_is_fail_closed():
    rows = [_si(), _si(profile=None, trigger="OBV_REVERSE"), _si(profile=None, mode="stage_ladder"), _si(profile=None)]

    class _Bad:
        id = 9

        @property
        def capital_management_mode(self):
            raise RuntimeError("boom")
    kept = F.drop_families(rows + [_Bad()], F.MANUAL_FAMILIES)
    assert [F.family_of(r) for r in kept] == [F.LADDER, F.OTHER]


def test_obv_profile_constant_fits_column():
    from app.core.risk_constants import LEGACY_MANUAL_PROFILE, OBV_AUTO_PROFILE
    assert OBV_AUTO_PROFILE == "obv_auto" and len(OBV_AUTO_PROFILE) <= 20 and OBV_AUTO_PROFILE != LEGACY_MANUAL_PROFILE
    s = _src("services", "strategy_service.py")
    assert "entry_profile=_entry_profile369" in s and "_OBV_PROFILE369 if" in s, "생성 시 두 가족 모두 표식"


# ── S2: 워커 가족 제한 ────────────────────────────────────────────────────
def test_reversal_workers_exclude_manual_families():
    for parts, fn in ((("workers", "peak_break_reversal_worker.py"), "def _get_active_short_strategies"),
                      (("workers", "resistance_reversal_worker.py"), "def _query_candidates")):
        s = _src(*parts)
        body = s[s.find(fn): s.find("\ndef ", s.find(fn) + 10)]
        assert "drop_families(drop_single_entry(" in body and "MANUAL_FAMILIES" in body, parts
    t = _src("workers", "time_reverse_exit_worker.py")
    assert "candidates = drop_families(candidates, MANUAL_FAMILIES" in t


def test_pyramiding_keeps_legacy_manual():
    s = _src("workers", "success_pyramiding_worker.py")
    assert "_family369(si) != LEGACY_MANUAL" not in s and "pyramid_include_legacy_manual" not in s, \
        "Fix 185 사장님 「모든 전략 — 수동/모달 전략도 수익 나면 추가 진입」 — 가족 분리로 추가를 끄지 않는다"


def test_auto_entry_missed_skips_obv_family():
    from app.workers.setting_preservation_agent import _check_auto_entry_silent_bug
    obv = _si(profile=None, trigger="OBV_REVERSE", name="_quick_m20260913_LONG")
    assert _check_auto_entry_silent_bug(_DB(), obv, Decimal("1")) == []                # 계획 조회 전에 빠진다 (_DB.execute 는 실패시킴)

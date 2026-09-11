"""🎯 Fix 367 — 사장님 2026-09-11 verbatim:
"새전략 기존 방식은 손절없고 단계별 트리거에 다음단계 포지션 진입할수 있게 해주 처음 개발한 것과 그의 동일해
 tp1 익절은 +25% 부터 포지션진입한 금액의 25%부터 익절 할 수 있게 설정해줘 과거로 돌악가는것과 같아"

「➕ 새 전략 (기존 방식)」(모달 + 가격 트리거 + fixed/scheduled + DYNAMIC_*) 로 **새로** 만드는 인스턴스만:
  TP1 임계 25 (설정 legacy_ladder_tp1_pct) · 강제손절 끔 (설정 legacy_ladder_force_sl_enabled, roi 0)
  · 생성 시 표식 entry_profile='legacy_manual' (alembic 0039).
Fix 367b: 그 가족은 단계 정리(Fix 304)도 제외 (설정 stage_trim_exclude_legacy_manual, 기본 1).
Fix 367c(반박 검증): 런타임 판정은 표식만 → 배포 전 인스턴스(#4478/#4480) 불변 · 모달 TP1 청산 기본 25 ·
  OBV 다중심볼 템플릿 trigger_mode 전송 · NaN 가드.
OBV 자동·자동 워커·볼밴 분할·v219 사다리·퍼프 터미널·기존 인스턴스는 그대로.
"""
import ast
import re
from decimal import Decimal
from pathlib import Path

from app.core import risk_constants as RC
from app.services import stage_trim as T
from app.services import strategy_service as SS
from app.services.risk_service import RiskService, resolve_force_sl
from app.services.system_settings_service import SystemSettingsService

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
M = SS.ENTRY_ORIGIN_MANUAL


class _KV:
    """SystemSetting 은 dict 로 흉내낸다 (db.get + execute 양쪽)."""

    def __init__(self, settings=None):
        self.kv = settings or {}

    def execute(self, stmt):                   # SystemSettingsService.get → select(SystemSetting).where(key == ...)
        key = None
        try:
            key = stmt.whereclause.right.value
        except Exception:  # noqa: BLE001
            for crit in getattr(stmt, "_where_criteria", ()):
                key = crit.right.value
        kv = self.kv

        class _R:
            def scalar_one_or_none(self_inner):
                return type("Row", (), {"value": kv[key]})() if key in kv else None
        return _R()

    def get(self, model, key):                 # stage_trim / risk_service → db.get(SystemSetting, key)
        if getattr(model, "__name__", "") == "StrategyTemplate":
            raise AssertionError("Fix 367c: 런타임 판정은 템플릿을 읽지 않는다")
        return type("Row", (), {"value": self.kv[key]})() if key in self.kv else None


class _S:
    def __init__(self, mode="fixed", *, profile=None, fs_on=False, fs_roi=Decimal("0"), retry=False):
        self.id, self.symbol, self.side = 1, "XUSDT", "LONG"
        self.capital_management_mode, self.strategy_template_id = mode, 7
        self.entry_profile = profile
        self.force_sl_enabled_override, self.force_sl_roi_override = fs_on, fs_roi
        self.retry_after_liquidation_enabled = retry


def test_constants_and_export():
    assert RC.LEGACY_LADDER_TP1_DEFAULT == Decimal("25")                       # 사장님 verbatim "+25%"
    assert RC.LEGACY_LADDER_FORCE_SL_DEFAULT is False                          # 사장님 "손절없고"
    assert RC.LEGACY_LADDER_TP1_QTY_DEFAULT == Decimal("25")                   # 사장님 "포지션진입한 금액의 25%"
    assert RC.LEGACY_MANUAL_PROFILE == "legacy_manual"
    assert RC.LEGACY_LADDER_TP1_KEY == "legacy_ladder_tp1_pct"
    assert RC.LEGACY_LADDER_FORCE_SL_KEY == "legacy_ladder_force_sl_enabled"
    assert RC.LEGACY_LADDER_TP1_QTY_KEY == "legacy_ladder_tp1_qty_ratio"
    for name in ("LEGACY_LADDER_TP1_KEY", "LEGACY_LADDER_TP1_DEFAULT", "LEGACY_LADDER_TP1_MAX", "LEGACY_LADDER_FORCE_SL_KEY",
                 "LEGACY_LADDER_FORCE_SL_DEFAULT", "LEGACY_LADDER_TP1_QTY_KEY", "LEGACY_LADDER_TP1_QTY_DEFAULT", "LEGACY_MANUAL_PROFILE"):
        assert name in RC.__all__, name
    assert T.SETTING_EXCLUDE_LEGACY == "stage_trim_exclude_legacy_manual"
    for name in ("SETTING_EXCLUDE_LEGACY", "legacy_manual_excluded", "is_legacy_manual_instance"):
        assert name in T.__all__, name
    # Fix 362 는 그대로 — OBV 자동·워커의 새 인스턴스 기본은 여전히 25 / TP1 15
    assert RC.FORCE_SL_ROI_NEW_DEFAULT == Decimal("25") and RC.TP1_PCT_DEFAULT == Decimal("15")


def test_template_predicate_price_fixed_dynamic_only():
    f = SS.legacy_manual_template
    assert f("PRICE_DOWN_PCT", "fixed", "DYNAMIC_LONG") is True
    assert f("PRICE_UP_PCT", "scheduled", "DYNAMIC_SHORT") is True             # Fix 182 예약도 모달 = 기존 방식
    assert f(None, None, "dynamic_long") is True                                 # 옛 템플릿(trigger_mode 없음) = PRICE_DOWN_PCT, 대소문자 무관
    assert f("OBV_REVERSE", "fixed", "DYNAMIC_LONG") is False                    # 📊 OBV 자동 (관리 재진입 클론 포함) = Fix 362~365 그대로
    assert f("PRICE_DOWN_PCT", "split_entry", "DYNAMIC_LONG") is False           # 볼밴 분할
    assert f("PRICE_DOWN_PCT", "stage_ladder", "DYNAMIC_LONG") is False          # v219 사다리
    assert f("PRICE_DOWN_PCT", "fixed", "terminal_manual") is False              # 퍼프 터미널
    assert f("PRICE_DOWN_PCT", "fixed", "auto_bb_break_SAJANGNIM_BO") is False   # AUTO_BB 1단계(fixed)
    assert f("PRICE_DOWN_PCT", "fixed", None) is False


def test_family_predicate_requires_manual_origin():
    f = SS.legacy_manual_family
    assert f("PRICE_DOWN_PCT", "fixed", M, "DYNAMIC_LONG") is True
    assert f("PRICE_DOWN_PCT", "fixed", None, "DYNAMIC_LONG") is False           # 자동 워커(auto_reentry 등)는 entry_origin 을 안 넘긴다
    assert f("PRICE_DOWN_PCT", "fixed", "worker", "DYNAMIC_LONG") is False
    assert f("PRICE_DOWN_PCT", "fixed", M) is False                              # strategy_type 없음 = 보수적으로 아님


def test_defaults_without_rows():
    svc = SystemSettingsService(_KV())
    assert svc.get_legacy_ladder_defaults() == (Decimal("25"), False, Decimal("0"))
    assert svc.get_legacy_ladder_tp1_qty_ratio() == Decimal("25")


def test_defaults_from_settings_rows():
    # 사장님이 설정으로 바꾸면 그대로 (재시작 불필요)
    assert SystemSettingsService(_KV({"legacy_ladder_tp1_pct": "30"})).get_legacy_ladder_defaults() == (Decimal("30"), False, Decimal("0"))
    # 강제손절을 켜면 Fix 362 기본(-25)으로 돌아간다
    assert SystemSettingsService(_KV({"legacy_ladder_force_sl_enabled": "1"})).get_legacy_ladder_defaults() == (Decimal("25"), True, Decimal("25"))
    _, on, roi = SystemSettingsService(_KV({"legacy_ladder_force_sl_enabled": "true", "force_sl_roi_new_default": "10"})).get_legacy_ladder_defaults()
    assert (on, roi) == (True, Decimal("10"))
    # 0(TP 끔)·범위 밖·쓰레기·NaN/Infinity 는 25 — 새 전략 전체의 TP 를 설정 한 줄로 조용히 끄지 못한다 (Fix 362c 와 같은 이유)
    for bad in ("0", "-5", "301", "abc", "", "NaN", "nan", "Infinity", "-Infinity", "sNaN"):
        assert SystemSettingsService(_KV({"legacy_ladder_tp1_pct": bad})).get_legacy_ladder_defaults()[0] == Decimal("25"), bad
    assert SystemSettingsService(_KV({"legacy_ladder_tp1_pct": "300"})).get_legacy_ladder_defaults()[0] == Decimal("300")
    # TP1 청산 비율 기준: 0<x≤100, 그 밖은 25
    for bad in ("0", "101", "NaN", "x"):
        assert SystemSettingsService(_KV({"legacy_ladder_tp1_qty_ratio": bad})).get_legacy_ladder_tp1_qty_ratio() == Decimal("25"), bad
    assert SystemSettingsService(_KV({"legacy_ladder_tp1_qty_ratio": "50"})).get_legacy_ladder_tp1_qty_ratio() == Decimal("50")


def test_off_beats_global_long_on_and_does_not_exempt_stage_gate():
    # 전역 LONG 강제손절(기본 ON)이 켜져 있어도 전략의 명시적 끔이 이긴다 (resolve_force_sl)
    assert resolve_force_sl(override_enabled=False, override_roi=Decimal("0"), global_enabled=True, global_roi=Decimal("80")) == (False, Decimal("0"))
    rs = RiskService.__new__(RiskService)
    rs.db = _KV()
    # roi 0 은 Fix 322 「손절 명시」 면제가 아니다 → 템플릿 손절(자본 대비 %, 모달 80)은 옛 규칙대로 모든 단계 진입 후에만
    exempt, why = rs._stage_gate_exempt(_S(profile="legacy_manual"))
    assert exempt is False and why == ""
    # 대조: Fix 362 기본(25 명시)은 면제된다 — 옛 동작 유지
    assert rs._stage_gate_exempt(_S(fs_on=True, fs_roi=Decimal("25")))[0] is True


def test_trim_excluded_only_for_instances_stamped_legacy_manual():
    TRIM_ON = {"stage_trim_before_next_enabled": "1"}
    db = _KV(TRIM_ON)
    assert T.is_legacy_manual_instance(db, _S(profile="legacy_manual")) is True
    assert T.trim_enabled(db, _S(profile="legacy_manual")) is False             # 기존 방식(표식) = 정리 제외 (Fix 367b)
    assert T.trim_enabled(db, _S("scheduled", profile="legacy_manual")) is False
    # 배포 전 인스턴스(#4478/#4480: 표식 없음, 손절 ON 25) = Fix 304 그대로 (반박 검증 C0/C5/C13/C18/C21/C26)
    assert T.is_legacy_manual_instance(db, _S(fs_on=True, fs_roi=Decimal("25"))) is False
    assert T.trim_enabled(db, _S(fs_on=True, fs_roi=Decimal("25"))) is True
    assert T.trim_enabled(db, _S(profile=None)) is True                          # OBV 자동·워커·퍼프 터미널 = 그대로
    assert T.trim_enabled(db, _S(profile="other")) is True
    assert T.trim_enabled(db, _S("split_entry", profile="legacy_manual")) is False   # Fix 313 그대로 (먼저 걸린다)
    assert T.trim_enabled(db) is True                                            # 구 호출부(strategy 없음) = 전역 판정만
    # 되돌리기: stage_trim_exclude_legacy_manual = 0
    db0 = _KV({**TRIM_ON, "stage_trim_exclude_legacy_manual": "0"})
    assert T.legacy_manual_excluded(db0) is False and T.trim_enabled(db0, _S(profile="legacy_manual")) is True
    assert T.legacy_manual_excluded(_KV()) is True and T.legacy_manual_excluded(_KV({"stage_trim_exclude_legacy_manual": ""})) is True
    # 전역 스위치가 꺼져 있으면 어차피 False
    assert T.trim_enabled(_KV({}), _S(profile="legacy_manual")) is False


def test_trim_exclusion_removes_fix304_stage_gate_exemption_for_legacy_only():
    """단계 정리 ON 이면 손절 단계 게이트가 면제(Fix 321)되는데, 기존 방식(표식)은 정리 밖이므로 면제도 받지 않는다."""
    db = _KV({"stage_trim_before_next_enabled": "1"})
    rs = RiskService.__new__(RiskService)
    rs.db = db
    assert rs._stage_gate_exempt(_S(profile="legacy_manual"))[0] is False
    ok, why = rs._stage_gate_exempt(_S(profile=None))
    assert ok is True and "Fix304" in why                                        # 표식 없는 인스턴스는 옛 동작


def test_creation_wiring_pins():
    src = (APP / "services" / "strategy_service.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "create_strategy_instance"]
    assert len(fns) == 1 and "entry_origin" in [a.arg for a in fns[0].args.kwonlyargs]
    for name in ("legacy_manual_family", "legacy_manual_template"):
        assert sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name) == 1, name
    i = src.find("_is_legacy367 = legacy_manual_family(")
    j = src.find("instance = StrategyInstance(", i)
    assert 0 < i < j, "가족 판정이 인스턴스 생성 앞에 있어야 한다"
    assert 'getattr(template_model, "strategy_type", None)' in src[i:j]
    assert "get_legacy_ladder_defaults()" in src[i:j]
    assert "TP1_PCT_DEFAULT, True, _new_force_sl_roi" in src[i:j], "OBV 자동·워커 경로는 Fix 362 기본 그대로"
    assert '_tpl_tp1_qty367 = getattr(template_model, "tp1_qty_ratio", None)' in src[i:j], "커밋 전에 캡처 (lazy-load 회피)"
    body = src[j:j + 2500]
    for pin in ("tp1_pct_override=_tp1_default", "force_sl_enabled_override=_fs_on_default", "force_sl_roi_override=_fs_roi_default",
                "entry_profile=(LEGACY_MANUAL_PROFILE if _is_legacy367 else None)"):
        assert pin in body, pin
    assert "legacy_ladder_tp1_qty_ratio) — 모달 값 그대로 둔다" in src, "TP1 청산 비율은 경고만 (모달에서 고친 값은 사장님 뜻)"
    crud = (APP / "api" / "v1" / "strategies" / "crud.py").read_text(encoding="utf-8")
    assert "entry_origin=ENTRY_ORIGIN_MANUAL" in crud and "import ENTRY_ORIGIN_MANUAL" in crud
    # 워커 호출부는 entry_origin 을 넘기지 않는다 (= 가족 밖)
    for rel in ("services/surge_ladder_entry.py", "services/managed_symbols.py", "workers/auto_bb_breakdown_worker.py",
                "workers/auto_reentry_worker.py", "workers/ladder_restart_worker.py", "workers/pump_split_entry_worker.py"):
        assert "entry_origin=" not in (APP / rel).read_text(encoding="utf-8"), rel
    # 인스턴스를 만드는 곳은 strategy_service 하나뿐 (다른 생성 경로가 생기면 가족 판정을 우회한다)
    for p in list((APP / "workers").glob("*.py")) + list((APP / "services").glob("*.py")):
        if p.name == "strategy_service.py":
            continue
        assert not re.search(r"(?<![\w.])StrategyInstance\(", p.read_text(encoding="utf-8")), p.name
    # 표식 컬럼 + 마이그레이션 + 응답 스키마
    model = (APP / "models" / "strategy_instance.py").read_text(encoding="utf-8")
    assert "entry_profile: Mapped[str | None] = mapped_column(String(20), nullable=True)" in model
    mig = ROOT / "alembic" / "versions" / "0039_strategy_instances_entry_profile.py"
    assert mig.exists() and "down_revision = '0038_managed_symbols_entry_ids'" in mig.read_text(encoding="utf-8")
    assert "entry_profile: str | None = None" in (APP / "schemas" / "strategy.py").read_text(encoding="utf-8")
    # 단계 정리 훅 + 런타임 판정은 표식만
    ts = (APP / "services" / "stage_trim.py").read_text(encoding="utf-8")
    i_te = ts.find("def trim_enabled(")
    assert "if legacy_manual_excluded(db) and is_legacy_manual_instance(db, strategy):" in ts[i_te:i_te + 4000]
    i_il = ts.find("def is_legacy_manual_instance(")
    assert 'getattr(strategy, "entry_profile", None)' in ts[i_il:i_il + 1500] and "db.get(StrategyTemplate" not in ts[i_il:i_il + 1500]
    es = (APP / "services" / "execution_service.py").read_text(encoding="utf-8")
    assert "if trim_enabled(self.db, strategy) and stage_no > 1:" in es


def test_checker_and_ui_pins():
    chk = (ROOT / "scripts" / "verify_fix364_deploy.py").read_text(encoding="utf-8")
    assert "def check_legacy_ladder()" in chk and "\n    check_legacy_ladder()\n" in chk
    for pin in ('"legacy_ladder_tp1_pct", "25"', '"legacy_ladder_force_sl_enabled", "0"', '"stage_trim_exclude_legacy_manual", "1"',
                '"legacy_ladder_tp1_qty_ratio", "25"', "is_legacy_manual_instance", 'strategy_type.startswith("DYNAMIC_"',
                '_prof == "legacy_manual"', "if _fam_rt and _trim and _excl_on:"):
        assert pin in chk, pin
    js = (APP / "static" / "js" / "cm-submit.js").read_text(encoding="utf-8")
    assert "created.force_sl_enabled_override === false" in js and "created.tp1_pct_override" in js
    assert "strategy_type: cmState.side === 'SHORT' ? 'DYNAMIC_SHORT' : 'DYNAMIC_LONG'" in js   # 모달 템플릿 = DYNAMIC_*
    html = (APP / "static" / "index.html").read_text(encoding="utf-8")
    assert "legacy_ladder_tp1_pct" in html
    # 모달 기본 = TP1 청산 25% (사장님 "포지션진입한 금액의 25%") — blueprint 자동 복원 뒤에도 기존 방식 신규는 25 로 시작
    om = (APP / "static" / "js" / "cm-open-modal.js").read_text(encoding="utf-8")
    assert "1: ['10', '25']" in om
    i_bp = om.find("await loadPrevBlueprint(_last.id, /*silent=*/true);")
    assert i_bp > 0 and "if (cmState && !cmState._pendingObv)" in om[i_bp:i_bp + 3000] and "_q1.value = '25'" in om[i_bp:i_bp + 3000]
    i_obv = om.find("async function openCreateChartObvModal()")
    assert "cmState._pendingObv = true;" in om[i_obv:i_obv + 600] and "cmState._pendingObv = false;" in om[i_obv:i_obv + 600]
    # 다중 심볼도 trigger_mode 를 보낸다 (OBV 모달 + 다중심볼이 가격 사다리로 저장되던 누락, 반박 검증 C8)
    ms = (APP / "static" / "js" / "multi-symbol.js").read_text(encoding="utf-8")
    assert "trigger_mode: cmState._triggerMode || 'PRICE_DOWN_PCT'" in ms and "capital_management_mode: 'fixed'" in ms

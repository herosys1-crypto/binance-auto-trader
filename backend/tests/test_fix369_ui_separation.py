"""🎨 Fix 369 S3 — 화면(UI)/API 창구 분리 테스트 (2026-09-13, 리드 S1/S2 다음 단계).

사장님: "새 전략기존방식 과 새전략 obv 자동 둘을 완전 다르게 둘로 분리해서 개발을해줘
두개가 계속 겹치는것 같아"

리드가 런타임 판정(strategy_family.family_of, entry_profile 생성 표식)을 이미 구현했다
(tests/test_fix369_family_separation.py = S1/S2). 이 파일은 그 위의 **화면/API 창구**를 다룬다
(읽기 전용 감사 9/13 이 잡은 9건 — 각 클래스 docstring 에 감사 번호를 남긴다).

건드리지 않는 것: services/**, workers/**, core/** — 매매 판정은 리드 전담.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from fastapi import HTTPException

from app.api.v1.admin import templates as admin_templates
from app.api.v1.strategies import crud
from app.schemas.strategy import StrategyCreateRequest

ROOT = Path(__file__).resolve().parent.parent / "app"


def _src(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════
# API: POST /strategies — family vs 템플릿 trigger_mode 검증 (신설)
# ═══════════════════════════════════════════════════════════════════════════
class _TplDB:
    """create_strategy 의 db.get(StrategyTemplate, id) 만 흉내낸다 (진짜 DB 불필요)."""

    def __init__(self, templates: dict[int, str]):
        self._templates = templates

    def get(self, _model, key):
        trig = self._templates.get(key)
        return None if trig is None else NS(id=key, trigger_mode=trig)


def _payload(**kw) -> StrategyCreateRequest:
    base = dict(
        exchange_account_id=1, strategy_template_id=1, symbol="BTCUSDT", side="SHORT",
        start_price=Decimal("100"),
    )
    base.update(kw)
    return StrategyCreateRequest(**base)


def _fake_instance(**kw) -> NS:
    """StrategyDetailResponse.model_validate() 가 요구하는 필수 필드만 채운 가짜 인스턴스."""
    base = dict(
        id=1, symbol="BTCUSDT", side="SHORT", status="WAITING", reentry_ready=False,
        leverage=2, current_stage=0, current_position_qty=Decimal("0"),
        invested_capital=Decimal("0"), realized_pnl=Decimal("0"), unrealized_pnl=Decimal("0"),
        entry_profile=None, capital_management_mode="fixed",
        strategy_template=None, template=None,
    )
    base.update(kw)
    return NS(**base)


class TestCreateStrategyFamilyValidation:
    """감사 신설 항목 — family 필드가 템플릿의 trigger_mode 와 다르면 400."""

    def test_mismatch_rejected_with_korean_message(self):
        db = _TplDB({1: "PRICE_DOWN_PCT"})   # 템플릿은 기존 방식인데
        payload = _payload(family="obv_auto")  # OBV 모달이 보냄 → 불일치
        with pytest.raises(HTTPException) as ei:
            crud.create_strategy(payload, db, user_id=1)
        assert ei.value.status_code == 400
        assert "가족" in ei.value.detail or "다릅니다" in ei.value.detail

    def test_match_accepted_and_family_echoed_back(self, monkeypatch):
        db = _TplDB({1: "OBV_REVERSE"})
        monkeypatch.setattr(
            crud.StrategyService, "create_strategy_instance",
            lambda self, **kw: _fake_instance(entry_profile="obv_auto"),
        )
        resp = crud.create_strategy(_payload(family="obv_auto"), db, user_id=1)
        assert resp.family == "obv_auto"

    def test_legacy_match_accepted(self, monkeypatch):
        db = _TplDB({1: "PRICE_DOWN_PCT"})
        monkeypatch.setattr(
            crud.StrategyService, "create_strategy_instance",
            lambda self, **kw: _fake_instance(entry_profile="legacy_manual"),
        )
        resp = crud.create_strategy(_payload(family="legacy_manual"), db, user_id=1)
        assert resp.family == "legacy_manual"

    def test_missing_family_accepted_fail_open_with_warning_log(self, monkeypatch, caplog):
        """family 없음 = 구 프론트/외부 호출자 — 막지 않는다(fail-open, 표시용 표식이라 자본 판정이 아님). 대신 로그를 남긴다."""
        import logging
        db = _TplDB({1: "PRICE_DOWN_PCT"})
        monkeypatch.setattr(
            crud.StrategyService, "create_strategy_instance",
            lambda self, **kw: _fake_instance(entry_profile="legacy_manual"),
        )
        with caplog.at_level(logging.WARNING, logger="app.api.v1.strategies.crud"):
            resp = crud.create_strategy(_payload(family=None), db, user_id=1)
        assert resp.family == "legacy_manual"
        assert any("family" in r.message for r in caplog.records)

    def test_unknown_template_rejected(self):
        db = _TplDB({})  # 존재하지 않는 template_id
        with pytest.raises(HTTPException) as ei:
            crud.create_strategy(_payload(family="legacy_manual", strategy_template_id=999), db, user_id=1)
        assert ei.value.status_code == 400

    def test_invalid_family_literal_rejected_by_pydantic(self):
        with pytest.raises(Exception):
            _payload(family="something_else")


# ═══════════════════════════════════════════════════════════════════════════
# API: GET /admin/strategy-templates — 가족 필터 (감사 #2)
# ═══════════════════════════════════════════════════════════════════════════
def _tpl(*, id_, name: str, trigger_mode: str) -> NS:
    """StrategyTemplateResponse.model_validate() 가 요구하는 필드만 채운 가짜 template row.

    (conftest.py 의 db_session 픽스처는 Base.metadata 전체를 SQLite 에 만들려다
    symbols.raw_exchange_info(JSONB) 에서 깨진다 — 이 저장소의 다른 라우터 테스트들도
    실 DB 대신 가짜 객체를 쓴다, tests/test_fix369_family_separation.py 참조.)
    """
    return NS(
        id=id_, name=name, strategy_type="manual", side="SHORT", leverage=2,
        total_capital=Decimal("100"), stages_config=None,
        tp1_percent=Decimal("10"), tp2_percent=Decimal("15"), tp3_percent=Decimal("20"),
        stop_loss_percent_of_capital=Decimal("80"), is_active=True, is_favorite=False,
        trigger_mode=trigger_mode,
    )


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def order_by(self, *_a, **_kw):
        return self

    def all(self):
        return list(self._rows)


class _TemplatesDB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, _model):
        return _FakeQuery(self._rows)


class TestTemplatesFamilyFilter:
    """감사 #2 — 「📋 템플릿 선택」 탭이 다른 가족 템플릿을 골라 가족이 섞이던 사고."""

    def _rows(self):
        return [
            _tpl(id_=1, name="legacy1", trigger_mode="PRICE_DOWN_PCT"),
            _tpl(id_=2, name="obv1", trigger_mode="OBV_REVERSE"),
        ]

    def test_no_filter_returns_all(self):
        out = admin_templates.list_strategy_templates(family=None, db=_TemplatesDB(self._rows()), user_id=1)
        assert {t.name for t in out} == {"legacy1", "obv1"}

    def test_family_legacy_manual_excludes_obv(self):
        out = admin_templates.list_strategy_templates(family="legacy_manual", db=_TemplatesDB(self._rows()), user_id=1)
        names = {t.name for t in out}
        assert "legacy1" in names and "obv1" not in names

    def test_family_obv_auto_excludes_legacy(self):
        out = admin_templates.list_strategy_templates(family="obv_auto", db=_TemplatesDB(self._rows()), user_id=1)
        names = {t.name for t in out}
        assert "obv1" in names and "legacy1" not in names

    def test_unknown_family_value_is_fail_open_ignored(self):
        """목록 조회는 종목을 고르는 화면 필터 — 모르는 값이면 막지 말고 전체를 보여준다."""
        out = admin_templates.list_strategy_templates(family="garbage", db=_TemplatesDB(self._rows()), user_id=1)
        assert {t.name for t in out} == {"legacy1", "obv1"}

    def test_template_response_exposes_trigger_mode(self):
        """template-save.js 의 「템플릿 선택 복제」 경로가 trigger_mode 를 읽어야 한다."""
        out = admin_templates.list_strategy_templates(family=None, db=_TemplatesDB(self._rows()), user_id=1)
        row = next(t for t in out if t.name == "obv1")
        assert row.trigger_mode == "OBV_REVERSE"


# ═══════════════════════════════════════════════════════════════════════════
# API: GET /strategies/{id}/blueprint — trigger_mode + family 포함 (감사 #4)
# ═══════════════════════════════════════════════════════════════════════════
class TestBlueprintIncludesFamily:
    """감사 #4 — blueprint 에 trigger_mode 가 없어 「이전 전략 불러오기」가 가족을 잃었다."""

    def test_source_returns_trigger_mode_and_family(self):
        s = _src("api", "v1", "strategies", "crud.py")
        i_fn = s.find("def get_strategy_blueprint(")
        assert i_fn > 0
        body = s[i_fn:s.find("\n@router", i_fn) if s.find("\n@router", i_fn) > 0 else len(s)]
        assert '"trigger_mode": tpl.trigger_mode' in body
        assert '"family": family_of(strategy)' in body
        assert "from app.services.strategy_family import family_of" in body

    def test_create_list_get_endpoints_set_family(self):
        s = _src("api", "v1", "strategies", "crud.py")
        assert s.count("family_of(") >= 4, "create/list/get/blueprint 4곳 모두 family 를 채워야 한다"
        assert "resp.family = family_of(instance)" in s
        assert "resp.family = family_of(r)" in s
        assert "resp.family = family_of(strategy)" in s


# ═══════════════════════════════════════════════════════════════════════════
# 정적 소스 핀 — JS 동작 (감사 #1, #3, #5, #6, #7, #8)
# ═══════════════════════════════════════════════════════════════════════════
class TestStaticJsBehaviorPins:
    def test_cm_family_module_exists_and_loaded_before_consumers(self):
        path = ROOT / "static" / "js" / "cm-family.js"
        assert path.exists(), "cm-family.js missing"
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        fam_pos = html.find("/static/js/cm-family.js")
        loaders_pos = html.find("/static/js/cm-loaders.js")
        open_modal_pos = html.find("/static/js/cm-open-modal.js")
        assert 0 < fam_pos < loaders_pos < open_modal_pos

    def test_cm_family_defines_required(self):
        js = (ROOT / "static" / "js" / "cm-family.js").read_text(encoding="utf-8")
        for fn in ["function _resolveFamilyLoose", "function familyFromStrategy",
                   "function computeModalFamily",
                   "function _applyObvModalVisuals", "function _resetObvModalVisuals"]:
            assert fn in js, fn

    def test_family_decision_functions_have_no_dialog_or_dom(self):
        """리뷰 HIGH #2 — 판정 함수는 confirm()/document 를 쓰지 않는다(순수 함수, node 로도 실행 가능)."""
        js = (ROOT / "static" / "js" / "cm-family.js").read_text(encoding="utf-8")
        for fn_name in ("familyFromStrategy", "computeModalFamily", "_resolveFamilyLoose"):
            i_fn = js.find(f"function {fn_name}")
            assert i_fn > 0, fn_name
            end = js.find("\nfunction ", i_fn + 10)
            body = js[i_fn:end if end > 0 else len(js)]
            assert "confirm(" not in body, f"{fn_name} 에 confirm() 대화상자가 있으면 안 된다"
            assert "document." not in body, f"{fn_name} 은 DOM 을 건드리면 안 된다(순수 함수)"

    def test_obv_modal_disables_template_and_prev_tabs(self):
        """감사 #1 — 존재하지 않는 cm-template-select 대신 실제 탭 버튼을 비활성화해야 한다."""
        js = (ROOT / "static" / "js" / "cm-family.js").read_text(encoding="utf-8")
        i_fn = js.find("function _applyObvModalVisuals")
        body = js[i_fn:js.find("\nfunction ", i_fn + 10)]
        assert "_disableModeTab('cm-mode-template')" in body
        assert "_disableModeTab('cm-mode-prev')" in body
        assert "cm-template-select" not in js, "존재하지 않는 element id 재도입 금지"

    def test_reset_reenables_tabs(self):
        js = (ROOT / "static" / "js" / "cm-family.js").read_text(encoding="utf-8")
        i_fn = js.find("function _resetObvModalVisuals")
        body = js[i_fn:js.find("\nfunction ", i_fn + 10) if js.find("\nfunction ", i_fn + 10) > 0 else len(js)]
        assert "_enableModeTab('cm-mode-template')" in body
        assert "_enableModeTab('cm-mode-prev')" in body

    def test_open_modal_resets_visuals_via_shared_helper(self):
        om = (ROOT / "static" / "js" / "cm-open-modal.js").read_text(encoding="utf-8")
        assert "_resetObvModalVisuals();" in om
        assert "_applyObvModalVisuals();" in om

    def test_cm_loaders_filters_templates_by_family(self):
        """감사 #2 — 「기존 방식」 모달의 템플릿 탭이 OBV 템플릿을 목록에서 뺀다(그 반대도)."""
        js = (ROOT / "static" / "js" / "cm-loaders.js").read_text(encoding="utf-8")
        i_fn = js.find("async function loadCmTemplates")
        body = js[i_fn:js.find("\nasync function ", i_fn + 10) if js.find("\nasync function ", i_fn + 10) > 0 else len(js)]
        # S3 재검증: 가족은 모달 세션 내내 유지되는 _triggerMode 로 판정 (_pendingObv 는 열기 끝에서 지워지는 일회용)
        assert "cmState._triggerMode === 'OBV_REVERSE'" in body
        assert "cmState._pendingObv" not in body
        assert "/admin/strategy-templates?family=" in body

    def test_edit_restart_abort_on_lookup_failure(self):
        """감사 #5 — 조회 실패 시 조용히 기존 방식으로 폴백하지 않고 중단해야 한다."""
        om = (ROOT / "static" / "js" / "cm-open-modal.js").read_text(encoding="utf-8")
        i_fn = om.find("async function openCreateModal(editStrategyId)")
        assert i_fn > 0
        head = om[i_fn:i_fn + 2500]
        assert "catch (_e369)" in head and "return;" in head[head.find("catch (_e369)"):]
        assert "familyFromStrategy(_orig369)" in head
        # trigger_mode 자체를 확인할 수 없을 때만 중단한다(리뷰 HIGH #2 — confirm() 으로 되묻지 않음)
        assert "if (!_resolvedFamily369)" in head
        assert "confirm(" not in head, "리뷰 HIGH #2 — 수정/재시작 경로에 확인창을 다시 넣지 않는다"

    def test_pending_obv_captured_and_cleared_immediately_at_top(self):
        """리뷰 BLOCKING #1 — 다음 open 으로 새지 않도록 맨 위에서 캡처 후 즉시 지운다."""
        om = (ROOT / "static" / "js" / "cm-open-modal.js").read_text(encoding="utf-8")
        i_fn = om.find("async function openCreateModal(editStrategyId)")
        i_cap = om.find("const _pendingObvForThisOpen369 = !!(cmState && cmState._pendingObv);", i_fn)
        assert i_fn < i_cap
        after = om[i_cap:i_cap + 200]
        assert "if (cmState) cmState._pendingObv = false;" in after
        # editStrategyId 조회/판정 블록보다 먼저 캡처돼야 한다(조회 도중 값이 바뀌지 않게)
        i_edit_check = om.find("if (editStrategyId) {", i_fn)
        assert i_cap < i_edit_check

    def test_compute_modal_family_ignores_stale_flag_when_editing(self):
        """리뷰 BLOCKING #1(a) — editStrategyId 가 있으면 resolvedFamily 만 본다, pendingObv 무시."""
        om = (ROOT / "static" / "js" / "cm-open-modal.js").read_text(encoding="utf-8")
        i = om.find("const _modalFamily369 = computeModalFamily({")
        assert i > 0
        body = om[i:i + 200]
        assert "editStrategyId," in body and "resolvedFamily: _resolvedFamily369," in body
        assert "pendingObvForThisOpen: _pendingObvForThisOpen369" in body

    def test_open_modal_clears_pending_obv_at_end(self):
        """리뷰 BLOCKING #1(c) — 함수 끝에서도 소거해 다음 호출로 새지 않게 한다."""
        om = (ROOT / "static" / "js" / "cm-open-modal.js").read_text(encoding="utf-8")
        i_fn = om.find("async function openCreateModal(editStrategyId)")
        i_end = om.find("\nasync function loadRecentStrategiesQuick", i_fn)
        assert i_fn < i_end
        tail = om[i_end - 400:i_end]
        assert "if (cmState) cmState._pendingObv = false;" in tail

    def test_close_create_modal_clears_pending_obv(self):
        """리뷰 BLOCKING #1(c) — 모달을 닫을 때도 방어적으로 소거한다."""
        js = (ROOT / "static" / "js" / "cm-state-helpers.js").read_text(encoding="utf-8")
        i_fn = js.find("function closeCreateModal()")
        assert i_fn > 0
        body = js[i_fn:js.find("\nfunction ", i_fn + 10) if js.find("\nfunction ", i_fn + 10) > 0 else len(js)]
        assert "cmState._pendingObv = false;" in body

    def test_load_prev_blueprint_uses_trigger_mode_not_stale_pending_flag(self):
        """리뷰 BLOCKING #1(d) — 「이전 전략 불러오기」 탭 안전장치는 _triggerMode(모달 세션 내내
        유지)를 봐야 한다. _pendingObv 는 openCreateModal() 호출 동안만 유효한 일회용 신호라
        탭 클릭 시점(모달이 이미 열려 있음)엔 항상 false 라서 이 안전장치가 무력화된다."""
        js = (ROOT / "static" / "js" / "cm-prev-blueprint.js").read_text(encoding="utf-8")
        i = js.find("const _wantObvNow = ")
        assert i > 0
        assert "cmState._triggerMode === 'OBV_REVERSE'" in js[i:i + 150]
        assert "cmState._pendingObv" not in js[i:i + 150]

    def test_edit_restart_never_silently_falls_back_to_legacy_pricecode(self):
        """구 Fix 367d 의 '조회 실패 시 PRICE_DOWN_PCT 유지' 문구가 되살아나면 안 된다."""
        om = (ROOT / "static" / "js" / "cm-open-modal.js").read_text(encoding="utf-8")
        assert "원 전략 trigger_mode 조회 실패 → PRICE_DOWN_PCT 유지" not in om

    def test_both_quick_action_buttons_send_family(self):
        """감사 설계 — 두 「+ 새 전략」 버튼(cm-submit.js 단일 경로 + multi-symbol.js 다중 경로)이 명시적으로 family 를 보낸다."""
        submit = (ROOT / "static" / "js" / "cm-submit.js").read_text(encoding="utf-8")
        assert "family: _familyToSend369" in submit
        assert "_familyToSend369 = (cmState._triggerMode === 'OBV_REVERSE') ? 'obv_auto' : 'legacy_manual'" in submit

        multi = (ROOT / "static" / "js" / "multi-symbol.js").read_text(encoding="utf-8")
        assert "family: (cmState._triggerMode === 'OBV_REVERSE') ? 'obv_auto' : 'legacy_manual'" in multi

    def test_toast_reflects_actual_created_family(self):
        """감사 설계 — 토스트는 요청 의도가 아니라 서버가 실제로 만든 가족(created.family)을 본다."""
        submit = (ROOT / "static" / "js" / "cm-submit.js").read_text(encoding="utf-8")
        assert "const _actualFamily369 = created && created.family;" in submit
        i = submit.find("const _modeLabel = ")
        assert "_actualFamily369 === 'obv_auto'" in submit[i:i + 300]

    def test_multi_symbol_collects_fresh_inputs_not_cache(self):
        """감사 #7 — 미리보기 캐시 대신 제출 시점에 폼을 다시 읽는다."""
        multi = (ROOT / "static" / "js" / "multi-symbol.js").read_text(encoding="utf-8")
        assert "const inp = (typeof _collectDirectInputs === 'function') ? _collectDirectInputs() : cmState._directInputs;" in multi
        assert "const inp = cmState._directInputs || _collectDirectInputs();" not in multi

    def test_favorite_templates_routes_by_trigger_mode(self):
        """감사 #6 — 「⭐ 즐겨찾기」/「저장된 전략」 클릭이 템플릿 가족에 맞는 모달을 연다."""
        js = (ROOT / "static" / "js" / "favorite-templates.js").read_text(encoding="utf-8")
        i_fn = js.find("async function startStrategyFromTemplate")
        body = js[i_fn:js.find("\nasync function ", i_fn + 10) if js.find("\nasync function ", i_fn + 10) > 0 else len(js)]
        assert "trigger_mode || '').toUpperCase() === 'OBV_REVERSE'" in body
        assert "openCreateChartObvModal" in body

    def test_prev_blueprint_tab_excludes_obv_family(self):
        """감사 #4 — 「📂 이전 전략 불러오기」 탭(기존 방식 모달 전용)이 OBV 가족을 목록에서 뺀다."""
        js = (ROOT / "static" / "js" / "cm-prev-blueprint.js").read_text(encoding="utf-8")
        i_fn = js.find("async function loadCmPrevStrategies")
        body = js[i_fn:js.find("\nasync function ", i_fn + 10) if js.find("\nasync function ", i_fn + 10) > 0 else len(js)]
        assert "_resolveFamilyLoose(s) !== 'obv_auto'" in body

    def test_load_prev_blueprint_refuses_cross_family(self):
        js = (ROOT / "static" / "js" / "cm-prev-blueprint.js").read_text(encoding="utf-8")
        i_fn = js.find("async function loadPrevBlueprint")
        body = js[i_fn:i_fn + 1200]
        assert "_isObvBp" in body and "_wantObvNow" in body
        assert "OBV 자동 전략입니다" in body

    def test_strategies_list_badge_prefers_family_field(self):
        """감사 #8 — 배지가 template 값 대신 서버가 계산한 family 를 우선 쓴다."""
        js = (ROOT / "static" / "js" / "strategies-list.js").read_text(encoding="utf-8")
        assert "s.family === 'obv_auto' : s.trigger_mode === 'OBV_REVERSE'" in js
        assert "s.family === 'legacy_manual'" in js

    def test_two_main_buttons_still_call_distinct_modals(self):
        """두 「+ 새 전략」 버튼은 그대로 openCreateModal()/openCreateChartObvModal() 을 명시적으로 호출한다."""
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        assert 'onclick="openCreateModal()"' in html
        assert 'onclick="openCreateChartObvModal()"' in html

    def test_new_strategy_autofill_filters_by_same_family(self):
        """감사 #3 — 새 전략 자동 채움이 가족을 가리지 않고 "가장 최근 전략"을 쓰던 것."""
        om = (ROOT / "static" / "js" / "cm-open-modal.js").read_text(encoding="utf-8")
        i_fn = om.find("const _prev = await api('/strategies?include_archived=false');")
        assert i_fn > 0
        body = om[i_fn:i_fn + 900]
        assert "_resolveFamilyLoose(s) !== (_wantObv369 ? 'obv_auto' : 'legacy_manual')" in body
        assert "_wantObv369 = _modalFamily369 === 'obv_auto'" in body

    def test_new_strategy_autofill_excludes_managed_reentry_clones(self):
        """리뷰 HIGH #2 부수 항목 — 관리 재진입 복제 템플릿(_quick_m...)은 OBV 모달 자동 채움에서 뺀다
        (코드 주석은 이미 그렇게 주장했지만 실제로는 걸러내지 않던 것 — 주석과 코드를 맞춘다)."""
        om = (ROOT / "static" / "js" / "cm-open-modal.js").read_text(encoding="utf-8")
        i_fn = om.find("const _sameFamily369 = (_prev || []).filter((s) => {")
        assert i_fn > 0
        body = om[i_fn:i_fn + 700]
        assert "String(s.template_name || '').startsWith('_quick_m')" in body

    def test_strategy_detail_response_exposes_template_name(self):
        """위 제외 로직이 쓰는 template_name 필드가 실제로 응답에 있는지."""
        schema = _src("schemas", "strategy.py")
        assert "template_name: str | None = None" in schema
        crud_src = _src("api", "v1", "strategies", "crud.py")
        assert crud_src.count("resp.template_name = tpl.name if tpl else None") >= 2


# ═══════════════════════════════════════════════════════════════════════════
# 행동 실행 테스트 — cm-family.js 의 순수 함수를 node 로 직접 돌린다 (문자열 핀만이 아니라
# 실제로 그 값을 계산해서 검증한다). 리뷰(2026-09-13) 요청: BLOCKING #1 / HIGH #2 재발 방지.
# ═══════════════════════════════════════════════════════════════════════════
_NODE = shutil.which("node")


def _run_family_scenarios() -> dict:
    """cm-family.js 를 node vm 으로 로드하고 6가지 시나리오를 계산해 JSON 으로 돌려받는다."""
    cm_family_src = (Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "cm-family.js").read_text(encoding="utf-8")
    harness = f"""
'use strict';
const vm = require('vm');
const sandbox = {{}};
vm.createContext(sandbox);
vm.runInContext({json.dumps(cm_family_src)}, sandbox);

const out = {{}};

// 1. OBV 수정 → 닫기 → 「기존 방식」 새 전략 = legacy
//    (닫힌 뒤의 새 open 은 editStrategyId 없음 + 이번 호출의 pendingObv 는 false 여야 한다 —
//     computeModalFamily 자체가 "이전 세션"을 아예 파라미터로 받지 않는다는 것이 곧 그 증명이다)
out.obv_edit_then_close_then_legacy_new = sandbox.computeModalFamily({{
  editStrategyId: undefined, resolvedFamily: null, pendingObvForThisOpen: false,
}});

// 2. OBV 수정 → (닫지 않고) 다른 legacy 전략 수정 = legacy
out.obv_edit_then_legacy_edit = sandbox.computeModalFamily({{
  editStrategyId: 2, resolvedFamily: 'legacy_manual', pendingObvForThisOpen: false,
}});
// 같은 시나리오를 "만약 pendingObv 가 stale 하게 true 로 남아있었다면" 조건으로도 확인 —
// editStrategyId 가 있으면 결과가 바뀌면 안 된다(리뷰 BLOCKING #1(a) 의 핵심 요구).
out.obv_edit_then_legacy_edit_even_with_stale_pending_obv = sandbox.computeModalFamily({{
  editStrategyId: 2, resolvedFamily: 'legacy_manual', pendingObvForThisOpen: true,
}});

// 3. 📊 OBV 버튼으로 새 전략 = obv
out.obv_button_new = sandbox.computeModalFamily({{
  editStrategyId: undefined, resolvedFamily: null, pendingObvForThisOpen: true,
}});

// 4. family='other' (사다리/분할/단일/자동워커 등) + trigger_mode=PRICE_DOWN_PCT = legacy, 대화상자 없음
//    (confirm 을 전역에 정의하지 않았다 — 만약 호출됐다면 ReferenceError 로 여기서 죽는다)
out.family_other_with_price_trigger = sandbox.familyFromStrategy({{
  id: 3, family: 'other', entry_profile: null, trigger_mode: 'PRICE_DOWN_PCT',
}});

// 5. trigger_mode = OBV_REVERSE = obv
out.trigger_mode_obv_reverse = sandbox.familyFromStrategy({{ id: 4, trigger_mode: 'OBV_REVERSE' }});

// 6. trigger_mode 없음(응답 손상) = null(중단)
out.trigger_mode_missing = sandbox.familyFromStrategy({{ id: 5, trigger_mode: null }});
out.orig_missing_entirely = sandbox.familyFromStrategy(null);

console.log(JSON.stringify(out));
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(harness)
        path = f.name
    try:
        proc = subprocess.run([_NODE, path], capture_output=True, text=True, timeout=30)
    finally:
        Path(path).unlink(missing_ok=True)
    assert proc.returncode == 0, f"node 실행 실패:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(_NODE is None, reason="node 미설치 — cm-family.js 순수 함수 행동 테스트 건너뜀")
class TestFamilyDecisionFunctionsBehavior:
    """cm-family.js 의 computeModalFamily/familyFromStrategy 를 실제로 실행해 검증한다.

    문자열 핀은 "그 코드가 존재하는지" 만 보고 "그 코드가 맞는 값을 계산하는지" 는 못 본다 —
    리뷰가 잡은 BLOCKING #1(오래된 OBV 플래그가 다음 open 으로 샘)과 HIGH #2(확인창 OK 가
    OBV 를 고름)는 둘 다 "핀은 통과하는데 값은 틀린" 종류의 사고였다.
    """

    @pytest.fixture(scope="class")
    def scenarios(self):
        return _run_family_scenarios()

    def test_obv_edit_then_close_then_legacy_new_is_legacy(self, scenarios):
        assert scenarios["obv_edit_then_close_then_legacy_new"] == "legacy_manual"

    def test_obv_edit_then_legacy_edit_is_legacy(self, scenarios):
        assert scenarios["obv_edit_then_legacy_edit"] == "legacy_manual"

    def test_edit_path_ignores_stale_pending_obv_flag(self, scenarios):
        """리뷰 BLOCKING #1(a) 핵심 — editStrategyId 가 있으면 pendingObv 값이 뭐든 결과가 같아야 한다."""
        assert (
            scenarios["obv_edit_then_legacy_edit"]
            == scenarios["obv_edit_then_legacy_edit_even_with_stale_pending_obv"]
            == "legacy_manual"
        )

    def test_obv_button_new_is_obv(self, scenarios):
        assert scenarios["obv_button_new"] == "obv_auto"

    def test_family_other_with_price_trigger_is_legacy_no_dialog(self, scenarios):
        """리뷰 HIGH #2 — family 가 애매해도(사다리/분할 등) trigger_mode 가 있으면 확인창 없이 legacy."""
        assert scenarios["family_other_with_price_trigger"] == "legacy_manual"

    def test_trigger_mode_obv_reverse_is_obv(self, scenarios):
        assert scenarios["trigger_mode_obv_reverse"] == "obv_auto"

    def test_trigger_mode_missing_aborts(self, scenarios):
        assert scenarios["trigger_mode_missing"] is None
        assert scenarios["orig_missing_entirely"] is None

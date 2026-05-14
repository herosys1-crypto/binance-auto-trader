"""Static asset 무결성 검증 — Phase 3 분리 회귀 방지 (2026-05-14).

배경:
- index.html 5,875 줄 monolith 에서 상수 모듈을 /static/js/constants.js 로 분리
- 분리 후 누군가 inline 으로 다시 정의하거나 script tag 를 빼먹으면 frontend 깨짐
- 또한 dead reference (예: 제거된 dropdown element id) 가 다시 추가되면 죽은 코드 누적

이 테스트는 frontend 자체를 실행하지 않지만 분리 의도가 유지됐는지 lint 차원에서 검증.
"""
from __future__ import annotations

import re
from pathlib import Path


def _backend_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _index_html() -> str:
    return (_backend_root() / "app" / "static" / "index.html").read_text(encoding="utf-8")


def _constants_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "constants.js").read_text(encoding="utf-8")


def _api_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "api.js").read_text(encoding="utf-8")


def _stats_modals_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "stats-modals.js").read_text(encoding="utf-8")


def _health_page_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "health-page.js").read_text(encoding="utf-8")


def _ranking_page_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "ranking-page.js").read_text(encoding="utf-8")


def _helpers_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "helpers.js").read_text(encoding="utf-8")


def _ranking_modal_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "ranking-modal.js").read_text(encoding="utf-8")


def _trade_history_modal_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "trade-history-modal.js").read_text(encoding="utf-8")


def _system_banner_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "system-banner.js").read_text(encoding="utf-8")


def _multi_symbol_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "multi-symbol.js").read_text(encoding="utf-8")


def _template_save_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "template-save.js").read_text(encoding="utf-8")


def _cm_collectors_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "cm-collectors.js").read_text(encoding="utf-8")


def _cm_prev_blueprint_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "cm-prev-blueprint.js").read_text(encoding="utf-8")


def _cm_loaders_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "cm-loaders.js").read_text(encoding="utf-8")


def _cm_market_info_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "cm-market-info.js").read_text(encoding="utf-8")


def _cm_capitals_grid_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "cm-capitals-grid.js").read_text(encoding="utf-8")


def _cm_submit_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "cm-submit.js").read_text(encoding="utf-8")


def _cm_state_helpers_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "cm-state-helpers.js").read_text(encoding="utf-8")


def _cm_preview_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "cm-preview.js").read_text(encoding="utf-8")


def _cm_open_modal_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "cm-open-modal.js").read_text(encoding="utf-8")


def _dashboard_refresh_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "dashboard-refresh.js").read_text(encoding="utf-8")


def _templates_panel_js() -> str:
    return (_backend_root() / "app" / "static" / "js" / "templates-panel.js").read_text(encoding="utf-8")


class TestStaticAssetsIntegrity:
    """index.html + js/constants.js 분리 구조 검증."""

    def test_constants_js_exists(self):
        """app/static/js/constants.js 파일 존재."""
        path = _backend_root() / "app" / "static" / "js" / "constants.js"
        assert path.exists(), "constants.js missing — Phase 3 분리 깨짐"

    def test_index_html_loads_constants_js_before_inline_script(self):
        """<script src='/static/js/constants.js'> 가 본문 inline script 보다 먼저 로드돼야.

        본문이 STATUS_MAP / TERMINAL_STATUSES 등을 참조하므로 순서 중요.
        """
        html = _index_html()
        tag_pos = html.find("/static/js/constants.js")
        # 2026-05-14 Phase 3 추가: const API_BASE 가 api.js 로 이동했으므로 anchor 변경.
        # 본문 첫 inline 함수 (showDashboard) 위치를 anchor 로 사용.
        inline_pos = html.find("function showDashboard")
        assert tag_pos > 0, "<script src='/static/js/constants.js'> tag 누락"
        assert inline_pos > tag_pos, (
            "constants.js 가 본문 inline script 뒤에 로드됨 — 순서 잘못됨"
        )

    def test_no_inline_constants_redefinition_in_index_html(self):
        """index.html 안에 STATUS_MAP / TERMINAL_STATUSES 등이 다시 정의돼있으면 안 됨.

        분리 후 누군가 inline 으로 복원하면 두 곳에서 정의 → 후자가 덮어써서 silent bug.
        """
        html = _index_html()
        # 'const NAME = ' 패턴 검출 (script 안에서 top-level 선언)
        forbidden_names = ["STATUS_MAP", "ORDER_STATUS_MAP", "PURPOSE_MAP", "TERMINAL_STATUSES"]
        violations = []
        for name in forbidden_names:
            # const NAME = { 또는 const NAME = [
            pattern = re.compile(r'\bconst\s+' + re.escape(name) + r'\s*=', re.MULTILINE)
            matches = pattern.findall(html)
            if matches:
                violations.append(f"{name} ({len(matches)} 회 inline 정의)")
        assert not violations, (
            "index.html 에 상수 inline 정의 발견 — constants.js 와 중복:\n  "
            + "\n  ".join(violations)
        )

    def test_constants_js_defines_all_required(self):
        """constants.js 가 STATUS_MAP / ORDER_STATUS_MAP / PURPOSE_MAP / TERMINAL_STATUSES 모두 정의."""
        js = _constants_js()
        for name in ["STATUS_MAP", "ORDER_STATUS_MAP", "PURPOSE_MAP", "TERMINAL_STATUSES"]:
            pattern = re.compile(r'\bconst\s+' + re.escape(name) + r'\s*=')
            assert pattern.search(js), f"{name} 정의 누락 — constants.js"

    def test_status_map_includes_all_stage_and_tp_levels(self):
        """STATUS_MAP 이 STAGE1~10 + TP1~5 PARTIAL 모두 포함.

        TP10 확장 같은 차원 변경 시 frontend 도 동기화 필요한지 검증.
        backend 의 strategy_status.py (TOTAL_STAGES_MAX = 10, TOTAL_TP_LEVELS = 10)
        와 의미 일치 확인.
        """
        js = _constants_js()
        for n in range(1, 11):
            assert f"'STAGE{n}_OPEN'" in js, f"STAGE{n}_OPEN 누락 (10단계 동적)"
        # TP1~5 _DONE_PARTIAL 는 frontend 라벨로 사용 (TP6~10 은 status 자체 없음 — 정상)
        for n in range(1, 6):
            assert f"'TP{n}_DONE_PARTIAL'" in js, f"TP{n}_DONE_PARTIAL 누락"

    def test_terminal_statuses_matches_backend(self):
        """frontend TERMINAL_STATUSES 가 backend TERMINAL_STATUSES 와 의미 동일.

        STOPPING 은 frontend 에선 hide (사용자 관점 종료), backend 에선 active
        (race-window 보호) — 의도적 차이라 frontend 만 STOPPING 추가.
        나머지 항목은 양측 모두 포함해야 함.
        """
        from app.core.strategy_status import TERMINAL_STATUSES as BACKEND_TERMINAL

        js = _constants_js()
        # extract array literal
        m = re.search(r'const\s+TERMINAL_STATUSES\s*=\s*\[(.*?)\]', js, re.DOTALL)
        assert m, "TERMINAL_STATUSES 배열 찾을 수 없음"
        items = re.findall(r"'([^']+)'", m.group(1))
        frontend_set = set(items)

        # 모든 backend TERMINAL_STATUSES 가 frontend 에도 있어야 함
        missing_in_frontend = BACKEND_TERMINAL - frontend_set
        assert not missing_in_frontend, (
            f"backend TERMINAL_STATUSES 가 frontend 에 누락: {missing_in_frontend}\n"
            "constants.js 의 TERMINAL_STATUSES 갱신 필요"
        )

        # frontend 만 가질 수 있는 항목 (의도적): STOPPING
        extras = frontend_set - BACKEND_TERMINAL
        allowed_extras = {"STOPPING"}
        unexpected = extras - allowed_extras
        assert not unexpected, (
            f"frontend TERMINAL_STATUSES 에 backend 미포함 + STOPPING 외 추가 항목: {unexpected}"
        )

    def test_api_js_exists_and_loaded_before_inline_script(self):
        """api.js (Phase 3 추가) 가 존재 + index.html 본문 inline script 보다 먼저 로드."""
        path = _backend_root() / "app" / "static" / "js" / "api.js"
        assert path.exists(), "api.js missing — Phase 3 추가 분리 깨짐"

        html = _index_html()
        api_tag_pos = html.find("/static/js/api.js")
        # 첫 번째 본문 inline 의 의미있는 식별자 (auth handler 등록)
        inline_pos = html.find("login-form")
        assert api_tag_pos > 0, "<script src='/static/js/api.js'> tag 누락"
        # 정확한 본문 inline script 시작은 const 선언인데, 이제 그게 빠져있어 다른 anchor 사용.
        # api.js 가 constants.js 다음에 와야 (둘 다 inline 보다 먼저).
        const_tag_pos = html.find("/static/js/constants.js")
        assert const_tag_pos > 0
        # 두 script tag 모두 본문 첫 inline 함수 정의 (showDashboard 등) 보다 먼저
        first_func_pos = html.find("function showDashboard")
        assert const_tag_pos < first_func_pos
        assert api_tag_pos < first_func_pos

    def test_api_js_defines_all_required(self):
        """api.js 가 API_BASE / token / api / toast / logout 모두 정의."""
        js = _api_js()
        required_patterns = [
            r"const\s+API_BASE\s*=",
            r"let\s+token\s*=",
            r"function\s+logout\s*\(",
            r"async\s+function\s+api\s*\(",
            r"function\s+toast\s*\(",
        ]
        for pat in required_patterns:
            assert re.search(pat, js), f"api.js 에 패턴 누락: {pat}"

    def test_no_inline_api_helpers_in_index_html(self):
        """index.html 본문에 api/toast/logout/API_BASE/token 정의가 다시 들어오면 안 됨.

        Phase 3 추가 분리 후 누군가 inline 으로 복원하면 두 곳 정의 → silent bug.
        """
        html = _index_html()
        forbidden = [
            (r"^const\s+API_BASE\s*=", "API_BASE inline"),
            (r"^let\s+token\s*=\s*localStorage", "token inline"),
            (r"^function\s+logout\s*\(\)", "logout() inline"),
            (r"^async\s+function\s+api\s*\(", "api() inline"),
            (r"^function\s+toast\s*\(", "toast() inline"),
        ]
        violations = []
        for pat, label in forbidden:
            if re.search(pat, html, re.MULTILINE):
                violations.append(label)
        assert not violations, (
            "index.html 에 api.js 의 helper 가 inline 정의됨 (분리 깨짐):\n  "
            + "\n  ".join(violations)
        )

    def test_stats_modals_js_exists_and_loaded(self):
        """stats-modals.js (Phase 3 추가) 존재 + script tag 순서 검증.

        api.js 의존하므로 api.js 다음에 로드돼야.
        """
        path = _backend_root() / "app" / "static" / "js" / "stats-modals.js"
        assert path.exists(), "stats-modals.js missing — Phase 3 분리 깨짐"

        html = _index_html()
        api_pos = html.find("/static/js/api.js")
        modals_pos = html.find("/static/js/stats-modals.js")
        assert modals_pos > 0, "<script src='/static/js/stats-modals.js'> tag 누락"
        assert modals_pos > api_pos, (
            "stats-modals.js 가 api.js 보다 먼저 로드됨 — api() 의존성 순서 깨짐"
        )

    def test_stats_modals_js_defines_all_required(self):
        """stats-modals.js 가 5개 모달 함수 모두 정의."""
        js = _stats_modals_js()
        required = [
            "async function openStatsBreakdownModal",
            "function closeStatsBreakdownModal",
            "async function loadStatsBreakdown",
            "async function openTpNotificationsModal",
            "function closeTpNotificationsModal",
        ]
        missing = [r for r in required if r not in js]
        assert not missing, f"stats-modals.js 누락 함수: {missing}"

    def test_no_inline_stats_modals_in_index_html(self):
        """index.html 본문에 5개 모달 함수가 다시 inline 정의되면 안 됨.

        분리 후 누군가 inline 으로 복원 → 두 곳 정의 → 후자가 덮어써서 silent bug.
        """
        html = _index_html()
        forbidden = [
            "async function openStatsBreakdownModal",
            "async function loadStatsBreakdown",
            "async function openTpNotificationsModal",
        ]
        violations = [pat for pat in forbidden if pat in html]
        assert not violations, (
            "index.html 에 stats-modals 함수 inline 재정의 발견:\n  "
            + "\n  ".join(violations)
        )

    def test_health_page_js_exists_and_loaded(self):
        """health-page.js (Phase 3 추가) 존재 + script tag 순서 검증."""
        path = _backend_root() / "app" / "static" / "js" / "health-page.js"
        assert path.exists(), "health-page.js missing"

        html = _index_html()
        api_pos = html.find("/static/js/api.js")
        health_pos = html.find("/static/js/health-page.js")
        assert health_pos > 0, "<script src='/static/js/health-page.js'> tag 누락"
        assert health_pos > api_pos, "health-page.js 가 api.js 보다 먼저 로드됨"

    def test_health_page_js_defines_loadHealthDashboard(self):
        """health-page.js 가 loadHealthDashboard 정의."""
        js = _health_page_js()
        assert "async function loadHealthDashboard" in js, "loadHealthDashboard 정의 누락"

    def test_no_inline_load_health_dashboard_in_index_html(self):
        """index.html 에 loadHealthDashboard inline 재정의 금지."""
        html = _index_html()
        assert "async function loadHealthDashboard" not in html, (
            "loadHealthDashboard 가 index.html 에 inline 재정의됨 — health-page.js 와 중복"
        )

    def test_ranking_page_js_exists_and_loaded(self):
        """ranking-page.js (Phase 3 추가) 존재 + script tag 검증."""
        path = _backend_root() / "app" / "static" / "js" / "ranking-page.js"
        assert path.exists(), "ranking-page.js missing"

        html = _index_html()
        api_pos = html.find("/static/js/api.js")
        ranking_pos = html.find("/static/js/ranking-page.js")
        assert ranking_pos > 0, "<script src='/static/js/ranking-page.js'> tag 누락"
        assert ranking_pos > api_pos, "ranking-page.js 가 api.js 보다 먼저 로드됨"

    def test_ranking_page_js_defines_required(self):
        """ranking-page.js 가 loadRankingPage + startNewStrategyFromRanking 정의."""
        js = _ranking_page_js()
        assert "async function loadRankingPage" in js
        assert "function startNewStrategyFromRanking" in js

    def test_no_inline_ranking_page_in_index_html(self):
        """index.html 에 ranking-page 함수 inline 재정의 금지."""
        html = _index_html()
        assert "async function loadRankingPage" not in html
        assert "function startNewStrategyFromRanking" not in html

    def test_helpers_js_exists_and_loaded(self):
        """helpers.js (Phase 3 추가) 존재 + script tag 검증.

        다른 모듈 (stats-modals 등) 이 escapeHtml/fmtNum 등 의존하므로
        constants.js 다음, 다른 feature 모듈보다 먼저 로드돼야.
        """
        path = _backend_root() / "app" / "static" / "js" / "helpers.js"
        assert path.exists(), "helpers.js missing"

        html = _index_html()
        const_pos = html.find("/static/js/constants.js")
        helpers_pos = html.find("/static/js/helpers.js")
        modals_pos = html.find("/static/js/stats-modals.js")
        assert helpers_pos > 0, "<script src='/static/js/helpers.js'> tag 누락"
        assert helpers_pos > const_pos, "helpers.js 가 constants.js 보다 먼저 로드됨"
        # helpers.js 가 stats-modals.js 보다 먼저여야 (escapeHtml 의존)
        assert helpers_pos < modals_pos, (
            "helpers.js 가 stats-modals.js 보다 늦게 로드됨 — escapeHtml 의존 깨짐"
        )

    def test_helpers_js_defines_all_required(self):
        """helpers.js 가 핵심 helper 함수 모두 정의."""
        js = _helpers_js()
        required = [
            "function statusInfo",
            "function sideBadge",
            "function renderStageBar",
            "function _tpCountFromStatus",
            "function renderTpBar",
            "function fmtNum",
            "function fmtQty",
            "function fmtPnL",
            "function setMetric",
            "function setSignal",
            "function showAlert",
            "function hideAlert",
            "function escapeHtml",
        ]
        missing = [r for r in required if r not in js]
        assert not missing, f"helpers.js 누락 함수: {missing}"

    def test_no_inline_helpers_in_index_html(self):
        """index.html 에 helpers 함수 inline 재정의 금지."""
        html = _index_html()
        forbidden = [
            "function statusInfo(status) {",
            "function escapeHtml(s) {",
            "function fmtNum(v) {",
            "function fmtQty(v) {",
            "function fmtPnL(v) {",
        ]
        violations = [pat for pat in forbidden if pat in html]
        assert not violations, (
            "index.html 에 helpers 함수 inline 재정의 발견:\n  " + "\n  ".join(violations)
        )

    def test_ranking_modal_js_exists_and_loaded(self):
        """ranking-modal.js (Phase 3 추가) 존재 + script tag 검증."""
        path = _backend_root() / "app" / "static" / "js" / "ranking-modal.js"
        assert path.exists(), "ranking-modal.js missing"

        html = _index_html()
        helpers_pos = html.find("/static/js/helpers.js")
        modal_pos = html.find("/static/js/ranking-modal.js")
        assert modal_pos > 0, "<script src='/static/js/ranking-modal.js'> tag 누락"
        assert modal_pos > helpers_pos, "ranking-modal.js 가 helpers.js 보다 먼저 로드됨"

    def test_ranking_modal_js_defines_required(self):
        """ranking-modal.js 가 4 함수 모두 정의."""
        js = _ranking_modal_js()
        for fn in [
            "async function openSymbolRankingModal",
            "function closeSymbolRankingModal",
            "async function loadSymbolRanking",
            "function selectSymbolFromRanking",
        ]:
            assert fn in js, f"ranking-modal.js 누락: {fn}"

    def test_no_inline_ranking_modal_in_index_html(self):
        """index.html 에 ranking-modal 함수 inline 재정의 금지."""
        html = _index_html()
        forbidden = [
            "async function openSymbolRankingModal",
            "async function loadSymbolRanking",
            "function selectSymbolFromRanking",
        ]
        violations = [pat for pat in forbidden if pat in html]
        assert not violations, (
            "index.html 에 ranking-modal 함수 inline 재정의 발견:\n  " + "\n  ".join(violations)
        )

    def test_trade_history_modal_js_exists_and_loaded(self):
        """trade-history-modal.js 존재 + script tag 검증."""
        path = _backend_root() / "app" / "static" / "js" / "trade-history-modal.js"
        assert path.exists(), "trade-history-modal.js missing"

        html = _index_html()
        helpers_pos = html.find("/static/js/helpers.js")
        modal_pos = html.find("/static/js/trade-history-modal.js")
        assert modal_pos > 0, "<script src='/static/js/trade-history-modal.js'> tag 누락"
        assert modal_pos > helpers_pos, "trade-history-modal.js 가 helpers.js 보다 먼저 로드됨"

    def test_trade_history_modal_js_defines_required(self):
        """trade-history-modal.js 가 5 함수 모두 정의."""
        js = _trade_history_modal_js()
        for fn in [
            "async function openTradeHistoryModal",
            "function closeTradeHistoryModal",
            "async function loadTradeHistory",
            "function filterTradeHistoryByDate",
            "function _renderTradeOrdersTable",
        ]:
            assert fn in js, f"trade-history-modal.js 누락: {fn}"

    def test_no_inline_trade_history_modal_in_index_html(self):
        """index.html 에 trade-history-modal 함수 inline 재정의 금지."""
        html = _index_html()
        forbidden = [
            "async function openTradeHistoryModal",
            "async function loadTradeHistory",
            "function filterTradeHistoryByDate",
        ]
        violations = [pat for pat in forbidden if pat in html]
        assert not violations, (
            "index.html 에 trade-history-modal inline 재정의 발견:\n  " + "\n  ".join(violations)
        )

    def test_system_banner_js_exists_and_loaded(self):
        """system-banner.js 존재 + script tag 검증."""
        path = _backend_root() / "app" / "static" / "js" / "system-banner.js"
        assert path.exists(), "system-banner.js missing"

        html = _index_html()
        api_pos = html.find("/static/js/api.js")
        banner_pos = html.find("/static/js/system-banner.js")
        assert banner_pos > 0
        assert banner_pos > api_pos

    def test_system_banner_js_defines_required(self):
        js = _system_banner_js()
        assert "async function loadSystemStatus" in js
        assert "async function clearKillSwitch" in js

    def test_no_inline_system_banner_in_index_html(self):
        html = _index_html()
        assert "async function loadSystemStatus" not in html
        assert "async function clearKillSwitch" not in html

    def test_multi_symbol_js_exists_and_loaded(self):
        """multi-symbol.js 존재 + script tag 검증."""
        path = _backend_root() / "app" / "static" / "js" / "multi-symbol.js"
        assert path.exists(), "multi-symbol.js missing"

        html = _index_html()
        helpers_pos = html.find("/static/js/helpers.js")
        ms_pos = html.find("/static/js/multi-symbol.js")
        assert ms_pos > 0
        assert ms_pos > helpers_pos, "multi-symbol.js 가 helpers.js 보다 먼저 로드됨 (escapeHtml 의존)"

    def test_multi_symbol_js_defines_required(self):
        """multi-symbol.js 가 6 함수 + state 정의."""
        js = _multi_symbol_js()
        for fn in [
            "let _cmMultiSymbols",
            "function toggleMultiSymbolMode",
            "async function addSymbolChip",
            "function removeSymbolChip",
            "function _renderMultiSymbolChips",
            "async function submitCreateMulti",
            "function _refreshSubmitBtnLabel",
        ]:
            assert fn in js, f"multi-symbol.js 누락: {fn}"

    def test_no_inline_multi_symbol_in_index_html(self):
        """index.html 에 multi-symbol 함수 inline 재정의 금지."""
        html = _index_html()
        forbidden = [
            "function toggleMultiSymbolMode",
            "async function submitCreateMulti",
            "function _refreshSubmitBtnLabel",
            "async function addSymbolChip",
        ]
        violations = [pat for pat in forbidden if pat in html]
        assert not violations, (
            "index.html 에 multi-symbol 함수 inline 재정의 발견:\n  " + "\n  ".join(violations)
        )

    def test_template_save_js_exists_and_loaded(self):
        """template-save.js 존재 + script tag 검증."""
        path = _backend_root() / "app" / "static" / "js" / "template-save.js"
        assert path.exists(), "template-save.js missing"

        html = _index_html()
        ms_pos = html.find("/static/js/multi-symbol.js")
        ts_pos = html.find("/static/js/template-save.js")
        assert ts_pos > 0
        assert ts_pos > ms_pos, "template-save.js 가 multi-symbol.js 보다 먼저 로드됨 (toggleMultiSymbolMode 의존)"

    def test_template_save_js_defines_required(self):
        js = _template_save_js()
        for fn in [
            "async function saveAsTemplate",
            "async function openCreateModalForBatch",
            "function _parseBatchSymbols",
        ]:
            assert fn in js, f"template-save.js 누락: {fn}"

    def test_no_inline_template_save_in_index_html(self):
        html = _index_html()
        forbidden = [
            "async function saveAsTemplate",
            "async function openCreateModalForBatch",
            "function _parseBatchSymbols",
        ]
        violations = [pat for pat in forbidden if pat in html]
        assert not violations, (
            "index.html 에 template-save 함수 inline 재정의 발견:\n  " + "\n  ".join(violations)
        )

    def test_cm_collectors_js_exists_and_loaded_before_consumers(self):
        """cm-collectors.js 가 multi-symbol.js / template-save.js 보다 먼저 로드.

        둘 다 _collectTpSl/_collectDirectInputs/_defaultLeverageForSide 의존.
        """
        path = _backend_root() / "app" / "static" / "js" / "cm-collectors.js"
        assert path.exists(), "cm-collectors.js missing"

        html = _index_html()
        coll_pos = html.find("/static/js/cm-collectors.js")
        ms_pos = html.find("/static/js/multi-symbol.js")
        ts_pos = html.find("/static/js/template-save.js")
        assert coll_pos > 0
        assert coll_pos < ms_pos, "cm-collectors.js 가 multi-symbol.js 보다 늦게 로드 — 의존성 깨짐"
        assert coll_pos < ts_pos, "cm-collectors.js 가 template-save.js 보다 늦게 로드 — 의존성 깨짐"

    def test_cm_collectors_js_defines_required(self):
        js = _cm_collectors_js()
        for fn in [
            "function _collectDirectInputs",
            "function _collectTpSl",
            "function _defaultLeverageForSide",
        ]:
            assert fn in js, f"cm-collectors.js 누락: {fn}"

    def test_no_inline_cm_collectors_in_index_html(self):
        html = _index_html()
        # body 만 들어간 정의 검출 (주석 OK)
        assert "function _collectDirectInputs() {" not in html
        assert "function _collectTpSl() {" not in html
        assert "function _defaultLeverageForSide(side) {" not in html

    def test_cm_prev_blueprint_js_exists_and_loaded(self):
        path = _backend_root() / "app" / "static" / "js" / "cm-prev-blueprint.js"
        assert path.exists(), "cm-prev-blueprint.js missing"
        html = _index_html()
        coll_pos = html.find("/static/js/cm-collectors.js")
        prev_pos = html.find("/static/js/cm-prev-blueprint.js")
        assert prev_pos > 0
        assert prev_pos > coll_pos, "cm-prev-blueprint.js 가 cm-collectors.js 보다 먼저 로드됨"

    def test_cm_prev_blueprint_js_defines_required(self):
        js = _cm_prev_blueprint_js()
        assert "async function loadCmPrevStrategies" in js
        assert "async function loadPrevBlueprint" in js

    def test_no_inline_cm_prev_blueprint_in_index_html(self):
        html = _index_html()
        assert "async function loadCmPrevStrategies" not in html
        assert "async function loadPrevBlueprint" not in html

    def test_cm_loaders_js_exists_and_loaded(self):
        path = _backend_root() / "app" / "static" / "js" / "cm-loaders.js"
        assert path.exists(), "cm-loaders.js missing"
        html = _index_html()
        loaders_pos = html.find("/static/js/cm-loaders.js")
        assert loaders_pos > 0

    def test_cm_loaders_js_defines_required(self):
        js = _cm_loaders_js()
        for fn in [
            "async function loadCmAccounts",
            "async function loadCmTemplates",
            "async function loadCmSymbols",
            "function _renderWhitelistHint",
            "function _validateCurrentSymbol",
        ]:
            assert fn in js, f"cm-loaders.js 누락: {fn}"

    def test_no_inline_cm_loaders_in_index_html(self):
        html = _index_html()
        forbidden = [
            "async function loadCmAccounts",
            "async function loadCmTemplates",
            "async function loadCmSymbols",
        ]
        violations = [pat for pat in forbidden if pat in html]
        assert not violations

    def test_cm_market_info_js_exists_and_loaded(self):
        path = _backend_root() / "app" / "static" / "js" / "cm-market-info.js"
        assert path.exists(), "cm-market-info.js missing"
        html = _index_html()
        mi_pos = html.find("/static/js/cm-market-info.js")
        assert mi_pos > 0

    def test_cm_market_info_js_defines_required(self):
        js = _cm_market_info_js()
        for fn in [
            "let _cmCurrentPrice",
            "let _cmTickSize",
            "async function loadCmMarketInfo",
            "function _drawCmChart",
            "function _decimalsForPrice",
            "function _tickSizeDecimals",
            "function fillStartPrice",
        ]:
            assert fn in js, f"cm-market-info.js 누락: {fn}"

    def test_no_inline_cm_market_info_in_index_html(self):
        html = _index_html()
        forbidden = [
            "async function loadCmMarketInfo",
            "function fillStartPrice",
            "function _drawCmChart",
        ]
        violations = [pat for pat in forbidden if pat in html]
        assert not violations

    def test_cm_capitals_grid_js_exists_and_loaded(self):
        path = _backend_root() / "app" / "static" / "js" / "cm-capitals-grid.js"
        assert path.exists(), "cm-capitals-grid.js missing"
        html = _index_html()
        cg_pos = html.find("/static/js/cm-capitals-grid.js")
        mi_pos = html.find("/static/js/cm-market-info.js")
        assert cg_pos > 0
        assert cg_pos > mi_pos, "cm-capitals-grid.js 가 cm-market-info.js 보다 먼저 로드 — _decimalsForPrice 의존"

    def test_cm_capitals_grid_js_defines_required(self):
        js = _cm_capitals_grid_js()
        for fn in [
            "function _defaultTriggerPct",
            "function buildCapitalsGrid",
            "function _refreshLiveCalc",
            "function onCapitalsChange",
        ]:
            assert fn in js, f"cm-capitals-grid.js 누락: {fn}"

    def test_no_inline_cm_capitals_grid_in_index_html(self):
        html = _index_html()
        forbidden = [
            "function buildCapitalsGrid()",
            "function _refreshLiveCalc()",
            "function onCapitalsChange()",
        ]
        violations = [pat for pat in forbidden if pat in html]
        assert not violations

    def test_cm_submit_js_exists_and_loaded(self):
        path = _backend_root() / "app" / "static" / "js" / "cm-submit.js"
        assert path.exists(), "cm-submit.js missing"
        html = _index_html()
        # cm-submit 는 multi-symbol.js (submitCreateMulti) + cm-collectors (_collectTpSl) 의존
        ms_pos = html.find("/static/js/multi-symbol.js")
        sub_pos = html.find("/static/js/cm-submit.js")
        assert sub_pos > 0
        assert sub_pos > ms_pos, "cm-submit.js 가 multi-symbol.js 보다 먼저 로드 — submitCreateMulti 의존"

    def test_cm_submit_js_defines_submitCreate(self):
        js = _cm_submit_js()
        assert "async function submitCreate" in js

    def test_no_inline_submit_create_in_index_html(self):
        html = _index_html()
        assert "async function submitCreate(" not in html, (
            "submitCreate 가 index.html 에 inline 재정의됨 (cm-submit.js 와 중복)"
        )

    def test_cm_state_helpers_js_exists_and_loaded(self):
        path = _backend_root() / "app" / "static" / "js" / "cm-state-helpers.js"
        assert path.exists(), "cm-state-helpers.js missing"
        html = _index_html()
        sh_pos = html.find("/static/js/cm-state-helpers.js")
        assert sh_pos > 0

    def test_cm_state_helpers_js_defines_required(self):
        js = _cm_state_helpers_js()
        for fn in [
            "function setCmMode",
            "function closeCreateModal",
            "function resetCmLeverage",
            "function setCmSide",
            "let cmLeverageManuallyEdited",
        ]:
            assert fn in js, f"cm-state-helpers.js 누락: {fn}"

    def test_no_inline_cm_state_helpers_in_index_html(self):
        html = _index_html()
        forbidden = [
            "function setCmMode(mode) {",
            "function closeCreateModal() {",
            "function setCmSide(side) {",
            "function resetCmLeverage() {",
        ]
        violations = [pat for pat in forbidden if pat in html]
        assert not violations

    def test_cm_preview_js_exists_and_loaded(self):
        path = _backend_root() / "app" / "static" / "js" / "cm-preview.js"
        assert path.exists(), "cm-preview.js missing"
        html = _index_html()
        prev_pos = html.find("/static/js/cm-preview.js")
        assert prev_pos > 0

    def test_cm_preview_js_defines_required(self):
        js = _cm_preview_js()
        for fn in [
            "function updateCmSubmit",
            "async function loadBalanceForPreview",
            "function _filledCapitals",
            "async function calcPreview",
            "function _estimateLiquidationPrice",
            "function _renderPreview",
            "async function submitInPlaceSettings",
        ]:
            assert fn in js, f"cm-preview.js 누락: {fn}"

    def test_no_inline_cm_preview_in_index_html(self):
        html = _index_html()
        forbidden = [
            "function updateCmSubmit() {",
            "async function loadBalanceForPreview()",
            "async function calcPreview()",
            "function _renderPreview(data)",
            "async function submitInPlaceSettings()",
        ]
        violations = [pat for pat in forbidden if pat in html]
        assert not violations, (
            "index.html 에 cm-preview 함수 inline 재정의 발견:\n  " + "\n  ".join(violations)
        )

    def test_cm_open_modal_js_exists_and_loaded(self):
        path = _backend_root() / "app" / "static" / "js" / "cm-open-modal.js"
        assert path.exists(), "cm-open-modal.js missing"
        html = _index_html()
        # cm-open-modal 은 다른 cm-* 모듈 (buildCapitalsGrid, setCmSide 등) 의존하므로 마지막에 로드.
        # cmState 는 hoisting 으로 함수 호출 시점에만 평가되므로 위치 무관 (다만 모듈 함수가
        # 모듈 load 시점에 cmState 읽으면 깨짐 — 모든 cm-*.js 는 함수 정의만, 호출 X 라 안전).
        om_pos = html.find("/static/js/cm-open-modal.js")
        assert om_pos > 0

    def test_cm_open_modal_js_defines_required(self):
        js = _cm_open_modal_js()
        for fn in [
            "let cmState",
            "async function openCreateModal",
            "async function editStrategy",
            "async function restartStrategy",
        ]:
            assert fn in js, f"cm-open-modal.js 누락: {fn}"

    def test_no_inline_cm_open_modal_in_index_html(self):
        html = _index_html()
        forbidden = [
            "let cmState =",
            "async function openCreateModal(editStrategyId)",
            "async function editStrategy(id)",
            "async function restartStrategy(id)",
        ]
        violations = [pat for pat in forbidden if pat in html]
        assert not violations, (
            "index.html 에 cm-open-modal 함수 inline 재정의 발견:\n  " + "\n  ".join(violations)
        )

    def test_no_duplicate_function_definitions_in_index_html(self):
        """index.html 에 같은 이름의 function 이 중복 정의되면 안 됨.

        2026-05-14 발견: deleteTemplate 이 line 1460 + 1506 두 번 정의돼
        두 번째가 첫 번째를 silently override 하던 상태 (dead code + 혼란).
        분리 작업 중 비슷한 중복 발생 시 즉시 catch.
        """
        import re
        html = _index_html()
        # async function NAME / function NAME 패턴 검출 (top-level 만)
        # 주석 안의 「function name」 은 무시 (line.startswith with stripping)
        defs: dict[str, list[int]] = {}
        for lineno, line in enumerate(html.splitlines(), start=1):
            stripped = line.lstrip()
            # 주석 라인 무시
            if stripped.startswith("//") or stripped.startswith("*") or stripped.startswith("<!--"):
                continue
            m = re.match(r"^(async\s+)?function\s+(\w+)\s*\(", stripped)
            if m:
                name = m.group(2)
                # 시작 시 이름이 _ 로 시작하는 helper, 또는 anonymous 제외
                defs.setdefault(name, []).append(lineno)
        duplicates = {n: lines for n, lines in defs.items() if len(lines) > 1}
        assert not duplicates, (
            "index.html 에 같은 이름의 function 중복 정의 발견 (dead code + override 위험):\n  "
            + "\n  ".join(f"{n}: lines {lines}" for n, lines in duplicates.items())
        )

    def test_dashboard_refresh_js_exists_and_loaded(self):
        path = _backend_root() / "app" / "static" / "js" / "dashboard-refresh.js"
        assert path.exists(), "dashboard-refresh.js missing"
        html = _index_html()
        dr_pos = html.find("/static/js/dashboard-refresh.js")
        assert dr_pos > 0

    def test_dashboard_refresh_js_defines_required(self):
        js = _dashboard_refresh_js()
        for fn in [
            "async function refreshAll",
            "async function loadGlobalWhitelistInfo",
            "function renderWhitelistBadge",
            "function _localizeActivity",
            "async function refreshActivity",
            "async function refreshSysHealth",
            "async function refreshStats",
            "async function refreshHealth",
            "async function loadBalance",
        ]:
            assert fn in js, f"dashboard-refresh.js 누락: {fn}"

    def test_no_inline_dashboard_refresh_in_index_html(self):
        html = _index_html()
        forbidden = [
            "async function refreshAll() {",
            "async function refreshActivity() {",
            "async function refreshSysHealth() {",
            "async function refreshStats() {",
            "async function refreshHealth() {",
            "async function loadBalance() {",
        ]
        violations = [pat for pat in forbidden if pat in html]
        assert not violations, (
            "index.html 에 dashboard-refresh 함수 inline 재정의 발견:\n  " + "\n  ".join(violations)
        )

    def test_templates_panel_js_exists_and_loaded(self):
        path = _backend_root() / "app" / "static" / "js" / "templates-panel.js"
        assert path.exists(), "templates-panel.js missing"
        html = _index_html()
        tp_pos = html.find("/static/js/templates-panel.js")
        assert tp_pos > 0

    def test_templates_panel_js_defines_required(self):
        js = _templates_panel_js()
        for fn in [
            "async function refreshTemplates",
            "async function cleanupQuickTemplates",
            "async function deleteTemplate",
        ]:
            assert fn in js, f"templates-panel.js 누락: {fn}"

    def test_no_inline_templates_panel_in_index_html(self):
        html = _index_html()
        forbidden = [
            "async function refreshTemplates() {",
            "async function cleanupQuickTemplates() {",
            "async function deleteTemplate(id, name) {",
        ]
        violations = [pat for pat in forbidden if pat in html]
        assert not violations

    def test_no_dead_crisis_dropdown_refs_in_index_html(self):
        """제거된 cm-crisis-threshold UI element 참조가 다시 들어오면 안 됨.

        2026-05-14: 「손절만 사용」 사용자 결정으로 dropdown 영구 제거.
        document.getElementById('cm-crisis-threshold') 호출 = dead reference (null 반환).
        """
        html = _index_html()
        # JS 코드 내 getElementById('cm-crisis-threshold') 패턴 검출 (주석/HTML 제외)
        # 단순화: 라인 단위로 보고 주석이 아닌 곳에 patten 있으면 fail
        bad_lines = []
        for lineno, line in enumerate(html.splitlines(), start=1):
            if "cm-crisis-threshold" not in line:
                continue
            stripped = line.strip()
            # HTML 주석 / JS 주석은 OK (history 보존용)
            if stripped.startswith("<!--") or stripped.startswith("//") or stripped.startswith("*"):
                continue
            bad_lines.append(f"line {lineno}: {stripped[:100]}")
        assert not bad_lines, (
            "cm-crisis-threshold 죽은 참조 발견 — 제거 필요:\n  "
            + "\n  ".join(bad_lines)
        )

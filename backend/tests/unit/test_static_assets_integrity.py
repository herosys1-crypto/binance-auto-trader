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
        inline_pos = html.find("const API_BASE")
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

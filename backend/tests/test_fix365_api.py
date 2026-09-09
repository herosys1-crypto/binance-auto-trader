"""🧭 Fix 365 — 심볼 관리 재진입 API + 화면 카드. DB 없이 배선만 확인(정적 핀 테스트).

이 파일의 범위 (매매 판정이 아닌 코드): app/api/v1/managed_symbols.py 라우트 배선, app/api/router.py
등록, app/static/index.html 카드 마크업, app/static/js/managed-symbols.js 폴링/함수 정의.
실제 판정(진입/사다리/손절)은 app/services/managed_symbols.py + app/workers/managed_symbol_worker.py
(다른 담당) — 이 파일은 그 파일들의 내부 로직을 검증하지 않는다.

스타일 참고: tests/test_fix361_paper_trading.py 의 A3(API) 배선 핀 테스트.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


# ══════════════════════════════════════════════════════════════════════
# API 라우터 — 경로/메서드
# ══════════════════════════════════════════════════════════════════════

def test_managed_symbols_라우터_모듈이_있다():
    api_file = APP / "api" / "v1" / "managed_symbols.py"
    assert api_file.exists(), "app/api/v1/managed_symbols.py 없음"
    s = api_file.read_text(encoding="utf-8")
    assert 'prefix="/managed-symbols"' in s
    assert 'tags=["managed-symbols"]' in s


def test_managed_symbols_라우트_경로와_메서드():
    from app.api.v1.managed_symbols import router

    routes = {(r.path, frozenset(r.methods)) for r in router.routes}
    assert ("/managed-symbols", frozenset({"GET"})) in routes
    assert ("/managed-symbols", frozenset({"POST"})) in routes
    assert ("/managed-symbols/{managed_symbol_id}/reset", frozenset({"POST"})) in routes
    assert ("/managed-symbols/{managed_symbol_id}", frozenset({"DELETE"})) in routes


def test_모든_라우트가_인증을_요구한다():
    """get_current_user_id 의존성이 라우트 핸들러 시그니처에 있어야 한다 (실자금 명부 — fail-closed)."""
    from app.api.v1.managed_symbols import router

    for r in router.routes:
        params = getattr(r.endpoint, "__annotations__", {})
        # Depends 객체는 함수 기본값에 있으므로 소스 문자열로도 재확인 (아래 별도 테스트).
        assert params, f"{r.path} 핸들러에 타입 힌트가 없다"

    s = (APP / "api" / "v1" / "managed_symbols.py").read_text(encoding="utf-8")
    # 4개 라우트 함수 정의마다 get_current_user_id 의존성이 있어야 한다.
    assert s.count("Depends(get_current_user_id)") >= 4


def test_GET_응답에_items_last_cycle_settings_가_있다():
    s = (APP / "api" / "v1" / "managed_symbols.py").read_text(encoding="utf-8")
    assert '"items": items' in s
    assert '"last_cycle"' in s
    assert '"settings"' in s
    assert "active_sides" in s and "active_instance_ids" in s


def test_POST_는_OBV_인스턴스_없으면_400_한국어_메시지():
    from app.api.v1.managed_symbols import _NO_OBV_INSTANCE_MSG

    assert "OBV 자동 인스턴스가 없어" in _NO_OBV_INSTANCE_MSG
    assert "새 전략 (OBV 자동)" in _NO_OBV_INSTANCE_MSG
    s = (APP / "api" / "v1" / "managed_symbols.py").read_text(encoding="utf-8")
    assert "trigger_mode == \"OBV_REVERSE\"" in s
    assert "status_code=400" in s


def test_심볼_검증은_대문자_영숫자_USDT_로_끝나야_한다():
    from fastapi import HTTPException

    from app.api.v1.managed_symbols import _norm_symbol

    assert _norm_symbol("solusdt") == "SOLUSDT"
    assert _norm_symbol(" btcusdt ") == "BTCUSDT"
    for bad in ("SOL", "SOL-USDT", "usdtsol", "", "SOL USDT"):
        try:
            _norm_symbol(bad)
            raise AssertionError(f"{bad!r} 가 통과하면 안 된다")
        except HTTPException as e:
            assert e.status_code == 400


def test_reset은_시도0_WATCHING_해제는_RELEASED_행유지():
    s = (APP / "api" / "v1" / "managed_symbols.py").read_text(encoding="utf-8")
    assert "row.attempts = 0" in s
    assert "MS.STATUS_WATCHING" in s
    assert "MS.STATUS_RELEASED" in s
    assert "↺ 초기화 (사장님)" in s
    assert "✕ 해제 (사장님)" in s
    # 스펙: 해제는 행을 지우지 않는다 — delete/db.delete 호출이 없어야 한다.
    assert "db.delete(" not in s


# ══════════════════════════════════════════════════════════════════════
# app/api/router.py 등록
# ══════════════════════════════════════════════════════════════════════

def test_router_py에_등록된다():
    r = (APP / "api" / "router.py").read_text(encoding="utf-8")
    assert "managed_symbols_router" in r
    assert "from app.api.v1.managed_symbols import router as managed_symbols_router" in r
    assert "api_router.include_router(managed_symbols_router)" in r


def test_라우터_임포트가_실제로_등록된_라우트를_노출한다():
    from app.api.router import api_router

    paths = {r.path for r in api_router.routes}
    assert "/api/v1/managed-symbols" in paths
    assert "/api/v1/managed-symbols/{managed_symbol_id}/reset" in paths
    assert "/api/v1/managed-symbols/{managed_symbol_id}" in paths


# ══════════════════════════════════════════════════════════════════════
# 화면 — index.html 카드
# ══════════════════════════════════════════════════════════════════════

def test_index_html에_카드가_있다():
    html = (APP / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="managed-symbols-card"' in html
    assert 'id="managed-symbols-count"' in html
    assert 'id="managed-symbols-cycle"' in html
    assert 'id="managed-symbols-list"' in html
    assert 'id="managed-symbols-add-input"' in html
    assert 'id="managed-symbols-hide-released"' in html
    assert "Fix 365" in html


def test_카드는_재진입_알람_카드_바로_뒤에_있다():
    html = (APP / "static" / "index.html").read_text(encoding="utf-8")
    i_reentry = html.index('id="reentry-alerts-card"')
    i_managed = html.index('id="managed-symbols-card"')
    i_stats = html.index('id="section-stats"')
    assert i_reentry < i_managed < i_stats, "관리 심볼 카드가 재진입 알람 카드와 운영 통계 사이에 있어야 한다"


def test_스크립트_태그가_있고_v_캐시버스팅을_쓴다():
    html = (APP / "static" / "index.html").read_text(encoding="utf-8")
    assert '/static/js/managed-symbols.js?v=' in html


# ══════════════════════════════════════════════════════════════════════
# 화면 — managed-symbols.js
# ══════════════════════════════════════════════════════════════════════

def test_js_파일이_있고_로더_함수를_전역에_노출한다():
    js_file = APP / "static" / "js" / "managed-symbols.js"
    assert js_file.exists()
    s = js_file.read_text(encoding="utf-8")
    assert "async function loadManagedSymbols(" in s
    assert "window.loadManagedSymbols = loadManagedSymbols" in s
    assert "async function addManagedSymbol(" in s
    assert "async function resetManagedSymbol(" in s
    assert "async function releaseManagedSymbol(" in s


def test_js는_30초마다_폴링하고_DOMContentLoaded에서_시작한다():
    s = (APP / "static" / "js" / "managed-symbols.js").read_text(encoding="utf-8")
    assert "setInterval(loadManagedSymbols, 30000)" in s
    assert "DOMContentLoaded" in s


def test_js는_api_헬퍼로_호출하고_confirm_후_해제한다():
    s = (APP / "static" / "js" / "managed-symbols.js").read_text(encoding="utf-8")
    assert "api('/managed-symbols'" in s or 'api("/managed-symbols"' in s
    assert "api(`/managed-symbols" in s
    assert "confirm(" in s

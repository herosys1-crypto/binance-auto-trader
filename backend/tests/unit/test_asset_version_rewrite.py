"""🚨 Fix 266 — 화면이 옛 JS 를 쓰던 마지막 구멍.

## 실측 (2026-09-01, VPS 에서 직접 curl)

    /admin-ui          -> strategy-suggestions.js?v=eada1d9a0632   (내용 해시 ✓)
    /static/index.html -> strategy-suggestions.js?v=20260826-...   (원본 그대로 ✗)

Fix 190 이 `?v=` 를 내용 해시로 자동 생성하게 만들었는데, 그 재작성이
`/admin-ui` **라우트에만** 걸려 있었다. StaticFiles mount 로 들어오는
`/static/index.html` 은 원본을 그대로 내보냈고, 그 URL 로 들어온 브라우저는
8/26 자 JS 를 계속 썼다.

🚨 그날 사장님이 「최대 동시 포지션이 30 으로 바뀌어 있다」고 하셨는데,
   엔진 로그는 08-31 14:57 UTC 부터 계속 `used=N/50` 이었다.
   **엔진은 50, 화면만 옛 파일.**

이 파일이 지키는 것: **index.html 을 내보내는 모든 경로**가 재작성을 거친다.
"""
from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
MAIN = BACKEND / "app" / "main.py"
CORE = BACKEND / "app" / "core" / "asset_version.py"
STATIC = BACKEND / "app" / "static"

HASH_RE = re.compile(r"^[0-9a-f]{12}$")


# ───────────────────────── 재작성 함수 자체

def test_rewrite_replaces_every_versioned_ref():
    from app.core.asset_version import rewrite_asset_versions
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    out = rewrite_asset_versions(html, STATIC)
    refs = re.findall(r'(?:src|href)="/static/([^"?]+)(?:\?v=([^"]*))?"', out)
    assert refs, "정적 참조를 하나도 못 찾았다 (정규식이 깨졌다)"
    for path, ver in refs:
        if not (STATIC / path).exists():
            continue                      # 없는 파일은 손대지 않는 게 설계
        assert HASH_RE.match(ver or ""), f"{path} 의 버전이 해시가 아니다: {ver!r}"


def test_rewrite_is_stable_for_same_content():
    from app.core.asset_version import rewrite_asset_versions
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert rewrite_asset_versions(html, STATIC) == rewrite_asset_versions(html, STATIC)


def test_rewrite_leaves_missing_files_alone():
    """없는 파일까지 건드리면 오타가 조용히 묻힌다."""
    from app.core.asset_version import rewrite_asset_versions
    src = '<script src="/static/js/__없는파일__.js?v=abc"></script>'
    out = rewrite_asset_versions(src, STATIC)
    assert "__없는파일__.js" in out and "?v=" not in out


def test_rewrite_refuses_path_escape():
    """index.html 이 static 밖을 가리켜도 읽지 않는다."""
    from app.core.asset_version import asset_version
    assert asset_version(STATIC, "../main.py") is None
    assert asset_version(STATIC, "../../etc/passwd") is None


# ───────────────────────── 🚨 모든 경로가 재작성을 거치는가

def _code() -> str:
    return "\n".join(
        ln for ln in MAIN.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )


def test_static_mount_also_rewrites_index():
    """🚨 이게 실제 사고다 — mount 경로가 원본을 그대로 내보냈다."""
    code = _code()
    i = code.index("class _NoCacheStaticFiles")
    body = code[i: code.index("_STATIC_DIR = Path(", i)]
    assert "_rewrite_asset_versions" in body, (
        "StaticFiles mount 가 index.html 을 재작성하지 않는다 "
        "— /static/index.html 로 들어오면 옛 ?v= 가 그대로 나간다"
    )


def test_every_index_response_goes_through_rewrite():
    """index.html 을 읽어 내보내는 **모든** 지점이 재작성을 거쳐야 한다.

    FileResponse 로 원본을 그대로 주는 곳은 fail-open 폴백 하나뿐이어야 한다.
    """
    code = _code()
    # index.html 을 참조하는 응답 생성 지점 수집
    reads = [m.start() for m in re.finditer(r'_STATIC_DIR / "index\.html"', code)]
    assert len(reads) >= 2, "index.html 서빙 지점을 못 찾았다"
    for pos in reads:
        window = code[pos: pos + 700]
        assert "_rewrite_asset_versions" in window or "fail-open" in window or (
            "logger.warning" in window
        ), f"재작성 없이 index.html 을 내보내는 지점이 있다 (offset {pos})"


def test_index_is_served_no_store():
    """HTML 자체가 캐시되면 새 해시가 브라우저에 영영 도달하지 않는다."""
    code = _code()
    i = code.index("class _NoCacheStaticFiles")
    body = code[i: code.index("_STATIC_DIR = Path(", i)]
    assert "no-store" in body


def test_evidence_is_recorded():
    src = MAIN.read_text(encoding="utf-8")
    for token in ("Fix 266", "eada1d9a0632", "엔진은 내내 50"):
        assert token in src, f"근거 주석에 '{token}' 이 없다"

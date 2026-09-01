"""🔖 정적 자산 `?v=` 를 **내용 해시**로 자동 생성 (Fix 190 / 266).

## 왜 손으로 안 적는가

`?v=` 는 손으로 적는 규칙이었고 **반드시 잊힌다.** 실측으로 18개 파일이 낡아
있었다 (cm-open-modal / cm-submit / strategies-list / helpers /
strategy-suggestions ... 전부 그 세션에 고친 파일들이다).
「있는데 안 맞는 버전 문자열」은 없느니만 못하다 — 최신인 줄 착각하게 만든다.

## Fix 266 — 재작성이 한 라우트에만 걸려 있었다

    /admin-ui          -> strategy-suggestions.js?v=eada1d9a0632   (해시 ✓)
    /static/index.html -> strategy-suggestions.js?v=20260826-...   (원본 ✗)

StaticFiles mount 로 들어오면 원본이 그대로 나갔다. 그 URL 로 들어온 브라우저는
8/26 자 JS 를 계속 썼다. 사장님이 「최대 동시 포지션이 30 으로 바뀌어 있다」고
하신 날, 엔진 로그는 내내 `used=N/50` 이었다 — **엔진은 50, 화면만 옛 파일.**

이 모듈로 분리한 이유:
  - main.py 는 import 만으로 설정·암호키를 요구해서 **단위 테스트가 불가능**했다.
    (실제로 이 로직의 테스트가 CryptoError 로 죽었다.)
  - 재작성 규칙은 한 곳에만 있어야 한다 (헌법 6).
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

__all__ = ["asset_version", "rewrite_asset_versions", "ASSET_REF_RE"]

ASSET_REF_RE = re.compile(r'(src|href)="(/static/[^"?]+)(?:\?[^"]*)?"')

# rel_path -> (mtime, size, digest)
_CACHE: dict[str, tuple[float, int, str]] = {}


def asset_version(static_dir: Path, rel_path: str) -> str | None:
    """`<static_dir>/<rel_path>` 의 내용 해시 12자.

    mtime+size 가 같으면 재계산하지 않는다. 파일이 없으면 **None** —
    호출자는 그 참조를 손대지 않는다 (오타가 조용히 묻히지 않게).
    """
    root = Path(static_dir).resolve()
    target = (root / rel_path).resolve()
    # 경로 탈출 방어 — index.html 이 아무 경로나 가리켜도 static 밖은 읽지 않는다.
    try:
        target.relative_to(root)
    except ValueError:
        return None
    try:
        st = target.stat()
    except OSError:
        return None
    key = f"{root}|{rel_path}"
    hit = _CACHE.get(key)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]
    try:
        digest = hashlib.sha1(target.read_bytes()).hexdigest()[:12]
    except OSError:
        return None
    _CACHE[key] = (st.st_mtime, st.st_size, digest)
    return digest


def rewrite_asset_versions(html: str, static_dir: Path) -> str:
    """`src="/static/js/a.js?v=옛날"` → `?v=<내용해시>`. 실패하면 원문 유지."""
    def _sub(m: "re.Match[str]") -> str:
        attr, path = m.group(1), m.group(2)
        ver = asset_version(static_dir, path[len("/static/"):])
        return f'{attr}="{path}"' if ver is None else f'{attr}="{path}?v={ver}"'
    return ASSET_REF_RE.sub(_sub, html)

import asyncio
import hashlib
import logging
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.router import api_router
from app.core.config import settings
from app.core.crypto import validate_encryption_key
from app.core.redis_client import get_redis_client
from app.core.sentry import init_sentry
from app.middleware.idempotency import IdempotencyMiddleware
from app.observability.metrics import scheduler_leader_status, user_stream_connected

logger = logging.getLogger(__name__)

# 다른 worker process 가 Redis 에 쓰는 heartbeat 키
HEALTH_KEY_USER_STREAM = "health:user_stream:connected"
HEALTH_KEY_SCHEDULER_LEADER = "health:scheduler:leader"


async def _poll_health_metrics() -> None:
    """5초마다 Redis 의 worker heartbeat 키를 확인해 Prometheus gauge 를 갱신.

    user-stream / scheduler 는 별도 process 라 그들의 metric 이
    API process 의 /metrics 에 직접 보이지 않는다. Redis 를 가교로 사용.
    """
    while True:
        try:
            client = get_redis_client()
            user_stream_connected.set(1 if client.exists(HEALTH_KEY_USER_STREAM) else 0)
            scheduler_leader_status.set(1 if client.exists(HEALTH_KEY_SCHEDULER_LEADER) else 0)
        except Exception as e:  # pragma: no cover
            logger.debug("health poll error: %s", e)
        await asyncio.sleep(5)


init_sentry()
# 2026-05-04: encryption_key 가 invalid 면 startup 실패 — 첫 거래 시점에 crash 방지.
validate_encryption_key()
app = FastAPI(title=settings.app_name)
# 2026-06-05 코드 최적화 Phase 4 Step 3 — gzip 압축 (CODE_OPTIMIZATION_PLAN.md):
# - 1KB 이상 응답 = 자동 gzip (JSON 보통 70% 압축)
# - 사장님 폴링 부담 ↓ (네트워크 latency 절감)
# - 모바일 사용 시 효과 큼
# - 위험 = 0 (FastAPI 표준 middleware)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(IdempotencyMiddleware)


# 🚨 Fix 199 (2026-08-28): API 응답은 **절대 캐시되면 안 된다.**
#
# 사장님 증상: ⚙세팅 카드의 자본 사다리·피라미딩·볼밴 칸이 영원히 「불러오는 중」.
# 채워진 칸(최대 동시 포지션·초기 자본·최대 단계)과 빈 칸의 경계를 보면,
# 화면이 받는 응답에 capital_ladder(Fix144) / pyramid_capital(Fix176) /
# bbsplit_*(Fix181) 키가 **아예 없다** = 08-26 이전 형태의 응답이다.
# 서버 디스크는 최신인데 화면만 옛 응답을 보는 상태.
#
# 그런데 지금까지 Cache-Control 을 붙이는 곳은 /static 과 /admin-ui 뿐이었고
# /api/* 응답에는 **아무 캐시 지시가 없었다.** 지시가 없으면 브라우저·중간 프록시가
# 자기 판단으로 캐시할 수 있다(RFC 7234 휴리스틱 캐싱). 설정·잔고·포지션처럼
# 매번 달라지는 값에서 이건 「낡은 값을 진짜로 착각하는」 사고로 직결된다.
#
# → 모든 API 응답에 no-store 를 명시한다. 성능 영향은 없다 —
#   어차피 캐시하면 안 되는 값들이고, 지금도 사실상 캐시되지 않아야 정상이다.
@app.middleware("http")
async def _no_store_api(request, call_next):
    response = await call_next(request)
    try:
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
    except Exception:      # 헤더 설정 실패가 응답 자체를 막아서는 안 된다
        pass
    return response
app.include_router(api_router)


@app.on_event("startup")
async def _start_health_poller() -> None:
    asyncio.create_task(_poll_health_metrics())

# 2026-06-02 (사장님 요구): static 자산도 매번 ETag 검증 — release 후 사장님 화면이
# 옛 JS 캐시로 새 UI 못 봄 (Binance 비교 인라인 row #39 가 화면에 안 보였던 사고 재발 방지).
# ETag conditional GET → 변경 없으면 304 (효율 OK), 변경 있으면 즉시 새 파일.
class _NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        # ══════════════════════════════════════════════════════════════
        # 🚨 Fix 266 (2026-09-01): index.html 은 **여기서도** 재작성한다.
        #
        # Fix 190 이 `?v=` 를 내용 해시로 자동 생성하게 만들었는데, 그 재작성이
        # `/admin-ui` **라우트에만** 걸려 있었다. StaticFiles mount 로 들어오는
        # `/static/index.html` 은 원본을 그대로 내보낸다. 실측:
        #
        #   /admin-ui          -> strategy-suggestions.js?v=eada1d9a0632  (해시 ✓)
        #   /static/index.html -> strategy-suggestions.js?v=20260826-...  (원본 ✗)
        #
        # 그 URL 로 들어온 브라우저는 8/26 자 JS 를 계속 쓴다. 사장님이
        # 「최대 동시 포지션이 30 으로 바뀌어 있다」고 하신 날, 엔진은 내내 50
        # 이었다 — 화면만 옛 파일이었다.
        #
        # 헌법 6(단일 진실): 재작성을 **한 곳**에서 보장한다. 라우트가 늘어도
        # 이 클래스를 거치면 항상 최신 해시가 나간다.
        # ══════════════════════════════════════════════════════════════
        _p = str(path or "").replace("\\", "/").strip("/").lower()
        if _p in ("index.html", ""):
            try:
                _idx = _STATIC_DIR / "index.html"
                return HTMLResponse(
                    _rewrite_asset_versions(_idx.read_text(encoding="utf-8")),
                    headers={
                        "Cache-Control": "no-cache, no-store, must-revalidate",
                        "Pragma": "no-cache",
                        "Expires": "0",
                    },
                )
            except Exception as e:
                # 화면이 안 뜨는 것보다는 옛 방식으로라도 뜨는 게 낫다 (fail-open).
                logger.warning("[Fix266] index.html 재작성 실패 → 원본 그대로: %s", e)

        response = await super().get_response(path, scope)
        # 304 응답은 헤더 추가 X (이미 캐시된 것 그대로 사용)
        if hasattr(response, "headers") and response.status_code != 304:
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


# Static admin dashboard (single-page HTML)
_STATIC_DIR = Path(__file__).resolve().parent / "static"

# 🚨 Fix 190 (2026-08-28): index.html 의 `?v=...` 를 **자동 생성**한다.
#
# 왜: `?v=` 는 손으로 적는 규칙이었고 **반드시 잊힌다.** 실측으로 18개 파일이
#   낡아 있었다 (cm-open-modal / cm-submit / strategies-list / helpers /
#   strategy-suggestions ... 전부 이번 세션에 고친 파일들이다).
#   지금은 _NoCacheStaticFiles 의 no-cache 헤더가 막아주고 있지만,
#   「있는데 안 맞는 버전 문자열」은 없느니만 못하다 — 최신인 줄 착각하게 만든다.
#   파일 내용 해시로 바꾸면 사람이 개입할 여지가 사라진다 (헌법 6: 한 곳에서 보장).
# Fix 266: 재작성 로직은 app/core/asset_version.py 로 **분리**했다.
#   main.py 는 import 만으로 설정·암호키를 요구해서 이 로직의 단위 테스트가
#   CryptoError 로 죽고 있었다. 규칙은 한 곳에만 둔다 (헌법 6).
from app.core.asset_version import (            # noqa: E402
    asset_version as _asset_version_impl,
    rewrite_asset_versions as _rewrite_impl,
)


def _asset_version(rel_path: str) -> str | None:
    return _asset_version_impl(_STATIC_DIR, rel_path)


def _rewrite_asset_versions(html: str) -> str:
    return _rewrite_impl(html, _STATIC_DIR)


if _STATIC_DIR.exists():
    app.mount("/static", _NoCacheStaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/admin-ui", include_in_schema=False)
    def admin_ui_root():
        # 브라우저 캐시 무력화 — localhost / ngrok 양쪽 모두 항상 최신 HTML 받도록.
        # HTML 자체는 작아서 매 요청 갱신해도 부하 적음. 정적 자산 (/static/*) 은
        # 별도 mount 라 영향 없음.
        _headers = {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
        _index = _STATIC_DIR / "index.html"
        try:
            # Fix 190: 자산 버전을 내용 해시로 갱신해서 내보낸다.
            return HTMLResponse(
                _rewrite_asset_versions(_index.read_text(encoding="utf-8")),
                headers=_headers,
            )
        except Exception as e:
            # 화면이 안 뜨는 것보다는 옛 방식으로라도 뜨는 게 낫다 (fail-open).
            logger.warning("[Fix190] 자산 버전 재작성 실패 → 원본 그대로: %s", e)
            return FileResponse(str(_index), headers=_headers)

    @app.get("/", include_in_schema=False)
    def root_redirect() -> RedirectResponse:
        return RedirectResponse(url="/admin-ui")

if settings.enable_metrics:
    Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        should_respect_env_var=False,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/metrics"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, RedirectResponse
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
app.include_router(api_router)


@app.on_event("startup")
async def _start_health_poller() -> None:
    asyncio.create_task(_poll_health_metrics())

# 2026-06-02 (사장님 요구): static 자산도 매번 ETag 검증 — release 후 사장님 화면이
# 옛 JS 캐시로 새 UI 못 봄 (Binance 비교 인라인 row #39 가 화면에 안 보였던 사고 재발 방지).
# ETag conditional GET → 변경 없으면 304 (효율 OK), 변경 있으면 즉시 새 파일.
class _NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        # 304 응답은 헤더 추가 X (이미 캐시된 것 그대로 사용)
        if hasattr(response, "headers") and response.status_code != 304:
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


# Static admin dashboard (single-page HTML)
_STATIC_DIR = Path(__file__).resolve().parent / "static"
if _STATIC_DIR.exists():
    app.mount("/static", _NoCacheStaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/admin-ui", include_in_schema=False)
    def admin_ui_root() -> FileResponse:
        # 브라우저 캐시 무력화 — localhost / ngrok 양쪽 모두 항상 최신 HTML 받도록.
        # HTML 자체는 작아서 매 요청 갱신해도 부하 적음. 정적 자산 (/static/*) 은
        # 별도 mount 라 영향 없음.
        return FileResponse(
            str(_STATIC_DIR / "index.html"),
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

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

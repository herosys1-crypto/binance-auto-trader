import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.router import api_router
from app.core.config import settings
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
app = FastAPI(title=settings.app_name)
app.add_middleware(IdempotencyMiddleware)
app.include_router(api_router)


@app.on_event("startup")
async def _start_health_poller() -> None:
    asyncio.create_task(_poll_health_metrics())

# Static admin dashboard (single-page HTML)
_STATIC_DIR = Path(__file__).resolve().parent / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

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

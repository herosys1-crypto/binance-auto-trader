from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.router import api_router
from app.core.config import settings
from app.core.sentry import init_sentry
from app.middleware.idempotency import IdempotencyMiddleware

init_sentry()
app = FastAPI(title=settings.app_name)
app.add_middleware(IdempotencyMiddleware)
app.include_router(api_router)

# Static admin dashboard (single-page HTML)
_STATIC_DIR = Path(__file__).resolve().parent / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/admin-ui", include_in_schema=False)
    def admin_ui_root() -> FileResponse:
        return FileResponse(str(_STATIC_DIR / "index.html"))

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

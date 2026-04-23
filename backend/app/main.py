from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator
from app.api.router import api_router
from app.core.config import settings
from app.core.sentry import init_sentry
from app.middleware.idempotency import IdempotencyMiddleware

init_sentry()
app = FastAPI(title=settings.app_name)
app.add_middleware(IdempotencyMiddleware)
app.include_router(api_router)

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

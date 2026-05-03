from __future__ import annotations

import hashlib
import json

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.redis_client import get_redis_client


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await call_next(request)

        idem_key = request.headers.get("Idempotency-Key")
        if not idem_key:
            return await call_next(request)

        redis_client = get_redis_client()
        raw_body = await request.body()
        body_hash = hashlib.sha256(raw_body).hexdigest()
        cache_key = f"idempotency:{idem_key}"

        cached = redis_client.get(cache_key)
        if cached:
            data = json.loads(cached)
            if data["body_hash"] != body_hash:
                return JSONResponse(status_code=409, content={"detail": "Idempotency-Key reused with different payload"})
            return JSONResponse(status_code=data["status_code"], content=data["response_body"])

        response = await call_next(request)
        # 2026-05-04 fix: 이전엔 < 500 캐시 (4xx 도 포함) → 사용자가 input 고쳐서 같은
        # Idempotency-Key 로 재시도해도 캐시된 400 받음. 이제 2xx 만 캐시.
        # 4xx/5xx 는 업스트림 응답 그대로 반환 + 다음 요청 시 재시도 허용.
        if 200 <= response.status_code < 300:
            response_body = b""
            async for chunk in response.body_iterator:
                response_body += chunk
            try:
                parsed_body = json.loads(response_body.decode("utf-8"))
            except Exception:
                parsed_body = {"raw": response_body.decode("utf-8", errors="ignore")}

            redis_client.setex(cache_key, 3600, json.dumps({
                "body_hash": body_hash,
                "status_code": response.status_code,
                "response_body": parsed_body,
            }))
            return JSONResponse(status_code=response.status_code, content=parsed_body)
        return response

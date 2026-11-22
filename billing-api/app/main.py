import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

import hmac

from .config import get_settings
from .routers import v1
from .services import ApiError

log = logging.getLogger("billing-api")

app = FastAPI(
    title="Mobile Provider Billing API",
    version="1.0.0",
    description=(
        "Billing backend for the SE4458 billing support assistant. "
        "All public routes are versioned under `/api/v1` and are reached through the API gateway. "
        "Protected operations need `Authorization: Bearer <JWT>` from `/api/v1/auth/login`."
    ),
)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"status": "ERROR", "code": code, "message": message})


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError):
    return _error(exc.http_status, exc.code, exc.message)


@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, exc: HTTPException):
    codes = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND"}
    resp = _error(exc.status_code, codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail))
    if exc.headers:
        resp.headers.update(exc.headers)
    return resp


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    first = exc.errors()[0]
    field = ".".join(str(p) for p in first["loc"] if p not in ("body", "query"))
    return _error(422, "VALIDATION_ERROR", f"{field}: {first['msg']}")


@app.middleware("http")
async def only_through_gateway(request: Request, call_next):
    secret = get_settings().gateway_secret
    if secret and request.url.path != "/health":
        sent = request.headers.get("x-gateway-secret", "")
        if not hmac.compare_digest(sent, secret):
            return _error(403, "DIRECT_ACCESS_FORBIDDEN", "Use the API gateway")
    return await call_next(request)


@app.get("/health", tags=["Health"])
def health():
    return {"status": "UP"}


app.include_router(v1.router)

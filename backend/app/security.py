from __future__ import annotations

from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import settings

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def same_origin_request(request: Request) -> bool:
    host = request.headers.get("host", "")
    for header in ("origin", "referer"):
        value = request.headers.get(header)
        if not value:
            continue
        parsed = urlparse(value)
        if parsed.netloc and parsed.netloc != host:
            return False
    return True


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "detail": None}},
        status_code=status_code,
    )


def install(app: FastAPI) -> None:
    if settings.trusted_hosts and settings.trusted_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    @app.middleware("http")
    async def security_middleware(request: Request, call_next):
        if request.method in UNSAFE_METHODS and not request.url.path.startswith("/api/v1/health"):
            if request.headers.get("x-requested-with") != "tdl-web":
                return _error("csrf_header_missing", "Petición no autorizada.", 403)
            if not same_origin_request(request):
                return _error("cross_origin_blocked", "Origen no permitido.", 403)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        if settings.environment == "production":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response

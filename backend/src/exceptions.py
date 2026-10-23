import logging
import traceback
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.config import settings

logger = logging.getLogger(__name__)

# every error code in the app, filled in as each ErrorSpec is created
CATALOG: dict[str, ErrorSpec] = {}


@dataclass(frozen=True)
class ErrorSpec:
    code: str  # what the client branches on, never change it once shipped
    http_status: int
    message: str  # safe to show the user, can have {placeholders}
    log_level: int = logging.INFO

    def __post_init__(self):
        if self.code in CATALOG:
            raise ValueError(f"duplicate error code: {self.code}")
        CATALOG[self.code] = self


class AppError(Exception):
    def __init__(
        self,
        spec: ErrorSpec,
        params: dict | None = None,
        headers: dict[str, str] | None = None,
    ):
        self.spec = spec
        self.message = spec.message.format(**(params or {}))
        self.headers = headers
        super().__init__(self.message)


# shared errors, each domain keeps its own in <domain>/exceptions.py
INTERNAL_ERROR = ErrorSpec("internal_error", 500, "Something went wrong", logging.ERROR)
VALIDATION_ERROR = ErrorSpec("validation_error", 422, "Invalid request data")
ROUTE_NOT_FOUND = ErrorSpec("not_found", 404, "Route not found: {method} {path}")
RATE_LIMITED = ErrorSpec(
    "rate_limited",
    429,
    "Too many requests, try again in {seconds}s",
    logging.WARNING,
)


def _error_response(
    status_code: int, code: str, message: str, headers=None, **extra
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, **extra},
        headers=headers,
    )


async def app_error_handler(request: Request, exc: AppError):
    spec = exc.spec
    logger.log(
        spec.log_level,
        "%s %s -> %d %s",
        request.method,
        request.url.path,
        spec.http_status,
        spec.code,
        # stack trace only for real failures, a wrong password doesn't need one
        exc_info=spec.log_level >= logging.ERROR,
    )
    return _error_response(spec.http_status, spec.code, exc.message, exc.headers)


async def http_error_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        message = ROUTE_NOT_FOUND.message.format(
            method=request.method, path=request.url.path
        )
        return _error_response(404, ROUTE_NOT_FOUND.code, message)
    return _error_response(exc.status_code, "http_error", str(exc.detail))


async def validation_error_handler(request: Request, exc: RequestValidationError):
    issues = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"][1:])
        issues.append({"field": field, "message": err["msg"]})
    return _error_response(
        422, VALIDATION_ERROR.code, VALIDATION_ERROR.message, issues=issues
    )


async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    extra = {}
    if settings.environment == "development":
        extra["stack"] = traceback.format_exception(exc)
    return _error_response(500, INTERNAL_ERROR.code, INTERNAL_ERROR.message, **extra)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(StarletteHTTPException, http_error_handler)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(Exception, unhandled_error_handler)

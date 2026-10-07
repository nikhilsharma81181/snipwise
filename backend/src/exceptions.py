import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.config import settings

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 500
    code = "internal_error"
    message = "Something went wrong"

    def __init__(self, message: str | None = None):
        if message:
            self.message = message
        super().__init__(self.message)


class BadRequest(AppError):
    status_code = 400
    code = "bad_request"
    message = "Bad request"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Authentication required"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"
    message = "Forbidden"


class NotFound(AppError):
    status_code = 404
    code = "not_found"
    message = "Not found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"
    message = "Conflict"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"
    message = "File is too large"


class TooManyRequests(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests, try again in a minute"


def _error_response(status_code: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"code": code, "message": message, **extra}
    )


async def app_error_handler(request: Request, exc: AppError):
    return _error_response(exc.status_code, exc.code, exc.message)


async def http_error_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return _error_response(
            404, "not_found", f"Route not found: {request.method} {request.url.path}"
        )
    return _error_response(exc.status_code, "http_error", str(exc.detail))


async def validation_error_handler(request: Request, exc: RequestValidationError):
    issues = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"][1:])
        issues.append({"field": field, "message": err["msg"]})
    return _error_response(
        422, "validation_error", "Invalid request data", issues=issues
    )


async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    extra = {}
    if settings.environment == "development":
        extra["stack"] = traceback.format_exception(exc)
    return _error_response(500, "internal_error", "Something went wrong", **extra)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(StarletteHTTPException, http_error_handler)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # pyright: ignore[reportArgumentType]
    app.add_exception_handler(Exception, unhandled_error_handler)

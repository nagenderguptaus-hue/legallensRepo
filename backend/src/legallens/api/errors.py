"""Every error leaves the API in one envelope: ``{code, message, request_id}`` (BRD §6)."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from legallens.errors import AppError
from legallens.ids import new_id

HTTP_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    413: "file_too_large",
    415: "unsupported_type",
}


def request_id_of(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else new_id("req")


def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    request_id = request_id_of(request)
    return JSONResponse(
        {"code": code, "message": message, "request_id": request_id},
        status_code=status,
        headers={"X-Request-ID": request_id},
    )


async def _app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(request, exc.status, exc.code, exc.message)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = exc.errors()
    message = "The request is not valid."
    if errors:
        first = errors[0]
        where = ".".join(str(p) for p in first.get("loc", ()) if p not in ("body", "query", "path"))
        message = (
            f"{where}: {first.get('msg', 'invalid value')}" if where else str(first.get("msg"))
        )
    return error_response(request, 422, "validation_error", message)


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = HTTP_CODES.get(exc.status_code, "http_error")
    if exc.status_code == 404:
        message = "Not found."
    elif isinstance(exc.detail, str) and exc.detail:
        message = exc.detail
    else:
        message = f"Request failed ({exc.status_code})."
    return error_response(request, exc.status_code, code, message)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)

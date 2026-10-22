import logging
from dataclasses import dataclass

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


@dataclass
class APIError(Exception):
    status_code: int
    code: str
    message: str
    headers: dict[str, str] | None = None


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "unknown"))


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        headers=headers,
        content={
            "error": {
                "code": code,
                "message": message,
                "request_id": _request_id(request),
            }
        },
    )


def _http_error_code(status_code: int) -> str:
    return {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        413: "PAYLOAD_TOO_LARGE",
        415: "UNSUPPORTED_MEDIA_TYPE",
        422: "VALIDATION_ERROR",
        500: "INTERNAL_ERROR",
        503: "SERVICE_UNAVAILABLE",
        504: "GATEWAY_TIMEOUT",
    }.get(status_code, "HTTP_ERROR")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def handle_api_error(request: Request, error: APIError) -> JSONResponse:
        return error_response(
            request,
            status_code=error.status_code,
            code=error.code,
            message=error.message,
            headers=error.headers,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(
        request: Request,
        error: HTTPException,
    ) -> JSONResponse:
        message = error.detail if isinstance(error.detail, str) else "요청 처리에 실패했습니다."
        return error_response(
            request,
            status_code=error.status_code,
            code=_http_error_code(error.status_code),
            message=message,
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        return error_response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="요청 값이 올바르지 않습니다.",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        error: Exception,
    ) -> JSONResponse:
        logger.exception("Unhandled API error", exc_info=error)
        return error_response(
            request,
            status_code=500,
            code="INTERNAL_ERROR",
            message="서버 내부 오류가 발생했습니다.",
        )

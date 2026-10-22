"""Service-local infrastructure; no imports or database access to sibling services."""

import contextvars
import logging
import os
import time
from collections import Counter
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from psycopg.rows import dict_row
from sqlalchemy import URL, create_engine

SCHEMA = "ms_identity"
SERVICE = "identity"
request_id = contextvars.ContextVar("request_id", default="")
logger = logging.getLogger(SERVICE)


def required(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} must be configured")
    return value


@lru_cache
def engine():
    return create_engine(
        URL.create(
            "postgresql+psycopg",
            username=required("DB_USER"),
            password=required("DB_PASSWORD"),
            host=os.getenv("DB_HOST", "postgres"),
            port=int(os.getenv("DB_PORT", "5432")),
            database=os.getenv("DB_NAME", "secure_doc_agent"),
        ),
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=5,
        pool_pre_ping=True,
        pool_timeout=10,
        connect_args={"connect_timeout": 5},
    )


@contextmanager
def db(context=None):
    pooled = engine().raw_connection()
    conn = pooled.driver_connection
    conn.row_factory = dict_row
    try:
        with conn.transaction():
            conn.execute(f"SET LOCAL search_path TO {SCHEMA}")
            conn.execute("SET LOCAL statement_timeout = '30s'")
            if context:
                conn.execute(
                    "SELECT set_config('app.workspace_id',%s,true)",
                    (str(context["workspace_id"]),),
                )
                conn.execute(
                    "SELECT set_config('app.user_id',%s,true)",
                    (str(context["user_id"]),),
                )
            yield conn
    finally:
        pooled.close()


def migrate():
    with db() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (SCHEMA,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations(version text PRIMARY KEY, applied_at timestamptz DEFAULT now())"
        )
        for file in sorted(Path(__file__).parent.glob("[0-9][0-9][0-9]_*.sql")):
            if not conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version=%s", (file.name,)
            ).fetchone():
                conn.execute(file.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations(version) VALUES (%s)", (file.name,)
                )


def remote(method, url, *, authorization=None, **kwargs):
    headers = dict(kwargs.pop("headers", {}))
    headers["X-Request-ID"] = request_id.get() or str(uuid4())
    if authorization:
        headers["Authorization"] = authorization
    try:
        response = httpx.request(
            method,
            url,
            headers=headers,
            timeout=kwargs.pop("timeout", 10),
            follow_redirects=False,
            **kwargs,
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "DEPENDENCY_TIMEOUT") from exc
    except httpx.RequestError as exc:
        raise HTTPException(503, "DEPENDENCY_UNAVAILABLE") from exc
    if response.is_error:
        code = "DEPENDENCY_UNAVAILABLE"
        try:
            code = response.json().get("error", {}).get("code", code)
        except ValueError:
            pass
        raise HTTPException(
            response.status_code
            if response.status_code in (400, 401, 403, 404, 409, 422, 429)
            else 503,
            code,
            headers={"Retry-After": response.headers.get("Retry-After", "5")}
            if response.status_code == 429
            else None,
        )
    return response.json()


def authorize(request: Request):
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "UNAUTHORIZED", headers={"WWW-Authenticate": "Bearer"})
    context = remote(
        "GET",
        os.getenv("IDENTITY_URL", "http://identity:8000") + "/api/v1/auth/me",
        authorization=authorization,
    )
    # Validate the identity protocol, never accept client-supplied tenant headers.
    for key in ("user_id", "workspace_id", "organization_id"):
        context[key] = str(UUID(context[key]))
    if context.get("workspace_role") not in ("VIEWER", "EDITOR", "ADMIN"):
        raise HTTPException(403, "INSUFFICIENT_ROLE")
    return context


def require_role(context, *roles):
    if context["workspace_role"] not in roles:
        raise HTTPException(403, "INSUFFICIENT_ROLE")


def create_app(lifespan):
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    app = FastAPI(title=f"SecureDoc {SERVICE}", version="1.0.0", lifespan=lifespan)
    counts = Counter()

    @app.middleware("http")
    async def trace(request, call_next):
        try:
            rid = str(UUID(request.headers.get("X-Request-ID", "")))
        except ValueError:
            rid = str(uuid4())
        token = request_id.set(rid)
        started = time.monotonic()
        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception("Unhandled error request_id=%s", rid)
                response = JSONResponse(
                    status_code=500,
                    content={
                        "error": {
                            "code": "INTERNAL_ERROR",
                            "message": "요청 처리에 실패했습니다.",
                            "request_id": rid,
                        }
                    },
                )
            response.headers["X-Request-ID"] = rid
            counts[(request.method, response.status_code)] += 1
            logger.info(
                "%s %s status=%s duration=%.3f request_id=%s",
                request.method,
                request.url.path,
                response.status_code,
                time.monotonic() - started,
                rid,
            )
            return response
        finally:
            request_id.reset(token)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={
                "error": {
                    "code": str(exc.detail),
                    "message": str(exc.detail),
                    "request_id": request_id.get(),
                }
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "요청 값이 올바르지 않습니다.",
                    "request_id": request_id.get(),
                }
            },
        )

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        logger.exception("Unhandled error request_id=%s", request_id.get())
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "요청 처리에 실패했습니다.",
                    "request_id": request_id.get(),
                }
            },
        )

    @app.get("/health")
    @app.get("/api/v1/health")
    def health():
        return {"status": "healthy", "service": SERVICE}

    @app.get("/ready")
    @app.get("/api/v1/ready")
    def ready():
        try:
            with db() as conn:
                conn.execute("SELECT version FROM schema_migrations LIMIT 1")
        except Exception as exc:
            raise HTTPException(503, "DATABASE_UNAVAILABLE") from exc
        return {"status": "ready", "checks": {SERVICE: "ready", "postgresql": "ready"}}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics():
        extra = ""
        if hasattr(app.state, "extra_metrics"):
            try:
                extra = app.state.extra_metrics()
            except Exception:
                logger.exception("Additional metrics unavailable")
        return (
            "# TYPE secure_doc_service_requests_total counter\n"
            + "".join(
                f'secure_doc_service_requests_total{{service="{SERVICE}",method="{method}",status="{status}"}} {count}\n'
                for (method, status), count in list(counts.items())
            )
            + extra
        )

    return app

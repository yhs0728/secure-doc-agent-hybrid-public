from __future__ import annotations

import threading
import time
from collections import Counter

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: Counter[tuple[str, str, int]] = Counter()
        self._durations: Counter[tuple[str, str]] = Counter()
        self._duration_counts: Counter[tuple[str, str]] = Counter()
        self._duration_buckets: Counter[tuple[str, str, float]] = Counter()
        self._in_flight = 0

    def start(self) -> None:
        with self._lock:
            self._in_flight += 1

    def finish(self, method: str, path: str, status_code: int, duration: float) -> None:
        with self._lock:
            self._in_flight -= 1
            self._requests[(method, path, status_code)] += 1
            self._durations[(method, path)] += duration
            self._duration_counts[(method, path)] += 1
            for boundary in LATENCY_BUCKETS:
                if duration <= boundary:
                    self._duration_buckets[(method, path, boundary)] += 1

    def render(self) -> str:
        with self._lock:
            lines = [
                "# HELP secure_doc_http_requests_total HTTP requests processed.",
                "# TYPE secure_doc_http_requests_total counter",
            ]
            for (method, path, status_code), count in sorted(self._requests.items()):
                lines.append(
                    "secure_doc_http_requests_total"
                    f'{{method="{method}",path="{path}",status="{status_code}"}} {count}'
                )
            lines.extend(
                [
                    "# HELP secure_doc_http_request_duration_seconds HTTP request latency.",
                    "# TYPE secure_doc_http_request_duration_seconds histogram",
                ]
            )
            for (method, path), duration in sorted(self._durations.items()):
                lines.append(
                    "secure_doc_http_request_duration_seconds_sum"
                    f'{{method="{method}",path="{path}"}} {duration:.6f}'
                )
                for boundary in LATENCY_BUCKETS:
                    bucket_count = self._duration_buckets[(method, path, boundary)]
                    lines.append(
                        "secure_doc_http_request_duration_seconds_bucket"
                        f'{{method="{method}",path="{path}",le="{boundary:g}"}} '
                        f"{bucket_count}"
                    )
                count = self._duration_counts[(method, path)]
                lines.append(
                    "secure_doc_http_request_duration_seconds_bucket"
                    f'{{method="{method}",path="{path}",le="+Inf"}} {count}'
                )
                lines.append(
                    "secure_doc_http_request_duration_seconds_count"
                    f'{{method="{method}",path="{path}"}} {count}'
                )
            lines.extend(
                [
                    "# HELP secure_doc_http_requests_in_flight Current in-flight requests.",
                    "# TYPE secure_doc_http_requests_in_flight gauge",
                    f"secure_doc_http_requests_in_flight {self._in_flight}",
                ]
            )
            return "\n".join(lines) + "\n"


registry = MetricsRegistry()


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        registry.start()
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            path = getattr(route, "path", "__unmatched__")
            registry.finish(
                request.method,
                path,
                status_code,
                time.perf_counter() - started,
            )


def _database_metrics() -> str:
    from sqlalchemy import text

    from config.settings import get_settings
    from database.session import get_engine, set_local_user_context, transaction

    settings = get_settings()
    if not settings.database_enabled:
        return "secure_doc_metrics_collection_success 1\n"
    try:
        pool = get_engine().pool
        with transaction() as session:
            set_local_user_context(session, settings.system_user_id)
            outbox_backlog = session.scalar(
                text(
                    "SELECT count(*) FROM ops.outbox_events "
                    "WHERE status IN ('PENDING', 'PROCESSING', 'FAILED')"
                )
            )
            ingestion_backlog = session.scalar(
                text(
                    "SELECT count(*) FROM rag.ingestion_jobs "
                    "WHERE status NOT IN ('SUCCEEDED', 'CANCELLED')"
                )
            )
        return (
            "# TYPE secure_doc_db_pool_checked_out gauge\n"
            f"secure_doc_db_pool_checked_out {pool.checkedout()}\n"
            "# TYPE secure_doc_db_pool_checked_in gauge\n"
            f"secure_doc_db_pool_checked_in {pool.checkedin()}\n"
            "# TYPE secure_doc_db_pool_overflow gauge\n"
            f"secure_doc_db_pool_overflow {max(0, pool.overflow())}\n"
            "# TYPE secure_doc_db_pool_capacity gauge\n"
            "secure_doc_db_pool_capacity "
            f"{settings.database_pool_size + settings.database_max_overflow}\n"
            "# TYPE secure_doc_outbox_backlog gauge\n"
            f"secure_doc_outbox_backlog {outbox_backlog or 0}\n"
            "# TYPE secure_doc_ingestion_backlog gauge\n"
            f"secure_doc_ingestion_backlog {ingestion_backlog or 0}\n"
            "secure_doc_metrics_collection_success 1\n"
        )
    except Exception:  # noqa: BLE001 - metrics must stay available during outages
        return "secure_doc_metrics_collection_success 0\n"


def metrics_response() -> Response:
    payload = registry.render() + _database_metrics()
    return Response(payload, media_type="text/plain; version=0.0.4")

from app.metrics import MetricsRegistry


def test_metrics_registry_emits_cumulative_latency_histogram() -> None:
    registry = MetricsRegistry()

    registry.start()
    registry.finish("GET", "/api/v1/documents", 200, 0.02)
    registry.start()
    registry.finish("GET", "/api/v1/documents", 200, 0.2)

    rendered = registry.render()

    assert (
        'secure_doc_http_request_duration_seconds_bucket{method="GET",'
        'path="/api/v1/documents",le="0.01"} 0'
    ) in rendered
    assert (
        'secure_doc_http_request_duration_seconds_bucket{method="GET",'
        'path="/api/v1/documents",le="0.025"} 1'
    ) in rendered
    assert (
        'secure_doc_http_request_duration_seconds_bucket{method="GET",'
        'path="/api/v1/documents",le="0.25"} 2'
    ) in rendered
    assert (
        'secure_doc_http_request_duration_seconds_count{method="GET",'
        'path="/api/v1/documents"} 2'
    ) in rendered
    assert "secure_doc_http_requests_in_flight 0" in rendered

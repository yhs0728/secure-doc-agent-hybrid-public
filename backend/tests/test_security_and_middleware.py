import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_rag_graph
from app.main import app
from config.settings import Settings, get_settings


API_KEY = "test-service-api-key"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}


class FakeRAGGraph:
    def invoke(self, inputs: dict[str, str]) -> dict[str, object]:
        return {
            "answer": f"answer: {inputs['question']}",
            "citations": [],
            "requires_human_review": False,
        }


def override_get_settings() -> Settings:
    return Settings(
        llm_model="test-model",
        llm_api_key="test-llm-key",
        api_access_key=API_KEY,
    )


def override_get_rag_graph() -> FakeRAGGraph:
    return FakeRAGGraph()


@pytest.fixture
def client() -> TestClient:
    original_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_settings] = override_get_settings
    app.dependency_overrides[get_rag_graph] = override_get_rag_graph

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides = original_overrides


def test_protected_api_requires_authorization(client: TestClient) -> None:
    response = client.post(
        "/api/v1/questions",
        json={"question": "보안 정책은?"},
    )

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_protected_api_rejects_invalid_api_key(client: TestClient) -> None:
    response = client.post(
        "/api/v1/questions",
        headers={"Authorization": "Bearer wrong-key"},
        json={"question": "보안 정책은?"},
    )

    assert response.status_code == 401


def test_protected_api_accepts_valid_api_key(client: TestClient) -> None:
    response = client.post(
        "/api/v1/questions",
        headers=AUTH_HEADERS,
        json={"question": "보안 정책은?"},
    )

    assert response.status_code == 200


def test_health_api_does_not_require_authorization(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200


def test_response_has_generated_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]


def test_response_reuses_client_request_id(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health",
        headers={"X-Request-ID": "client-request-123"},
    )

    assert response.headers["X-Request-ID"] == "client-request-123"


def test_request_log_has_metadata_without_sensitive_content(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_question = "confidential-question-body"

    with caplog.at_level(logging.INFO, logger="app.middleware"):
        response = client.post(
            "/api/v1/questions",
            headers=AUTH_HEADERS,
            json={"question": secret_question},
        )

    assert response.status_code == 200
    record = next(
        record
        for record in caplog.records
        if '"event": "http_request"' in record.getMessage()
    )
    log_data = json.loads(record.getMessage())

    assert log_data["request_id"] == response.headers["X-Request-ID"]
    assert log_data["method"] == "POST"
    assert log_data["path"] == "/api/v1/questions"
    assert log_data["status_code"] == 200
    assert log_data["duration_seconds"] >= 0
    assert API_KEY not in record.getMessage()
    assert secret_question not in record.getMessage()

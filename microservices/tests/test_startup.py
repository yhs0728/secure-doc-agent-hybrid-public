import pytest
from fastapi.testclient import TestClient


def test_model_load_failure_prevents_knowledge_accepting_requests(monkeypatch):
    from knowledge_service import app as module

    monkeypatch.setenv("APP_ENVIRONMENT", "development")
    monkeypatch.setenv("KNOWLEDGE_SERVICE_TOKEN", "test-service-token-" + "x" * 40)
    monkeypatch.setattr(module, "migrate", lambda: None)

    def fail():
        raise RuntimeError("Embedding model unavailable")

    monkeypatch.setattr(module.storage, "embedding_model", fail)
    with (
        pytest.raises(RuntimeError, match="Embedding model unavailable"),
        TestClient(module.app),
    ):
        pytest.fail("API must not accept requests before model initialization")

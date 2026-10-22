"""Policy, outage isolation, bounded inference, authorization and history checks."""

from uuid import uuid4

import httpx
import pytest
from conversation_service import hybrid
from langchain_core.runnables import RunnableLambda
from openai import APIConnectionError, APIStatusError, APITimeoutError


def context():
    return {"workspace_id": str(uuid4()), "user_id": str(uuid4())}


class Provider:
    def __init__(self, error=None):
        self.error, self.calls = error, 0

    def bind(self, **kwargs):
        def invoke(value):
            self.calls += 1
            if self.error:
                raise self.error
            return "model-result"

        return RunnableLambda(invoke)


def test_default_policy_denies_and_never_calls_model(monkeypatch):
    monkeypatch.delenv("HYBRID_EXTERNAL_WORKSPACES", raising=False)
    backend = Provider()
    guarded = hybrid.ExternalModel(backend, context())
    with pytest.raises(hybrid.InferenceUnavailable, match="external_policy"):
        guarded.bind().invoke("sensitive prompt")
    assert backend.calls == 0


@pytest.mark.parametrize("value", ["*", "not-a-uuid", ",*", "all"])
def test_invalid_policy_is_rejected(value, monkeypatch):
    monkeypatch.setenv("HYBRID_EXTERNAL_WORKSPACES", value)
    with pytest.raises(ValueError):
        hybrid.allowed_workspaces()


def test_workspace_allowlist_is_exact(monkeypatch):
    allowed, denied = context(), context()
    monkeypatch.setenv("HYBRID_EXTERNAL_WORKSPACES", allowed["workspace_id"])
    assert hybrid.external_allowed(allowed)
    assert not hybrid.external_allowed(denied)


def test_policy_checked_again_between_graph_stages(monkeypatch):
    who, backend = context(), Provider()
    monkeypatch.setenv("HYBRID_EXTERNAL_WORKSPACES", who["workspace_id"])
    guarded = hybrid.ExternalModel(backend, who)
    assert guarded.bind(max_tokens=64).invoke("rewrite") == "model-result"
    monkeypatch.setenv("HYBRID_EXTERNAL_WORKSPACES", "")
    with pytest.raises(hybrid.InferenceUnavailable, match="external_policy"):
        guarded.bind().invoke("judge")
    assert backend.calls == 1


@pytest.mark.parametrize("kind", ["connection", "timeout", "capacity", "server"])
def test_provider_failures_do_not_retry_or_leak_response(kind, monkeypatch):
    who = context()
    monkeypatch.setenv("HYBRID_EXTERNAL_WORKSPACES", who["workspace_id"])
    request = httpx.Request("POST", "https://provider.invalid")
    error = {
        "connection": APIConnectionError(request=request),
        "timeout": APITimeoutError(request=request),
        "capacity": APIStatusError(
            "secret-provider-response",
            response=httpx.Response(429, request=request),
            body={},
        ),
        "server": APIStatusError(
            "secret-provider-response",
            response=httpx.Response(500, request=request),
            body={},
        ),
    }[kind]
    backend = Provider(error)
    guarded = hybrid.ExternalModel(backend, who)
    for _ in range(2):
        with pytest.raises(hybrid.InferenceUnavailable) as result:
            guarded.bind().invoke("private excerpt")
        assert "secret-provider-response" not in str(result.value)
    assert backend.calls == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_configuration_errors_are_not_outage_fallback(status, monkeypatch):
    who = context()
    monkeypatch.setenv("HYBRID_EXTERNAL_WORKSPACES", who["workspace_id"])
    error = APIStatusError(
        "private body",
        response=httpx.Response(
            status, request=httpx.Request("POST", "https://provider.invalid")
        ),
        body={},
    )
    with pytest.raises(hybrid.InferenceDenied, match="PROVIDER_CONFIGURATION_ERROR"):
        hybrid.ExternalModel(Provider(error), who).bind().invoke("prompt")


def test_budget_prevents_new_calls(monkeypatch):
    now, who, backend = [0], context(), Provider()
    monkeypatch.setenv("HYBRID_EXTERNAL_WORKSPACES", who["workspace_id"])
    guarded = hybrid.ExternalModel(backend, who, budget=5, clock=lambda: now[0])
    now[0] = 5
    with pytest.raises(hybrid.InferenceUnavailable, match="inference_budget"):
        guarded.bind().invoke("judge")
    assert backend.calls == 0


def test_circuit_blocks_single_probe_and_recovers():
    now = [0]
    breaker = hybrid.CircuitBreaker(threshold=2, cooldown=10, clock=lambda: now[0])
    breaker.finish(breaker.enter(), failed=True)
    breaker.finish(breaker.enter(), failed=True)
    assert breaker.metrics() == 1
    with pytest.raises(hybrid.InferenceUnavailable):
        breaker.enter()
    now[0] = 10
    probe = breaker.enter()
    with pytest.raises(hybrid.InferenceUnavailable):
        breaker.enter()
    breaker.finish(probe)
    assert breaker.metrics() == 0
    breaker.finish(breaker.enter())


def test_stale_success_does_not_close_new_circuit():
    breaker = hybrid.CircuitBreaker(threshold=1)
    first, second = breaker.enter(), breaker.enter()
    breaker.finish(first, failed=True)
    breaker.finish(second)
    assert breaker.metrics() == 1


def prepare_cloud(system, monkeypatch, *, allow=True):
    who = (
        system.clients["identity"].get("/api/v1/auth/me", headers=system.headers).json()
    )
    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv(
        "HYBRID_EXTERNAL_WORKSPACES", who["workspace_id"] if allow else ""
    )
    hybrid.circuit.cache_clear()
    client = system.clients["knowledge"]
    response = client.post(
        "/api/v1/documents/upload",
        headers=system.headers,
        files={
            "file": (
                "policy.txt",
                "비밀번호는 90일마다 변경합니다.".encode(),
                "text/plain",
            )
        },
    )
    assert response.status_code == 201
    assert system.worker.run_once()
    return who, response.json()["document_id"]


def test_http_policy_denial_preserves_search_and_history(system, monkeypatch):
    prepare_cloud(system, monkeypatch, allow=False)
    module = system.apps["conversation"]
    monkeypatch.setattr(
        module, "model", lambda: pytest.fail("external inference forbidden")
    )
    # A client cannot grant external permission by choosing a header or JSON field.
    response = system.clients["conversation"].post(
        "/api/v1/questions",
        headers={**system.headers, "X-Workspace-ID": str(uuid4())},
        json={"question": "비밀번호 변경 주기는?", "allow_external": True},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["response_mode"] == "search_only"
    assert body["response_reason"] == "external_policy"
    assert body["requires_human_review"]
    assert "90일" in body["answer"]
    assert body["citations"] == ["policy.txt"]
    history = (
        system.clients["conversation"]
        .get("/api/v1/conversations/" + body["conversation_id"], headers=system.headers)
        .json()
    )
    assert history["messages"][-1]["response_mode"] == "search_only"
    assert history["messages"][-1]["response_reason"] == "external_policy"
    assert (
        system.clients["knowledge"]
        .get("/api/v1/documents", headers=system.headers)
        .status_code
        == 200
    )


def test_http_outage_circuit_and_slot_release(system, monkeypatch):
    prepare_cloud(system, monkeypatch)
    module = system.apps["conversation"]
    backend = Provider(
        APIConnectionError(request=httpx.Request("POST", "https://provider.invalid"))
    )
    monkeypatch.setattr(module, "model", lambda: backend)
    monkeypatch.setattr(hybrid, "circuit", lambda: breaker)
    breaker = hybrid.CircuitBreaker(threshold=1)
    for reason in ["provider_unavailable", "circuit_open"]:
        response = system.clients["conversation"].post(
            "/api/v1/questions", headers=system.headers, json={"question": "비밀번호?"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["response_reason"] == reason
        assert response.json()["response_mode"] == "search_only"
        assert "90일" in response.json()["answer"]
    assert backend.calls == 1
    lease = module.capacity().acquire(0)
    lease.release()


def test_http_success_uses_cloud_and_preserves_source_validation(system, monkeypatch):
    prepare_cloud(system, monkeypatch)
    response = system.clients["conversation"].post(
        "/api/v1/questions",
        headers=system.headers,
        json={"question": "비밀번호 변경 주기는?"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["response_mode"] == "generated"
    assert not response.json()["requires_human_review"]
    assert response.json()["citations"] == ["policy.txt"]


def test_search_fallback_revalidates_deleted_documents(monkeypatch):
    from conversation_service import app as module
    from langchain_core.documents import Document

    doc = Document(
        page_content="deleted secret",
        metadata={
            "document_id": str(uuid4()),
            "source": "deleted.txt",
            "chunk_id": "x",
        },
    )
    monkeypatch.setattr(module.HttpRetriever, "invoke", lambda *args: [doc])
    monkeypatch.setattr(
        module, "knowledge", lambda *args: {"version": 1, "document_ids": []}
    )
    result = module.search_only("q", "Bearer test", "provider_unavailable")
    assert result["citations"] == []
    assert "deleted secret" not in result["answer"]


def test_forbidden_request_does_not_use_cloud_even_without_search_results(monkeypatch):
    from conversation_service import app as module

    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("HYBRID_EXTERNAL_WORKSPACES", "")
    monkeypatch.setattr(module, "model", lambda: pytest.fail("rewrite must not run"))
    monkeypatch.setattr(module.HttpRetriever, "invoke", lambda *args: [])
    result = module.hybrid_result("private", "Bearer test", context())
    assert result["response_reason"] == "external_policy"
    assert result["citations"] == []


def test_search_only_cold_start_needs_no_cloud_credentials(monkeypatch):
    from conversation_service import app as module
    from conversation_service.admission import LocalAdmission
    from fastapi.testclient import TestClient

    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("HYBRID_EXTERNAL_WORKSPACES", "")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("KNOWLEDGE_SERVICE_TOKEN", "test-token-" + "x" * 40)
    monkeypatch.setattr(module, "capacity", lambda: LocalAdmission(1))
    monkeypatch.setattr(module, "migrate", lambda: None)
    with TestClient(module.app) as client:
        assert client.get("/health").status_code == 200


def test_allowed_cloud_workspace_without_credentials_fails_startup(monkeypatch):
    from conversation_service import app as module
    from fastapi.testclient import TestClient

    monkeypatch.setenv("LLM_PROVIDER", "bedrock")
    monkeypatch.setenv("HYBRID_EXTERNAL_WORKSPACES", str(uuid4()))
    monkeypatch.setenv("KNOWLEDGE_SERVICE_TOKEN", "test-token-" + "x" * 40)
    monkeypatch.setenv("LLM_MODEL", "test")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with (
        pytest.raises(RuntimeError, match="LLM_API_KEY must be configured"),
        TestClient(module.app),
    ):
        pytest.fail("Invalid cloud deployment must not accept requests")

import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from uuid import uuid4

import pytest
import redis
from conversation_service import finops, hybrid
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda


@pytest.fixture
def ledger_clients():
    password = os.getenv("MICROSERVICES_TEST_REDIS_PASSWORD")
    if not password:
        pytest.skip("Real Redis required")
    namespace = "finops-test-" + uuid4().hex
    clients = [
        redis.Redis(
            host=os.getenv("MICROSERVICES_TEST_REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("MICROSERVICES_TEST_REDIS_PORT", "16379")),
            password=password,
            decode_responses=True,
            socket_timeout=2,
        )
        for _ in range(2)
    ]
    yield clients, namespace
    keys = list(clients[0].scan_iter(match=namespace + ":*"))
    if keys:
        clients[0].delete(*keys)
    for client in clients:
        client.close()


def test_shared_atomic_limits_under_concurrency(ledger_clients):
    clients, namespace = ledger_clients
    ledgers = [finops.Ledger(c, namespace, daily_calls=7) for c in clients]

    def reserve(i):
        try:
            ledgers[i % 2].reserve("synthetic", 10)
            return True
        except finops.FinOpsDenied:
            return False

    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(reserve, range(40)))
    assert sum(results) == 7
    assert int(ledgers[0].snapshot()["month"]["calls"]) == 7


def test_monthly_and_dollar_proxy_limits(ledger_clients):
    clients, namespace = ledger_clients
    ledger = finops.Ledger(clients[0], namespace, monthly_calls=1)
    keys = ledger.reserve("synthetic", 10)
    # Daily counter reset must not bypass the monthly aggregate limit.
    clients[0].delete(keys[0])
    with pytest.raises(finops.FinOpsDenied, match="finops_budget"):
        ledger.reserve("synthetic", 10)
    costly = finops.Ledger(clients[0], namespace + "-money", daily_microusd=1)
    with pytest.raises(finops.FinOpsDenied, match="finops_budget"):
        costly.reserve("synthetic", 10)
    assert costly.snapshot() == {"day": {}, "month": {}}


def test_usage_recorded_without_payload_or_refund(ledger_clients):
    clients, namespace = ledger_clients
    ledger = finops.Ledger(clients[0], namespace)
    keys = ledger.reserve("PRIVATE-CONTENT-SENTINEL", 64)
    before = ledger.snapshot()["month"]["reserved_microusd"]
    result = AIMessage(
        content="PRIVATE-ANSWER",
        usage_metadata={"input_tokens": 40, "output_tokens": 12, "total_tokens": 52},
    )
    ledger.record(keys, result)
    snapshot = ledger.snapshot()
    assert snapshot["month"]["input_tokens"] == "40"
    assert snapshot["month"]["output_tokens"] == "12"
    assert snapshot["month"]["reserved_microusd"] == before
    assert "PRIVATE" not in str(snapshot)
    assert 0 < clients[0].ttl(keys[1]) <= 3888000


def test_large_input_and_redis_failure_block_before_provider(ledger_clients):
    clients, namespace = ledger_clients
    ledger = finops.Ledger(clients[0], namespace, max_input_bytes=10)
    with pytest.raises(finops.FinOpsDenied, match="finops_input_limit"):
        ledger.reserve("a" * 11, 8)

    class Unavailable:
        def time(self):
            raise redis.ConnectionError("private endpoint")

    with pytest.raises(finops.FinOpsDenied, match="finops_unavailable") as error:
        finops.Ledger(Unavailable()).reserve("synthetic", 8)
    assert "private" not in str(error.value)


def test_every_graph_stage_charged_and_output_clamped(ledger_clients, monkeypatch):
    clients, namespace = ledger_clients
    ledger = finops.Ledger(clients[0], namespace, daily_calls=2, max_output=64)
    monkeypatch.setenv("FINOPS_ENABLED", "true")
    workspace = str(uuid4())
    monkeypatch.setenv("HYBRID_EXTERNAL_WORKSPACES", workspace)
    monkeypatch.setattr(finops, "ledger", lambda: ledger)
    bound_limits, calls = [], []

    class Provider:
        def bind(self, **kwargs):
            bound_limits.append(kwargs["max_tokens"])

            def invoke(value):
                calls.append(value)
                return AIMessage(content="synthetic")

            return RunnableLambda(invoke)

    guarded = hybrid.ExternalModel(Provider(), {"workspace_id": workspace})
    guarded.bind(max_tokens=4000).invoke("rewrite")
    guarded.bind(max_tokens=8).invoke("judge")
    with pytest.raises(hybrid.InferenceUnavailable, match="finops_budget"):
        guarded.bind().invoke("answer")
    assert bound_limits == [64, 8, 64]
    assert calls == ["rewrite", "judge"]
    assert int(ledger.snapshot()["month"]["calls"]) == 2


def test_provider_failure_keeps_reservation(ledger_clients, monkeypatch):
    import httpx
    from openai import APITimeoutError

    clients, namespace = ledger_clients
    ledger = finops.Ledger(clients[0], namespace)
    monkeypatch.setenv("FINOPS_ENABLED", "true")
    workspace = str(uuid4())
    monkeypatch.setenv("HYBRID_EXTERNAL_WORKSPACES", workspace)
    monkeypatch.setattr(finops, "ledger", lambda: ledger)

    class Provider:
        def bind(self, **kwargs):
            def fail(value):
                raise APITimeoutError(
                    request=httpx.Request("POST", "https://example.invalid")
                )

            return RunnableLambda(fail)

    guarded = hybrid.ExternalModel(Provider(), {"workspace_id": workspace})
    with pytest.raises(hybrid.InferenceUnavailable, match="provider_timeout"):
        guarded.bind().invoke("synthetic")
    snapshot = ledger.snapshot()["month"]
    assert snapshot["calls"] == "1"
    assert int(snapshot["reserved_microusd"]) > 0
    assert "completed" not in snapshot


def test_http_budget_degrades_without_provider(system, monkeypatch, ledger_clients):
    from test_hybrid import prepare_cloud

    prepare_cloud(system, monkeypatch)
    clients, namespace = ledger_clients
    ledger = finops.Ledger(clients[0], namespace, daily_calls=1)
    ledger.reserve("prior synthetic call", 8)
    monkeypatch.setenv("FINOPS_ENABLED", "true")
    monkeypatch.setattr(finops, "ledger", lambda: ledger)
    module = system.apps["conversation"]

    class Provider:
        def bind(self, **kwargs):
            return RunnableLambda(lambda _: pytest.fail("Paid provider must not run"))

    monkeypatch.setattr(module, "model", lambda: Provider())
    response = system.clients["conversation"].post(
        "/api/v1/questions",
        headers=system.headers,
        json={"question": "비밀번호 변경 주기는?"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["response_mode"] == "search_only"
    assert response.json()["response_reason"] == "finops_budget"
    assert response.json()["requires_human_review"] is True
    assert hybrid.circuit().failures == 0


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity"])
def test_invalid_control_tariff_fails_startup(value, monkeypatch):
    monkeypatch.setenv("FINOPS_TEST_RATE", value)
    with pytest.raises(ValueError):
        finops.positive("FINOPS_TEST_RATE", Decimal(1), decimal=True)


@pytest.mark.parametrize(
    "usage",
    [
        {"input_tokens": 40},
        {"input_tokens": 40, "output_tokens": -1},
        {"input_tokens": 40, "output_tokens": True},
    ],
)
def test_partial_usage_is_counted_as_missing(ledger_clients, usage):
    from types import SimpleNamespace

    clients, namespace = ledger_clients
    ledger = finops.Ledger(clients[0], namespace)
    keys = ledger.reserve("synthetic", 64)
    ledger.record(keys, SimpleNamespace(usage_metadata=usage))
    result = ledger.snapshot()["month"]
    assert result["input_tokens"] == "40"
    assert result["usage_missing"] == "1"
    assert "output_tokens" not in result

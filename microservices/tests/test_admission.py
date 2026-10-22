import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
import redis
from conversation_service.admission import (
    CapacityBusy,
    ControlUnavailable,
    GuardedModel,
    RateLimited,
    RedisAdmission,
)
from redis.backoff import NoBackoff
from redis.retry import Retry


@pytest.fixture
def controls():
    password = os.getenv("MICROSERVICES_TEST_REDIS_PASSWORD")
    if not password:
        pytest.skip("Set MICROSERVICES_TEST_REDIS_PASSWORD for real Redis tests")
    namespace = "secure-doc-test-" + uuid4().hex
    clients = [
        redis.Redis(
            host=os.getenv("MICROSERVICES_TEST_REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("MICROSERVICES_TEST_REDIS_PORT", "16379")),
            password=password,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            retry=Retry(NoBackoff(), 0),
        )
        for _ in range(2)
    ]
    for client in clients:
        client.ping()
    yield clients, namespace
    # Remove only this fixture's keys; never flush a shared Redis database.
    keys = list(clients[0].scan_iter(match=namespace + ":*"))
    if keys:
        clients[0].delete(*keys)
    for client in clients:
        client.close()


def test_two_replica_clients_share_one_limit(controls):
    clients, namespace = controls
    first, second = [
        RedisAdmission(c, namespace=namespace, ttl_ms=3000) for c in clients
    ]
    lease = first.acquire(0)
    try:
        with pytest.raises(CapacityBusy):
            second.acquire(0.1)
        lease.ensure_valid()
    finally:
        lease.release()
    other = second.acquire(0)
    other.ensure_valid()
    other.release()


def test_renewal_and_old_owner_cannot_release_replacement(controls):
    clients, namespace = controls
    first = RedisAdmission(clients[0], namespace=namespace, ttl_ms=300)
    second = RedisAdmission(clients[1], namespace=namespace, ttl_ms=300)
    lease = first.acquire(0)
    time.sleep(0.7)  # Longer than TTL: renewal must keep the live request admitted.
    with pytest.raises(CapacityBusy):
        second.acquire(0)
    lease.stop.set()
    lease.thread.join(timeout=2)
    clients[0].zadd(first.key, {lease.token: 0})
    replacement = second.acquire(0)
    try:
        with pytest.raises(ControlUnavailable):
            lease.ensure_valid()
        lease.release()
        replacement.ensure_valid()
    finally:
        replacement.release()


def test_atomic_limit_under_concurrent_clients(controls):
    clients, namespace = controls
    controllers = [
        RedisAdmission(client, namespace=namespace, limit=2, ttl_ms=3000)
        for client in clients
    ]
    count = 0
    peak = 0
    lock = threading.Lock()

    def work(n):
        nonlocal count, peak
        lease = controllers[n % 2].acquire(3)
        try:
            with lock:
                count += 1
                peak = max(peak, count)
            time.sleep(0.05)
            lease.ensure_valid()
        finally:
            with lock:
                count -= 1
            lease.release()

    with ThreadPoolExecutor(max_workers=12) as executor:
        list(executor.map(work, range(24)))
    assert peak == 2


def test_rate_limit_is_shared_and_scoped_to_workspace_user(controls):
    clients, namespace = controls
    first, second = [
        RedisAdmission(c, namespace=namespace, rate_limit=2, rate_window_ms=5000)
        for c in clients
    ]
    context = {"workspace_id": str(uuid4()), "user_id": str(uuid4())}
    first.enforce_rate(context)
    second.enforce_rate(context)
    with pytest.raises(RateLimited) as error:
        first.enforce_rate(context)
    assert 1 <= error.value.retry_after <= 5
    second.enforce_rate({**context, "user_id": str(uuid4())})
    second.enforce_rate({**context, "workspace_id": str(uuid4())})


def test_redis_outage_does_not_fall_back_to_local_capacity():
    class Offline:
        def eval(self, *args):
            raise redis.ConnectionError("offline")

    controller = RedisAdmission(Offline())
    with pytest.raises(ControlUnavailable):
        controller.acquire(0)
    with pytest.raises(ControlUnavailable):
        controller.enforce_rate({"workspace_id": "w", "user_id": "u"})


def test_lost_admission_blocks_next_model_call():
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    class Lost:
        def ensure_valid(self):
            raise ControlUnavailable()

    model = GuardedModel(FakeListChatModel(responses=["should not run"]), Lost())
    with pytest.raises(ControlUnavailable):
        model.bind(max_tokens=4).invoke("question")


def test_redis_failure_returns_503_without_running_rag(monkeypatch):
    from conversation_service import app as module
    from fastapi.testclient import TestClient

    class Offline:
        def enforce_rate(self, context):
            raise ControlUnavailable()

    monkeypatch.setattr(module, "capacity", lambda: Offline())
    monkeypatch.setattr(
        module,
        "generate",
        lambda *args: pytest.fail("RAG must not run without shared admission"),
    )
    module.app.dependency_overrides[module.authorize] = lambda: {
        "workspace_id": str(uuid4()),
        "user_id": str(uuid4()),
    }
    try:
        response = TestClient(module.app).post(
            "/api/v1/questions",
            json={"question": "test"},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "ADMISSION_CONTROL_UNAVAILABLE"
    finally:
        module.app.dependency_overrides.clear()


def test_llm_server_failure_returns_503_and_releases_slot(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    import httpx
    from conversation_service import app as module
    from conversation_service.admission import LocalAdmission
    from fastapi.testclient import TestClient
    from openai import InternalServerError

    controller = LocalAdmission(1)
    monkeypatch.setattr(module, "capacity", lambda: controller)

    def fail(*args):
        raise InternalServerError(
            "unavailable",
            response=httpx.Response(
                500, request=httpx.Request("POST", "http://test-llm")
            ),
            body={},
        )

    monkeypatch.setattr(module, "generate", fail)
    module.app.dependency_overrides[module.authorize] = lambda: {
        "workspace_id": str(uuid4()),
        "user_id": str(uuid4()),
    }
    try:
        response = TestClient(module.app).post(
            "/api/v1/questions",
            json={"question": "test"},
            headers={"Authorization": "Bearer test"},
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "LLM_UNAVAILABLE"
        controller.acquire(0).release()
    finally:
        module.app.dependency_overrides.clear()

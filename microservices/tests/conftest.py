"""Real PostgreSQL service tests; external S3/search/LLM adapters are deterministic doubles."""

import importlib
import io
import os
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel

ROOT = Path(__file__).resolve().parents[2]
for service in ("identity", "knowledge", "conversation"):
    sys.path.insert(0, str(ROOT / "microservices" / service))
sys.path.insert(0, str(ROOT / "infra" / "database"))


@pytest.fixture(scope="session")
def database():
    dsn = os.getenv("MICROSERVICES_TEST_DSN")
    if not dsn:
        pytest.skip(
            "Set MICROSERVICES_TEST_DSN to a disposable PostgreSQL database ending in _test"
        )
    info = psycopg.conninfo.conninfo_to_dict(dsn)
    if not info.get("dbname", "").endswith("_test"):
        raise RuntimeError("Refusing to use a non-test database")
    from bootstrap import provision_test_database

    passwords = {
        s: "test-password-for-" + s for s in ("identity", "knowledge", "conversation")
    }
    with psycopg.connect(dsn) as conn:
        provision_test_database(conn, passwords)
    yield info, passwords
    for service in ("identity", "knowledge", "conversation"):
        platform = importlib.import_module(service + "_service.platform")
        if platform.engine.cache_info().currsize:
            platform.engine().dispose()
            platform.engine.cache_clear()


@pytest.fixture
def system(database, monkeypatch):
    info, passwords = database
    monkeypatch.setenv("DB_HOST", info.get("host", "127.0.0.1"))
    monkeypatch.setenv("DB_PORT", info.get("port", "5432"))
    monkeypatch.setenv("DB_NAME", info["dbname"])
    monkeypatch.setenv("AUTH_JWT_SECRET", "test-identity-signing-key-" + "x" * 40)
    monkeypatch.setenv(
        "KNOWLEDGE_SERVICE_TOKEN", "test-knowledge-service-key-" + "x" * 40
    )
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "admin@test.local")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "test-admin-password-1234")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "test-llm")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("IDENTITY_URL", "http://identity")
    monkeypatch.setenv("KNOWLEDGE_URL", "http://knowledge")
    monkeypatch.setenv("APP_ENVIRONMENT", "test")
    monkeypatch.setenv("CAPACITY_BACKEND", "memory")
    monkeypatch.setenv("CHUNK_SIZE", "500")
    monkeypatch.setenv("CHUNK_OVERLAP", "50")
    clients = {}
    apps = {}
    stack = ExitStack()
    for service in ("identity", "knowledge", "conversation"):
        monkeypatch.setenv("DB_USER", "svc_" + service)
        monkeypatch.setenv("DB_PASSWORD", passwords[service])
        module = importlib.import_module(service + "_service.app")
        platform = importlib.import_module(service + "_service.platform")
        # Construct each independent pool using that service's credentials.
        platform.engine()
        apps[service] = module
        clients[service] = stack.enter_context(TestClient(module.app))
    with psycopg.connect(**info) as conn:
        conn.execute(
            "TRUNCATE ms_conversation.messages,ms_conversation.conversations,ms_knowledge.jobs,ms_knowledge.documents CASCADE"
        )
        conn.execute(
            "DELETE FROM ms_identity.memberships WHERE user_id IN (SELECT id FROM ms_identity.users WHERE email<>'admin@test.local')"
        )
        conn.execute("DELETE FROM ms_identity.users WHERE email<>'admin@test.local'")

    def http_request(method, url, **kwargs):
        host = urlparse(url).hostname
        if host not in clients:
            raise httpx.ConnectError("Service unavailable")
        kwargs.pop("timeout", None)
        kwargs.pop("follow_redirects", None)
        return clients[host].request(method, urlparse(url).path, **kwargs)

    monkeypatch.setattr(httpx, "request", http_request)

    class Store:
        def __init__(self):
            self.objects = {}

        def put_object(self, **kwargs):
            self.objects[kwargs["Key"]] = kwargs["Body"]

        def get_object(self, **kwargs):
            return {"Body": io.BytesIO(self.objects[kwargs["Key"]])}

        def delete_object(self, **kwargs):
            self.objects.pop(kwargs["Key"], None)

    store = Store()
    indexed = {}
    storage = apps["knowledge"].storage
    real_stage_generation = storage.stage_generation
    active_generation = {"value": "initial-generation"}
    monkeypatch.setattr(storage, "object_store", lambda: store)

    def put_chunks(document, chunks):
        indexed[str(document["id"])] = [
            {
                "document_id": str(document["id"]),
                "source": document["file_name"],
                "chunk_id": str(document["id"]) + ":" + str(i),
                "text": chunk["text"],
                "page": chunk["page"],
                "score": 1.0,
            }
            for i, chunk in enumerate(chunks)
        ]

    monkeypatch.setattr(storage, "put_chunks", put_chunks)
    monkeypatch.setattr(
        storage, "prepare_chunks", lambda chunks: [[1.0] for _ in chunks]
    )
    monkeypatch.setattr(storage, "ensure_alias", lambda *args: None)
    monkeypatch.setattr(
        storage,
        "put_prepared",
        lambda document, chunks, vectors: storage.put_chunks(document, chunks),
    )
    generations = {}

    def stage_generation(workspace, prepared):
        physical = "generation-" + str(len(generations))
        generations[physical] = {
            str(doc["id"]): (doc, chunks, vectors) for doc, chunks, vectors in prepared
        }
        return physical

    def write_prepared(doc, chunks, vectors, physical):
        generations[physical][str(doc["id"])] = (doc, chunks, vectors)

    def publish_generation(workspace, physical, count):
        assert count == sum(
            len(chunks) for doc, chunks, vectors in generations[physical].values()
        )
        indexed.clear()
        for doc, chunks, _vectors in generations[physical].values():
            put_chunks(doc, chunks)
        active_generation["value"] = physical

    def remove_generation_documents(physical, ids):
        for did in ids:
            generations[physical].pop(did, None)

    monkeypatch.setattr(storage, "stage_generation", stage_generation)
    monkeypatch.setattr(storage, "write_prepared", write_prepared)

    def copy_ready_document(document, physical):
        chunks = [
            {"text": chunk["text"], "page": chunk["page"]}
            for chunk in indexed[str(document["id"])]
        ]
        generations[physical][str(document["id"])] = (
            document,
            chunks,
            [[1.0] for _ in chunks],
        )
        return len(chunks)

    monkeypatch.setattr(storage, "copy_ready_document", copy_ready_document)
    monkeypatch.setattr(storage, "publish_generation", publish_generation)
    monkeypatch.setattr(
        storage, "active_generation", lambda workspace: active_generation["value"]
    )
    monkeypatch.setattr(
        storage, "remove_generation_documents", remove_generation_documents
    )
    monkeypatch.setattr(
        storage,
        "discard_generation",
        lambda workspace, physical: generations.pop(physical, None),
    )

    def rebuild_chunks(workspace, prepared):
        replacement = {}
        for document, chunks in prepared:
            replacement[str(document["id"])] = [
                {
                    "document_id": str(document["id"]),
                    "source": document["file_name"],
                    "chunk_id": str(document["id"]) + ":" + str(i),
                    "text": chunk["text"],
                    "page": chunk["page"],
                    "score": 1.0,
                }
                for i, chunk in enumerate(chunks)
            ]
        indexed.clear()
        indexed.update(replacement)

    monkeypatch.setattr(storage, "rebuild_chunks", rebuild_chunks)
    monkeypatch.setattr(
        storage, "delete_chunks", lambda doc: indexed.pop(str(doc["id"]), None)
    )
    monkeypatch.setattr(
        storage,
        "retrieve",
        lambda workspace, q, k, active: [
            chunk
            for did, chunks in indexed.items()
            if did in active
            for chunk in chunks
        ][:k],
    )
    monkeypatch.setattr(
        apps["conversation"],
        "model",
        lambda: FakeListChatModel(
            responses=[
                "0",
                "비밀번호는 90일마다 변경합니다.",
                '{"citations":[1]}',
                "GROUNDED",
            ]
        ),
    )
    worker = importlib.import_module("knowledge_service.worker")
    token = (
        clients["identity"]
        .post(
            "/api/v1/auth/login",
            json={"email": "admin@test.local", "password": "test-admin-password-1234"},
        )
        .json()["access_token"]
    )
    headers = {"Authorization": "Bearer " + token}
    yield SimpleNamespace(
        real_stage_generation=real_stage_generation,
        clients=clients,
        apps=apps,
        worker=worker,
        headers=headers,
        store=store,
        indexed=indexed,
        info=info,
        passwords=passwords,
    )
    stack.close()

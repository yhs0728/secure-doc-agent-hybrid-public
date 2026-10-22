import ast
import os
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_build_contexts_and_imports_are_independent():
    import yaml

    compose = yaml.safe_load((ROOT / "compose.yaml").read_text())["services"]
    for service in ("identity", "knowledge", "conversation"):
        assert compose[service]["build"] == "./microservices/" + service
        env = compose[service]["environment"]
        assert "POSTGRES_PASSWORD" not in env
        assert env["DB_USER"] == "svc_" + service
        if service != "knowledge":
            assert not any(
                key.startswith(("OPENSEARCH_", "OBJECT_STORAGE_")) for key in env
            )
        for file in (ROOT / "microservices" / service).rglob("*.py"):
            for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module:
                    assert not node.module.startswith(("backend.", "database."))
                    for sibling in {"identity", "knowledge", "conversation"} - {
                        service
                    }:
                        assert not node.module.startswith(sibling + "_service")
    assert not compose["conversation"].get("volumes")
    assert (
        "sentence-transformers"
        not in (ROOT / "microservices/conversation/requirements.txt").read_text()
    )


def test_role_permissions_and_no_cross_schema_foreign_keys(system):
    for service in ("identity", "knowledge", "conversation"):
        config = {
            **system.info,
            "user": "svc_" + service,
            "password": system.passwords[service],
        }
        with psycopg.connect(**config, autocommit=True) as conn:
            for other in {"identity", "knowledge", "conversation"} - {service}:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    conn.execute(f"SELECT * FROM ms_{other}.schema_migrations")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("CREATE SCHEMA unauthorized_schema")
    with psycopg.connect(**system.info) as conn:
        cross = conn.execute("""SELECT 1 FROM pg_constraint c JOIN pg_class a ON a.oid=c.conrelid
            JOIN pg_class b ON b.oid=c.confrelid JOIN pg_namespace n ON n.oid=a.relnamespace
            WHERE c.contype='f' AND n.nspname LIKE 'ms_%%' AND a.relnamespace<>b.relnamespace""").fetchall()
        assert cross == []


def upload(system):
    response = system.clients["knowledge"].post(
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
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "queued"
    return response.json()["document_id"]


def test_upload_search_rag_and_history_via_http_contract(system):
    did = upload(system)
    assert system.worker.run_once()
    row = (
        system.clients["knowledge"]
        .get("/api/v1/documents/" + did, headers=system.headers)
        .json()
    )
    assert row["processing_status"] == "READY"
    response = system.clients["conversation"].post(
        "/api/v1/questions",
        headers=system.headers,
        json={"question": "비밀번호 변경 주기는?"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["citations"] == ["policy.txt"]
    assert not body["requires_human_review"]
    cid = body["conversation_id"]
    detail = (
        system.clients["conversation"]
        .get("/api/v1/conversations/" + cid, headers=system.headers)
        .json()
    )
    assert [m["role"] for m in detail["messages"]] == ["USER", "ASSISTANT"]
    assert detail["messages"][1]["citations"] == ["policy.txt"]
    with psycopg.connect(**system.info) as conn:
        snapshot = conn.execute(
            "SELECT citations FROM ms_conversation.messages WHERE role='ASSISTANT'"
        ).fetchone()[0][0]
        assert (
            snapshot["document_id"] == did
            and snapshot["quote"]
            and snapshot["page"] == 1
        )


def test_deletion_hides_stale_search_immediately(system):
    did = upload(system)
    system.worker.run_once()
    response = system.clients["knowledge"].delete(
        "/api/v1/documents/" + did, headers=system.headers
    )
    assert response.status_code == 200 and response.json()["status"] == "deleting"
    assert did in system.indexed  # external deletion has deliberately not run yet
    headers = {**system.headers, "X-Service-Key": os.environ["KNOWLEDGE_SERVICE_TOKEN"]}
    response = system.clients["knowledge"].post(
        "/internal/v1/search", headers=headers, json={"query": "비밀번호"}
    )
    assert response.json()["chunks"] == []
    result = system.apps["conversation"].validated_result(
        {
            "answer": "90일",
            "requires_human_review": False,
            "citations": ["policy.txt"],
            "documents": [
                __import__("langchain_core.documents", fromlist=["Document"]).Document(
                    page_content="90일",
                    metadata={
                        "source": "policy.txt",
                        "document_id": did,
                        "chunk_id": did + ":0",
                    },
                )
            ],
        },
        system.headers["Authorization"],
    )
    assert result["requires_human_review"] and result["citations"] == []
    system.worker.run_once()
    assert did not in system.indexed
    assert not system.store.objects


def test_duplicate_upload_and_viewer_cannot_write(system):
    upload(system)
    response = system.clients["knowledge"].post(
        "/api/v1/documents/upload",
        headers=system.headers,
        files={
            "file": (
                "copy.txt",
                "비밀번호는 90일마다 변경합니다.".encode(),
                "text/plain",
            )
        },
    )
    assert response.status_code == 409
    identity = system.clients["identity"]
    assert (
        identity.post(
            "/api/v1/auth/users",
            headers=system.headers,
            json={
                "email": "viewer@test.local",
                "password": "viewer-password-1234",
                "display_name": "Viewer",
                "workspace_role": "VIEWER",
            },
        ).status_code
        == 201
    )
    token = identity.post(
        "/api/v1/auth/login",
        json={"email": "viewer@test.local", "password": "viewer-password-1234"},
    ).json()["access_token"]
    response = system.clients["knowledge"].post(
        "/api/v1/documents/upload",
        headers={"Authorization": "Bearer " + token},
        files={"file": ("another.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 403


def test_cross_workspace_and_user_isolation(system):
    did = upload(system)
    system.worker.run_once()
    identity = system.clients["identity"]
    created = identity.post(
        "/api/v1/auth/users",
        headers=system.headers,
        json={
            "email": "second@test.local",
            "password": "second-password-1234",
            "display_name": "Second",
            "workspace_role": "VIEWER",
        },
    ).json()
    cid = (
        system.clients["conversation"]
        .post("/api/v1/questions", headers=system.headers, json={"question": "주기?"})
        .json()["conversation_id"]
    )
    token = identity.post(
        "/api/v1/auth/login",
        json={"email": "second@test.local", "password": "second-password-1234"},
    ).json()["access_token"]
    headers = {"Authorization": "Bearer " + token}
    assert (
        system.clients["conversation"]
        .get("/api/v1/conversations", headers=headers)
        .json()
        == []
    )
    assert (
        system.clients["conversation"]
        .get("/api/v1/conversations/" + cid, headers=headers)
        .status_code
        == 404
    )
    user = {"id": UUID(created["user_id"]), "token_version": 1}
    other = uuid4()
    with psycopg.connect(**system.info) as conn:
        conn.execute(
            "INSERT INTO ms_identity.workspaces(id,organization_id,name) VALUES(%s,%s,%s)",
            (other, uuid4(), "Other"),
        )
        conn.execute(
            "INSERT INTO ms_identity.memberships(workspace_id,user_id,role) VALUES(%s,%s,%s)",
            (other, user["id"], "ADMIN"),
        )
    token = system.apps["identity"].issue_token(user, other)
    headers = {
        "Authorization": "Bearer " + token,
        "X-Workspace-ID": system.clients["identity"]
        .get("/api/v1/auth/me", headers=system.headers)
        .json()["workspace_id"],
    }
    assert (
        system.clients["knowledge"].get("/api/v1/documents", headers=headers).json()
        == []
    )
    assert (
        system.clients["knowledge"]
        .get("/api/v1/documents/" + did, headers=headers)
        .status_code
        == 404
    )


def test_expired_token_password_rotation_and_service_auth(system):
    identity = system.clients["identity"]
    forged = {
        **system.headers,
        "Authorization": system.headers["Authorization"][:-8] + "tampered",
    }
    assert identity.get("/api/v1/auth/me", headers=forged).status_code == 401
    assert (
        system.clients["knowledge"]
        .post("/internal/v1/search", headers=system.headers, json={"query": "test"})
        .status_code
        == 403
    )
    response = identity.post(
        "/api/v1/auth/change-password",
        headers=system.headers,
        json={
            "current_password": "test-admin-password-1234",
            "new_password": "changed-password-1234",
        },
    )
    assert response.status_code == 204
    assert identity.get("/api/v1/auth/me", headers=system.headers).status_code == 401
    # Restore the fixture administrator without allowing an old token to become valid again.
    with psycopg.connect(**system.info) as conn:
        conn.execute(
            "UPDATE ms_identity.users SET password_hash=%s WHERE email=%s",
            (
                system.apps["identity"].hash_password("test-admin-password-1234"),
                "admin@test.local",
            ),
        )


def test_lease_recovery_retry_and_fencing(system, monkeypatch):
    did = upload(system)
    first = system.worker.claim()
    assert first
    assert system.worker.claim() is None
    with psycopg.connect(**system.info) as conn:
        conn.execute(
            "UPDATE ms_knowledge.jobs SET leased_until=now()-interval '1 second' WHERE id=%s",
            (first["id"],),
        )
    second = system.worker.claim()
    assert second["lease_token"] != first["lease_token"]
    system.worker.process(first)
    with psycopg.connect(**system.info) as conn:
        assert (
            conn.execute(
                "SELECT status FROM ms_knowledge.jobs WHERE id=%s", (first["id"],)
            ).fetchone()[0]
            == "RUNNING"
        )
        assert (
            conn.execute(
                "SELECT state FROM ms_knowledge.documents WHERE id=%s", (UUID(did),)
            ).fetchone()[0]
            == "PENDING"
        )
    system.worker.process(second)
    with psycopg.connect(**system.info) as conn:
        assert (
            conn.execute(
                "SELECT status FROM ms_knowledge.jobs WHERE id=%s", (first["id"],)
            ).fetchone()[0]
            == "DONE"
        )


def test_job_failure_is_durable_and_retryable(system, monkeypatch):
    upload(system)
    monkeypatch.setattr(
        system.apps["knowledge"].storage,
        "put_chunks",
        lambda *args: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    system.worker.run_once()
    with psycopg.connect(**system.info) as conn:
        job = conn.execute(
            "SELECT status,attempts,error_code FROM ms_knowledge.jobs"
        ).fetchone()
    assert job == ("PENDING", 1, "DOCUMENT_PROCESSING_FAILED")


def test_identity_outage_fails_closed_and_chat_outage_does_not_block_documents(
    system, monkeypatch
):
    upload(system)
    monkeypatch.setattr(
        system.apps["conversation"],
        "generate",
        lambda *args: (_ for _ in ()).throw(RuntimeError("chat failed")),
    )
    assert (
        system.clients["knowledge"]
        .get("/api/v1/documents", headers=system.headers)
        .status_code
        == 200
    )
    monkeypatch.setattr(
        httpx,
        "request",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            httpx.ConnectError("identity offline")
        ),
    )
    assert (
        system.clients["knowledge"]
        .get("/api/v1/documents", headers=system.headers)
        .status_code
        == 503
    )


def test_parser_preserves_page_and_rejects_bad_overlap(monkeypatch):
    from knowledge_service.parsing import parse_and_split

    monkeypatch.setenv("CHUNK_SIZE", "10")
    monkeypatch.setenv("CHUNK_OVERLAP", "2")
    chunks, pages = parse_and_split(b"1234567890abcdefghij", ".txt")
    assert (
        pages == 1
        and all(chunk["page"] == 1 for chunk in chunks)
        and chunks[1]["text"].startswith("90")
    )
    monkeypatch.setenv("CHUNK_OVERLAP", "10")
    with pytest.raises(ValueError):
        parse_and_split(b"abc", ".txt")


def test_llm_provider_options_do_not_leak_to_openai(monkeypatch):
    from conversation_service.app import model

    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    model.cache_clear()
    try:
        assert model().extra_body["options"]["num_predict"] == 64
        model.cache_clear()
        monkeypatch.setenv("LLM_PROVIDER", "openai")
        assert not model().extra_body
    finally:
        model.cache_clear()


def test_rebuild_keeps_ready_documents_and_rejects_duplicate_job(system, monkeypatch):
    did = upload(system)
    system.worker.run_once()
    client = system.clients["knowledge"]
    assert (
        client.post("/api/v1/index/update", headers=system.headers).status_code == 202
    )
    assert (
        client.post("/api/v1/index/update", headers=system.headers).status_code == 409
    )
    assert (
        client.get("/api/v1/documents/" + did, headers=system.headers).json()[
            "processing_status"
        ]
        == "READY"
    )
    assert (
        client.get("/api/v1/index/status", headers=system.headers).json()["status"]
        == "indexing"
    )
    system.worker.run_once()
    assert (
        client.get("/api/v1/index/status", headers=system.headers).json()["status"]
        == "ready"
    )
    assert did in system.indexed


def test_rebuild_failure_preserves_previous_search(system, monkeypatch):
    did = upload(system)
    system.worker.run_once()
    system.clients["knowledge"].post("/api/v1/index/update", headers=system.headers)
    monkeypatch.setattr(
        system.apps["knowledge"].storage,
        "publish_generation",
        lambda *args: (_ for _ in ()).throw(RuntimeError("index failed")),
    )
    system.worker.run_once()
    assert did in system.indexed
    assert (
        system.clients["knowledge"]
        .get("/api/v1/documents/" + did, headers=system.headers)
        .json()["processing_status"]
        == "READY"
    )


def test_rebuild_job_reports_completion_and_generation_change(system):
    upload(system)
    system.worker.run_once()
    client = system.clients["knowledge"]
    response = client.post("/api/v1/index/update", headers=system.headers)
    path = "/api/v1/index/jobs/" + response.json()["job_id"]
    assert client.get(path, headers=system.headers).json()["status"] == "PENDING"
    system.worker.run_once()
    job = client.get(path, headers=system.headers).json()
    assert job["status"] == "DONE"
    assert job["generation_after"] != job["generation_before"]
    assert job["active_generation"] == job["generation_after"]
    assert client.get(path).status_code == 401
    module = system.apps["knowledge"]
    context = (
        system.clients["identity"].get("/api/v1/auth/me", headers=system.headers).json()
    )
    module.app.dependency_overrides[module.authorize] = lambda: {
        **context,
        "workspace_role": "VIEWER",
    }
    try:
        assert client.get(path, headers=system.headers).status_code == 403
    finally:
        module.app.dependency_overrides.clear()
    with psycopg.connect(**system.info) as conn:
        conn.execute(
            "UPDATE ms_knowledge.jobs SET workspace_id=%s WHERE id=%s",
            (uuid4(), UUID(job["id"])),
        )
    assert client.get(path, headers=system.headers).status_code == 404


def test_rebuild_job_reports_terminal_failure(system, monkeypatch):
    upload(system)
    system.worker.run_once()
    client = system.clients["knowledge"]
    response = client.post("/api/v1/index/update", headers=system.headers)
    job_id = response.json()["job_id"]
    with psycopg.connect(**system.info) as conn:
        conn.execute(
            "UPDATE ms_knowledge.jobs SET attempts=7 WHERE id=%s", (UUID(job_id),)
        )
    monkeypatch.setattr(
        system.apps["knowledge"].storage,
        "publish_generation",
        lambda *args: (_ for _ in ()).throw(RuntimeError("index failed")),
    )
    system.worker.run_once()
    job = client.get("/api/v1/index/jobs/" + job_id, headers=system.headers).json()
    assert job["status"] == "FAILED"
    assert job["generation_after"] is None
    assert job["error_code"] == "DOCUMENT_PROCESSING_FAILED"


def test_legacy_migration_is_read_only_idempotent_and_preserves_history(
    system, tmp_path
):
    import hashlib
    import importlib.util

    from psycopg.rows import dict_row

    spec = importlib.util.spec_from_file_location(
        "migration", ROOT / "tools/migrate_legacy_services.py"
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    uid, oid, wid, did, vid, cid, mid = [uuid4() for _ in range(7)]
    content = b"Legacy policy content."
    (tmp_path / "legacy.txt").write_bytes(content)
    checksum = hashlib.sha256(content).hexdigest()
    with psycopg.connect(**system.info) as conn:
        assert system.info["dbname"].endswith("_test")
        conn.execute("DROP SCHEMA IF EXISTS identity,content,rag,chat,ops CASCADE")
        conn.execute(
            (ROOT / "backend/database/schema/0001_initial.sql").read_text(
                encoding="utf-8"
            )
        )
        conn.execute(
            "INSERT INTO identity.users(id,email,display_name,status) VALUES(%s,'legacy@test.local','Legacy','ACTIVE')",
            (uid,),
        )
        conn.execute(
            "INSERT INTO identity.auth_identities(id,user_id,provider,provider_subject,password_hash) VALUES(%s,%s,'LOCAL','legacy@test.local',%s)",
            (
                uuid4(),
                uid,
                system.apps["identity"].hash_password("legacy-password-1234"),
            ),
        )
        conn.execute(
            "INSERT INTO identity.organizations(id,name,slug,status) VALUES(%s,'Legacy','legacy','ACTIVE')",
            (oid,),
        )
        conn.execute(
            "INSERT INTO identity.workspaces(id,organization_id,name,slug,status) VALUES(%s,%s,'Legacy','legacy','ACTIVE')",
            (wid, oid),
        )
        conn.execute(
            "INSERT INTO identity.organization_members(organization_id,user_id,role,status) VALUES(%s,%s,'OWNER','ACTIVE')",
            (oid, uid),
        )
        conn.execute(
            "INSERT INTO identity.workspace_members(workspace_id,user_id,role) VALUES(%s,%s,'ADMIN')",
            (wid, uid),
        )
        conn.execute(
            "INSERT INTO content.documents(id,workspace_id,created_by_user_id,title) VALUES(%s,%s,%s,'Legacy policy')",
            (did, wid, uid),
        )
        conn.execute(
            """INSERT INTO content.document_versions(id,document_id,version_no,original_filename,normalized_filename,media_type,
            file_extension,size_bytes,checksum_sha256,created_by_user_id) VALUES(%s,%s,1,'legacy.txt','legacy.txt','text/plain','.txt',%s,%s,%s)""",
            (vid, did, len(content), checksum, uid),
        )
        conn.execute(
            "UPDATE content.documents SET current_version_id=%s WHERE id=%s", (vid, did)
        )
        conn.execute(
            "INSERT INTO chat.conversations(id,workspace_id,created_by_user_id,title,status) VALUES(%s,%s,%s,'Legacy question','ACTIVE')",
            (cid, wid, uid),
        )
        conn.execute(
            "INSERT INTO chat.messages(id,conversation_id,role,content,status) VALUES(%s,%s,'ASSISTANT','Legacy answer','COMPLETED')",
            (mid, cid),
        )
        conn.execute(
            "INSERT INTO chat.message_citations(id,message_id,citation_rank,filename_snapshot,document_id) VALUES(%s,%s,1,'legacy.txt',%s)",
            (uuid4(), mid, did),
        )
    for apply in (False, True, True):
        with (
            psycopg.connect(**system.info, row_factory=dict_row) as source,
            psycopg.connect(**system.info, row_factory=dict_row) as target,
        ):
            counts = migration.run(source, target, tmp_path, {}, apply)
            assert counts["documents"] == 1 and counts["conversations"] == 1
    with psycopg.connect(**system.info) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM ms_knowledge.documents WHERE id=%s", (did,)
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM ms_knowledge.jobs WHERE document_id=%s", (did,)
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT citations FROM ms_conversation.messages WHERE id=%s", (mid,)
            ).fetchone()[0][0]["source"]
            == "legacy.txt"
        )
        assert (
            conn.execute(
                "SELECT title FROM content.documents WHERE id=%s", (did,)
            ).fetchone()[0]
            == "Legacy policy"
        )

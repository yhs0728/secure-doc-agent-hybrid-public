"""Regression checks for the seven review findings; no production dependencies."""

import importlib.util
import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("service", ["identity", "knowledge", "conversation"])
def test_uncaught_errors_are_counted_and_keep_request_id(service, caplog):
    module = __import__(service + "_service.platform", fromlist=["create_app"])
    app = module.create_app(None)

    @app.get("/synthetic-failure")
    def fail():
        raise RuntimeError("synthetic-regression-error")

    request_id = "00000000-0000-4000-8000-000000000099"
    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.INFO):
        response = client.get(
            "/synthetic-failure", headers={"X-Request-ID": request_id}
        )
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == request_id
    assert response.json()["error"]["request_id"] == request_id
    assert 'status="500"} 1' in client.get("/metrics").text
    assert any(
        "status=500" in r.message and request_id in r.message for r in caplog.records
    )


def test_long_csv_text_is_supported():
    from knowledge_service.parsing import parse_and_split

    chunks, pages = parse_and_split(b'text\n"' + b"x" * 150000 + b'"\n', ".csv")
    assert len(chunks) > 300
    assert pages == 1


def test_csv_cell_limit_has_a_permanent_error():
    from knowledge_service.parsing import CSV_FIELD_LIMIT, parse_and_split

    with pytest.raises(ValueError, match="^CSV_FIELD_LIMIT_EXCEEDED$"):
        parse_and_split(b"x" * (CSV_FIELD_LIMIT + 1), ".csv")


def test_chunk_limit_is_enforced(monkeypatch):
    from knowledge_service.parsing import parse_and_split

    monkeypatch.setenv("MAX_DOCUMENT_CHUNKS", "2")
    with pytest.raises(ValueError, match="DOCUMENT_CHUNK_LIMIT_EXCEEDED"):
        parse_and_split(b"x" * 1500, ".txt")


def test_docx_expansion_is_checked_before_loading(monkeypatch):
    import io
    import zipfile

    from knowledge_service.parsing import parse_and_split

    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as archive:
        for i in range(10001):
            archive.writestr(str(i), b"")
    with pytest.raises(ValueError, match="DOCX_EXPANSION_LIMIT_EXCEEDED"):
        parse_and_split(content.getvalue(), ".docx")


def test_history_respects_search_limit_and_keeps_current_question(monkeypatch):
    from conversation_service.history import with_history
    from knowledge_service.app import SearchRequest

    monkeypatch.setenv("LLM_HISTORY_MAX_CHARACTERS", "999999")
    rows = [{"role": "ASSISTANT", "content": "recent " * 3000}]
    question = "q" * 1000
    result = with_history(question, rows)
    SearchRequest(query=result)
    assert len(result) < 10000
    assert result.endswith(question)
    assert "recent" in result


def test_history_can_be_disabled(monkeypatch):
    from conversation_service.history import with_history

    monkeypatch.setenv("LLM_HISTORY_MAX_CHARACTERS", "0")
    assert with_history("current", [{"role": "USER", "content": "old"}]) == "current"


class RoleConnection:
    def __init__(self, existing=None, database="review_test"):
        self.existing = existing or {}
        self.database = database
        self.writes = []

    def execute(self, statement, parameters=None):
        if isinstance(statement, str) and "current_database()" in statement:
            self.result = (self.database,)
        elif isinstance(statement, str) and "pg_roles" in statement:
            role = parameters[0]
            self.result = (self.existing[role],) if role in self.existing else None
        else:
            self.result = None
            if not isinstance(statement, str) or "advisory" not in statement:
                self.writes.append(statement)
        return self

    def fetchone(self):
        return self.result


def test_test_provisioning_rejects_existing_application_roles_without_writes():
    from bootstrap import provision_test_database

    conn = RoleConnection(existing={"svc_conversation": None})
    with pytest.raises(RuntimeError, match="separate test PostgreSQL"):
        provision_test_database(conn, {})
    assert not conn.writes


def test_test_provisioning_rejects_other_test_database_roles():
    from bootstrap import provision_test_database

    conn = RoleConnection(existing={"svc_identity": "secure-doc-tests:another_test"})
    with pytest.raises(RuntimeError, match="separate test PostgreSQL"):
        provision_test_database(conn, {})
    assert not conn.writes


def test_test_provisioning_only_reuses_owned_roles(monkeypatch):
    import bootstrap

    conn = RoleConnection(existing={"svc_identity": "secure-doc-tests:review_test"})
    calls = []
    monkeypatch.setattr(bootstrap, "provision", lambda *args: calls.append(args))
    bootstrap.provision_test_database(conn, {})
    assert len(calls) == 1
    assert len(conn.writes) == 3  # Ownership comments.


@pytest.mark.parametrize(
    "tokens,forwarded,validation,files",
    [
        (
            ["--profile", "monitoring", "config", "--quiet"],
            ["--profile", "monitoring", "config", "--quiet"],
            False,
            [],
        ),
        (
            ["--validation", "--profile", "monitoring", "up", "-d"],
            ["--profile", "monitoring", "up", "-d"],
            True,
            [],
        ),
        (
            ["-f", "extra.yaml", "--profile", "monitoring", "ps"],
            ["--profile", "monitoring", "ps"],
            False,
            ["extra.yaml"],
        ),
        (
            ["--", "--profile", "monitoring", "ps"],
            ["--profile", "monitoring", "ps"],
            False,
            [],
        ),
        (
            ["up", "--scale", "knowledge-worker=2"],
            ["up", "--scale", "knowledge-worker=2"],
            False,
            [],
        ),
    ],
)
def test_compose_forwards_options_in_order(
    tmp_path, monkeypatch, tokens, forwarded, validation, files
):
    path = ROOT / "tools/compose.py"
    spec = importlib.util.spec_from_file_location("review_compose", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / ".env.microservices").touch()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["compose.py", *tokens])
    calls = []

    def command(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return ["docker", "compose", *arguments]

    monkeypatch.setattr(module, "compose_command", command)
    monkeypatch.setattr(module.subprocess, "call", lambda args: 0)
    assert module.main() == 0
    assert calls == [(forwarded, {"validation": validation, "extra_files": files})]


def test_failure_gauge_clears_after_successful_retry(system, monkeypatch):
    knowledge = system.apps["knowledge"]
    monkeypatch.setenv("MAX_EXTRACTED_CHARACTERS", "5")
    client = system.clients["knowledge"]
    response = client.post(
        "/api/v1/documents/ingest",
        headers=system.headers,
        json={
            "document_id": "review-failure-recovery",
            "title": "Review",
            "content": "long enough to fail",
        },
    )
    assert response.status_code == 201
    did = response.json()["document_id"]
    assert system.worker.run_once()
    assert "secure_doc_knowledge_unresolved_jobs 1\n" in knowledge.queue_metrics()
    monkeypatch.setenv("MAX_EXTRACTED_CHARACTERS", "1000")
    assert (
        client.post(
            f"/api/v1/documents/{did}/retry", headers=system.headers
        ).status_code
        == 202
    )
    assert system.worker.run_once()
    metrics = knowledge.queue_metrics()
    assert "secure_doc_knowledge_unresolved_jobs 0\n" in metrics
    assert 'secure_doc_knowledge_jobs{status="FAILED"} 1\n' in metrics

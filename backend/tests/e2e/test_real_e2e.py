"""Opt-in tests for the real MiniLM -> FAISS -> Ollama pipeline.

Run with: RUN_REAL_E2E=1 python -m pytest tests/e2e/test_real_e2e.py -v -s
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import dependencies as dependencies_module
from app import main as main_module
from app.dependencies import get_index_service, get_rag_graph
from app.main import app
from app.runtime import build_application_graph
from config.settings import Settings, get_settings

pytestmark = [
    pytest.mark.real_e2e,
    pytest.mark.skipif(
        os.getenv("RUN_REAL_E2E") != "1",
        reason="set RUN_REAL_E2E=1 to use the real embedding model and Ollama",
    ),
]

ROOT = Path(__file__).resolve().parents[2]
AUTH = {"Authorization": "Bearer real-e2e-key"}


def real_settings(tmp_path: Path, **changes: object) -> Settings:
    configured = Settings()
    values: dict[str, object] = configured.model_dump()
    values.update({
        "source_directory": str(tmp_path / "source"),
        "index_directory": str(tmp_path / "index"),
        "api_access_key": "real-e2e-key",
        # Real-model tests must never inherit persistent backends from the
        # developer's .env. Each case owns an isolated temporary directory.
        "database_enabled": False,
        "database_url": None,
        "object_storage_backend": "LOCAL",
        "search_backend": "FAISS",
        "llm_model": "qwen3:4b-instruct",
        "llm_base_url": "http://localhost:11434/v1",
        "llm_api_key": "ollama",
        "llm_timeout_seconds": 120.0,
        "retrieval_k": 3,
    })
    values.update(changes)
    return Settings.model_validate(values)


def configure_app(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> TestClient:
    Path(settings.source_directory).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(dependencies_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    app.dependency_overrides[get_settings] = lambda: settings
    get_rag_graph.cache_clear()
    get_index_service.cache_clear()
    return TestClient(app)


def ask(client: TestClient, question: str):
    return client.post(
        "/api/v1/questions",
        headers=AUTH,
        json={"question": question},
    )


def upload(client: TestClient, name: str, content: bytes) -> None:
    response = client.post(
        "/api/v1/documents/upload",
        headers=AUTH,
        files={"file": (name, content)},
    )
    assert response.status_code == 201, response.text


def test_real_txt_pdf_docx_delete_and_restart(tmp_path: Path, monkeypatch) -> None:
    settings = real_settings(tmp_path)
    client = configure_app(monkeypatch, settings)
    try:
        # 1. TXT upload -> real MiniLM -> FAISS -> qwen3:4b-instruct.
        upload(client, "emergency-code.txt", "비상 승인 코드는 ORBIT-7319입니다.".encode())
        response = ask(client, "비상 승인 코드는 무엇인가요?")
        assert response.status_code == 200, response.text
        assert "emergency-code.txt" in response.json()["citations"]
        assert "ORBIT-7319" in response.json()["answer"]
        print("scenario 1/8: TXT passed")

        # 2. Real PDF upload and query.
        upload(client, "backup-policy.pdf", (ROOT / "backup-policy.pdf").read_bytes())
        response = ask(client, "데이터베이스 백업은 몇 시에 실행되나요?")
        assert response.status_code == 200, response.text
        assert "backup-policy.pdf" in response.json()["citations"]
        print("scenario 2/8: PDF passed")

        # 3. Real DOCX upload and query.
        upload(client, "account-lock-policy.docx", (ROOT / "account-lock-policy.docx").read_bytes())
        response = ask(client, "계정은 몇 분 동안 잠기나요?")
        assert response.status_code == 200, response.text
        assert "account-lock-policy.docx" in response.json()["citations"]
        print("scenario 3/8: DOCX passed")

        # 4. An unsupported question must not cite an unrelated document.
        response = ask(client, "사내 카페의 오늘 디저트는 무엇인가요?")
        assert response.status_code == 200, response.text
        assert response.json()["citations"] == []
        assert response.json()["requires_human_review"] is True
        print("scenario 4/8: unsupported question passed")

        # 5. Deleting the source also removes it from subsequent retrieval.
        response = client.delete("/api/v1/documents/emergency-code", headers=AUTH)
        assert response.status_code == 200, response.text
        response = ask(client, "비상 승인 코드는 무엇인가요?")
        assert response.status_code == 200, response.text
        assert "emergency-code.txt" not in response.json()["citations"]
        assert response.json()["requires_human_review"] is True
        print("scenario 5/8: delete passed")

        # 6. Simulate a process restart. An unchanged snapshot must be loaded,
        # not rewritten/re-embedded.
        snapshot = Path(settings.index_directory) / "current" / "index.faiss"
        modified_before_restart = snapshot.stat().st_mtime_ns
        get_rag_graph.cache_clear()
        get_index_service.cache_clear()
        response = ask(client, "데이터베이스 백업은 몇 시에 실행되나요?")
        assert response.status_code == 200, response.text
        assert "backup-policy.pdf" in response.json()["citations"]
        assert snapshot.stat().st_mtime_ns == modified_before_restart
        print("scenario 6/8: restart passed")
    finally:
        app.dependency_overrides.clear()
        get_rag_graph.cache_clear()
        get_index_service.cache_clear()


@pytest.mark.parametrize(
    ("base_url", "timeout", "expected_status", "expected_code"),
    [
        ("http://127.0.0.1:1/v1", 1.0, 503, "LLM_UNAVAILABLE"),
        ("http://localhost:11434/v1", 0.000001, 504, "LLM_TIMEOUT"),
    ],
    ids=["ollama-stopped", "llm-timeout"],
)
def test_real_llm_failure_contracts(
    tmp_path: Path,
    monkeypatch,
    base_url: str,
    timeout: float,
    expected_status: int,
    expected_code: str,
) -> None:
    settings = real_settings(tmp_path, llm_base_url=base_url, llm_timeout_seconds=timeout)
    client = configure_app(monkeypatch, settings)
    try:
        upload(client, "policy.txt", "비밀번호 변경 주기는 90일입니다.".encode())
        graph = build_application_graph(settings)
        app.dependency_overrides[get_rag_graph] = lambda: graph

        response = ask(client, "비밀번호 변경 주기는?")

        assert response.status_code == expected_status, response.text
        assert response.json()["error"]["code"] == expected_code
        assert response.json()["error"]["request_id"]
    finally:
        app.dependency_overrides.clear()
        get_rag_graph.cache_clear()
        get_index_service.cache_clear()

from uuid import UUID

from fastapi.testclient import TestClient

from app.dependencies import get_rag_graph
from app.main import QuestionRequest, app, ask_question
from config.settings import Settings, get_settings


class FakeRAGGraph:
    def invoke(
        self,
        inputs: dict[str, str],
    ) -> dict[str, object]:
        assert inputs["question"] == (
            "비밀번호 변경 주기는?"
        )

        return {
            "answer": (
                "사용자는 비밀번호를 "
                "90일마다 변경해야 합니다."
            ),
            "citations": [
                "security-policy.txt",
            ],
            "requires_human_review": False,
        }


def override_get_rag_graph() -> FakeRAGGraph:
    return FakeRAGGraph()


def override_get_settings() -> Settings:
    return Settings(
        llm_model="test-model",
        llm_api_key="test-llm-key",
        api_access_key="test-service-api-key",
        database_enabled=False,
    )


app.dependency_overrides[get_rag_graph] = (
    override_get_rag_graph
)
app.dependency_overrides[get_settings] = (
    override_get_settings
)

client = TestClient(app)
AUTH_HEADERS = {
    "Authorization": "Bearer test-service-api-key",
}


def test_health_check() -> None:
    response = client.get(
        "/api/v1/health"
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
    }


def test_readiness_check_without_external_dependencies() -> None:
    response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"application": "ready"},
    }


def test_get_documents() -> None:
    response = client.get(
        "/api/v1/documents", headers=AUTH_HEADERS
    )

    assert response.status_code == 200

    response_data = response.json()

    assert len(response_data) == 3
    assert (
        response_data[0]["document_id"]
        == "doc-001"
    )


def test_get_documents_filters_by_keyword() -> None:
    response = client.get(
        "/api/v1/documents",
        headers=AUTH_HEADERS,
        params={
            "keyword": "보안",
        },
    )

    assert response.status_code == 200

    response_data = response.json()

    assert len(response_data) == 1
    assert (
        response_data[0]["document_id"]
        == "doc-003"
    )


def test_get_document_by_id() -> None:
    response = client.get(
        "/api/v1/documents/doc-001",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    assert (
        response.json()["document_id"]
        == "doc-001"
    )
    assert response.json()["title"] == (
        "문서 관리 규정"
    )


def test_get_document_by_id_returns_404() -> None:
    response = client.get(
        "/api/v1/documents/doc-999",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 404
    payload = response.json()
    assert payload["error"]["code"] == "NOT_FOUND"
    assert payload["error"]["message"] == "문서를 찾을 수 없습니다."
    assert payload["error"]["request_id"]
    assert response.headers["X-Request-ID"] == payload["error"]["request_id"]


def test_ask_question() -> None:
    response = client.post(
        "/api/v1/questions",
        headers=AUTH_HEADERS,
        json={
            "question": "비밀번호 변경 주기는?",
        },
    )

    assert response.status_code == 200

    assert response.json() == {
        "answer": (
            "사용자는 비밀번호를 "
            "90일마다 변경해야 합니다."
        ),
        "citations": [
            "security-policy.txt",
        ],
        "requires_human_review": False,
        "conversation_id": None,
    }


def test_ask_question_rejects_blank_question() -> None:
    response = client.post(
        "/api/v1/questions",
        headers=AUTH_HEADERS,
        json={
            "question": "  ",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_follow_up_question_uses_history_and_reuses_conversation(monkeypatch) -> None:
    conversation_id = UUID("00000000-0000-7000-8000-000000000123")
    captured: dict[str, object] = {}

    class CapturingGraph:
        def invoke(self, inputs):
            captured["graph_question"] = inputs["question"]
            return {
                "answer": "90일마다 변경합니다.",
                "citations": ["security-policy.txt"],
                "requires_human_review": False,
            }

    from services import postgres_persistence_service

    monkeypatch.setattr(
        postgres_persistence_service,
        "get_conversation_history",
        lambda settings, value: [
            ("USER", "비밀번호 변경 주기는?"),
            ("ASSISTANT", "90일입니다."),
        ],
    )

    def record(settings, question, result, value):
        captured["stored_question"] = question
        captured["stored_conversation_id"] = value
        return value

    monkeypatch.setattr(
        postgres_persistence_service,
        "record_question_exchange",
        record,
    )
    settings = override_get_settings().model_copy(
        update={
            "database_enabled": True,
            "database_url": "postgresql+psycopg://test:test@localhost/test",
        }
    )

    response = ask_question(
        QuestionRequest(question="그건 언제 바꿔야 해?", conversation_id=conversation_id),
        CapturingGraph(),
        settings,
    )

    assert "비밀번호 변경 주기는?" in str(captured["graph_question"])
    assert "그건 언제 바꿔야 해?" in str(captured["graph_question"])
    assert captured["stored_question"] == "그건 언제 바꿔야 해?"
    assert captured["stored_conversation_id"] == conversation_id
    assert response.conversation_id == conversation_id


def test_saved_conversations_can_be_listed_and_reopened(monkeypatch) -> None:
    conversation_id = "00000000-0000-7000-8000-000000000123"
    from services import postgres_persistence_service

    monkeypatch.setattr(
        postgres_persistence_service,
        "list_user_conversations",
        lambda settings: [{
            "conversation_id": conversation_id,
            "title": "비밀번호 변경 주기는?",
            "updated_at": "2026-10-16T10:00:00Z",
        }],
    )
    monkeypatch.setattr(
        postgres_persistence_service,
        "get_user_conversation",
        lambda settings, value: {
            "conversation_id": value,
            "title": "비밀번호 변경 주기는?",
            "updated_at": "2026-10-16T10:00:00Z",
            "messages": [
                {
                    "message_id": "00000000-0000-7000-8000-000000000124",
                    "role": "USER",
                    "content": "비밀번호 변경 주기는?",
                    "citations": [],
                    "requires_human_review": False,
                    "created_at": "2026-10-16T09:59:00Z",
                },
                {
                    "message_id": "00000000-0000-7000-8000-000000000125",
                    "role": "ASSISTANT",
                    "content": "90일입니다.",
                    "citations": ["security-policy.txt"],
                    "requires_human_review": False,
                    "created_at": "2026-10-16T10:00:00Z",
                },
            ],
        },
    )
    database_settings = override_get_settings().model_copy(
        update={
            "database_enabled": True,
            "database_url": "postgresql+psycopg://test:test@localhost/test",
        }
    )
    app.dependency_overrides[get_settings] = lambda: database_settings
    try:
        listed = client.get("/api/v1/conversations", headers=AUTH_HEADERS)
        detail = client.get(
            f"/api/v1/conversations/{conversation_id}",
            headers=AUTH_HEADERS,
        )
    finally:
        app.dependency_overrides[get_settings] = override_get_settings

    assert listed.status_code == 200
    assert listed.json()[0]["title"] == "비밀번호 변경 주기는?"
    assert detail.status_code == 200
    assert [message["role"] for message in detail.json()["messages"]] == [
        "USER",
        "ASSISTANT",
    ]
    assert detail.json()["messages"][1]["citations"] == ["security-policy.txt"]


def test_error_response_preserves_client_request_id() -> None:
    response = client.get(
        "/api/v1/documents/doc-999",
        headers={
            **AUTH_HEADERS,
            "X-Request-ID": "client-request-123",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["request_id"] == "client-request-123"
    assert response.headers["X-Request-ID"] == "client-request-123"


def test_question_timeout_has_stable_error_contract() -> None:
    class TimeoutGraph:
        def invoke(self, inputs):
            raise TimeoutError("slow")

    app.dependency_overrides[get_rag_graph] = lambda: TimeoutGraph()
    try:
        response = client.post(
            "/api/v1/questions",
            headers=AUTH_HEADERS,
            json={"question": "비밀번호 변경 주기는?"},
        )
    finally:
        app.dependency_overrides[get_rag_graph] = override_get_rag_graph

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "LLM_TIMEOUT"


def test_question_connection_failure_has_stable_error_contract() -> None:
    class OfflineGraph:
        def invoke(self, inputs):
            raise ConnectionError("offline")

    app.dependency_overrides[get_rag_graph] = lambda: OfflineGraph()
    try:
        response = client.post(
            "/api/v1/questions",
            headers=AUTH_HEADERS,
            json={"question": "비밀번호 변경 주기는?"},
        )
    finally:
        app.dependency_overrides[get_rag_graph] = override_get_rag_graph

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLM_UNAVAILABLE"

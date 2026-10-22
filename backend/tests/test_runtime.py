import pytest
from pydantic import ValidationError

from app import runtime as runtime_module
from config.settings import Settings


def create_test_settings(
    retrieval_k: int = 3,
) -> Settings:
    return Settings(
        llm_model="test-model",
        llm_api_key="test-api-key",
        api_access_key="test-service-api-key",
        llm_base_url="http://localhost:8000/v1",
        embedding_model="test-embedding-model",
        embedding_device="cpu",
        source_directory="data/source",
        chunk_size=500,
        chunk_overlap=50,
        retrieval_k=retrieval_k,
    )


def test_build_application_graph(
    monkeypatch,
) -> None:
    fake_vector_store = object()
    fake_retriever = object()
    fake_model = object()
    fake_graph = object()

    received_arguments: dict[str, object] = {}

    def fake_update_persisted_index(settings):
        received_arguments["index_settings"] = settings
        return type("Result", (), {"vector_store": fake_vector_store})()

    def fake_create_retriever(vector_store, k: int):
        received_arguments["vector_store"] = vector_store
        received_arguments["retrieval_k"] = k
        return fake_retriever

    def fake_create_chat_model(settings):
        received_arguments["settings"] = settings
        return fake_model

    def fake_build_rag_workflow(
        retriever,
        model,
    ):
        received_arguments["retriever"] = retriever
        received_arguments["model"] = model
        return fake_graph

    monkeypatch.setattr(
        runtime_module,
        "update_persisted_index",
        fake_update_persisted_index,
    )
    monkeypatch.setattr(
        runtime_module,
        "create_retriever",
        fake_create_retriever,
    )
    monkeypatch.setattr(
        runtime_module,
        "create_chat_model",
        fake_create_chat_model,
    )
    monkeypatch.setattr(
        runtime_module,
        "build_rag_workflow",
        fake_build_rag_workflow,
    )

    settings = create_test_settings()

    graph = runtime_module.build_application_graph(
        settings=settings,
    )

    assert graph is fake_graph

    assert received_arguments["index_settings"] is settings
    assert received_arguments["vector_store"] is fake_vector_store
    assert received_arguments["retrieval_k"] == 3
    assert received_arguments["retriever"] is (
        fake_retriever
    )
    assert received_arguments["model"] is fake_model


def test_settings_rejects_invalid_retrieval_k() -> None:
    with pytest.raises(ValidationError):
        create_test_settings(
            retrieval_k=0,
        )


def test_settings_rejects_external_storage_without_database() -> None:
    with pytest.raises(ValidationError, match="DATABASE_ENABLED"):
        Settings(
            llm_model="test-model",
            llm_api_key="test-api-key",
            api_access_key="test-service-api-key",
            database_enabled=False,
            object_storage_backend="MINIO",
            object_storage_endpoint_url="http://localhost:9000",
            object_storage_access_key="access",
            object_storage_secret_key="secret",
        )


def test_settings_rejects_opensearch_without_database() -> None:
    with pytest.raises(ValidationError, match="DATABASE_ENABLED"):
        Settings(
            llm_model="test-model",
            llm_api_key="test-api-key",
            api_access_key="test-service-api-key",
            database_enabled=False,
            search_backend="OPENSEARCH",
        )


def production_settings(**changes) -> dict:
    values = {
        "app_environment": "production",
        "llm_model": "production-model",
        "llm_api_key": "production-llm-key",
        "api_access_key": "a" * 32,
        "auth_jwt_secret": "j" * 32,
        "allow_legacy_api_key": False,
        "database_enabled": True,
        "database_url": "postgresql+psycopg://app:secret@db/app",
        "object_storage_backend": "S3",
        "object_storage_access_key": "storage-user",
        "object_storage_secret_key": "storage-secret",
        "object_storage_secure": True,
        "search_backend": "OPENSEARCH",
        "opensearch_url": "https://search.example.test:9200",
        "opensearch_username": "secure-doc-service",
        "opensearch_password": "o" * 16,
        "opensearch_verify_certs": True,
    }
    values.update(changes)
    return values


def test_settings_accepts_hardened_production_configuration() -> None:
    settings = Settings(**production_settings())

    assert settings.app_environment == "production"


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"allow_legacy_api_key": True}, "ALLOW_LEGACY_API_KEY"),
        ({"auth_jwt_secret": "short"}, "AUTH_JWT_SECRET"),
        ({"object_storage_secure": False}, "OBJECT_STORAGE_SECURE"),
        ({"opensearch_url": "http://search:9200"}, "HTTPS"),
        ({"opensearch_verify_certs": False}, "OPENSEARCH_VERIFY_CERTS"),
    ],
)
def test_settings_rejects_insecure_production_configuration(changes, message) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(**production_settings(**changes))


def test_settings_rejects_missing_opensearch_ca_file(tmp_path) -> None:
    with pytest.raises(ValidationError, match="OPENSEARCH_CA_CERTS"):
        Settings(
            llm_model="test-model",
            llm_api_key="test-key",
            api_access_key="test-api-key",
            opensearch_ca_certs=str(tmp_path / "missing.pem"),
        )

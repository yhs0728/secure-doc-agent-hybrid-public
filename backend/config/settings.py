from functools import lru_cache
from pathlib import Path
from uuid import UUID

from pydantic import (
    AliasChoices,
    Field,
    SecretStr,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    llm_model: str
    llm_api_key: SecretStr
    app_environment: str = "development"
    api_access_key: SecretStr = Field(
        validation_alias=AliasChoices(
            "API_ACCESS_KEY",
            "API_KEY",
        )
    )
    auth_jwt_secret: SecretStr | None = None
    auth_jwt_issuer: str = "secure-doc-agent"
    auth_jwt_audience: str = "secure-doc-agent-api"
    auth_access_token_minutes: int = Field(default=30, ge=5, le=1440)
    allow_legacy_api_key: bool = True
    log_level: str = "INFO"
    llm_base_url: str | None = None
    llm_thinking: bool = False

    llm_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
    )

    llm_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
    )

    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    embedding_device: str = "cpu"

    source_directory: str = "data/source"
    index_directory: str = "data/index"

    chunk_size: int = Field(
        default=500,
        gt=0,
    )
    chunk_overlap: int = Field(
        default=50,
        ge=0,
    )
    retrieval_k: int = Field(
        default=3,
        ge=1,
    )

    database_enabled: bool = False
    database_url: SecretStr | None = None
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=100)
    database_pool_timeout_seconds: float = Field(default=10.0, gt=0)
    database_statement_timeout_ms: int = Field(default=30_000, ge=1_000)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60)
    database_pool_use_lifo: bool = True
    default_organization_id: UUID = UUID("00000000-0000-7000-8000-000000000002")
    default_workspace_id: UUID = UUID("00000000-0000-7000-8000-000000000003")
    system_user_id: UUID = UUID("00000000-0000-7000-8000-000000000001")

    object_storage_backend: str = "LOCAL"
    object_storage_endpoint_url: str | None = None
    object_storage_region: str = "us-east-1"
    object_storage_bucket: str = "secure-documents"
    object_storage_access_key: SecretStr | None = None
    object_storage_secret_key: SecretStr | None = None
    object_storage_secure: bool = False

    search_backend: str = "FAISS"
    opensearch_url: str = "http://localhost:9200"
    opensearch_username: str | None = None
    opensearch_password: SecretStr | None = None
    opensearch_verify_certs: bool = False
    opensearch_ca_certs: str | None = None
    opensearch_index_prefix: str = "secure-doc"
    opensearch_number_of_replicas: int = Field(default=0, ge=0, le=10)

    outbox_batch_size: int = Field(default=20, ge=1, le=500)
    outbox_poll_seconds: float = Field(default=2.0, gt=0)
    worker_stale_after_seconds: int = Field(default=300, ge=30)
    llm_max_concurrency: int = Field(default=4, ge=1, le=100)
    llm_queue_timeout_seconds: float = Field(default=5.0, gt=0)

    @model_validator(mode="after")
    def validate_database_configuration(self) -> "Settings":
        self.app_environment = self.app_environment.lower()
        if self.app_environment not in {"development", "test", "production"}:
            raise ValueError("APP_ENVIRONMENT는 development, test, production 중 하나입니다.")
        if self.database_enabled and self.database_url is None:
            raise ValueError("DATABASE_ENABLED=true이면 DATABASE_URL이 필요합니다.")
        self.object_storage_backend = self.object_storage_backend.upper()
        if self.object_storage_backend not in {"LOCAL", "S3", "MINIO"}:
            raise ValueError("OBJECT_STORAGE_BACKEND는 LOCAL, S3, MINIO 중 하나입니다.")
        if self.object_storage_backend in {"S3", "MINIO"}:
            if not self.database_enabled:
                raise ValueError("External Object Storage requires DATABASE_ENABLED=true.")
            if self.object_storage_access_key is None or self.object_storage_secret_key is None:
                raise ValueError("외부 Object Storage에는 access key와 secret key가 필요합니다.")
            if self.object_storage_backend == "MINIO" and not self.object_storage_endpoint_url:
                raise ValueError("MINIO에는 OBJECT_STORAGE_ENDPOINT_URL이 필요합니다.")
        self.search_backend = self.search_backend.upper()
        if self.search_backend not in {"FAISS", "OPENSEARCH"}:
            raise ValueError("SEARCH_BACKEND는 FAISS 또는 OPENSEARCH여야 합니다.")
        if self.search_backend == "OPENSEARCH" and not self.database_enabled:
            raise ValueError("OpenSearch requires DATABASE_ENABLED=true.")
        if self.opensearch_ca_certs and not Path(self.opensearch_ca_certs).is_file():
            raise ValueError("OPENSEARCH_CA_CERTS 파일을 찾을 수 없습니다.")
        if self.app_environment == "production":
            self._validate_production_security()
        return self

    def _validate_production_security(self) -> None:
        weak_values = {
            "change-me",
            "replace-with-secure-api-key",
            "your-api-key",
            "minioadmin",
        }

        def require_secret(name: str, value: SecretStr | None, minimum: int = 32) -> None:
            raw = value.get_secret_value() if value is not None else ""
            if len(raw) < minimum or raw.lower() in weak_values:
                raise ValueError(f"production에서는 {name}에 {minimum}자 이상의 강한 값이 필요합니다.")

        if not self.database_enabled:
            raise ValueError("production에서는 DATABASE_ENABLED=true여야 합니다.")
        if self.object_storage_backend not in {"S3", "MINIO"}:
            raise ValueError("production에서는 외부 Object Storage를 사용해야 합니다.")
        if not self.object_storage_secure:
            raise ValueError("production에서는 OBJECT_STORAGE_SECURE=true여야 합니다.")
        if self.search_backend != "OPENSEARCH":
            raise ValueError("production에서는 SEARCH_BACKEND=OPENSEARCH여야 합니다.")
        if not self.opensearch_url.lower().startswith("https://"):
            raise ValueError("production OpenSearch URL은 HTTPS여야 합니다.")
        if not self.opensearch_verify_certs:
            raise ValueError("production에서는 OPENSEARCH_VERIFY_CERTS=true여야 합니다.")
        if not self.opensearch_username:
            raise ValueError("production에서는 OPENSEARCH_USERNAME이 필요합니다.")
        require_secret("OPENSEARCH_PASSWORD", self.opensearch_password, 16)
        require_secret("API_ACCESS_KEY", self.api_access_key)
        require_secret("AUTH_JWT_SECRET", self.auth_jwt_secret)
        if self.allow_legacy_api_key:
            raise ValueError("production에서는 ALLOW_LEGACY_API_KEY=false여야 합니다.")


@lru_cache
def get_settings() -> Settings:

    return Settings()

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.ids import new_uuid7


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_version_id", "ordinal"),
        CheckConstraint("ordinal >= 0", name="nonnegative_ordinal"),
        CheckConstraint(
            "token_count IS NULL OR token_count >= 0", name="nonnegative_tokens"
        ),
        Index("ix_chunks_version_ordinal", "document_version_id", "ordinal"),
        {"schema": "rag"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("content.document_versions.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(String(500))
    extra_metadata: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class IndexProfile(Base):
    __tablename__ = "index_profiles"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name"),
        CheckConstraint("embedding_dimension > 0", name="positive_embedding_dimension"),
        CheckConstraint("chunk_size > 0", name="positive_chunk_size"),
        CheckConstraint("chunk_overlap >= 0", name="nonnegative_chunk_overlap"),
        CheckConstraint("retrieval_k > 0", name="positive_retrieval_k"),
        CheckConstraint(
            "distance_metric IN ('cosinesimil', 'l2', 'innerproduct')",
            name="valid_distance_metric",
        ),
        Index(
            "ux_index_profiles_workspace_active",
            "workspace_id",
            unique=True,
            postgresql_where=text("active = true"),
        ),
        {"schema": "rag"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(500), nullable=False)
    embedding_model_revision: Mapped[str | None] = mapped_column(String(200))
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding_normalization: Mapped[bool] = mapped_column(
        nullable=False, server_default="true"
    )
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_overlap: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_metric: Mapped[str] = mapped_column(String(30), nullable=False)
    retrieval_k: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="3"
    )
    parser_version: Mapped[str] = mapped_column(String(100), nullable=False)
    search_options: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class SearchIndex(Base):
    __tablename__ = "search_indexes"
    __table_args__ = (
        UniqueConstraint("backend", "physical_index_name"),
        CheckConstraint("backend IN ('FAISS', 'OPENSEARCH')", name="valid_backend"),
        CheckConstraint(
            "status IN ('BUILDING', 'VALIDATING', 'ACTIVE', 'RETIRED', 'FAILED')",
            name="valid_status",
        ),
        {"schema": "rag"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    index_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag.index_profiles.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("identity.workspaces.id", ondelete="CASCADE")
    )
    backend: Mapped[str] = mapped_column(String(20), nullable=False)
    physical_index_name: Mapped[str] = mapped_column(String(255), nullable=False)
    alias_name: Mapped[str | None] = mapped_column(String(255))
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    document_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentIndexState(Base):
    __tablename__ = "document_index_states"
    __table_args__ = (
        UniqueConstraint("document_version_id", "search_index_id"),
        CheckConstraint(
            "status IN ('PENDING', 'INDEXING', 'INDEXED', 'FAILED', 'DELETED')",
            name="valid_status",
        ),
        {"schema": "rag"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("content.document_versions.id", ondelete="CASCADE"), nullable=False
    )
    search_index_id: Mapped[UUID] = mapped_column(
        ForeignKey("rag.search_indexes.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    expected_chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    indexed_chunk_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    source_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        CheckConstraint(
            "job_type IN ("
            "'INGEST_DOCUMENT', 'REINDEX_DOCUMENT', 'DELETE_DOCUMENT', "
            "'REBUILD_INDEX', 'GENERATE_PREVIEW'"
            ")",
            name="valid_job_type",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'RETRY_WAIT', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="valid_status",
        ),
        CheckConstraint("attempt_count >= 0", name="nonnegative_attempts"),
        CheckConstraint("max_attempts >= 1", name="positive_max_attempts"),
        Index(
            "ix_ingestion_jobs_available",
            "priority",
            "available_at",
            "created_at",
            postgresql_where=text("status IN ('PENDING', 'RETRY_WAIT')"),
        ),
        {"schema": "rag"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("content.document_versions.id", ondelete="CASCADE")
    )
    job_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PENDING"
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="3"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(200))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_details: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

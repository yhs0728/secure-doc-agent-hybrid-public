from pathlib import Path
from uuid import RFC_4122, UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

import database.models  # noqa: F401
from config.settings import Settings
from database.base import Base
from database.ids import new_uuid7
from database.repositories.document_repository import PostgresDocumentRepository

EXPECTED_TABLES = {
    "identity.users",
    "identity.auth_identities",
    "identity.organizations",
    "identity.organization_members",
    "identity.workspaces",
    "identity.workspace_members",
    "identity.api_keys",
    "content.documents",
    "content.document_versions",
    "content.storage_objects",
    "content.document_artifacts",
    "rag.document_chunks",
    "rag.index_profiles",
    "rag.search_indexes",
    "rag.document_index_states",
    "rag.ingestion_jobs",
    "chat.conversations",
    "chat.messages",
    "chat.message_citations",
    "chat.message_feedback",
    "ops.outbox_events",
    "ops.idempotency_keys",
    "ops.audit_logs",
    "ops.usage_events",
}


def test_database_metadata_contains_complete_erd() -> None:
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_vector_and_document_bodies_are_not_duplicated_in_postgres() -> None:
    chunk_columns = set(Base.metadata.tables["rag.document_chunks"].columns.keys())
    assert "embedding" not in chunk_columns
    assert "content" not in chunk_columns
    assert {"content_hash", "page_start", "page_end"}.issubset(chunk_columns)


def test_storage_objects_are_workspace_scoped() -> None:
    columns = set(Base.metadata.tables["content.storage_objects"].columns.keys())
    assert "workspace_id" in columns


def test_citations_keep_audit_snapshots() -> None:
    columns = set(Base.metadata.tables["chat.message_citations"].columns.keys())
    assert {
        "filename_snapshot",
        "page_start_snapshot",
        "page_end_snapshot",
        "quote_snapshot",
    }.issubset(columns)


def test_uuid7_generator_sets_version_and_variant() -> None:
    value = new_uuid7()
    assert value.version == 7
    assert value.variant == RFC_4122
    assert (value.int >> 62) & 0b11 == 0b10


def test_database_configuration_requires_url_when_enabled() -> None:
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(
            llm_model="test",
            llm_api_key="test",
            api_access_key="test",
            database_enabled=True,
            database_url=None,
        )


def test_document_repository_query_is_workspace_scoped() -> None:
    repository = object.__new__(PostgresDocumentRepository)
    repository._workspace_id = UUID("00000000-0000-7000-8000-000000000003")
    query = repository._base_query()
    sql = str(
        query.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "content.documents.workspace_id" in sql
    assert "content.documents.deleted_at IS NULL" in sql
    assert "content.document_versions.processing_status = 'READY'" in sql


def test_frozen_baseline_contains_rls_and_all_tables() -> None:
    schema_path = Path("database/schema/0001_initial.sql")
    schema_sql = schema_path.read_text(encoding="utf-8")
    assert "ENABLE ROW LEVEL SECURITY" in schema_sql
    for qualified_name in EXPECTED_TABLES:
        assert f"CREATE TABLE {qualified_name}" in schema_sql

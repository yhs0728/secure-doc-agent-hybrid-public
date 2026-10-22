from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

from langchain_core.documents import Document as LangChainDocument
from langchain_core.embeddings import Embeddings
from opensearchpy import NotFoundError, OpenSearch, helpers
from sqlalchemy import func, select

from config.settings import Settings
from database.models.content import Document, DocumentVersion
from database.models.rag import (
    DocumentChunk,
    DocumentIndexState,
    IndexProfile,
    SearchIndex,
)
from database.session import set_local_user_context, transaction
from ingestion.incremental_indexer import collect_source_files, load_and_split_document


@dataclass(frozen=True)
class OpenSearchIndexingResult:
    added: list[str]
    modified: list[str]
    deleted: list[str]
    unchanged: list[str]
    full_rebuild: bool = True


class OpenSearchRetriever:
    def __init__(
        self,
        client: OpenSearch,
        alias_name: str,
        workspace_id: UUID,
        embeddings: Embeddings,
        k: int,
    ) -> None:
        self._client = client
        self._alias_name = alias_name
        self._workspace_id = workspace_id
        self._embeddings = embeddings
        self._k = k

    def invoke(self, question: str) -> list[LangChainDocument]:
        vector = self._embeddings.embed_query(question)
        response = self._client.search(
            index=self._alias_name,
            body={
                "size": self._k,
                "query": {
                    "knn": {
                        "embedding": {
                            "vector": vector,
                            "k": self._k,
                            "filter": {
                                "term": {"workspace_id": str(self._workspace_id)}
                            },
                        }
                    }
                },
            },
        )
        return [
            LangChainDocument(
                page_content=hit["_source"]["content"],
                metadata=hit["_source"]["metadata"],
            )
            for hit in response["hits"]["hits"]
        ]


def create_opensearch_client(settings: Settings) -> OpenSearch:
    parsed = urlparse(settings.opensearch_url)
    authentication = None
    if settings.opensearch_username and settings.opensearch_password is not None:
        authentication = (
            settings.opensearch_username,
            settings.opensearch_password.get_secret_value(),
        )
    options: dict[str, object] = {}
    if settings.opensearch_ca_certs:
        options["ca_certs"] = settings.opensearch_ca_certs
    return OpenSearch(
        hosts=[
            {
                "host": parsed.hostname or "localhost",
                "port": parsed.port or (443 if parsed.scheme == "https" else 9200),
                "scheme": parsed.scheme or "http",
            }
        ],
        http_auth=authentication,
        verify_certs=settings.opensearch_verify_certs,
        ssl_show_warn=False,
        timeout=30,
        **options,
    )


def alias_name(settings: Settings) -> str:
    return f"{settings.opensearch_index_prefix}-{str(settings.default_workspace_id)[:8]}-current"


def build_opensearch_index(
    settings: Settings,
    embeddings: Embeddings,
    client: OpenSearch | None = None,
) -> OpenSearchIndexingResult:
    search_client = client or create_opensearch_client(settings)
    source_files = collect_source_files(
        Path(settings.source_directory),
        allow_empty=True,
    )
    chunks: list[LangChainDocument] = []
    for file_path in source_files:
        chunks.extend(
            load_and_split_document(
                file_path,
                settings.chunk_size,
                settings.chunk_overlap,
            )
        )
    contents = [chunk.page_content for chunk in chunks]
    vectors = embeddings.embed_documents(contents)
    dimension = (
        len(vectors[0])
        if vectors
        else len(embeddings.embed_query("embedding dimension probe"))
    )
    if dimension < 1:
        raise RuntimeError("OpenSearch embedding dimension을 확인할 수 없습니다.")

    physical_name = (
        f"{settings.opensearch_index_prefix}-{str(settings.default_workspace_id)[:8]}-"
        f"{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
    ).lower()
    current_alias = alias_name(settings)
    search_index_id = _register_build(settings, physical_name, dimension)
    try:
        search_client.indices.create(
            index=physical_name,
            body=_index_mapping(dimension, settings.opensearch_number_of_replicas),
        )
        actions = [
            {
                "_op_type": "index",
                "_index": physical_name,
                "_id": str(chunk.metadata["chunk_id"]),
                "_source": {
                    "workspace_id": str(settings.default_workspace_id),
                    "document_id": str(chunk.metadata["document_id"]),
                    "chunk_id": str(chunk.metadata["chunk_id"]),
                    "source": str(chunk.metadata["source"]),
                    "content": chunk.page_content,
                    "metadata": dict(chunk.metadata),
                    "embedding": vector,
                },
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        if actions:
            helpers.bulk(search_client, actions, raise_on_error=True)
        search_client.indices.refresh(index=physical_name)
        actual_count = int(search_client.count(index=physical_name)["count"])
        if actual_count != len(chunks):
            raise RuntimeError(
                f"OpenSearch 검증 실패: expected={len(chunks)} actual={actual_count}"
            )
        try:
            aliases = search_client.indices.get_alias(
                name=current_alias,
                ignore_unavailable=True,
            )
        except NotFoundError:
            aliases = {}
        alias_actions = [
            {"remove": {"index": name, "alias": current_alias}}
            for name in aliases
        ]
        alias_actions.append(
            {"add": {"index": physical_name, "alias": current_alias}}
        )
        search_client.indices.update_aliases(body={"actions": alias_actions})
        _activate_index(settings, search_index_id, len(source_files), len(chunks))
    except Exception:
        _fail_index(settings, search_index_id)
        if search_client.indices.exists(index=physical_name):
            search_client.indices.delete(index=physical_name)
        raise

    return OpenSearchIndexingResult(
        added=[path.name for path in source_files],
        modified=[],
        deleted=[],
        unchanged=[],
    )


def create_opensearch_retriever(
    settings: Settings,
    embeddings: Embeddings,
    client: OpenSearch | None = None,
) -> OpenSearchRetriever:
    return OpenSearchRetriever(
        client or create_opensearch_client(settings),
        alias_name(settings),
        settings.default_workspace_id,
        embeddings,
        settings.retrieval_k,
    )


def _index_mapping(dimension: int, number_of_replicas: int = 0) -> dict:
    return {
        "settings": {
            "index": {
                "knn": True,
                "number_of_replicas": number_of_replicas,
            }
        },
        "mappings": {
            "properties": {
                "workspace_id": {"type": "keyword"},
                "document_id": {"type": "keyword"},
                "chunk_id": {"type": "keyword"},
                "source": {"type": "keyword"},
                "content": {"type": "text"},
                "metadata": {"type": "object", "enabled": True},
                "embedding": {
                    "type": "knn_vector",
                    "dimension": dimension,
                    "method": {
                        "name": "hnsw",
                        "space_type": "cosinesimil",
                        "engine": "lucene",
                    },
                },
            }
        },
    }


def _config_hash(settings: Settings) -> str:
    value = json.dumps(
        {
            "model": settings.embedding_model,
            "chunk_size": settings.chunk_size,
            "chunk_overlap": settings.chunk_overlap,
            "backend": "OPENSEARCH",
        },
        sort_keys=True,
    )
    return hashlib.sha256(value.encode()).hexdigest()


def _register_build(settings: Settings, physical_name: str, dimension: int) -> UUID:
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        profile = session.scalar(
            select(IndexProfile).where(
                IndexProfile.workspace_id == settings.default_workspace_id,
                IndexProfile.config_hash == _config_hash(settings),
            )
        )
        if profile is None:
            for active in session.scalars(
                select(IndexProfile).where(
                    IndexProfile.workspace_id == settings.default_workspace_id,
                    IndexProfile.active.is_(True),
                )
            ):
                active.active = False
            profile = IndexProfile(
                workspace_id=settings.default_workspace_id,
                name=f"opensearch-{_config_hash(settings)[:12]}",
                embedding_model=settings.embedding_model,
                embedding_dimension=dimension,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
                distance_metric="cosinesimil",
                retrieval_k=settings.retrieval_k,
                parser_version="1",
                config_hash=_config_hash(settings),
                active=True,
                created_by_user_id=settings.system_user_id,
            )
            session.add(profile)
            session.flush()
        index = SearchIndex(
            index_profile_id=profile.id,
            workspace_id=settings.default_workspace_id,
            backend="OPENSEARCH",
            physical_index_name=physical_name,
            alias_name=alias_name(settings),
            status="BUILDING",
        )
        session.add(index)
        session.flush()
        return index.id


def _activate_index(
    settings: Settings,
    index_id: UUID,
    document_count: int,
    chunk_count: int,
) -> None:
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        now = datetime.now(UTC)
        for active in session.scalars(
            select(SearchIndex).where(
                SearchIndex.workspace_id == settings.default_workspace_id,
                SearchIndex.backend == "OPENSEARCH",
                SearchIndex.status == "ACTIVE",
                SearchIndex.id != index_id,
            )
        ):
            active.status = "RETIRED"
            active.retired_at = now
        index = session.get(SearchIndex, index_id)
        if index is None:
            raise LookupError("검색 인덱스 DB 레코드가 없습니다.")
        index.status = "ACTIVE"
        index.document_count = document_count
        index.chunk_count = chunk_count
        index.activated_at = now
        _record_document_states(session, settings, index)


def _record_document_states(session, settings: Settings, index: SearchIndex) -> None:
    versions = session.execute(
        select(DocumentVersion)
        .join(Document, Document.current_version_id == DocumentVersion.id)
        .where(
            Document.workspace_id == settings.default_workspace_id,
            Document.lifecycle_status == "ACTIVE",
            Document.deleted_at.is_(None),
        )
    ).scalars()
    for version in versions:
        chunk_count = int(
            session.scalar(
                select(func.count(DocumentChunk.id)).where(
                    DocumentChunk.document_version_id == version.id
                )
            )
            or 0
        )
        state = DocumentIndexState(
            document_version_id=version.id,
            search_index_id=index.id,
            status="INDEXED",
            expected_chunk_count=chunk_count,
            indexed_chunk_count=chunk_count,
            source_checksum=version.checksum_sha256,
            indexed_at=datetime.now(UTC),
            verified_at=datetime.now(UTC),
        )
        session.add(state)


def _fail_index(settings: Settings, index_id: UUID) -> None:
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        index = session.get(SearchIndex, index_id)
        if index is not None:
            index.status = "FAILED"

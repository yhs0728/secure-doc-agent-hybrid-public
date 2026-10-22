from pathlib import Path

from app.index_lock import index_lock
from config.settings import Settings
from database.locks import workspace_advisory_lock
from graph.workflow import build_rag_workflow
from ingestion.incremental_indexer import build_or_update_index
from rag.model import create_chat_model
from retrieval.embedding_model import (
    create_embedding_model,
)
from retrieval.vector_store import create_retriever


def build_application_graph(
    settings: Settings,
):
    indexing_result = update_persisted_index(settings=settings)
    if settings.search_backend == "OPENSEARCH":
        from integrations.opensearch_index import create_opensearch_retriever

        embeddings = create_embedding_model(
            model_name=settings.embedding_model,
            device=settings.embedding_device,
        )
        retriever = create_opensearch_retriever(settings, embeddings)
    else:
        retriever = create_retriever(
            vector_store=indexing_result.vector_store,
            k=settings.retrieval_k,
        )

    model = create_chat_model(
        settings=settings,
    )

    return build_rag_workflow(
        retriever=retriever,
        model=model,
    )


def update_persisted_index(settings: Settings):
    """Apply source changes without constructing the chat model or graph."""
    embeddings = create_embedding_model(
        model_name=settings.embedding_model,
        device=settings.embedding_device,
    )

    with index_lock:
        if settings.database_enabled:
            with workspace_advisory_lock(
                settings.default_workspace_id,
                "search-index-write",
            ):
                return _update_search_backend(settings, embeddings)
        return _update_search_backend(settings, embeddings)


def _update_search_backend(settings: Settings, embeddings):
    if settings.search_backend == "OPENSEARCH":
        from integrations.opensearch_index import build_opensearch_index

        return build_opensearch_index(settings, embeddings)
    indexing_result = build_or_update_index(
        source_directory=Path(settings.source_directory),
        index_directory=Path(settings.index_directory),
        embeddings=embeddings,
        embedding_model=settings.embedding_model,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )

    return indexing_result

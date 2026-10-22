from functools import lru_cache
from pathlib import Path

from app.runtime import (
    build_application_graph,
)
from config.settings import (
    get_settings,
)
from retrieval.embedding_model import (
    create_embedding_model,
)
from services.index_service import (
    IndexService,
    IndexServiceConfig,
)


@lru_cache
def get_rag_graph():
    return build_application_graph(
        settings=get_settings(),
    )


@lru_cache
def get_index_service() -> IndexService:
    settings = get_settings()

    embeddings = create_embedding_model(
        model_name=settings.embedding_model,
        device=settings.embedding_device,
    )

    config = IndexServiceConfig(
        source_directory=Path(
            settings.source_directory
        ),
        index_directory=Path(
            settings.index_directory
        ),
        embedding_model=(
            settings.embedding_model
        ),
        chunk_size=settings.chunk_size,
        chunk_overlap=(
            settings.chunk_overlap
        ),
    )

    return IndexService(
        embeddings=embeddings,
        config=config,
    )


def invalidate_rag_graph() -> None:
    get_rag_graph.cache_clear()
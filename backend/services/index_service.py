from dataclasses import dataclass
from pathlib import Path

from langchain_core.embeddings import(
    Embeddings,
)

from ingestion.incremental_indexer import(
    IndexingResult,
    build_or_update_index,
)

@dataclass(frozen=True)
class IndexServiceConfig:
    source_directory: Path
    index_directory: Path
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    
class IndexService:
    def __init__(
        self,
        embeddings: Embeddings,
        config: IndexServiceConfig,
    ) -> None:
        self._embeddings = embeddings
        self._config = config

    def update_index(
        self,
    ) -> IndexingResult:
        return build_or_update_index(
            source_directory=(
                self._config
                .source_directory
            ),
            index_directory=(
                self._config
                .index_directory
            ),
            embeddings=self._embeddings,
            embedding_model=(
                self._config
                .embedding_model
            ),
            chunk_size=(
                self._config
                .chunk_size
            ),
            chunk_overlap=(
                self._config
                .chunk_overlap
            ),
        )

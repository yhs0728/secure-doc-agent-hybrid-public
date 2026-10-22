import logging
from dataclasses import dataclass
from pathlib import Path

from langchain_core.embeddings import Embeddings

from ingestion.document_loader import (
    load_source_document,
)
from ingestion.index_change_detector import (
    detect_index_changes,
)
from ingestion.index_manifest import (
    IndexManifestError,
    build_indexed_document,
    load_index_manifest,
    manifest_configuration_matches,
)
from ingestion.text_splitter import (
    split_documents,
)
from models.index_manifest import (
    IndexedDocument,
    IndexManifest,
)
from retrieval.faiss_store import FaissVectorStore
from retrieval.index_repository import (
    IndexSnapshotError,
    VectorIndexNotFoundError,
    load_vector_index,
    save_index_snapshot,
    validate_index_snapshot,
    vector_index_exists,
)
from retrieval.vector_store import (
    add_documents_to_vector_store,
    build_vector_store,
    delete_chunks_from_vector_store,
)

SUPPORTED_EXTENSIONS = {
    ".txt",
    ".pdf",
    ".docx",
    ".csv",
}
logger = logging.getLogger(__name__)


class IncrementalIndexingError(RuntimeError):
    """증분 인덱싱 과정에서 발생한 오류입니다."""


@dataclass(frozen=True)
class IndexingResult:
    vector_store: FaissVectorStore
    added: list[str]
    modified: list[str]
    deleted: list[str]
    unchanged: list[str]
    full_rebuild: bool


def collect_source_files(
    source_directory: Path,
    *,
    allow_empty: bool = False,
) -> list[Path]:
    if not source_directory.exists():
        raise IncrementalIndexingError(
            "원본 문서 디렉터리를 찾을 수 없습니다: "
            f"{source_directory}"
        )

    if not source_directory.is_dir():
        raise IncrementalIndexingError(
            "원본 문서 경로가 디렉터리가 아닙니다: "
            f"{source_directory}"
        )

    source_files = sorted(
        file_path
        for file_path in source_directory.iterdir()
        if (
            file_path.is_file()
            and file_path.suffix.lower()
            in SUPPORTED_EXTENSIONS
        )
    )

    if not source_files and not allow_empty:
        raise IncrementalIndexingError(
            "인덱싱할 지원 문서가 없습니다."
        )

    validate_unique_document_ids(
        source_files=source_files,
    )

    return source_files


def validate_unique_document_ids(
    source_files: list[Path],
) -> None:
    document_ids = [
        file_path.stem
        for file_path in source_files
    ]

    if len(document_ids) != len(
        set(document_ids)
    ):
        raise IncrementalIndexingError(
            "파일 확장자를 제외한 이름이 "
            "중복된 문서가 있습니다."
        )


def load_and_split_document(
    file_path: Path,
    chunk_size: int,
    chunk_overlap: int,
):
    document = load_source_document(
        file_path=file_path,
        document_id=file_path.stem,
        title=file_path.stem,
    )

    return split_documents(
        documents=[
            document,
        ],
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


def create_manifest_entry(
    file_path: Path,
    chunks,
) -> IndexedDocument:
    chunk_ids = [
        chunk.metadata["chunk_id"]
        for chunk in chunks
    ]

    return build_indexed_document(
        file_path=file_path,
        document_id=file_path.stem,
        chunk_ids=chunk_ids,
    )


def build_full_index(
    source_files: list[Path],
    embeddings: Embeddings,
    index_directory: Path,
    embedding_model: str,
    chunk_size: int,
    chunk_overlap: int,
) -> IndexingResult:
    all_chunks = []
    manifest_documents: dict[
        str,
        IndexedDocument,
    ] = {}

    for file_path in source_files:
        chunks = load_and_split_document(
            file_path=file_path,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        all_chunks.extend(chunks)

        manifest_documents[
            file_path.name
        ] = create_manifest_entry(
            file_path=file_path,
            chunks=chunks,
        )

    vector_store = build_vector_store(
        documents=all_chunks,
        embeddings=embeddings,
    )

    manifest = IndexManifest(
        embedding_model=embedding_model,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        documents=manifest_documents,
    )

    save_index_snapshot(
        vector_store=vector_store,
        manifest=manifest,
        index_directory=index_directory,
    )

    return IndexingResult(
        vector_store=vector_store,
        added=[
            file_path.name
            for file_path in source_files
        ],
        modified=[],
        deleted=[],
        unchanged=[],
        full_rebuild=True,
    )


def build_or_update_index(
    source_directory: Path,
    index_directory: Path,
    embeddings: Embeddings,
    embedding_model: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> IndexingResult:
    try:
        existing_manifest = load_index_manifest(
            index_directory=index_directory,
        )
    except IndexManifestError:
        logger.warning(
            "Index manifest is corrupted; a full rebuild will be performed.",
            exc_info=True,
        )
        existing_manifest = None

    has_existing_index = vector_index_exists(
        index_directory=index_directory,
    )
    source_files = collect_source_files(
        source_directory=source_directory,
        allow_empty=(
            existing_manifest is not None
            and has_existing_index
        ),
    )

    requires_full_rebuild = (
        existing_manifest is None
        or not has_existing_index
        or not manifest_configuration_matches(
            manifest=existing_manifest,
            embedding_model=embedding_model,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    )

    if requires_full_rebuild:
        return build_full_index(
            source_files=source_files,
            embeddings=embeddings,
            index_directory=index_directory,
            embedding_model=embedding_model,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    try:
        vector_store = load_vector_index(
            index_directory=index_directory,
            embeddings=embeddings,
        )
        validate_index_snapshot(
            vector_store=vector_store,
            manifest=existing_manifest,
        )
    except (
        EOFError,
        IndexSnapshotError,
        OSError,
        RuntimeError,
        ValueError,
        VectorIndexNotFoundError,
    ):
        logger.warning(
            "Persisted index validation failed; a full rebuild will be performed.",
            exc_info=True,
        )
        return build_full_index(
            source_files=source_files,
            embeddings=embeddings,
            index_directory=index_directory,
            embedding_model=embedding_model,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    changes = detect_index_changes(
        source_directory=source_directory,
        manifest=existing_manifest,
    )

    if not changes.has_changes:
        return IndexingResult(
            vector_store=vector_store,
            added=[],
            modified=[],
            deleted=[],
            unchanged=[path.name for path in changes.unchanged],
            full_rebuild=False,
        )

    updated_documents = dict(
        existing_manifest.documents
    )

    for file_name in changes.deleted:
        indexed_document = (
            updated_documents[file_name]
        )

        delete_chunks_from_vector_store(
            vector_store=vector_store,
            chunk_ids=indexed_document.chunk_ids,
        )

        del updated_documents[file_name]

    for file_path in changes.added + changes.modified:
        file_name = file_path.name

        if file_path in changes.modified:
            previous_document = (
                updated_documents[file_name]
            )

            delete_chunks_from_vector_store(
                vector_store=vector_store,
                chunk_ids=(
                    previous_document.chunk_ids
                ),
            )

        chunks = load_and_split_document(
            file_path=file_path,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

        add_documents_to_vector_store(
            vector_store=vector_store,
            documents=chunks,
        )

        updated_documents[file_name] = (
            create_manifest_entry(
                file_path=file_path,
                chunks=chunks,
            )
        )

    updated_manifest = IndexManifest(
        embedding_model=embedding_model,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        documents=updated_documents,
    )

    save_index_snapshot(
        vector_store=vector_store,
        manifest=updated_manifest,
        index_directory=index_directory,
    )

    return IndexingResult(
        vector_store=vector_store,
        added=[path.name for path in changes.added],
        modified=[path.name for path in changes.modified],
        deleted=changes.deleted,
        unchanged=[path.name for path in changes.unchanged],
        full_rebuild=False,
    )

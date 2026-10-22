import json
import logging
import shutil
from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings

from retrieval.faiss_store import FaissVectorStore

INDEX_FILE_NAME = "index.faiss"
DOCSTORE_FILE_NAME = "index.pkl"
MANIFEST_FILE_NAME = "manifest.json"
CURRENT_DIRECTORY_NAME = "current"
TEMPORARY_DIRECTORY_NAME = "temporary"
BACKUP_DIRECTORY_NAME = "backup"
logger = logging.getLogger(__name__)


class VectorIndexNotFoundError(FileNotFoundError):
    """Raised when a complete persisted FAISS index cannot be found."""


class IndexSnapshotError(RuntimeError):
    """Raised when an index snapshot cannot be validated or committed."""


def resolve_index_directory(index_directory: Path) -> Path:
    """Return the active snapshot, with support for the legacy flat layout."""
    current_directory = index_directory / CURRENT_DIRECTORY_NAME
    if current_directory.is_dir():
        return current_directory
    return index_directory


def vector_index_exists(index_directory: Path) -> bool:
    active_directory = resolve_index_directory(index_directory)
    return (
        (active_directory / INDEX_FILE_NAME).is_file()
        and (active_directory / DOCSTORE_FILE_NAME).is_file()
    )


def save_vector_index(vector_store: FaissVectorStore, index_directory: Path) -> None:
    """Save only FAISS files. Transactional application saves use snapshots."""
    index_directory.mkdir(parents=True, exist_ok=True)
    vector_store.save_local(folder_path=str(index_directory))


def load_vector_index(index_directory: Path, embeddings: Embeddings) -> FaissVectorStore:
    if not vector_index_exists(index_directory=index_directory):
        raise VectorIndexNotFoundError(
            f"저장된 FAISS 인덱스를 찾을 수 없습니다: {index_directory}"
        )

    active_directory = resolve_index_directory(index_directory)
    return FaissVectorStore.load_local(
        folder_path=str(active_directory),
        embeddings=embeddings,
        allow_dangerous_deserialization=True,
    )


def collect_vector_chunk_ids(vector_store: FaissVectorStore) -> set[str]:
    return set(vector_store.index_to_docstore_id.values())


def collect_manifest_chunk_ids(manifest: Any) -> set[str]:
    return {
        chunk_id
        for document in manifest.documents.values()
        for chunk_id in document.chunk_ids
    }


def validate_index_snapshot(vector_store: FaissVectorStore, manifest: Any) -> None:
    if collect_vector_chunk_ids(vector_store) != collect_manifest_chunk_ids(manifest):
        raise IndexSnapshotError(
            "FAISS와 manifest의 chunk_id가 일치하지 않습니다."
        )


def _remove_directory(directory: Path) -> None:
    if directory.exists():
        shutil.rmtree(directory)


def save_index_snapshot(
    vector_store: FaissVectorStore,
    manifest: Any,
    index_directory: Path,
) -> None:
    """Commit FAISS and its manifest as one recoverable directory snapshot."""
    validate_index_snapshot(vector_store=vector_store, manifest=manifest)
    index_directory.mkdir(parents=True, exist_ok=True)

    current_directory = index_directory / CURRENT_DIRECTORY_NAME
    temporary_directory = index_directory / TEMPORARY_DIRECTORY_NAME
    backup_directory = index_directory / BACKUP_DIRECTORY_NAME
    _remove_directory(temporary_directory)
    temporary_directory.mkdir()

    try:
        vector_store.save_local(folder_path=str(temporary_directory))
        (temporary_directory / MANIFEST_FILE_NAME).write_text(
            manifest.model_dump_json(indent=2),
            encoding="utf-8",
        )

        required_files = (INDEX_FILE_NAME, DOCSTORE_FILE_NAME, MANIFEST_FILE_NAME)
        if not all((temporary_directory / name).is_file() for name in required_files):
            raise IndexSnapshotError("임시 인덱스 스냅샷이 완전하지 않습니다.")

        json.loads((temporary_directory / MANIFEST_FILE_NAME).read_text("utf-8"))

        _remove_directory(backup_directory)
        if current_directory.exists():
            current_directory.replace(backup_directory)

        try:
            temporary_directory.replace(current_directory)
        except OSError:
            if backup_directory.exists() and not current_directory.exists():
                backup_directory.replace(current_directory)
            raise
    except Exception as error:
        logger.exception(
            "Failed to commit index snapshot to %s",
            index_directory,
        )
        _remove_directory(temporary_directory)
        if isinstance(error, IndexSnapshotError):
            raise
        raise IndexSnapshotError("인덱스 스냅샷 저장에 실패했습니다.") from error


def restore_previous_snapshot(index_directory: Path) -> bool:
    """Restore the last committed snapshot, returning False when none exists."""
    current_directory = index_directory / CURRENT_DIRECTORY_NAME
    backup_directory = index_directory / BACKUP_DIRECTORY_NAME
    if not backup_directory.is_dir():
        return False

    failed_directory = index_directory / TEMPORARY_DIRECTORY_NAME
    _remove_directory(failed_directory)
    if current_directory.exists():
        current_directory.replace(failed_directory)
    backup_directory.replace(current_directory)
    _remove_directory(failed_directory)
    return True

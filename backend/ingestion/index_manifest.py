import hashlib
from pathlib import Path

from pydantic import ValidationError

from models.index_manifest import (
    IndexedDocument,
    IndexManifest,
)
from retrieval.index_repository import resolve_index_directory

MANIFEST_FILE_NAME = "manifest.json"


class IndexManifestError(RuntimeError):
    """인덱스 manifest 처리 오류입니다."""


def calculate_file_sha256(
    file_path: Path,
) -> str:
    digest = hashlib.sha256()

    try:
        with file_path.open("rb") as file:
            while chunk := file.read(
                1024 * 1024
            ):
                digest.update(chunk)

    except OSError as error:
        raise IndexManifestError(
            "문서 해시를 계산할 수 없습니다: "
            f"{file_path}"
        ) from error

    return digest.hexdigest()


def build_indexed_document(
    file_path: Path,
    document_id: str,
    chunk_ids: list[str],
) -> IndexedDocument:
    try:
        file_stat = file_path.stat()

    except OSError as error:
        raise IndexManifestError(
            "문서 정보를 읽을 수 없습니다: "
            f"{file_path}"
        ) from error

    return IndexedDocument(
        document_id=document_id,
        sha256=calculate_file_sha256(
            file_path=file_path,
        ),
        file_size=file_stat.st_size,
        modified_at_ns=file_stat.st_mtime_ns,
        chunk_ids=chunk_ids,
    )


def save_index_manifest(
    manifest: IndexManifest,
    index_directory: Path,
) -> None:
    index_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    manifest_path = (
        index_directory / MANIFEST_FILE_NAME
    )
    temporary_path = (
        index_directory / "manifest.json.tmp"
    )

    try:
        temporary_path.write_text(
            manifest.model_dump_json(
                indent=2,
            ),
            encoding="utf-8",
        )

        temporary_path.replace(
            manifest_path
        )

    except OSError as error:
        raise IndexManifestError(
            "인덱스 manifest를 "
            "저장할 수 없습니다."
        ) from error


def load_index_manifest(
    index_directory: Path,
) -> IndexManifest | None:
    index_directory = resolve_index_directory(index_directory)
    manifest_path = (
        index_directory / MANIFEST_FILE_NAME
    )

    if not manifest_path.exists():
        return None

    try:
        manifest_text = (
            manifest_path.read_text(
                encoding="utf-8",
            )
        )

        return IndexManifest.model_validate_json(
            manifest_text
        )

    except (
        OSError,
        ValidationError,
        ValueError,
    ) as error:
        raise IndexManifestError(
            "인덱스 manifest를 "
            "읽을 수 없습니다."
        ) from error


def manifest_configuration_matches(
    manifest: IndexManifest,
    embedding_model: str,
    chunk_size: int,
    chunk_overlap: int,
) -> bool:
    return (
        manifest.embedding_model
        == embedding_model
        and manifest.chunk_size
        == chunk_size
        and manifest.chunk_overlap
        == chunk_overlap
    )

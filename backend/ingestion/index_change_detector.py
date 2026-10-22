from dataclasses import dataclass
from pathlib import Path

from ingestion.document_loader import (
    SUPPORTED_EXTENSIONS,
)

from ingestion.index_manifest import (
    calculate_file_sha256,
)

from models.index_manifest import (
    IndexManifest,
)

class IndexChangeDetectionError(
    RuntimeError,
): """문서 변경 감지 중 발생한 오류입니다."""

@dataclass(frozen=True)
class IndexChanges:
    added: list[Path]
    modified: list[Path]
    deleted: list[str]
    unchanged: list[Path]
    
    @property
    def has_changes(self) -> bool:
        return bool(
            self.added
            or self.modified
            or self.deleted
        )
def list_supported_source_files(
    source_directory: Path,
) -> list[Path]:
    if not source_directory.exists():
        raise IndexChangeDetectionError(
            "원본 문서 디렉터리를 "
            f"찾을 수 없습니다: {source_directory}"
        )

    if not source_directory.is_dir():
        raise IndexChangeDetectionError(
            "원본 문서 경로가 "
            f"디렉터리가 아닙니다: {source_directory}"
        )

    return sorted(
        file_path
        for file_path in source_directory.iterdir()
        if (
            file_path.is_file()
            and file_path.suffix.lower()
            in SUPPORTED_EXTENSIONS
        )
    )


def detect_index_changes(
    source_directory: Path,
    manifest: IndexManifest,
) -> IndexChanges:
    source_files = (
        list_supported_source_files(
            source_directory=source_directory,
        )
    )

    current_files = {
        file_path.name: file_path
        for file_path in source_files
    }

    added: list[Path] = []
    modified: list[Path] = []
    unchanged: list[Path] = []

    for file_name, file_path in (
        current_files.items()
    ):
        indexed_document = (
            manifest.documents.get(
                file_name
            )
        )

        if indexed_document is None:
            added.append(file_path)
            continue

        current_sha256 = (
            calculate_file_sha256(
                file_path=file_path,
            )
        )

        if (
            current_sha256
            != indexed_document.sha256
        ):
            modified.append(file_path)
            continue

        unchanged.append(file_path)

    deleted = sorted(
        set(manifest.documents)
        - set(current_files)
    )

    return IndexChanges(
        added=sorted(added),
        modified=sorted(modified),
        deleted=deleted,
        unchanged=sorted(unchanged),
    )
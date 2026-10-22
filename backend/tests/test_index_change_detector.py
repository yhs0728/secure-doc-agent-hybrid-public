from pathlib import Path

import pytest

from ingestion.index_change_detector import (
    IndexChangeDetectionError,
    detect_index_changes,
    list_supported_source_files,
)
from ingestion.index_manifest import (
    build_indexed_document,
)
from models.index_manifest import (
    IndexManifest,
)


def create_manifest(
    source_directory: Path,
    file_names: list[str],
) -> IndexManifest:
    documents = {}

    for file_name in file_names:
        file_path = (
            source_directory / file_name
        )

        documents[file_name] = (
            build_indexed_document(
                file_path=file_path,
                document_id=file_path.stem,
                chunk_ids=[
                    (
                        f"{file_path.stem}"
                        "-chunk-0000"
                    ),
                ],
            )
        )

    return IndexManifest(
        embedding_model="test-embedding",
        chunk_size=500,
        chunk_overlap=50,
        documents=documents,
    )


def test_detect_index_changes_detects_added_file(
    tmp_path: Path,
) -> None:
    source_directory = (
        tmp_path / "source"
    )
    source_directory.mkdir()

    new_file = (
        source_directory / "new-policy.txt"
    )
    new_file.write_text(
        "새로운 정책",
        encoding="utf-8",
    )

    manifest = IndexManifest(
        embedding_model="test-embedding",
        chunk_size=500,
        chunk_overlap=50,
    )

    changes = detect_index_changes(
        source_directory=source_directory,
        manifest=manifest,
    )

    assert changes.added == [
        new_file,
    ]
    assert changes.modified == []
    assert changes.deleted == []
    assert changes.unchanged == []
    assert changes.has_changes is True


def test_detect_index_changes_detects_modified_file(
    tmp_path: Path,
) -> None:
    source_directory = (
        tmp_path / "source"
    )
    source_directory.mkdir()

    file_path = (
        source_directory / "policy.txt"
    )
    file_path.write_text(
        "기존 정책",
        encoding="utf-8",
    )

    manifest = create_manifest(
        source_directory=source_directory,
        file_names=[
            "policy.txt",
        ],
    )

    file_path.write_text(
        "변경된 정책",
        encoding="utf-8",
    )

    changes = detect_index_changes(
        source_directory=source_directory,
        manifest=manifest,
    )

    assert changes.added == []
    assert changes.modified == [
        file_path,
    ]
    assert changes.deleted == []
    assert changes.unchanged == []
    assert changes.has_changes is True


def test_detect_index_changes_detects_deleted_file(
    tmp_path: Path,
) -> None:
    source_directory = (
        tmp_path / "source"
    )
    source_directory.mkdir()

    file_path = (
        source_directory / "policy.txt"
    )
    file_path.write_text(
        "삭제될 정책",
        encoding="utf-8",
    )

    manifest = create_manifest(
        source_directory=source_directory,
        file_names=[
            "policy.txt",
        ],
    )

    file_path.unlink()

    changes = detect_index_changes(
        source_directory=source_directory,
        manifest=manifest,
    )

    assert changes.added == []
    assert changes.modified == []
    assert changes.deleted == [
        "policy.txt",
    ]
    assert changes.unchanged == []
    assert changes.has_changes is True


def test_detect_index_changes_detects_unchanged_file(
    tmp_path: Path,
) -> None:
    source_directory = (
        tmp_path / "source"
    )
    source_directory.mkdir()

    file_path = (
        source_directory / "policy.txt"
    )
    file_path.write_text(
        "변경되지 않은 정책",
        encoding="utf-8",
    )

    manifest = create_manifest(
        source_directory=source_directory,
        file_names=[
            "policy.txt",
        ],
    )

    changes = detect_index_changes(
        source_directory=source_directory,
        manifest=manifest,
    )

    assert changes.added == []
    assert changes.modified == []
    assert changes.deleted == []
    assert changes.unchanged == [
        file_path,
    ]
    assert changes.has_changes is False


def test_list_supported_source_files_ignores_other_files(
    tmp_path: Path,
) -> None:
    source_directory = (
        tmp_path / "source"
    )
    source_directory.mkdir()

    text_file = (
        source_directory / "policy.txt"
    )
    text_file.write_text(
        "정책",
        encoding="utf-8",
    )

    (
        source_directory / "image.png"
    ).write_bytes(
        b"not-an-image"
    )

    result = list_supported_source_files(
        source_directory=source_directory,
    )

    assert result == [
        text_file,
    ]


def test_list_supported_source_files_rejects_missing_directory(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        IndexChangeDetectionError,
        match="원본 문서 디렉터리를",
    ):
        list_supported_source_files(
            source_directory=(
                tmp_path / "missing"
            ),
        )
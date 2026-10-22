from pathlib import Path

import pytest

from ingestion.index_manifest import (
    IndexManifestError,
    build_indexed_document,
    calculate_file_sha256,
    load_index_manifest,
    manifest_configuration_matches,
    save_index_manifest,
)
from models.index_manifest import (
    IndexManifest,
)


def test_calculate_file_sha256_changes_when_content_changes(
    tmp_path: Path,
) -> None:
    file_path = (
        tmp_path / "policy.txt"
    )

    file_path.write_text(
        "기존 정책",
        encoding="utf-8",
    )

    first_hash = calculate_file_sha256(
        file_path=file_path,
    )

    file_path.write_text(
        "변경된 정책",
        encoding="utf-8",
    )

    second_hash = calculate_file_sha256(
        file_path=file_path,
    )

    assert first_hash != second_hash


def test_build_indexed_document(
    tmp_path: Path,
) -> None:
    file_path = (
        tmp_path / "policy.txt"
    )

    file_path.write_text(
        "비밀번호는 90일마다 변경합니다.",
        encoding="utf-8",
    )

    indexed_document = (
        build_indexed_document(
            file_path=file_path,
            document_id="policy",
            chunk_ids=[
                "policy-chunk-0000",
            ],
        )
    )

    assert (
        indexed_document.document_id
        == "policy"
    )
    assert indexed_document.file_size > 0
    assert len(indexed_document.sha256) == 64
    assert indexed_document.chunk_ids == [
        "policy-chunk-0000",
    ]


def test_save_and_load_index_manifest(
    tmp_path: Path,
) -> None:
    file_path = (
        tmp_path / "policy.txt"
    )

    file_path.write_text(
        "보안 정책",
        encoding="utf-8",
    )

    indexed_document = (
        build_indexed_document(
            file_path=file_path,
            document_id="policy",
            chunk_ids=[
                "policy-chunk-0000",
            ],
        )
    )

    manifest = IndexManifest(
        embedding_model="test-embedding",
        chunk_size=500,
        chunk_overlap=50,
        documents={
            "policy.txt": indexed_document,
        },
    )

    index_directory = (
        tmp_path / "index"
    )

    save_index_manifest(
        manifest=manifest,
        index_directory=index_directory,
    )

    loaded_manifest = load_index_manifest(
        index_directory=index_directory,
    )

    assert loaded_manifest is not None
    assert (
        loaded_manifest.embedding_model
        == "test-embedding"
    )
    assert (
        loaded_manifest.documents[
            "policy.txt"
        ].chunk_ids
        == [
            "policy-chunk-0000",
        ]
    )


def test_load_index_manifest_returns_none_when_missing(
    tmp_path: Path,
) -> None:
    result = load_index_manifest(
        index_directory=(
            tmp_path / "missing-index"
        ),
    )

    assert result is None


def test_load_index_manifest_rejects_invalid_json(
    tmp_path: Path,
) -> None:
    index_directory = (
        tmp_path / "index"
    )
    index_directory.mkdir()

    (
        index_directory / "manifest.json"
    ).write_text(
        "{invalid-json",
        encoding="utf-8",
    )

    with pytest.raises(
        IndexManifestError,
        match="manifest를 읽을 수 없습니다",
    ):
        load_index_manifest(
            index_directory=index_directory,
        )


def test_manifest_configuration_matches(
) -> None:
    manifest = IndexManifest(
        embedding_model="test-embedding",
        chunk_size=500,
        chunk_overlap=50,
    )

    assert manifest_configuration_matches(
        manifest=manifest,
        embedding_model="test-embedding",
        chunk_size=500,
        chunk_overlap=50,
    ) is True

    assert manifest_configuration_matches(
        manifest=manifest,
        embedding_model="changed-embedding",
        chunk_size=500,
        chunk_overlap=50,
    ) is False
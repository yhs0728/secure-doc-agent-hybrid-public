from pathlib import Path

import pytest
from langchain_core.documents import (
    Document as LangChainDocument,
)
from langchain_core.embeddings import (
    DeterministicFakeEmbedding,
)

from models.index_manifest import IndexedDocument, IndexManifest
from retrieval.index_repository import (
    IndexSnapshotError,
    VectorIndexNotFoundError,
    load_vector_index,
    restore_previous_snapshot,
    save_index_snapshot,
    save_vector_index,
    vector_index_exists,
)
from retrieval.vector_store import (
    build_vector_store,
)


def test_save_and_load_vector_index(
    tmp_path: Path,
) -> None:
    documents = [
        LangChainDocument(
            page_content=(
                "비밀번호는 90일마다 "
                "변경해야 합니다."
            ),
            metadata={
                "document_id": "security-policy",
                "chunk_id": (
                    "security-policy-chunk-0000"
                ),
                "source": "security-policy.txt",
            },
        ),
        LangChainDocument(
            page_content=(
                "외부 접속에는 "
                "다중 인증이 필요합니다."
            ),
            metadata={
                "document_id": "access-policy",
                "chunk_id": (
                    "access-policy-chunk-0000"
                ),
                "source": "access-policy.txt",
            },
        ),
    ]

    embeddings = DeterministicFakeEmbedding(
        size=32,
    )

    vector_store = build_vector_store(
        documents=documents,
        embeddings=embeddings,
    )

    index_directory = (
        tmp_path / "index"
    )

    save_vector_index(
        vector_store=vector_store,
        index_directory=index_directory,
    )

    assert vector_index_exists(
        index_directory=index_directory,
    ) is True

    assert (
        index_directory / "index.faiss"
    ).is_file()

    assert (
        index_directory / "index.pkl"
    ).is_file()

    loaded_vector_store = load_vector_index(
        index_directory=index_directory,
        embeddings=embeddings,
    )

    results = (
        loaded_vector_store.similarity_search(
            "비밀번호 변경 주기는?",
            k=1,
        )
    )

    assert len(results) == 1
    assert isinstance(
        results[0],
        LangChainDocument,
    )


def test_vector_index_exists_returns_false(
    tmp_path: Path,
) -> None:
    assert vector_index_exists(
        index_directory=tmp_path / "index",
    ) is False


def test_load_vector_index_rejects_missing_index(
    tmp_path: Path,
) -> None:
    embeddings = DeterministicFakeEmbedding(
        size=32,
    )

    with pytest.raises(
        VectorIndexNotFoundError,
        match="저장된 FAISS 인덱스를",
    ):
        load_vector_index(
            index_directory=(
                tmp_path / "missing-index"
            ),
            embeddings=embeddings,
        )


def test_snapshot_save_keeps_recoverable_backup(tmp_path: Path) -> None:
    embeddings = DeterministicFakeEmbedding(size=32)

    def snapshot(label: str):
        chunk_id = f"{label}-chunk-0000"
        store = build_vector_store(
            documents=[LangChainDocument(
                page_content=label,
                metadata={"document_id": label, "chunk_id": chunk_id},
            )],
            embeddings=embeddings,
        )
        manifest = IndexManifest(
            embedding_model="test",
            chunk_size=500,
            chunk_overlap=50,
            documents={f"{label}.txt": IndexedDocument(
                document_id=label,
                sha256="0" * 64,
                file_size=1,
                modified_at_ns=1,
                chunk_ids=[chunk_id],
            )},
        )
        return store, manifest

    index = tmp_path / "index"
    first_store, first_manifest = snapshot("first")
    second_store, second_manifest = snapshot("second")
    save_index_snapshot(first_store, first_manifest, index)
    save_index_snapshot(second_store, second_manifest, index)

    assert (index / "current" / "manifest.json").is_file()
    assert (index / "backup" / "manifest.json").is_file()
    assert restore_previous_snapshot(index) is True
    restored = load_vector_index(index, embeddings)
    assert set(restored.index_to_docstore_id.values()) == {"first-chunk-0000"}


def test_snapshot_rejects_manifest_vector_mismatch(tmp_path: Path) -> None:
    embeddings = DeterministicFakeEmbedding(size=32)
    store = build_vector_store(
        documents=[LangChainDocument(
            page_content="policy",
            metadata={"document_id": "policy", "chunk_id": "real-id"},
        )],
        embeddings=embeddings,
    )
    manifest = IndexManifest(
        embedding_model="test",
        chunk_size=500,
        chunk_overlap=50,
        documents={"policy.txt": IndexedDocument(
            document_id="policy",
            sha256="0" * 64,
            file_size=1,
            modified_at_ns=1,
            chunk_ids=["different-id"],
        )},
    )

    with pytest.raises(IndexSnapshotError):
        save_index_snapshot(store, manifest, tmp_path / "index")

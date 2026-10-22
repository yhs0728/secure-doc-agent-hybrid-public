from pathlib import Path

from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings

from ingestion.incremental_indexer import build_or_update_index
from ingestion.index_manifest import load_index_manifest
from retrieval.index_repository import collect_vector_chunk_ids


def write_document(directory: Path, name: str, content: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(content, encoding="utf-8")
    return path


def build_index(source: Path, index: Path, *, chunk_size: int = 80):
    return build_or_update_index(
        source_directory=source,
        index_directory=index,
        embeddings=DeterministicFakeEmbedding(size=32),
        embedding_model="test-embedding",
        chunk_size=chunk_size,
        chunk_overlap=10,
    )


def indexed_contents(result) -> list[str]:
    return [
        document.page_content
        for document in result.vector_store.docstore._dict.values()
    ]


def test_initial_build_creates_complete_snapshot(tmp_path: Path) -> None:
    source = tmp_path / "source"
    index = tmp_path / "index"
    write_document(source, "alpha.txt", "alpha policy " * 20)

    result = build_index(source, index)

    assert result.full_rebuild is True
    assert result.added == ["alpha.txt"]
    assert (index / "current" / "index.faiss").is_file()
    assert (index / "current" / "index.pkl").is_file()
    assert (index / "current" / "manifest.json").is_file()
    assert collect_vector_chunk_ids(result.vector_store)


def test_unchanged_build_reuses_all_chunks(tmp_path: Path) -> None:
    source = tmp_path / "source"
    index = tmp_path / "index"
    write_document(source, "alpha.txt", "alpha policy " * 20)
    first = build_index(source, index)

    second = build_index(source, index)

    assert second.full_rebuild is False
    assert second.added == second.modified == second.deleted == []
    assert second.unchanged == ["alpha.txt"]
    assert collect_vector_chunk_ids(second.vector_store) == collect_vector_chunk_ids(
        first.vector_store
    )


def test_added_document_only_adds_its_chunks(tmp_path: Path) -> None:
    source = tmp_path / "source"
    index = tmp_path / "index"
    write_document(source, "alpha.txt", "alpha policy " * 20)
    first = build_index(source, index)
    old_ids = collect_vector_chunk_ids(first.vector_store)
    write_document(source, "beta.txt", "beta controls " * 20)

    second = build_index(source, index)

    assert second.added == ["beta.txt"]
    assert second.unchanged == ["alpha.txt"]
    assert old_ids < collect_vector_chunk_ids(second.vector_store)


def test_modified_document_replaces_old_chunks(tmp_path: Path) -> None:
    source = tmp_path / "source"
    index = tmp_path / "index"
    path = write_document(source, "alpha.txt", "obsolete phrase " * 20)
    build_index(source, index)
    path.write_text("replacement phrase " * 20, encoding="utf-8")

    result = build_index(source, index)

    assert result.modified == ["alpha.txt"]
    contents = " ".join(indexed_contents(result))
    assert "obsolete phrase" not in contents
    assert "replacement phrase" in contents


def test_deleted_document_removes_chunks_and_manifest_entry(tmp_path: Path) -> None:
    source = tmp_path / "source"
    index = tmp_path / "index"
    write_document(source, "alpha.txt", "alpha policy " * 20)
    deleted = write_document(source, "beta.txt", "beta controls " * 20)
    build_index(source, index)
    deleted.unlink()

    result = build_index(source, index)
    manifest = load_index_manifest(index)

    assert result.deleted == ["beta.txt"]
    assert manifest is not None
    assert "beta.txt" not in manifest.documents
    assert all(not item.startswith("beta-chunk-") for item in collect_vector_chunk_ids(result.vector_store))


def test_deleting_last_document_creates_empty_index(tmp_path: Path) -> None:
    source = tmp_path / "source"
    index = tmp_path / "index"
    deleted = write_document(source, "alpha.txt", "alpha policy " * 20)
    build_index(source, index)
    deleted.unlink()

    result = build_index(source, index)
    manifest = load_index_manifest(index)

    assert result.deleted == ["alpha.txt"]
    assert result.vector_store.index.ntotal == 0
    assert manifest is not None
    assert manifest.documents == {}


def test_configuration_change_forces_full_rebuild(tmp_path: Path) -> None:
    source = tmp_path / "source"
    index = tmp_path / "index"
    write_document(source, "alpha.txt", "alpha policy " * 30)
    build_index(source, index, chunk_size=80)

    result = build_index(source, index, chunk_size=40)
    manifest = load_index_manifest(index)

    assert result.full_rebuild is True
    assert manifest is not None
    assert manifest.chunk_size == 40


def test_corrupted_manifest_forces_full_rebuild(tmp_path: Path) -> None:
    source = tmp_path / "source"
    index = tmp_path / "index"
    write_document(source, "alpha.txt", "alpha policy " * 20)
    build_index(source, index)
    (index / "current" / "manifest.json").write_text(
        "{broken-json", encoding="utf-8"
    )

    result = build_index(source, index)

    assert result.full_rebuild is True
    assert load_index_manifest(index) is not None


def test_restart_loads_index_without_reembedding_documents(tmp_path: Path) -> None:
    source = tmp_path / "source"
    index = tmp_path / "index"
    write_document(source, "alpha.txt", "alpha policy " * 20)
    class CountingEmbeddings(Embeddings):
        def __init__(self) -> None:
            self.delegate = DeterministicFakeEmbedding(size=32)
            self.document_calls = 0

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            self.document_calls += 1
            return self.delegate.embed_documents(texts)

        def embed_query(self, text: str) -> list[float]:
            return self.delegate.embed_query(text)

    embeddings = CountingEmbeddings()
    arguments = {
        "source_directory": source,
        "index_directory": index,
        "embeddings": embeddings,
        "embedding_model": "test-embedding",
        "chunk_size": 80,
        "chunk_overlap": 10,
    }

    first = build_or_update_index(**arguments)
    calls_after_build = embeddings.document_calls
    second = build_or_update_index(**arguments)

    assert first.full_rebuild is True
    assert second.full_rebuild is False
    assert calls_after_build > 0
    assert embeddings.document_calls == calls_after_build
    assert second.vector_store.similarity_search("alpha", k=1)


def test_corrupted_faiss_file_forces_full_rebuild(tmp_path: Path) -> None:
    source = tmp_path / "source"
    index = tmp_path / "index"
    write_document(source, "alpha.txt", "alpha policy " * 20)
    build_index(source, index)
    (index / "current" / "index.faiss").write_bytes(b"not-a-faiss-index")

    result = build_index(source, index)

    assert result.full_rebuild is True
    assert result.vector_store.similarity_search("alpha", k=1)


def test_missing_pickle_file_forces_full_rebuild(tmp_path: Path) -> None:
    source = tmp_path / "source"
    index = tmp_path / "index"
    write_document(source, "alpha.txt", "alpha policy " * 20)
    build_index(source, index)
    (index / "current" / "index.pkl").unlink()

    result = build_index(source, index)

    assert result.full_rebuild is True
    assert (index / "current" / "index.pkl").is_file()


def test_embedding_model_change_forces_full_rebuild(tmp_path: Path) -> None:
    source = tmp_path / "source"
    index = tmp_path / "index"
    write_document(source, "alpha.txt", "alpha policy " * 20)
    build_index(source, index)

    result = build_or_update_index(
        source_directory=source,
        index_directory=index,
        embeddings=DeterministicFakeEmbedding(size=32),
        embedding_model="replacement-embedding",
        chunk_size=80,
        chunk_overlap=10,
    )
    manifest = load_index_manifest(index)

    assert result.full_rebuild is True
    assert manifest is not None
    assert manifest.embedding_model == "replacement-embedding"

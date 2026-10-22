from pathlib import Path

from services import index_service as index_service_module
from services.index_service import IndexService, IndexServiceConfig


def test_update_index_passes_complete_configuration(monkeypatch) -> None:
    embeddings = object()
    expected_result = object()
    received: dict[str, object] = {}

    def fake_build_or_update_index(**kwargs):
        received.update(kwargs)
        return expected_result

    monkeypatch.setattr(
        index_service_module,
        "build_or_update_index",
        fake_build_or_update_index,
    )
    service = IndexService(
        embeddings=embeddings,
        config=IndexServiceConfig(
            source_directory=Path("source"),
            index_directory=Path("index"),
            embedding_model="test-embedding",
            chunk_size=500,
            chunk_overlap=50,
        ),
    )

    result = service.update_index()

    assert result is expected_result
    assert received == {
        "source_directory": Path("source"),
        "index_directory": Path("index"),
        "embeddings": embeddings,
        "embedding_model": "test-embedding",
        "chunk_size": 500,
        "chunk_overlap": 50,
    }

from pathlib import Path
from uuid import UUID

from botocore.exceptions import ClientError
from opensearchpy import NotFoundError

from config.settings import Settings
from integrations import opensearch_index as opensearch_module
from integrations.object_storage import S3ObjectStore
from integrations.opensearch_index import (
    OpenSearchRetriever,
    _index_mapping,
    build_opensearch_index,
)


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, dict] = {}

    def head_bucket(self, *, Bucket: str) -> dict:
        assert Bucket == "documents"
        return {}

    def put_object(self, *, Bucket: str, Key: str, Body, Metadata: dict) -> dict:
        content = Body.read()
        self.objects[Key] = {"content": content, "metadata": Metadata}
        return {"ETag": '"etag-1"', "VersionId": "version-1"}

    def head_object(self, *, Bucket: str, Key: str) -> dict:
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "404", "Message": "missing"}},
                "HeadObject",
            )
        value = self.objects[Key]
        return {
            "ContentLength": len(value["content"]),
            "Metadata": value["metadata"],
        }

    def delete_object(self, *, Bucket: str, Key: str, **kwargs) -> dict:
        self.objects.pop(Key, None)
        return {}


class FakeEmbeddings:
    def embed_query(self, question: str) -> list[float]:
        assert question == "question"
        return [0.1, 0.2, 0.3]


class FakeOpenSearch:
    def __init__(self) -> None:
        self.request: dict | None = None

    def search(self, *, index: str, body: dict) -> dict:
        self.request = {"index": index, "body": body}
        return {
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "content": "matched content",
                            "metadata": {"source": "document.txt"},
                        }
                    }
                ]
            }
        }


class FakeIndices:
    def __init__(self, missing_alias: bool = False) -> None:
        self.created_body: dict | None = None
        self.alias_actions: list[dict] | None = None
        self.missing_alias = missing_alias

    def create(self, *, index: str, body: dict) -> None:
        self.created_body = body

    def refresh(self, *, index: str) -> None:
        return None

    def get_alias(self, **kwargs) -> dict:
        if self.missing_alias:
            raise NotFoundError(404, "missing", {})
        return {}

    def update_aliases(self, *, body: dict) -> None:
        self.alias_actions = body["actions"]

    def exists(self, *, index: str) -> bool:
        return False


class FakeEmptyOpenSearch:
    def __init__(self, missing_alias: bool = False) -> None:
        self.indices = FakeIndices(missing_alias)

    def count(self, *, index: str) -> dict[str, int]:
        return {"count": 0}


class FakeEmptyEmbeddings:
    def embed_documents(self, contents: list[str]) -> list[list[float]]:
        assert contents == []
        return []

    def embed_query(self, question: str) -> list[float]:
        return [0.0, 0.0, 0.0]


def test_object_store_upload_verify_and_delete(tmp_path: Path) -> None:
    source = tmp_path / "document.txt"
    source.write_text("content", encoding="utf-8")
    client = FakeS3Client()
    store = S3ObjectStore(client, "documents")

    stored = store.upload(source, "workspace/document.txt", "sha256-value")

    assert stored.etag == "etag-1"
    assert stored.version_id == "version-1"
    assert stored.size_bytes == 7
    assert store.exists("workspace/document.txt", "sha256-value")
    assert store.healthcheck()

    store.delete("workspace/document.txt", "version-1")
    assert not store.exists("workspace/document.txt")


def test_opensearch_retriever_always_filters_workspace() -> None:
    workspace_id = UUID("00000000-0000-7000-8000-000000000003")
    client = FakeOpenSearch()
    retriever = OpenSearchRetriever(
        client=client,
        alias_name="secure-doc-current",
        workspace_id=workspace_id,
        embeddings=FakeEmbeddings(),
        k=3,
    )

    documents = retriever.invoke("question")

    assert documents[0].page_content == "matched content"
    assert client.request is not None
    knn = client.request["body"]["query"]["knn"]["embedding"]
    assert knn["filter"] == {"term": {"workspace_id": str(workspace_id)}}


def test_opensearch_mapping_uses_requested_vector_dimension() -> None:
    mapping = _index_mapping(384)

    embedding = mapping["mappings"]["properties"]["embedding"]
    assert embedding["type"] == "knn_vector"
    assert embedding["dimension"] == 384
    assert mapping["settings"]["index"]["knn"] is True
    assert mapping["settings"]["index"]["number_of_replicas"] == 0


def test_opensearch_client_uses_configured_ca_bundle(tmp_path, monkeypatch) -> None:
    ca_bundle = tmp_path / "ca.pem"
    ca_bundle.write_text("test CA")
    captured: dict[str, object] = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(opensearch_module, "OpenSearch", fake_client)
    settings = Settings(
        llm_model="test-model",
        llm_api_key="test-key",
        api_access_key="test-api-key",
        opensearch_url="https://search.example.test:9200",
        opensearch_verify_certs=True,
        opensearch_ca_certs=str(ca_bundle),
    )

    opensearch_module.create_opensearch_client(settings)

    assert captured["verify_certs"] is True
    assert captured["ca_certs"] == str(ca_bundle)


def test_opensearch_can_publish_empty_index(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(
        llm_model="test-model",
        llm_api_key="test-key",
        api_access_key="test-api-key",
        source_directory=str(tmp_path),
    )
    client = FakeEmptyOpenSearch(missing_alias=True)
    index_id = UUID("00000000-0000-7000-8000-000000000099")
    activated: dict[str, int] = {}
    monkeypatch.setattr(
        opensearch_module,
        "_register_build",
        lambda *args: index_id,
    )
    monkeypatch.setattr(
        opensearch_module,
        "_activate_index",
        lambda settings, identity, documents, chunks: activated.update(
            documents=documents, chunks=chunks
        ),
    )

    result = build_opensearch_index(settings, FakeEmptyEmbeddings(), client)

    assert result.added == []
    assert client.indices.created_body is not None
    assert (
        client.indices.created_body["mappings"]["properties"]["embedding"][
            "dimension"
        ]
        == 3
    )
    assert activated == {"documents": 0, "chunks": 0}
    assert client.indices.alias_actions is not None
    assert client.indices.alias_actions[-1]["add"]["alias"].endswith("-current")

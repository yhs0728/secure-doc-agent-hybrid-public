"""Private adapters: only the knowledge service holds storage/search credentials."""

import hashlib
import os
import threading
from functools import lru_cache
from uuid import uuid4

import boto3
from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk, scan

from .platform import required

_embedding_lock = threading.Lock()


@lru_cache
def object_store():
    return boto3.client(
        "s3",
        endpoint_url=required("OBJECT_STORAGE_ENDPOINT_URL"),
        aws_access_key_id=required("OBJECT_STORAGE_ACCESS_KEY"),
        aws_secret_access_key=required("OBJECT_STORAGE_SECRET_KEY"),
        region_name=os.getenv("OBJECT_STORAGE_REGION", "us-east-1"),
    )


def bucket():
    return os.getenv("OBJECT_STORAGE_BUCKET", "secure-documents")


@lru_cache
def search_client():
    url = required("OPENSEARCH_URL")
    username = os.getenv("OPENSEARCH_USERNAME")
    options = {
        "hosts": [url],
        "timeout": 30,
        "max_retries": 2,
        "retry_on_timeout": True,
        "verify_certs": os.getenv("OPENSEARCH_VERIFY_CERTS", "true").lower() == "true",
    }
    if username:
        options["http_auth"] = (username, required("OPENSEARCH_PASSWORD"))
    if os.getenv("OPENSEARCH_CA_CERTS"):
        options["ca_certs"] = os.environ["OPENSEARCH_CA_CERTS"]
    return OpenSearch(**options)


def model_name():
    return os.getenv(
        "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )


@lru_cache
def embedding_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(
        model_name(), device=os.getenv("EMBEDDING_DEVICE", "cpu")
    )


def embed(texts):
    with _embedding_lock:
        return embedding_model().encode(texts, normalize_embeddings=True).tolist()


def index_name(workspace_id):
    fingerprint = hashlib.sha256(
        f"{model_name()}:{os.getenv('CHUNK_SIZE', '500')}:{os.getenv('CHUNK_OVERLAP', '50')}".encode()
    ).hexdigest()[:12]
    return "secure-doc-v1-" + str(workspace_id).replace("-", "") + "-" + fingerprint


def create_physical(index, dimension):
    search_client().indices.create(
        index=index,
        body={
            "settings": {
                "index.knn": True,
                "number_of_shards": 1,
                "number_of_replicas": 0,
            },
            "mappings": {
                "properties": {
                    "vector": {
                        "type": "knn_vector",
                        "dimension": dimension,
                        "method": {
                            "name": "hnsw",
                            "engine": "lucene",
                            "space_type": "cosinesimil",
                        },
                    },
                    "document_id": {"type": "keyword"},
                    "text": {"type": "text"},
                    "source": {"type": "keyword"},
                    "ordinal": {"type": "integer"},
                    "page": {"type": "integer"},
                }
            },
        },
    )


def swap_alias(alias, physical):
    client = search_client()
    actions = []
    if client.indices.exists_alias(name=alias):
        actions.extend(
            {"remove": {"index": name, "alias": alias}}
            for name in client.indices.get_alias(name=alias)
        )
    actions.append({"add": {"index": physical, "alias": alias}})
    client.indices.update_aliases(body={"actions": actions})


def write_chunks(document, chunks, index):
    write_prepared(document, chunks, prepare_chunks(chunks), index)


def prepare_chunks(chunks):
    return embed([chunk["text"] for chunk in chunks])


def write_prepared(document, chunks, vectors, index):
    client = search_client()
    # Deterministic IDs make retry after a crash safe. Rebuilds hide the document first.
    client.delete_by_query(
        index=index,
        body={"query": {"term": {"document_id": str(document["id"])}}},
        refresh=True,
        conflicts="proceed",
    )
    actions = [
        {
            "_index": index,
            "_id": f"{document['id']}:{n}",
            "_source": {
                "document_id": str(document["id"]),
                "source": document["file_name"],
                "text": chunk["text"],
                "page": chunk["page"],
                "ordinal": n,
                "vector": vector,
            },
        }
        for n, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    bulk(client, actions, refresh=True, raise_on_error=True)


def put_chunks(document, chunks):
    vectors = prepare_chunks(chunks)
    ensure_alias(document["workspace_id"], len(vectors[0]))
    put_prepared(document, chunks, vectors)


def ensure_alias(workspace_id, dimension):
    """Caller holds the short index-initialization advisory lock."""
    alias = index_name(workspace_id)
    if not search_client().indices.exists_alias(name=alias):
        physical = alias + "-" + uuid4().hex
        create_physical(physical, dimension)
        swap_alias(alias, physical)


def put_prepared(document, chunks, vectors):
    alias = index_name(document["workspace_id"])
    write_prepared(document, chunks, vectors, alias)


def stage_generation(workspace_id, prepared):
    alias = index_name(workspace_id)
    physical = alias + "-" + uuid4().hex
    dimension = embedding_model().get_sentence_embedding_dimension()
    create_physical(physical, dimension)
    try:
        for document, chunks, vectors in prepared:
            write_prepared(document, chunks, vectors, physical)
            del chunks, vectors
    except Exception:
        discard_generation(workspace_id, physical)
        raise
    return physical


def active_generation(workspace_id):
    client = search_client()
    alias = index_name(workspace_id)
    if not client.indices.exists_alias(name=alias):
        return None
    indices = list(client.indices.get_alias(name=alias))
    if len(indices) != 1:
        raise RuntimeError("INDEX_ALIAS_AMBIGUOUS")
    return indices[0]


def remove_generation_documents(physical, ids):
    if ids:
        search_client().delete_by_query(
            index=physical,
            body={"query": {"terms": {"document_id": list(ids)}}},
            refresh=True,
            conflicts="proceed",
        )


def copy_ready_document(document, physical):
    """Catch up published vectors without parsing/embedding under the swap barrier."""
    client = search_client()
    count = 0

    def actions():
        nonlocal count
        for hit in scan(
            client,
            index=index_name(document["workspace_id"]),
            query={"query": {"term": {"document_id": str(document["id"])}}},
        ):
            count += 1
            yield {"_index": physical, "_id": hit["_id"], "_source": hit["_source"]}

    bulk(client, actions(), refresh=True, raise_on_error=True)
    if count != document["chunk_count"] or count == 0:
        raise RuntimeError("INDEX_CATCHUP_SOURCE_INCOMPLETE")
    return count


def publish_generation(workspace_id, physical, expected_count):
    if search_client().count(index=physical)["count"] != expected_count:
        raise RuntimeError("INDEX_COUNT_MISMATCH")
    swap_alias(index_name(workspace_id), physical)


def discard_generation(workspace_id, physical):
    # An alias update can succeed while its network response is lost. Never delete
    # an index that may already be serving reads.
    client = search_client()
    alias = index_name(workspace_id)
    if client.indices.exists_alias(name=alias) and physical in client.indices.get_alias(
        name=alias
    ):
        return
    client.indices.delete(index=physical, ignore=[404])


def rebuild_chunks(workspace_id, documents):
    alias = index_name(workspace_id)
    physical = alias + "-" + uuid4().hex
    dimension = embedding_model().get_sentence_embedding_dimension()
    create_physical(physical, dimension)
    try:
        for document, chunks in documents:
            write_chunks(document, chunks, physical)
        count = search_client().count(index=physical)["count"]
        if count != sum(len(chunks) for document, chunks in documents):
            raise RuntimeError("INDEX_COUNT_MISMATCH")
        swap_alias(alias, physical)
    except Exception:
        search_client().indices.delete(index=physical, ignore=[404])
        raise


def delete_chunks(document):
    # Include previous embedding-model index generations, not just the active one.
    pattern = "secure-doc-v1-" + str(document["workspace_id"]).replace("-", "") + "-*"
    client = search_client()
    if client.indices.exists(index=pattern):
        client.delete_by_query(
            index=pattern,
            body={"query": {"term": {"document_id": str(document["id"])}}},
            refresh=True,
            conflicts="proceed",
        )


def retrieve(workspace_id, query, k, active_ids):
    index = index_name(workspace_id)
    client = search_client()
    if not active_ids or not client.indices.exists(index=index):
        return []
    vector = embed([query])[0]
    response = client.search(
        index=index,
        body={
            "size": k,
            "_source": {"excludes": ["vector"]},
            "query": {
                "knn": {
                    "vector": {
                        "vector": vector,
                        "k": k,
                        "filter": {"terms": {"document_id": active_ids}},
                    }
                }
            },
        },
    )
    return [
        {
            "document_id": hit["_source"]["document_id"],
            "source": hit["_source"]["source"],
            "chunk_id": hit["_id"],
            "text": hit["_source"]["text"],
            "page": hit["_source"].get("page"),
            "score": hit["_score"],
        }
        for hit in response["hits"]["hits"]
    ]

from langchain_core.documents import (
    Document as LangChainDocument,
)
from langchain_core.embeddings import (
    Embeddings,
)
from langchain_core.vectorstores import (
    VectorStoreRetriever,
)

from retrieval.faiss_store import FaissVectorStore


class VectorStoreError(ValueError):
    pass


def collect_chunk_ids(
    documents: list[LangChainDocument],
) -> list[str]:
    chunk_ids: list[str] = []

    for document in documents:
        chunk_id = document.metadata.get("chunk_id")

        if not isinstance(chunk_id, str):
            raise VectorStoreError("모든 문서 청크에는 문자열 chunk_id가 필요합니다.")

        normalized_chunk_id = chunk_id.strip()

        if not normalized_chunk_id:
            raise VectorStoreError("chunk_id는 비어 있을 수 없습니다.")

        chunk_ids.append(normalized_chunk_id)

    if len(chunk_ids) != len(set(chunk_ids)):
        raise VectorStoreError("중복된 chunk_id가 존재합니다.")

    return chunk_ids


def build_vector_store(
    documents: list[LangChainDocument],
    embeddings: Embeddings,
) -> FaissVectorStore:
    if not documents:
        raise ValueError("Vector Store에 저장할 문서가 없습니다.")

    chunk_ids = collect_chunk_ids(
        documents=documents,
    )

    vector_store = FaissVectorStore.from_documents(
        documents=documents,
        embedding=embeddings,
        ids=chunk_ids,
    )

    return vector_store


def add_documents_to_vector_store(
    vector_store: FaissVectorStore,
    documents: list[LangChainDocument],
) -> list[str]:
    if not documents:
        return []

    chunk_ids = collect_chunk_ids(
        documents=documents,
    )

    vector_store.add_documents(
        documents=documents,
        ids=chunk_ids,
    )

    return chunk_ids


def delete_chunks_from_vector_store(
    vector_store: FaissVectorStore,
    chunk_ids: list[str],
) -> None:
    if not chunk_ids:
        return

    result = vector_store.delete(
        ids=chunk_ids,
    )

    if result is False:
        raise VectorStoreError("FAISS에서 문서 청크를 삭제하지 못했습니다.")


def create_retriever(
    vector_store: FaissVectorStore, k: int = 3
) -> VectorStoreRetriever:
    if k < 1:
        raise ValueError("검색 문서 개수 k는 1 이상이어야 합니다.")

    return vector_store.as_retriever(search_kwargs={"k": k})

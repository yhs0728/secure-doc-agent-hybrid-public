import pytest

from langchain_core.documents import (
    Document as LangChainDocument,
)
from langchain_core.embeddings import (
    DeterministicFakeEmbedding,
)

from retrieval.vector_store import (
    build_vector_store,
    create_retriever,
    VectorStoreError,
    add_documents_to_vector_store,
    delete_chunks_from_vector_store,
)


def create_test_documents() -> list[LangChainDocument]:
    return [
        LangChainDocument(
            page_content=(
                "사용자는 비밀번호를 90일마다 "
                "변경해야 합니다."
            ),
            metadata={
                "document_id": "doc-003",
                "chunk_id": "doc-003-chunk-0000",
                "title": "정보보안 운영 규정",
                "source": "security-policy.txt",
            },
        ),
        LangChainDocument(
            page_content=(
                "개인정보는 업무 목적에 필요한 "
                "최소 범위에서 수집합니다."
            ),
            metadata={
                "document_id": "doc-002",
                "chunk_id": "doc-002-chunk-0000",
                "title": "개인정보 처리 지침",
                "source": "privacy-guide.txt",
            },
        ),
        LangChainDocument(
            page_content=(
                "기밀 문서는 권한이 있는 사용자만 "
                "열람할 수 있습니다."
            ),
            metadata={
                "document_id": "doc-001",
                "chunk_id": "doc-001-chunk-0000",
                "title": "문서 관리 규정",
                "source": "document-policy.txt",
            },
        ),
    ]


def create_test_embeddings() -> DeterministicFakeEmbedding:
    return DeterministicFakeEmbedding(
        size=64,
    )


def test_build_vector_store() -> None:
    documents = create_test_documents()
    embeddings = create_test_embeddings()

    vector_store = build_vector_store(
        documents=documents,
        embeddings=embeddings,
    )

    results = vector_store.similarity_search(
        query="비밀번호 변경",
        k=2,
    )

    assert len(results) == 2

    for result in results:
        assert result.page_content
        assert "document_id" in result.metadata
        assert "chunk_id" in result.metadata


def test_create_retriever() -> None:
    documents = create_test_documents()
    embeddings = create_test_embeddings()

    vector_store = build_vector_store(
        documents=documents,
        embeddings=embeddings,
    )

    retriever = create_retriever(
        vector_store=vector_store,
        k=2,
    )

    results = retriever.invoke(
        "비밀번호 변경 주기는?",
    )

    assert len(results) == 2

    for result in results:
        assert isinstance(
            result,
            LangChainDocument,
        )


def test_build_vector_store_rejects_empty_documents() -> None:
    embeddings = create_test_embeddings()

    with pytest.raises(
        ValueError,
        match="저장할 문서가 없습니다",
    ):
        build_vector_store(
            documents=[],
            embeddings=embeddings,
        )


def test_create_retriever_rejects_invalid_k() -> None:
    documents = create_test_documents()
    embeddings = create_test_embeddings()

    vector_store = build_vector_store(
        documents=documents,
        embeddings=embeddings,
    )

    with pytest.raises(
        ValueError,
        match="k는 1 이상",
    ):
        create_retriever(
            vector_store=vector_store,
            k=0,
        )
        
def test_build_vector_store_uses_chunk_ids(
) -> None:
    documents = [
        LangChainDocument(
            page_content="첫 번째 정책",
            metadata={
                "chunk_id": (
                    "policy-chunk-0000"
                ),
                "source": "policy.txt",
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

    assert (
        "policy-chunk-0000"
        in vector_store.index_to_docstore_id.values()
    )
    
def test_add_documents_to_vector_store(
) -> None:
    embeddings = DeterministicFakeEmbedding(
        size=32,
    )

    initial_documents = [
        LangChainDocument(
            page_content="기존 정책",
            metadata={
                "chunk_id": (
                    "existing-chunk-0000"
                ),
                "source": "existing.txt",
            },
        ),
    ]

    vector_store = build_vector_store(
        documents=initial_documents,
        embeddings=embeddings,
    )

    new_documents = [
        LangChainDocument(
            page_content="새 정책",
            metadata={
                "chunk_id": (
                    "new-chunk-0000"
                ),
                "source": "new.txt",
            },
        ),
    ]

    added_ids = (
        add_documents_to_vector_store(
            vector_store=vector_store,
            documents=new_documents,
        )
    )

    assert added_ids == [
        "new-chunk-0000",
    ]
    assert (
        "new-chunk-0000"
        in vector_store.index_to_docstore_id.values()
    )
    
def test_delete_chunks_from_vector_store(
) -> None:
    documents = [
        LangChainDocument(
            page_content="삭제할 정책",
            metadata={
                "chunk_id": (
                    "delete-chunk-0000"
                ),
                "source": "delete.txt",
            },
        ),
        LangChainDocument(
            page_content="유지할 정책",
            metadata={
                "chunk_id": (
                    "keep-chunk-0000"
                ),
                "source": "keep.txt",
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

    delete_chunks_from_vector_store(
        vector_store=vector_store,
        chunk_ids=[
            "delete-chunk-0000",
        ],
    )

    stored_ids = set(
        vector_store.index_to_docstore_id.values()
    )

    assert "delete-chunk-0000" not in (
        stored_ids
    )
    assert "keep-chunk-0000" in stored_ids
    
def test_build_vector_store_rejects_duplicate_chunk_ids(
) -> None:
    documents = [
        LangChainDocument(
            page_content="첫 번째 문서",
            metadata={
                "chunk_id": "duplicate-id",
            },
        ),
        LangChainDocument(
            page_content="두 번째 문서",
            metadata={
                "chunk_id": "duplicate-id",
            },
        ),
    ]

    embeddings = DeterministicFakeEmbedding(
        size=32,
    )

    with pytest.raises(
        VectorStoreError,
        match="중복된 chunk_id",
    ):
        build_vector_store(
            documents=documents,
            embeddings=embeddings,
        )
        

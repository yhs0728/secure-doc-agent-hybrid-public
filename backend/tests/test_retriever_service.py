import pytest

from langchain_core.documents import (
    Document as LangChainDocument,
)
from langchain_core.embeddings import (
    DeterministicFakeEmbedding,
)

from retrieval.retriever_service import (
    retrieve_documents,
)
from retrieval.vector_store import (
    build_vector_store,
    create_retriever,
)


def create_test_retriever():
    documents = [
        LangChainDocument(
            page_content=(
                "사용자는 비밀번호를 "
                "90일마다 변경해야 합니다."
            ),
            metadata={
                "document_id": "doc-001",
                "chunk_id": "doc-001-chunk-0000",
            },
        ),
        LangChainDocument(
            page_content=(
                "외부 접속에는 다중 인증이 필요합니다."
            ),
            metadata={
                "document_id": "doc-002",
                "chunk_id": "doc-002-chunk-0000",
            },
        ),
        LangChainDocument(
            page_content=(
                "문서는 보안 등급에 따라 관리합니다."
            ),
            metadata={
                "document_id": "doc-003",
                "chunk_id": "doc-003-chunk-0000",
            },
        ),
    ]

    embeddings = DeterministicFakeEmbedding(
        size=32
    )

    vector_store = build_vector_store(
        documents=documents,
        embeddings=embeddings,
    )

    return create_retriever(
        vector_store=vector_store,
        k=2,
    )


def test_retrieve_documents_returns_documents() -> None:
    retriever = create_test_retriever()

    results = retrieve_documents(
        retriever=retriever,
        question="비밀번호 변경 주기는?",
    )

    assert len(results) == 2

    for document in results:
        assert isinstance(
            document,
            LangChainDocument,
        )
        assert "document_id" in document.metadata
        assert "chunk_id" in document.metadata


def test_retrieve_documents_rejects_blank_question() -> None:
    retriever = create_test_retriever()

    with pytest.raises(
        ValueError,
        match="검색 질문은 비어 있을 수 없습니다.",
    ):
        retrieve_documents(
            retriever=retriever,
            question="   ",
        )
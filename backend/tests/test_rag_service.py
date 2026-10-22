import pytest

from langchain_core.documents import (
    Document as LangChainDocument,
)
from langchain_core.embeddings import (
    DeterministicFakeEmbedding,
)
from langchain_core.language_models.fake_chat_models import (
    FakeListChatModel,
)

from retrieval.vector_store import (
    build_vector_store,
    create_retriever,
)
from services.rag_service import (
    answer_question,
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
                "source": "security-policy.txt",
            },
        ),
        LangChainDocument(
            page_content=(
                "외부 접속에는 다중 인증이 필요합니다."
            ),
            metadata={
                "document_id": "doc-002",
                "chunk_id": "doc-002-chunk-0000",
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

    return create_retriever(
        vector_store=vector_store,
        k=2,
    )


def test_answer_question_returns_answer_and_citations(
) -> None:
    retriever = create_test_retriever()

    model = FakeListChatModel(
        responses=[
            (
                "사용자는 비밀번호를 "
                "90일마다 변경해야 합니다."
            ),
        ]
    )

    result = answer_question(
        question="비밀번호 변경 주기는?",
        retriever=retriever,
        model=model,
    )

    assert result["answer"] == (
        "사용자는 비밀번호를 "
        "90일마다 변경해야 합니다."
    )

    assert set(result["citations"]) == {
        "security-policy.txt",
        "access-policy.txt",
    }

    assert result["requires_human_review"] is False


def test_answer_question_rejects_blank_question(
) -> None:
    retriever = create_test_retriever()

    model = FakeListChatModel(
        responses=[
            "테스트 응답",
        ]
    )

    with pytest.raises(
        ValueError,
        match="검색 질문은 비어 있을 수 없습니다.",
    ):
        answer_question(
            question="   ",
            retriever=retriever,
            model=model,
        )
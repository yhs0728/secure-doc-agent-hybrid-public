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

from graph.nodes import citation_filter_node
from graph.workflow import build_rag_workflow
from retrieval.vector_store import (
    build_vector_store,
    create_retriever,
)


@pytest.mark.parametrize(
    "response, expected",
    [
        ('{"citations": ["account-lock-policy.docx"]}', ["account-lock-policy.docx"]),
        ('{"citations": ["invented-policy.txt"]}', []),
        ('{"citations": ["account-lock-policy.docx", "account-lock-policy.docx", null, {}]}', ["account-lock-policy.docx"]),
        ('{"citations": "account-lock-policy.docx"}', []),
        ('[]', []),
        ('{}', []),
        ('invalid json', []),
    ],
)
def test_citation_filter_selects_valid_sources(response, expected) -> None:
    documents = [
        LangChainDocument(
            page_content="로그인에 5회 연속 실패하면 계정을 30분 동안 잠급니다.",
            metadata={"source": "account-lock-policy.docx"},
        ),
        LangChainDocument(
            page_content="비밀번호는 90일마다 변경해야 합니다.",
            metadata={"source": "security-policy.txt"},
        ),
    ]
    result = citation_filter_node(
        state={
            "question": "로그인에 몇 번 실패하면 계정이 잠깁니까?",
            "answer": "로그인에 5회 연속 실패하면 계정이 30분 동안 잠깁니다.",
            "documents": documents,
        },
        model=FakeListChatModel(responses=[response]),
    )
    assert result == {"citations": expected}


@pytest.mark.parametrize(
    "documents, answer",
    [
        ([], "answer"),
        ([LangChainDocument(page_content="content", metadata={"source": "a.txt"})], " "),
        ([LangChainDocument(page_content="content")], "answer"),
        ([LangChainDocument(page_content="content", metadata={"source": None})], "answer"),
    ],
)
def test_citation_filter_skips_model_without_input(documents, answer) -> None:
    result = citation_filter_node(
        state={"documents": documents, "answer": answer},
        model=FakeListChatModel(responses=[]),
    )
    assert result == {"citations": []}


def create_test_graph():
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
                "외부 접속에는 "
                "다중 인증이 필요합니다."
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

    retriever = create_retriever(
        vector_store=vector_store,
        k=2,
    )

    model = FakeListChatModel(
        responses=[
            "0,1",
            (
                "사용자는 비밀번호를 "
                "90일마다 변경해야 합니다."
            ),
            '{"citations": ["security-policy.txt"]}',
            "GROUNDED",
        ]
    )

    return build_rag_workflow(
        retriever=retriever,
        model=model,
    )


def test_rag_workflow() -> None:
    graph = create_test_graph()

    result = graph.invoke(
        {
            "question": "비밀번호 변경 주기는?",
        }
    )

    assert result["question"] == (
        "비밀번호 변경 주기는?"
    )

    assert result["answer"] == (
        "사용자는 비밀번호를 "
        "90일마다 변경해야 합니다."
    )

    assert len(result["documents"]) == 2

    assert set(result["citations"]) == {
        "security-policy.txt",
    }

    assert result["context"]
    assert result["documents_relevant"] is True
    assert result["answer_grounded"] is True
    assert result["requires_human_review"] is False
    
    
def test_rag_workflow_returns_review_when_no_documents(
    monkeypatch,
)-> None:
    class EmptyRetriever:
        def invoke(
            self,
            query: str,
        )-> list:
            return []
        
    model = FakeListChatModel(
    responses=[
        "0",
        (
            "사용자는 비밀번호를 "
            "90일마다 변경해야 합니다."
        ),
    ]
)
    
    graph = build_rag_workflow(
        retriever=EmptyRetriever(),
        model=model,
    )
    
    result = graph.invoke(
        {
            "question": "문서에 없는 질문",
        }
    )
    
    assert result["answer"] == (
        "검색된 문서에서 질문에 대한 "
        "근거를 찾을 수 없습니다."
    )
    
    assert result["citations"] == []
    assert result["requires_human_review"] is True  
    
def test_rag_workflow_returns_review_when_documents_irrelevant(
) -> None:
    documents = [
        LangChainDocument(
            page_content=(
                "직원은 매주 월요일 오전에 "
                "주간회의에 참석해야 합니다."
            ),
            metadata={
                "document_id": "doc-003",
                "chunk_id": "doc-003-chunk-0000",
                "source": "meeting-policy.txt",
            },
        ),
    ]

    class IrrelevantRetriever:
        def invoke(
            self,
            query: str,
        ) -> list[LangChainDocument]:
            return documents

    model = FakeListChatModel(
        responses=[
            "NONE",
        ]
    )

    graph = build_rag_workflow(
        retriever=IrrelevantRetriever(),
        model=model,
    )

    result = graph.invoke(
        {
            "question": "비밀번호 변경 주기는?",
        }
    )

    assert result["documents_relevant"] is False

    assert result["answer"] == (
        "검색된 문서에서 질문에 대한 "
        "근거를 찾을 수 없습니다."
    )

    assert result["citations"] == []
    assert result["requires_human_review"] is True
    
    
    
def test_rag_workflow_requires_review_when_answer_not_grounded(
) -> None:
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
    ]

    class TestRetriever:
        def invoke(
            self,
            query: str,
        ) -> list[LangChainDocument]:
            return documents

    model = FakeListChatModel(
        responses=[
            "0",
            (
                "사용자는 비밀번호를 "
                "30일마다 변경해야 합니다."
            ),
            '{"citations": ["security-policy.txt"]}',
            "NOT_GROUNDED",
        ]
    )

    graph = build_rag_workflow(
        retriever=TestRetriever(),
        model=model,
    )

    result = graph.invoke(
        {
            "question": "비밀번호 변경 주기는?",
        }
    )

    assert result["documents_relevant"] is True
    assert result["answer_grounded"] is False

    assert result["answer"] == (
        "생성된 답변이 검색 문서에 "
        "충분히 근거하는지 확인하지 못했습니다."
    )

    assert result["citations"] == []
    assert result["requires_human_review"] is True
    
def test_rag_workflow_rewrites_query_and_retries(
) -> None:
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
    ]

    received_queries: list[str] = []

    class RetryRetriever:
        def invoke(
            self,
            query: str,
        ) -> list[LangChainDocument]:
            received_queries.append(query)

            if len(received_queries) == 1:
                return []

            return documents

    model = FakeListChatModel(
        responses=[
            (
                "비밀번호 정책의 "
                "변경 주기 규정"
            ),
            "0",
            (
                "사용자는 비밀번호를 "
                "90일마다 변경해야 합니다."
            ),
            '{"citations": ["security-policy.txt"]}',
            "GROUNDED",
        ]
    )

    graph = build_rag_workflow(
        retriever=RetryRetriever(),
        model=model,
    )

    result = graph.invoke(
        {
            "question": "비밀번호 언제 바꿔?",
        }
    )

    assert received_queries == [
        "비밀번호 언제 바꿔?",
        "비밀번호 정책의 변경 주기 규정",
    ]

    assert result["question"] == (
        "비밀번호 언제 바꿔?"
    )

    assert result["search_query"] == (
        "비밀번호 정책의 변경 주기 규정"
    )

    assert result["retrieval_attempts"] == 2

    assert result["answer"] == (
        "사용자는 비밀번호를 "
        "90일마다 변경해야 합니다."
    )

    assert result["answer_grounded"] is True
    assert result["requires_human_review"] is False
    
    
def test_rag_workflow_filters_irrelevant_citations(
) -> None:
    documents = [
        LangChainDocument(
            page_content=(
                "사용자는 비밀번호를 "
                "90일마다 변경해야 합니다."
            ),
            metadata={
                "source": "security-policy.txt",
            },
        ),
        LangChainDocument(
            page_content=(
                "개인정보는 목적 달성 후 "
                "지체 없이 파기해야 합니다."
            ),
            metadata={
                "source": "privacy-guide.txt",
            },
        ),
        LangChainDocument(
            page_content=(
                "문서 보존 기간은 "
                "등급에 따라 결정됩니다."
            ),
            metadata={
                "source": "document-policy.txt",
            },
        ),
    ]

    class ThreeDocumentRetriever:
        def invoke(
            self,
            query: str,
        ) -> list[LangChainDocument]:
            return documents

    model = FakeListChatModel(
        responses=[
            "0",
            (
                "비밀번호 변경 주기는 "
                "90일입니다."
            ),
            '{"citations": ["security-policy.txt"]}',
            "GROUNDED",
        ]
    )

    graph = build_rag_workflow(
        retriever=ThreeDocumentRetriever(),
        model=model,
    )

    result = graph.invoke(
        {
            "question": "비밀번호 변경 주기는?",
        }
    )

    assert len(result["documents"]) == 1

    assert result["citations"] == [
        "security-policy.txt",
    ]

    assert result["answer"] == (
        "비밀번호 변경 주기는 "
        "90일입니다."
    )

    assert result["documents_relevant"] is True
    assert result["answer_grounded"] is True
    assert (
        result["requires_human_review"]
        is False
    )

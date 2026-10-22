from langchain_core.documents import (
    Document as LangChainDocument,
)

from retrieval.result_formatter import (
    build_retrieval_result,
    collect_citations,
    format_context,
)


def create_documents() -> list[LangChainDocument]:
    return [
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
                "관리자 계정에도 동일한 "
                "비밀번호 정책을 적용합니다."
            ),
            metadata={
                "document_id": "doc-001",
                "chunk_id": "doc-001-chunk-0001",
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


def test_format_context_includes_content_and_metadata() -> None:
    documents = create_documents()

    context = format_context(documents)

    assert "비밀번호를 90일마다" in context
    assert "security-policy.txt" in context
    assert "doc-001-chunk-0000" in context


def test_collect_citations_removes_duplicates() -> None:
    documents = create_documents()

    citations = collect_citations(documents)

    assert citations == [
        "security-policy.txt",
        "access-policy.txt",
    ]

#assert 이 조건은 반드시 참이어야 한다.
# 조건이 True 면 아무일 없이 다음 코드 진행
#        False면 assertionError 발생
def test_build_retrieval_result() -> None:
    documents = create_documents()

    result = build_retrieval_result(documents)

    assert result["documents"] == documents
    assert result["context"]
    assert result["citations"] == [
        "security-policy.txt",
        "access-policy.txt",
    ]


def test_build_retrieval_result_handles_empty_documents() -> None:
    result = build_retrieval_result([])

    assert result["context"] == ""
    assert result["citations"] == []
    assert result["documents"] == []
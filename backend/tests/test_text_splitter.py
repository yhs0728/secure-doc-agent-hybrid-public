from langchain_core.documents import (
    Document as LangChainDocument,
)

from ingestion.text_splitter import (
    split_documents,
)


def test_split_documents_creates_multiple_chunks() -> None:
    document = LangChainDocument(
        page_content=(
            "사용자는 비밀번호를 90일마다 변경해야 합니다. "
            * 30
        ),
        metadata={
            "document_id": "doc-003",
            "title": "정보보안 운영 규정",
            "source": "security-policy.txt",
        },
    )

    chunks = split_documents(
        documents=[document],
        chunk_size=100,
        chunk_overlap=10,
    )

    assert len(chunks) > 1

    for chunk in chunks:
        assert len(chunk.page_content) <= 100


def test_split_documents_preserves_metadata() -> None:
    document = LangChainDocument(
        page_content=(
            "비밀번호 관리 규정입니다. "
            "사용자는 비밀번호를 주기적으로 변경해야 합니다."
        ),
        metadata={
            "document_id": "doc-003",
            "title": "정보보안 운영 규정",
            "source": "security-policy.txt",
        },
    )

    chunks = split_documents(
        documents=[document],
        chunk_size=50,
        chunk_overlap=10,
    )

    first_chunk = chunks[0]

    assert first_chunk.metadata["document_id"] == "doc-003"
    assert first_chunk.metadata["title"] == "정보보안 운영 규정"
    assert first_chunk.metadata["source"] == (
        "security-policy.txt"
    )


def test_split_documents_adds_chunk_information() -> None:
    document = LangChainDocument(
        page_content=(
            "정보보안 규정 내용입니다. " * 20
        ),
        metadata={
            "document_id": "doc-003",
            "title": "정보보안 운영 규정",
            "source": "security-policy.txt",
        },
    )

    chunks = split_documents(
        documents=[document],
        chunk_size=80,
        chunk_overlap=10,
    )

    assert chunks[0].metadata["chunk_index"] == 0
    assert chunks[0].metadata["chunk_id"] == (
        "doc-003-chunk-0000"
    )

    if len(chunks) > 1:
        assert chunks[1].metadata["chunk_index"] == 1
        assert chunks[1].metadata["chunk_id"] == (
            "doc-003-chunk-0001"
        )
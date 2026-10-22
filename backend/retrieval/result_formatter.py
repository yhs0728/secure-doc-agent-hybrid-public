from typing import TypedDict

from langchain_core.documents import (
    Document as LangChainDocument,
)


class RetrievalResult(TypedDict):
    context: str
    citations: list[str]
    documents: list[LangChainDocument]


def format_context(
    documents: list[LangChainDocument],
) -> str:
    context_blocks: list[str] = []

    for document in documents:
        source = str(
            document.metadata.get(
                "source",
                "출처 없음",
            )
        )

        chunk_id = str(
            document.metadata.get(
                "chunk_id",
                "청크 정보 없음",
            )
        )

        content = document.page_content.strip()

        context_blocks.append(
            f"[출처: {source}, 청크: {chunk_id}]\n"
            f"{content}"
        )

    return "\n\n".join(context_blocks)


def collect_citations(
    documents: list[LangChainDocument],
) -> list[str]:
    citations: list[str] = []
    seen_sources: set[str] = set()

    for document in documents:
        source = document.metadata.get("source")

        if not isinstance(source, str):
            continue

        normalized_source = source.strip()

        if not normalized_source:
            continue

        if normalized_source in seen_sources:
            continue

        seen_sources.add(normalized_source)
        citations.append(normalized_source)

    return citations


def build_retrieval_result(
    documents: list[LangChainDocument],
) -> RetrievalResult:
    return {
        "context": format_context(documents),
        "citations": collect_citations(documents),
        "documents": documents,
    }
from langchain_core.documents import (
    Document as LangChainDocument,
)
from langchain_core.vectorstores import (
    VectorStoreRetriever,
)


def retrieve_documents(
    retriever: VectorStoreRetriever,
    question: str,
) -> list[LangChainDocument]:
    normalized_question = question.strip()

    if not normalized_question:
        raise ValueError("검색 질문은 비어 있을 수 없습니다.")

    return retriever.invoke(normalized_question)

from langchain_core.documents import (
    Document as LangChainDocument,
)
from typing_extensions import (
    NotRequired,
    TypedDict,
)


class GraphState(TypedDict):
    question: str

    search_query: NotRequired[str]
    retrieval_attempts: NotRequired[int]

    documents: NotRequired[list[LangChainDocument]]
    context: NotRequired[str]
    citations: NotRequired[list[str]]
    answer: NotRequired[str]
    requires_human_review: NotRequired[bool]
    documents_relevant: NotRequired[bool]
    answer_grounded: NotRequired[bool]

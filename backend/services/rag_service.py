from  typing import TypedDict

from langchain_core.language_models.chat_models import (
    BaseChatModel,
)

from langchain_core.vectorstores import (
    VectorStoreRetriever,
)

from rag.generator import generate_answer
from retrieval.result_formatter import (
    build_retrieval_result,
)
from retrieval.retriever_service import (
    retrieve_documents,
)

class RAGResponse(TypedDict):
    answer: str
    citations: list[str]
    requires_human_review: bool
    
    
    
def answer_question(
    question: str,
    retriever: VectorStoreRetriever,
    model: BaseChatModel,
)-> RAGResponse:
    documents = retrieve_documents(
        retriever=retriever,
        question=question,
    )
    
    retrieval_result = build_retrieval_result(
        documents=documents,
    )
    
    answer = generate_answer(
        question=question,
        context=retrieval_result["context"],
        model=model,
        )
    
    return {
        "answer": answer,
        "citations": retrieval_result["citations"],
        "requires_human_review": False,
    }
    
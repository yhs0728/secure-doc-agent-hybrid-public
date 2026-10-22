from langchain_core.language_models.chat_models import (
    BaseChatModel,
)
from langchain_core.output_parsers import (
    StrOutputParser,
)

from rag.prompt import RAG_PROMPT

NO_ANSWER_MESSAGE = (
    "제공된 문서에서 답변을 찾을 수 없습니다."
)


def create_rag_chain(
    model: BaseChatModel,
):
    return (
        RAG_PROMPT
        | model.bind(max_tokens=64)
        | StrOutputParser()
    )


def generate_answer(
    question: str,
    context: str,
    model: BaseChatModel,
) -> str:
    normalized_question = question.strip()
    normalized_context = context.strip()

    if not normalized_question:
        raise ValueError(
            "질문은 비어 있을 수 없습니다."
        )

    if not normalized_context:
        return NO_ANSWER_MESSAGE

    rag_chain = create_rag_chain(
        model=model,
    )

    answer = rag_chain.invoke(
        {
            "question": normalized_question,
            "context": normalized_context,
        }
    )

    return answer.strip()

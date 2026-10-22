import logging

from langchain_core.language_models.chat_models import (
    BaseChatModel,
)
from langchain_core.output_parsers import (
    JsonOutputParser,
    StrOutputParser,
)
from langchain_core.prompts import (
    ChatPromptTemplate,
)
from langchain_core.vectorstores import (
    VectorStoreRetriever,
)

from conversation_service.graph.state import GraphState

logger = logging.getLogger(__name__)
from conversation_service.rag.generator import generate_answer
from conversation_service.retrieval.result_formatter import (
    build_retrieval_result,
)
from conversation_service.retrieval.retriever_service import (
    retrieve_documents,
)


def retrieve_node(
    state: GraphState,
    retriever: VectorStoreRetriever,
) -> dict[str, object]:
    search_query = state.get(
        "search_query",
        state["question"],
    )

    documents = retrieve_documents(
        retriever=retriever,
        question=search_query,
    )

    retrieval_result = build_retrieval_result(
        documents=documents,
    )

    retrieval_attempts = state.get("retrieval_attempts", 0) + 1

    return {
        "documents": documents,
        "context": retrieval_result["context"],
        "citations": retrieval_result["citations"],
        "retrieval_attempts": retrieval_attempts,
    }


def generate_node(
    state: GraphState,
    model: BaseChatModel,
) -> dict[str, object]:
    answer = generate_answer(
        question=state["question"],
        context=state.get("context", ""),
        model=model,
    )
    return {"answer": answer, "requires_human_review": False}


def citation_filter_node(
    state: GraphState,
    model: BaseChatModel,
) -> dict[str, object]:
    documents = state.get("documents", [])
    answer = state.get("answer", "")
    if not documents or not answer.strip():
        return {"citations": []}

    document_blocks: list[str] = []
    sources_by_number: dict[int, str] = {}
    for index, document in enumerate(documents, start=1):
        source = document.metadata.get("source", "")
        if not isinstance(source, str) or not source.strip():
            continue
        sources_by_number[index] = source
        document_blocks.append(
            f"[문서 {index}]\nsource: {source}\ncontent:\n{document.page_content}"
        )

    if not document_blocks:
        return {"citations": []}

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
/no_think

당신은 생성된 답변의 직접적인 근거 문서를
선택하는 엄격한 출처 검증기입니다.

문서별로 다음 기준을 적용하세요.

1. 문서에 답변의 핵심 내용이 직접 명시되어야 합니다.
2. 답변에 횟수, 기간, 수치 또는 조건이 있다면
   해당 값이 문서에도 명시되어야 합니다.
3. 질문과 주제만 비슷한 문서는 제외하세요.
4. 답변 작성에 실제로 필요하지 않은 문서는 제외하세요.
5. 문서 하나만 읽었을 때 해당 답변을 도출할 수 있어야
   직접 근거로 인정합니다.

예시:

답변:
로그인에 5회 연속 실패하면 계정이 30분 잠깁니다.

선택 가능:
5회 실패와 30분 잠금을 명시한 문서

선택 불가:
비밀번호 길이, 변경 주기 또는 일반적인 보안 정책만
설명한 문서

반드시 다음 JSON 형식만 출력하세요.
{{"citations": [1]}}

직접 근거가 없다면 다음과 같이 출력하세요.
{{"citations": []}}

검색 문서에 표시된 문서 번호(1부터 시작하는 정수)만 선택하세요.
파일명이나 source 값을 다시 작성하지 마세요.
설명과 마크다운은 출력하지 마세요.
""".strip(),
            ),
            (
                "human",
                (
                    "질문:\n{question}\n\n"
                    "생성된 답변:\n{answer}\n\n"
                    "검색 문서:\n{documents}"
                ),
            ),
        ]
    )
    chain = prompt | model.bind(max_tokens=64) | JsonOutputParser()
    try:
        result = chain.invoke(
            {
                "question": state["question"],
                "answer": answer,
                "documents": "\n\n".join(document_blocks),
            }
        )
        logger.debug("Citation filter response parsed")
    except Exception as error:  # noqa: BLE001 - invalid model output must fail closed
        logger.warning("Citation filter failed (%s)", type(error).__name__)
        return {"citations": []}

    selected = result.get("citations", []) if isinstance(result, dict) else []
    if not isinstance(selected, list):
        return {"citations": []}

    citations: list[str] = []
    for number in selected:
        if type(number) is not int or number not in sources_by_number:
            continue
        source = sources_by_number[number]
        if source not in citations:
            citations.append(source)
    return {"citations": citations}


def query_rewrite_node(
    state: GraphState,
    model: BaseChatModel,
) -> dict[str, object]:
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
당신은 문서 검색용 질문 재작성기입니다.

사용자의 원래 의미를 변경하지 말고,
벡터 검색에서 관련 문서를 더 잘 찾을 수 있도록
질문을 명확한 검색 문장으로 재작성하세요.

새로운 사실을 추가하지 마세요.
재작성된 질문만 출력하고
설명은 작성하지 마세요.
""".strip(),
            ),
            (
                "human",
                """
원본 질문:
{question}

이전 검색어:
{search_query}
""".strip(),
            ),
        ]
    )

    chain = prompt | model.bind(max_tokens=64) | StrOutputParser()

    rewritten_query = chain.invoke(
        {
            "question": state["question"],
            "search_query": state.get(
                "search_query",
                state["question"],
            ),
        }
    )

    rewritten_query = rewritten_query.strip()

    if not rewritten_query:
        rewritten_query = state["question"]

    return {
        "search_query": rewritten_query,
        "documents": [],
        "context": "",
        "citations": [],
        "documents_relevant": False,
    }


def no_context_node(
    state: GraphState,
) -> GraphState:
    return {
        "answer": ("검색된 문서에서 질문에 대한 근거를 찾을 수 없습니다."),
        "citations": [],
        "requires_human_review": True,
    }


MAX_RETRIEVAL_ATTEMPTS = 2


def route_after_retrieve(
    state: GraphState,
) -> str:
    documents = state.get(
        "documents",
        [],
    )

    if documents:
        return "relevance_check"

    retrieval_attempts = state.get(
        "retrieval_attempts",
        0,
    )

    if retrieval_attempts < MAX_RETRIEVAL_ATTEMPTS:
        return "query_rewrite"

    return "no_context"


def relevance_check_node(
    state: GraphState,
    model: BaseChatModel,
) -> dict[str, object]:
    documents = state.get(
        "documents",
        [],
    )

    if not documents:
        return {
            "documents": [],
            "context": "",
            "citations": [],
            "documents_relevant": False,
        }

    document_blocks = []

    for index, document in enumerate(documents):
        source = str(
            document.metadata.get(
                "source",
                "출처 없음",
            )
        )

        document_blocks.append(
            f"[문서 번호: {index}]\n출처: {source}\n내용:\n{document.page_content}"
        )

    formatted_documents = "\n\n".join(document_blocks)

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
/no_think

당신은 검색 문서 관련성 평가기입니다.

각 검색 문서가 사용자의 질문에 답하는 데
직접적인 근거로 사용할 수 있는지 판단하세요.

관련 있는 문서 번호만 쉼표로 구분하여
출력하세요.

예:
0
0,2
1,2

관련 있는 문서가 하나도 없다면
NONE만 출력하세요.

문서 번호 또는 NONE 이외의 설명은
출력하지 마세요.
""".strip(),
            ),
            (
                "human",
                """
질문:
{question}

검색 문서:
{documents}
""".strip(),
            ),
        ]
    )

    chain = prompt | model.bind(max_tokens=32) | StrOutputParser()

    result = chain.invoke(
        {
            "question": state["question"],
            "documents": formatted_documents,
        }
    )

    normalized_result = result.strip().upper()

    if normalized_result == "NONE":
        return {
            "documents": [],
            "context": "",
            "citations": [],
            "documents_relevant": False,
        }

    relevant_indexes: set[int] = set()

    for value in normalized_result.split(","):
        normalized_value = value.strip()

        if not normalized_value.isdigit():
            continue

        index = int(normalized_value)

        if 0 <= index < len(documents):
            relevant_indexes.add(index)

    relevant_documents = [
        document
        for index, document in enumerate(documents)
        if index in relevant_indexes
    ]

    if not relevant_documents:
        return {
            "documents": [],
            "context": "",
            "citations": [],
            "documents_relevant": False,
        }

    retrieval_result = build_retrieval_result(
        documents=relevant_documents,
    )

    return {
        "documents": relevant_documents,
        "context": retrieval_result["context"],
        "citations": retrieval_result["citations"],
        "documents_relevant": True,
    }


def route_after_relevance(
    state: GraphState,
) -> str:
    if state.get(
        "documents_relevant",
        False,
    ):
        return "generate"

    retrieval_attempts = state.get(
        "retrieval_attempts",
        0,
    )

    if retrieval_attempts < MAX_RETRIEVAL_ATTEMPTS:
        return "query_rewrite"

    return "no_context"


def groundedness_check_node(
    state: GraphState,
    model: BaseChatModel,
) -> dict[str, object]:
    context = state.get(
        "context",
        "",
    )
    answer = state.get(
        "answer",
        "",
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                """
당신은 RAG 답변 근거성 평가기입니다.

생성된 답변의 모든 핵심 내용이
검색 문서에서 확인되는지 판단하세요.

검색 문서로 답변을 뒷받침할 수 있으면
GROUNDED를 출력하세요.

답변에 검색 문서에서 확인할 수 없는 내용,
잘못된 수치 또는 추측이 포함되어 있으면
NOT_GROUNDED를 출력하세요.

GROUNDED 또는 NOT_GROUNDED 중
하나만 출력하고 설명은 작성하지 마세요.
""".strip(),
            ),
            (
                "human",
                """
검색 문서:
{context}

생성된 답변:
{answer}
""".strip(),
            ),
        ]
    )

    chain = prompt | model.bind(max_tokens=16) | StrOutputParser()

    result = chain.invoke(
        {
            "context": context,
            "answer": answer,
        }
    )

    normalized_result = result.strip().upper()

    is_grounded = normalized_result == "GROUNDED"

    return {
        "answer_grounded": is_grounded,
    }


def route_after_groundedness(
    state: GraphState,
) -> str:
    if state.get(
        "answer_grounded",
        False,
    ):
        return "end"

    return "review_required"


def review_required_node(
    state: GraphState,
) -> dict[str, object]:
    return {
        "answer": ("생성된 답변이 검색 문서에 충분히 근거하는지 확인하지 못했습니다."),
        "citations": [],
        "requires_human_review": True,
    }

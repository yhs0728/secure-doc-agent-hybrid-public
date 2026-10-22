import logging
from functools import lru_cache
from threading import BoundedSemaphore

import httpx
from langchain_core.runnables import Runnable
from openai import (
    APIConnectionError,
    APITimeoutError,
)

from app.exceptions import (
    LLMCapacityError,
    LLMConnectionError,
    LLMTimeoutError,
    RAGExecutionError,
)

logger = logging.getLogger(__name__)


@lru_cache(maxsize=16)
def _llm_slots(limit: int) -> BoundedSemaphore:
    return BoundedSemaphore(limit)


def _is_connection_timeout(error: BaseException) -> bool:
    """Distinguish connect timeouts from a server that stopped responding."""
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if current.__class__.__name__ == "ConnectTimeout":
            return True
        current = current.__cause__ or current.__context__
    return False


def execute_rag_question(
    graph: Runnable,
    question: str,
    max_concurrency: int | None = None,
    queue_timeout_seconds: float = 5.0,
) -> dict[str, object]:
    semaphore = _llm_slots(max_concurrency) if max_concurrency else None
    if semaphore is not None and not semaphore.acquire(timeout=queue_timeout_seconds):
        raise LLMCapacityError("LLM 요청이 많습니다. 잠시 후 다시 시도해 주세요.")
    try:
        return graph.invoke(
            {
                "question": question,
            }
        )

    # Timeout을 연결 오류보다 먼저 처리해야 합니다.
    except (
        APITimeoutError,
        httpx.TimeoutException,
        TimeoutError,
    ) as error:
        if _is_connection_timeout(error):
            logger.exception("LLM 서버 연결 시간이 초과됐습니다.")
            raise LLMConnectionError(
                "LLM 서버에 연결할 수 없습니다."
            ) from error

        logger.exception(
            "LLM 서버 응답 시간이 초과됐습니다."
        )

        raise LLMTimeoutError(
            "LLM 서버 응답 시간이 초과됐습니다."
        ) from error

    except (
        APIConnectionError,
        httpx.ConnectError,
        ConnectionError,
    ) as error:
        logger.exception(
            "LLM 서버 연결에 실패했습니다."
        )

        raise LLMConnectionError(
            "LLM 서버에 연결할 수 없습니다."
        ) from error

    except Exception as error:
        logger.exception(
            "RAG 그래프 실행에 실패했습니다."
        )

        raise RAGExecutionError(
            "RAG 요청 처리에 실패했습니다."
        ) from error
    finally:
        if semaphore is not None:
            semaphore.release()

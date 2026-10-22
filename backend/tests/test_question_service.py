from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

from app.exceptions import (
    LLMCapacityError,
    LLMConnectionError,
    LLMTimeoutError,
    RAGExecutionError,
)
from services.question_service import (
    execute_rag_question,
)


class SuccessfulGraph:
    def invoke(
        self,
        inputs: dict[str, str],
    ) -> dict[str, object]:
        assert inputs == {
            "question": "테스트 질문",
        }

        return {
            "answer": "정상 답변입니다.",
            "citations": ["policy.txt"],
            "requires_human_review": False,
        }


class TimeoutGraph:
    def invoke(
        self,
        inputs: dict[str, str],
    ) -> dict[str, object]:
        raise httpx.ReadTimeout(
            "응답 시간 초과",
        )


class ConnectionFailedGraph:
    def invoke(
        self,
        inputs: dict[str, str],
    ) -> dict[str, object]:
        raise httpx.ConnectError(
            "연결 실패",
        )


class ConnectionTimeoutGraph:
    def invoke(self, inputs: dict[str, str]) -> dict[str, object]:
        raise httpx.ConnectTimeout("연결 시간 초과")


class UnexpectedErrorGraph:
    def invoke(
        self,
        inputs: dict[str, str],
    ) -> dict[str, object]:
        raise RuntimeError(
            "예상하지 못한 오류",
        )


def test_execute_rag_question() -> None:
    result = execute_rag_question(
        graph=SuccessfulGraph(),
        question="테스트 질문",
    )

    assert result == {
        "answer": "정상 답변입니다.",
        "citations": ["policy.txt"],
        "requires_human_review": False,
    }


def test_execute_rag_question_handles_timeout(
) -> None:
    with pytest.raises(
        LLMTimeoutError,
        match="LLM 서버 응답 시간이 초과됐습니다.",
    ):
        execute_rag_question(
            graph=TimeoutGraph(),
            question="테스트 질문",
        )


def test_execute_rag_question_handles_connection_error(
) -> None:
    with pytest.raises(
        LLMConnectionError,
        match="LLM 서버에 연결할 수 없습니다.",
    ):
        execute_rag_question(
            graph=ConnectionFailedGraph(),
            question="테스트 질문",
        )


def test_execute_rag_question_handles_unexpected_error(
) -> None:
    with pytest.raises(
        RAGExecutionError,
        match="RAG 요청 처리에 실패했습니다.",
    ):
        execute_rag_question(
            graph=UnexpectedErrorGraph(),
            question="테스트 질문",
        )


def test_execute_rag_question_treats_connect_timeout_as_unavailable() -> None:
    with pytest.raises(
        LLMConnectionError,
        match="LLM 서버에 연결할 수 없습니다.",
    ):
        execute_rag_question(
            graph=ConnectionTimeoutGraph(),
            question="테스트 질문",
        )


def test_execute_rag_question_applies_concurrency_backpressure() -> None:
    started = Event()
    release = Event()

    class BlockingGraph:
        def invoke(self, inputs: dict[str, str]) -> dict[str, object]:
            started.set()
            assert release.wait(timeout=2)
            return SuccessfulGraph().invoke(inputs)

    with ThreadPoolExecutor(max_workers=1) as executor:
        first = executor.submit(
            execute_rag_question,
            BlockingGraph(),
            "테스트 질문",
            1,
            1.0,
        )
        assert started.wait(timeout=1)
        with pytest.raises(LLMCapacityError):
            execute_rag_question(
                SuccessfulGraph(),
                "테스트 질문",
                max_concurrency=1,
                queue_timeout_seconds=0.01,
            )
        release.set()
        assert first.result(timeout=1)["answer"] == "정상 답변입니다."

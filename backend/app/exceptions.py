class RAGServiceError(Exception):
    """RAG 서비스의 기본 예외입니다."""


class LLMTimeoutError(RAGServiceError):
    """LLM 응답 시간 초과 예외입니다."""


class LLMConnectionError(RAGServiceError):
    """LLM 서버 연결 실패 예외입니다."""


class LLMCapacityError(RAGServiceError):
    """LLM 동시 처리 슬롯이 모두 사용 중인 경우입니다."""


class RAGExecutionError(RAGServiceError):
    """예상하지 못한 RAG 실행 예외입니다."""

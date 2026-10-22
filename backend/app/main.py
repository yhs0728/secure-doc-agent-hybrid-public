from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from langchain_core.runnables import Runnable
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api_errors import APIError, ErrorResponse, register_error_handlers
from app.auth_routes import router as auth_router
from app.dependencies import (
    get_index_service,
    get_rag_graph,
    invalidate_rag_graph,
)
from app.exceptions import (
    LLMCapacityError,
    LLMConnectionError,
    LLMTimeoutError,
    RAGExecutionError,
)
from app.index_lock import index_lock
from app.logging_config import configure_logging
from app.metrics import MetricsMiddleware, metrics_response
from app.middleware import RequestLoggingMiddleware
from app.runtime import update_persisted_index
from app.security import (
    AuthContext,
    require_admin,
    require_editor,
    require_viewer,
    tenant_settings,
)
from config.settings import Settings, get_settings
from ingestion.index_manifest import (
    load_index_manifest,
)
from models.index import (
    DocumentDeleteResponse,
    IndexStatusResponse,
    IndexUpdateResponse,
)
from models.ingestion import (
    ApiDocumentIngestRequest,
    ApiDocumentIngestResponse,
)
from models.upload import (
    DocumentUploadResponse,
)
from services.api_ingestion_service import (
    ingest_api_document,
)
from services.document_management_service import (
    AmbiguousDocumentError,
    ManagedDocumentNotFoundError,
    delete_source_document,
)
from services.document_service import (
    DocumentLoadError,
    find_document_by_id,
    load_documents,
    search_documents,
)
from services.index_service import (
    IndexService,
)
from services.question_service import (
    execute_rag_question,
)
from services.upload_service import (
    DuplicateDocumentContentError,
    DuplicateUploadContentError,
    DuplicateUploadFileError,
    EmptyUploadFileError,
    UnsafeFileNameError,
    UnsupportedFileTypeError,
    UploadFileTooLargeError,
    save_uploaded_document,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DOCUMENTS_FILE = BASE_DIR / "data" / "documents.json"

configure_logging()

app = FastAPI(
    title="SecureDoc Agent API",
    description="보안 문서 질의 AI Agent",
    version="0.2.0",
    responses={
        status_code: {"model": ErrorResponse}
        for status_code in (400, 401, 403, 404, 409, 413, 415, 422, 429, 500, 503, 504)
    },
)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(MetricsMiddleware)
register_error_handlers(app)
app.include_router(auth_router)

class QuestionRequest(BaseModel):
    question: str = Field(
        min_length=1,
        max_length=1000,
    )
    conversation_id: UUID | None = None
    
    
    @field_validator("question")
    @classmethod
    def validate_question(
        cls,
        value: str,
    ) -> str:
        
        normalized_question = value.strip()
        
        if not normalized_question:
            raise ValueError(
                "질문은 비어 있을 수 없습니다."
            )
        return normalized_question
class QuestionResponse(BaseModel):
    answer: str
    citations: list[str]
    requires_human_review: bool
    conversation_id: UUID | None = None


class ConversationSummaryResponse(BaseModel):
    conversation_id: UUID
    title: str
    updated_at: datetime


class ConversationMessageResponse(BaseModel):
    message_id: UUID
    role: str
    content: str
    citations: list[str]
    requires_human_review: bool
    created_at: datetime


class ConversationDetailResponse(ConversationSummaryResponse):
    messages: list[ConversationMessageResponse]
    
class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    document_id: str
    title: str
    file_name: str
    page_count: int
    
@app.get("/api/v1/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/metrics", include_in_schema=False)
def metrics() -> object:
    return metrics_response()


@app.get("/api/v1/ready")
def readiness_check(
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    checks: dict[str, str] = {"application": "ready"}
    if settings.database_enabled:
        from database.session import check_database_connection

        checks["postgresql"] = (
            "ready" if check_database_connection() else "unavailable"
        )
    if settings.object_storage_backend != "LOCAL":
        from integrations.object_storage import S3ObjectStore

        try:
            object_ready = S3ObjectStore.from_settings(settings).healthcheck()
        except Exception:  # noqa: BLE001 - readiness reports dependency state
            object_ready = False
        checks["object_storage"] = "ready" if object_ready else "unavailable"
    if settings.search_backend == "OPENSEARCH":
        from integrations.opensearch_index import create_opensearch_client

        try:
            search_ready = bool(create_opensearch_client(settings).ping())
        except Exception:  # noqa: BLE001 - readiness reports dependency state
            search_ready = False
        checks["opensearch"] = "ready" if search_ready else "unavailable"

    unavailable = [name for name, value in checks.items() if value != "ready"]
    if unavailable:
        raise APIError(
            status_code=503,
            code="DEPENDENCY_UNAVAILABLE",
            message=f"Unavailable dependencies: {', '.join(unavailable)}",
        )
    return {"status": "ready", "checks": checks}



@app.get(
    "/api/v1/documents",
    response_model=list[DocumentResponse],
)
def get_documents(
    settings: Annotated[Settings, Depends(get_settings)],
    auth: Annotated[AuthContext, Depends(require_viewer)],
    keyword: str | None = None,
    ) -> list[DocumentResponse]:
    settings = tenant_settings(settings, auth)
    try:
        if settings.database_enabled:
            from services.postgres_persistence_service import list_postgres_documents

            matched_documents = list_postgres_documents(settings, keyword)
        else:
            documents = load_documents(DOCUMENTS_FILE)
            matched_documents = search_documents(documents, keyword)
    except DocumentLoadError as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        ) from error
        
        
    return [
        DocumentResponse.model_validate(document)
        for document in matched_documents
    ]
@app.get(
        "/api/v1/documents/{document_id}",
        response_model=DocumentResponse,
    )
    
def get_document(
        document_id: str,
        settings: Annotated[Settings, Depends(get_settings)],
        auth: Annotated[AuthContext, Depends(require_viewer)],
    ) -> DocumentResponse:
    settings = tenant_settings(settings, auth)
    try:
        if settings.database_enabled:
            from services.postgres_persistence_service import get_postgres_document

            document = get_postgres_document(settings, document_id)
        else:
            documents = load_documents(DOCUMENTS_FILE)
            document = find_document_by_id(
                documents=documents,
                document_id=document_id,
            )
    except DocumentLoadError as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        ) from error
        
    if document is None:
            raise HTTPException(
                status_code=404,
                detail="문서를 찾을 수 없습니다.",
            )
            
    return DocumentResponse.model_validate(document)




#Document는 서비스 내부에서 사용하는 도메인 객체
#DocumentResponse 외부에서 API에 공개하는 응답계약
@app.post(
    "/api/v1/questions",
    response_model=QuestionResponse,
)
def ask_question_endpoint(
    request: QuestionRequest,
    graph: Annotated[Runnable, Depends(get_rag_graph)],
    settings: Annotated[Settings, Depends(get_settings)],
    auth: Annotated[AuthContext, Depends(require_viewer)],
) -> QuestionResponse:
    return ask_question(request, graph, tenant_settings(settings, auth))


def ask_question(
    request: QuestionRequest,
    graph: Runnable,
    settings: Settings | None = None,
) -> QuestionResponse:
    conversation_id = (
        request.conversation_id
        if settings is not None and settings.database_enabled
        else None
    )
    try:
        graph_question = request.question
        if settings is not None and settings.database_enabled and conversation_id:
            from services.postgres_persistence_service import get_conversation_history

            history = get_conversation_history(settings, conversation_id)
            if history:
                turns = "\n".join(
                    f"{'사용자' if role == 'USER' else '도우미'}: {content}"
                    for role, content in history
                )
                graph_question = (
                    "다음 이전 대화를 참고해 현재 질문의 생략된 대상을 해석하세요. "
                    "답변의 사실 근거는 반드시 검색 문서에서만 찾으세요.\n\n"
                    f"이전 대화:\n{turns}\n\n현재 질문:\n{request.question}"
                )
        result = execute_rag_question(
            graph=graph,
            question=graph_question,
            max_concurrency=(settings.llm_max_concurrency if settings else None),
            queue_timeout_seconds=(
                settings.llm_queue_timeout_seconds if settings else 5.0
            ),
        )
        if settings is not None and settings.database_enabled:
            from services.postgres_persistence_service import record_question_exchange

            conversation_id = record_question_exchange(
                settings,
                request.question,
                result,
                conversation_id,
            )

    except LookupError as error:
        raise APIError(
            status_code=404,
            code="CONVERSATION_NOT_FOUND",
            message=str(error),
        ) from error

    except LLMCapacityError as error:
        raise APIError(
            status_code=429,
            code="LLM_CAPACITY_EXCEEDED",
            message=str(error),
            headers={"Retry-After": "5"},
        ) from error

    except LLMTimeoutError as error:
        raise APIError(
            status_code=504,
            code="LLM_TIMEOUT",
            message=str(error),
        ) from error

    except LLMConnectionError as error:
        raise APIError(
            status_code=503,
            code="LLM_UNAVAILABLE",
            message=str(error),
        ) from error

    except RAGExecutionError as error:
        raise APIError(
            status_code=500,
            code="RAG_EXECUTION_ERROR",
            message=str(error),
        ) from error

    return QuestionResponse(
        answer=str(result["answer"]),
        citations=list(
            result.get(
                "citations",
                [],
            )
        ),
        requires_human_review=bool(
            result.get(
                "requires_human_review",
                True,
            )
        ),
        conversation_id=conversation_id,
    )


@app.get(
    "/api/v1/conversations",
    response_model=list[ConversationSummaryResponse],
)
def list_conversations(
    settings: Annotated[Settings, Depends(get_settings)],
    auth: Annotated[AuthContext, Depends(require_viewer)],
) -> list[ConversationSummaryResponse]:
    settings = tenant_settings(settings, auth)
    if not settings.database_enabled:
        raise APIError(503, "CHAT_HISTORY_UNAVAILABLE", "대화 기록에는 PostgreSQL이 필요합니다.")
    from services.postgres_persistence_service import list_user_conversations

    return [
        ConversationSummaryResponse.model_validate(item)
        for item in list_user_conversations(settings)
    ]


@app.get(
    "/api/v1/conversations/{conversation_id}",
    response_model=ConversationDetailResponse,
)
def get_conversation(
    conversation_id: UUID,
    settings: Annotated[Settings, Depends(get_settings)],
    auth: Annotated[AuthContext, Depends(require_viewer)],
) -> ConversationDetailResponse:
    settings = tenant_settings(settings, auth)
    if not settings.database_enabled:
        raise APIError(503, "CHAT_HISTORY_UNAVAILABLE", "대화 기록에는 PostgreSQL이 필요합니다.")
    from services.postgres_persistence_service import get_user_conversation

    try:
        conversation = get_user_conversation(settings, conversation_id)
    except LookupError as error:
        raise APIError(404, "CONVERSATION_NOT_FOUND", str(error)) from error
    return ConversationDetailResponse.model_validate(conversation)


@app.post(
    "/api/v1/documents/upload",
    response_model=DocumentUploadResponse,
    status_code=201,
)
async def upload_document(
    file: Annotated[UploadFile, File()],
    settings: Annotated[Settings, Depends(get_settings)],
    auth: Annotated[AuthContext, Depends(require_editor)],
) -> DocumentUploadResponse:
    settings = tenant_settings(settings, auth)
    if file.filename is None:
        raise HTTPException(
            status_code=400,
            detail="파일 이름이 필요합니다.",
        )

    content = await file.read()

    try:
        with index_lock:
            saved_path = save_uploaded_document(
                source_directory=Path(settings.source_directory),
                file_name=file.filename,
                content=content,
            )
            if settings.database_enabled:
                from services.postgres_ingestion_service import (
                    enqueue_ingestion,
                    run_ingestion_job,
                )

                job_id = enqueue_ingestion(saved_path, settings)
                if settings.object_storage_backend == "LOCAL":
                    run_ingestion_job(job_id, settings, update_persisted_index)
            else:
                update_persisted_index(settings=settings)
            get_rag_graph.cache_clear()

    except UnsupportedFileTypeError as error:
        raise HTTPException(
            status_code=415,
            detail=str(error),
        ) from error

    except UploadFileTooLargeError as error:
        raise HTTPException(
            status_code=413,
            detail=str(error),
        ) from error

    except (
        DuplicateUploadFileError,
        DuplicateUploadContentError,
        DuplicateDocumentContentError,
    ) as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error
        
    except (
        EmptyUploadFileError,
        UnsafeFileNameError,
    ) as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    finally:
        await file.close()

    return DocumentUploadResponse(
        file_name=saved_path.name,
        size_bytes=saved_path.stat().st_size,
        status=(
            "queued"
            if settings.database_enabled
            and settings.object_storage_backend != "LOCAL"
            else "uploaded"
        ),
    )    
    
    
@app.post(
    "/api/v1/documents/ingest",
    response_model=ApiDocumentIngestResponse,
    status_code=201,
)
def ingest_document_from_api(
    request: ApiDocumentIngestRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    auth: Annotated[AuthContext, Depends(require_editor)],
) -> ApiDocumentIngestResponse:
    settings = tenant_settings(settings, auth)
    try:
        with index_lock:
            saved_path = ingest_api_document(
                source_directory=Path(settings.source_directory),
                document_id=request.document_id,
                title=request.title,
                content=request.content,
                source=request.source,
                metadata=request.metadata,
            )
            if settings.database_enabled:
                from services.postgres_ingestion_service import (
                    enqueue_ingestion,
                    run_ingestion_job,
                )

                job_id = enqueue_ingestion(saved_path, settings, request.title)
                if settings.object_storage_backend == "LOCAL":
                    run_ingestion_job(job_id, settings, update_persisted_index)
            else:
                update_persisted_index(settings=settings)
            get_rag_graph.cache_clear()

    except (
        DuplicateUploadFileError,
        DuplicateUploadContentError,
        DuplicateDocumentContentError,
    ) as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        ) from error

    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    return ApiDocumentIngestResponse(
        document_id=request.document_id,
        file_name=saved_path.name,
        status=(
            "queued"
            if settings.database_enabled
            and settings.object_storage_backend != "LOCAL"
            else "ingested"
        ),
    )
@app.post(
    "/api/v1/index/update",
    response_model=IndexUpdateResponse,
)
def update_index(
    index_service: Annotated[IndexService, Depends(get_index_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    auth: Annotated[AuthContext, Depends(require_admin)],
) -> IndexUpdateResponse:
    settings = tenant_settings(settings, auth)
    with index_lock:
        result = (
            update_persisted_index(settings)
            if settings.database_enabled
            else index_service.update_index()
        )
        if settings.database_enabled:
            from services.postgres_ingestion_service import (
                synchronize_ready_document_chunks,
            )

            synchronize_ready_document_chunks(settings)

    invalidate_rag_graph()

    return IndexUpdateResponse(
        status="updated",
        full_rebuild=result.full_rebuild,
        added=result.added,
        modified=result.modified,
        deleted=result.deleted,
        unchanged=result.unchanged,
    )
    
@app.get(
    "/api/v1/index/status",
    response_model=IndexStatusResponse,
)
def get_index_status(
    settings: Annotated[Settings, Depends(get_settings)],
    auth: Annotated[AuthContext, Depends(require_viewer)],
) -> (
    IndexStatusResponse
):
    settings = tenant_settings(settings, auth)

    if settings.search_backend == "OPENSEARCH":
        from sqlalchemy import select

        from database.models.rag import SearchIndex
        from database.session import set_local_user_context, transaction

        with transaction() as session:
            set_local_user_context(session, settings.system_user_id)
            index = session.scalar(
                select(SearchIndex).where(
                    SearchIndex.workspace_id == settings.default_workspace_id,
                    SearchIndex.backend == "OPENSEARCH",
                    SearchIndex.status == "ACTIVE",
                )
            )
            if index is None:
                raise HTTPException(status_code=404, detail="활성 인덱스가 없습니다.")
            return IndexStatusResponse(
                status="ready",
                document_count=index.document_count,
                chunk_count=index.chunk_count,
                embedding_model=settings.embedding_model,
                chunk_size=settings.chunk_size,
                chunk_overlap=settings.chunk_overlap,
            )

    manifest = load_index_manifest(
        index_directory=Path(
            settings.index_directory
        ),
    )

    if manifest is None:
        raise HTTPException(
            status_code=404,
            detail="생성된 인덱스가 없습니다.",
        )

    chunk_count = sum(
        len(document.chunk_ids)
        for document
        in manifest.documents.values()
    )

    return IndexStatusResponse(
        status="ready",
        document_count=len(
            manifest.documents
        ),
        chunk_count=chunk_count,
        embedding_model=(
            manifest.embedding_model
        ),
        chunk_size=manifest.chunk_size,
        chunk_overlap=(
            manifest.chunk_overlap
        ),
    )
    
@app.delete(
    "/api/v1/documents/{document_id}",
    response_model=DocumentDeleteResponse,
)
def delete_document(
    document_id: str,
    index_service: Annotated[IndexService, Depends(get_index_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    auth: Annotated[AuthContext, Depends(require_editor)],
) -> DocumentDeleteResponse:
    settings = tenant_settings(settings, auth)
    try:
        with index_lock:
            if settings.database_enabled:
                from services.postgres_persistence_service import (
                    complete_document_delete,
                    delete_resolved_source_file,
                    enqueue_external_document_delete,
                    resolve_document_source,
                    restore_document_after_delete_failure,
                )

                source = resolve_document_source(settings, document_id)
                if source is None:
                    raise ManagedDocumentNotFoundError(document_id)
                deleted_file = None
                try:
                    deleted_file = delete_resolved_source_file(
                        Path(settings.source_directory), source.file_name
                    )
                    if settings.database_enabled:
                        update_persisted_index(settings)
                    else:
                        index_service.update_index()
                    if source.storage_provider == "LOCAL":
                        complete_document_delete(settings, document_id)
                    else:
                        enqueue_external_document_delete(settings, source)
                except Exception:
                    if deleted_file is None or deleted_file.exists():
                        restore_document_after_delete_failure(settings, document_id)
                    raise
            else:
                deleted_file = delete_source_document(
                    source_directory=Path(settings.source_directory),
                    document_id=document_id,
                )
                index_service.update_index()
            invalidate_rag_graph()

        return DocumentDeleteResponse(
            document_id=document_id,
            file_name=deleted_file.name,
            status=(
                "deleting"
                if settings.database_enabled
                and source.storage_provider != "LOCAL"
                else "deleted"
            ),
        )

    except ManagedDocumentNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="문서를 찾을 수 없습니다.",
        )

    except AmbiguousDocumentError as error:
        raise HTTPException(
            status_code=409,
            detail=str(error),
        )

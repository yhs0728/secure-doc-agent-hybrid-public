from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from langchain_core.documents import Document as LangChainDocument
from sqlalchemy import func, select

from app.runtime import update_persisted_index
from config.settings import get_settings
from database.models.content import DocumentVersion
from database.models.rag import DocumentChunk, IngestionJob
from database.repositories.chat_repository import PostgresChatRepository
from database.session import get_session_factory, set_local_user_context, transaction
from services.postgres_ingestion_service import enqueue_ingestion, run_ingestion_job
from services.postgres_persistence_service import (
    complete_document_delete,
    delete_resolved_source_file,
    list_postgres_documents,
    resolve_document_source,
)
from services.upload_service import save_uploaded_document


def verify_runtime_integration() -> dict[str, object]:
    settings = get_settings()
    if not settings.database_enabled:
        raise RuntimeError("DATABASE_ENABLED=true가 필요합니다.")

    suffix = uuid4().hex[:12]
    file_name = f"stage6-runtime-check-{suffix}.txt"
    source_directory = Path(settings.source_directory)
    path = save_uploaded_document(
        source_directory=source_directory,
        file_name=file_name,
        content=f"SecureDoc stage 6 runtime verification {suffix}".encode(),
    )
    job_id = enqueue_ingestion(path, settings, "Stage 6 Runtime Check")
    run_ingestion_job(job_id, settings, update_persisted_index)

    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        job = session.get(IngestionJob, job_id)
        if job is None or job.document_version_id is None:
            raise RuntimeError("검증 작업이 생성되지 않았습니다.")
        version = session.get(DocumentVersion, job.document_version_id)
        chunk_count = session.scalar(
            select(func.count(DocumentChunk.id)).where(
                DocumentChunk.document_version_id == job.document_version_id
            )
        )
        if job.status != "SUCCEEDED" or version is None:
            raise RuntimeError("검증 작업이 완료되지 않았습니다.")
        if version.processing_status != "READY" or not chunk_count:
            raise RuntimeError("문서 버전 또는 청크가 준비되지 않았습니다.")

    catalog = list_postgres_documents(settings, file_name)
    if len(catalog) != 1:
        raise RuntimeError("PostgreSQL 문서 조회 결과가 일치하지 않습니다.")
    document_id = catalog[0].document_id

    session = get_session_factory()()
    tx = session.begin()
    try:
        set_local_user_context(session, settings.system_user_id)
        PostgresChatRepository(session, settings).record_exchange(
            "6단계 검증 질문",
            {
                "answer": "6단계 저장 경로가 정상입니다.",
                "citations": [file_name],
                "requires_human_review": False,
                "documents": [
                    LangChainDocument(
                        page_content=f"SecureDoc stage 6 runtime verification {suffix}",
                        metadata={
                            "source": file_name,
                            "chunk_index": 0,
                        },
                    )
                ],
            },
        )
        session.flush()
        tx.rollback()
    finally:
        session.close()

    source = resolve_document_source(settings, document_id)
    if source is None:
        raise RuntimeError("검증 문서를 삭제 단계에서 찾지 못했습니다.")
    delete_resolved_source_file(source_directory, source.file_name)
    update_persisted_index(settings=settings)
    complete_document_delete(settings, document_id)

    return {
        "ok": True,
        "job_status": "SUCCEEDED",
        "version_status": "READY",
        "chunk_count": int(chunk_count or 0),
        "catalog_read": True,
        "chat_write_rollback_verified": True,
        "cleanup": "soft-deleted",
    }


if __name__ == "__main__":
    print(json.dumps(verify_runtime_integration(), ensure_ascii=False, indent=2))

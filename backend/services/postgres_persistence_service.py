from __future__ import annotations

from pathlib import Path
from uuid import UUID

from config.settings import Settings
from database.repositories.chat_repository import PostgresChatRepository
from database.repositories.document_repository import PostgresDocumentRepository
from database.session import set_local_user_context, transaction
from models.document import Document


def list_postgres_documents(settings: Settings, keyword: str | None) -> list[Document]:
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        return PostgresDocumentRepository(
            session, settings.default_workspace_id
        ).list(keyword)


def get_postgres_document(settings: Settings, document_id: str) -> Document | None:
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        repository = PostgresDocumentRepository(session, settings.default_workspace_id)
        source = repository.find_source(document_id)
        return repository.get(source.document_id) if source else None


def resolve_document_source(settings: Settings, document_id: str):
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        repository = PostgresDocumentRepository(session, settings.default_workspace_id)
        source = repository.find_source(document_id)
        if source is not None:
            repository.mark_deleting(source)
        return source


def enqueue_external_document_delete(settings: Settings, source) -> None:
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        PostgresDocumentRepository(
            session, settings.default_workspace_id
        ).enqueue_external_delete(source)


def complete_document_delete(settings: Settings, document_id: str) -> None:
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        repository = PostgresDocumentRepository(session, settings.default_workspace_id)
        source = repository.find_source(document_id)
        if source is None:
            raise LookupError("삭제할 문서를 찾을 수 없습니다.")
        repository.complete_delete(source)


def restore_document_after_delete_failure(settings: Settings, document_id: str) -> None:
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        repository = PostgresDocumentRepository(session, settings.default_workspace_id)
        source = repository.find_source(document_id)
        if source is not None:
            repository.restore_active(source)


def record_question_exchange(
    settings: Settings,
    question: str,
    result: dict[str, object],
    conversation_id: UUID | None = None,
) -> UUID:
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        stored_conversation_id, _ = PostgresChatRepository(
            session, settings
        ).record_exchange(question, result, conversation_id)
        return stored_conversation_id


def get_conversation_history(
    settings: Settings,
    conversation_id: UUID,
    limit: int = 6,
) -> list[tuple[str, str]]:
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        return PostgresChatRepository(session, settings).conversation_history(
            conversation_id, limit
        )


def list_user_conversations(settings: Settings, limit: int = 50) -> list[dict[str, object]]:
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        conversations = PostgresChatRepository(
            session, settings
        ).list_conversations(limit)
        return [
            {
                "conversation_id": conversation.id,
                "title": conversation.title,
                "updated_at": conversation.updated_at,
            }
            for conversation in conversations
        ]


def get_user_conversation(
    settings: Settings,
    conversation_id: UUID,
) -> dict[str, object]:
    with transaction() as session:
        set_local_user_context(session, settings.system_user_id)
        conversation, messages, citations = PostgresChatRepository(
            session, settings
        ).conversation_messages(conversation_id)
        return {
            "conversation_id": conversation.id,
            "title": conversation.title,
            "updated_at": conversation.updated_at,
            "messages": [
                {
                    "message_id": message.id,
                    "role": message.role,
                    "content": message.content,
                    "citations": citations.get(message.id, []),
                    "requires_human_review": message.requires_human_review,
                    "created_at": message.created_at,
                }
                for message in messages
            ],
        }


def delete_resolved_source_file(source_directory: Path, file_name: str) -> Path:
    path = source_directory / file_name
    if path.is_file():
        path.unlink()
    return path

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from langchain_core.documents import Document as LangChainDocument
from sqlalchemy import select
from sqlalchemy.orm import Session

from config.settings import Settings
from database.models.chat import Conversation, Message, MessageCitation
from database.models.content import Document, DocumentVersion
from database.models.rag import DocumentChunk


class PostgresChatRepository:
    def __init__(self, session: Session, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    def record_exchange(
        self,
        question: str,
        result: dict[str, object],
        conversation_id: UUID | None = None,
    ) -> tuple[UUID, UUID]:
        now = datetime.now(UTC)
        conversation = (
            self._find_conversation(conversation_id) if conversation_id else None
        )
        if conversation is None:
            conversation = Conversation(
                workspace_id=self._settings.default_workspace_id,
                created_by_user_id=self._settings.system_user_id,
                title=question[:500],
                status="ACTIVE",
                model_name=self._settings.llm_model,
            )
            self._session.add(conversation)
            self._session.flush()
        conversation.updated_at = now

        previous_message_id = self._session.scalar(
            select(Message.id)
            .where(
                Message.conversation_id == conversation.id,
                Message.role == "ASSISTANT",
                Message.status == "COMPLETED",
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )

        user_message = Message(
            conversation_id=conversation.id,
            parent_message_id=previous_message_id,
            created_by_user_id=self._settings.system_user_id,
            role="USER",
            content=question,
            status="COMPLETED",
            completed_at=now,
        )
        self._session.add(user_message)
        self._session.flush()

        assistant_message = Message(
            conversation_id=conversation.id,
            parent_message_id=user_message.id,
            role="ASSISTANT",
            content=str(result.get("answer", "")),
            status="COMPLETED",
            model_name=self._settings.llm_model,
            requires_human_review=bool(result.get("requires_human_review", True)),
            completed_at=now,
        )
        self._session.add(assistant_message)
        self._session.flush()

        retrieved = result.get("documents", [])
        documents = (
            [item for item in retrieved if isinstance(item, LangChainDocument)]
            if isinstance(retrieved, list)
            else []
        )
        citations = result.get("citations", [])
        citation_names = (
            [item for item in citations if isinstance(item, str)]
            if isinstance(citations, list)
            else []
        )
        for rank, filename in enumerate(citation_names, start=1):
            self._add_citation(assistant_message.id, rank, filename, documents)
        return conversation.id, assistant_message.id

    def conversation_history(
        self,
        conversation_id: UUID,
        limit: int = 6,
    ) -> list[tuple[str, str]]:
        conversation = self._find_conversation(conversation_id)
        messages = list(
            self._session.execute(
                select(Message.role, Message.content)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.status == "COMPLETED",
                    Message.role.in_(("USER", "ASSISTANT")),
                )
                .order_by(Message.created_at.desc())
                .limit(limit)
            ).all()
        )
        return [(role, content) for role, content in reversed(messages)]

    def list_conversations(self, limit: int = 50) -> list[Conversation]:
        return list(
            self._session.scalars(
                select(Conversation)
                .where(
                    Conversation.workspace_id == self._settings.default_workspace_id,
                    Conversation.created_by_user_id == self._settings.system_user_id,
                    Conversation.status == "ACTIVE",
                    Conversation.deleted_at.is_(None),
                )
                .order_by(Conversation.updated_at.desc())
                .limit(limit)
            ).all()
        )

    def conversation_messages(
        self,
        conversation_id: UUID,
    ) -> tuple[Conversation, list[Message], dict[UUID, list[str]]]:
        conversation = self._find_conversation(conversation_id)
        messages = list(
            self._session.scalars(
                select(Message)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.status == "COMPLETED",
                    Message.role.in_(("USER", "ASSISTANT")),
                )
                .order_by(Message.created_at.asc())
            ).all()
        )
        message_ids = [message.id for message in messages]
        citations: dict[UUID, list[str]] = {}
        if message_ids:
            rows = self._session.execute(
                select(
                    MessageCitation.message_id,
                    MessageCitation.filename_snapshot,
                )
                .where(MessageCitation.message_id.in_(message_ids))
                .order_by(
                    MessageCitation.message_id,
                    MessageCitation.citation_rank,
                )
            ).all()
            for message_id, filename in rows:
                citations.setdefault(message_id, []).append(filename)
        return conversation, messages, citations

    def _find_conversation(self, conversation_id: UUID) -> Conversation:
        conversation = self._session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.workspace_id == self._settings.default_workspace_id,
                Conversation.created_by_user_id == self._settings.system_user_id,
                Conversation.status == "ACTIVE",
                Conversation.deleted_at.is_(None),
            )
        )
        if conversation is None:
            raise LookupError("대화를 찾을 수 없습니다.")
        return conversation

    def _add_citation(
        self,
        message_id: UUID,
        rank: int,
        filename: str,
        retrieved: list[LangChainDocument],
    ) -> None:
        row = self._session.execute(
            select(Document, DocumentVersion)
            .join(DocumentVersion, DocumentVersion.id == Document.current_version_id)
            .where(
                Document.workspace_id == self._settings.default_workspace_id,
                Document.deleted_at.is_(None),
                DocumentVersion.original_filename == filename,
            )
        ).one_or_none()
        document = row[0] if row else None
        version = row[1] if row else None

        retrieved_document = next(
            (
                item
                for item in retrieved
                if str(item.metadata.get("source", "")) == filename
            ),
            None,
        )
        ordinal = None
        quote = None
        if retrieved_document is not None:
            value = retrieved_document.metadata.get("chunk_index")
            ordinal = value if isinstance(value, int) else None
            quote = retrieved_document.page_content.strip() or None

        chunk = None
        if version is not None and ordinal is not None:
            chunk = self._session.scalar(
                select(DocumentChunk).where(
                    DocumentChunk.document_version_id == version.id,
                    DocumentChunk.ordinal == ordinal,
                )
            )

        self._session.add(
            MessageCitation(
                message_id=message_id,
                document_id=document.id if document else None,
                document_version_id=version.id if version else None,
                chunk_id=chunk.id if chunk else None,
                citation_rank=rank,
                filename_snapshot=filename,
                page_start_snapshot=chunk.page_start if chunk else None,
                page_end_snapshot=chunk.page_end if chunk else None,
                quote_snapshot=quote,
            )
        )

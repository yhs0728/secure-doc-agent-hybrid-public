from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin
from database.ids import new_uuid7


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED', 'DELETED')",
            name="valid_status",
        ),
        Index(
            "ix_conversations_workspace_user_recent",
            "workspace_id",
            "created_by_user_id",
            "updated_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        {"schema": "chat"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="ACTIVE"
    )
    model_name: Mapped[str | None] = mapped_column(String(500))
    generation_options: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('SYSTEM', 'USER', 'ASSISTANT', 'TOOL')",
            name="valid_role",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'STREAMING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name="valid_status",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="nonnegative_input_tokens"
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="nonnegative_output_tokens",
        ),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        {"schema": "chat"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("chat.conversations.id", ondelete="CASCADE"), nullable=False
    )
    parent_message_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("chat.messages.id", ondelete="SET NULL")
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("identity.users.id", ondelete="SET NULL")
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(500))
    prompt_version: Mapped[str | None] = mapped_column(String(100))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    retrieval_duration_ms: Mapped[int | None] = mapped_column(Integer)
    generation_duration_ms: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    requires_human_review: Mapped[bool] = mapped_column(
        nullable=False, server_default="false"
    )
    error_code: Mapped[str | None] = mapped_column(String(100))
    extra_metadata: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MessageCitation(Base):
    __tablename__ = "message_citations"
    __table_args__ = (
        UniqueConstraint("message_id", "citation_rank"),
        CheckConstraint("citation_rank >= 1", name="positive_rank"),
        {"schema": "chat"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("chat.messages.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("content.documents.id", ondelete="SET NULL")
    )
    document_version_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("content.document_versions.id", ondelete="SET NULL")
    )
    chunk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("rag.document_chunks.id", ondelete="SET NULL")
    )
    citation_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    filename_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    page_start_snapshot: Mapped[int | None] = mapped_column(Integer)
    page_end_snapshot: Mapped[int | None] = mapped_column(Integer)
    quote_snapshot: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class MessageFeedback(Base):
    __tablename__ = "message_feedback"
    __table_args__ = (
        UniqueConstraint("message_id", "user_id"),
        CheckConstraint("rating IN (-1, 1)", name="valid_rating"),
        {"schema": "chat"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    message_id: Mapped[UUID] = mapped_column(
        ForeignKey("chat.messages.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.users.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(100))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

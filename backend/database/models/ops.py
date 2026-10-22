from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.ids import new_uuid7


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'PUBLISHED', 'FAILED')",
            name="valid_status",
        ),
        Index(
            "ix_outbox_events_available",
            "available_at",
            "created_at",
            postgresql_where=text("status IN ('PENDING', 'FAILED')"),
        ),
        UniqueConstraint("workspace_id", "event_type", "dedupe_key"),
        {"schema": "ops"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    aggregate_type: Mapped[str] = mapped_column(String(100), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PENDING"
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="10"
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(200))
    error_message: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("workspace_id", "operation", "key"),
        CheckConstraint(
            "status IN ('PROCESSING', 'COMPLETED', 'FAILED')",
            name="valid_status",
        ),
        Index("ix_idempotency_keys_expires", "expires_at"),
        {"schema": "ops"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.workspaces.id", ondelete="CASCADE"), nullable=False
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    response_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_workspace_created", "workspace_id", "created_at"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
        {"schema": "ops"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("identity.organizations.id", ondelete="SET NULL")
    )
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("identity.workspaces.id", ondelete="SET NULL")
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("identity.users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column()
    request_id: Mapped[str | None] = mapped_column(String(100))
    ip_address: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)
    result: Mapped[str] = mapped_column(String(30), nullable=False)
    details: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="nonnegative_quantity"),
        Index("ix_usage_events_org_created", "organization_id", "created_at"),
        {"schema": "ops"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.organizations.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("identity.workspaces.id", ondelete="SET NULL")
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("identity.users.id", ondelete="SET NULL")
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(500))
    request_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

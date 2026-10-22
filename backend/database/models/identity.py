from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base, TimestampMixin
from database.ids import new_uuid7


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'SUSPENDED', 'DELETED')",
            name="valid_status",
        ),
        {"schema": "identity"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="ACTIVE"
    )
    locale: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="ko-KR"
    )
    timezone: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="Asia/Seoul"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthIdentity(Base):
    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "provider_subject"),
        {"schema": "identity"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(500), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Organization(TimestampMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE', 'SUSPENDED', 'DELETED')",
            name="valid_status",
        ),
        {"schema": "identity"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="ACTIVE"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrganizationMember(Base):
    __tablename__ = "organization_members"
    __table_args__ = (
        CheckConstraint(
            "role IN ('OWNER', 'ADMIN', 'MEMBER', 'AUDITOR')",
            name="valid_role",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'INVITED', 'SUSPENDED')",
            name="valid_status",
        ),
        {"schema": "identity"},
    )

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.organizations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="ACTIVE"
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Workspace(TimestampMixin, Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("organization_id", "slug"),
        CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED', 'DELETED')",
            name="valid_status",
        ),
        {"schema": "identity"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.organizations.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="ACTIVE"
    )
    settings: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        CheckConstraint(
            "role IN ('ADMIN', 'EDITOR', 'VIEWER')",
            name="valid_role",
        ),
        {"schema": "identity"},
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.workspaces.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_owner_active", "user_id", "revoked_at"),
        {"schema": "identity"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_uuid7)
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.organizations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("identity.users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    scopes: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

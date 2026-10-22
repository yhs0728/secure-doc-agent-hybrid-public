from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.api_errors import APIError
from config.settings import Settings, get_settings

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    user_id: UUID
    organization_id: UUID
    workspace_id: UUID
    workspace_role: str
    auth_type: str


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _signing_key(settings: Settings) -> bytes:
    configured = (
        settings.auth_jwt_secret.get_secret_value().strip()
        if settings.auth_jwt_secret is not None
        else ""
    )
    secret = configured or settings.api_access_key.get_secret_value()
    return secret.encode("utf-8")


def create_access_token(context: AuthContext, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(context.user_id),
        "org": str(context.organization_id),
        "workspace": str(context.workspace_id),
        "role": context.workspace_role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.auth_access_token_minutes)).timestamp()),
        "iss": settings.auth_jwt_issuer,
        "aud": settings.auth_jwt_audience,
    }
    header = {"alg": "HS256", "typ": "JWT"}
    encoded_header = _b64encode(json.dumps(header, separators=(",", ":")).encode())
    encoded_payload = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(_signing_key(settings), signing_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{_b64encode(signature)}"


def decode_access_token(token: str, settings: Settings) -> dict[str, object]:
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        expected = hmac.new(_signing_key(settings), signing_input, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(encoded_signature)):
            raise ValueError("invalid signature")
        header = json.loads(_b64decode(encoded_header))
        payload = json.loads(_b64decode(encoded_payload))
        now = int(datetime.now(UTC).timestamp())
        if header.get("alg") != "HS256" or int(payload["exp"]) <= now:
            raise ValueError("expired or unsupported token")
        if payload.get("iss") != settings.auth_jwt_issuer:
            raise ValueError("invalid issuer")
        if payload.get("aud") != settings.auth_jwt_audience:
            raise ValueError("invalid audience")
        return payload
    except (
        binascii.Error,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        raise APIError(
            status_code=401,
            code="INVALID_TOKEN",
            message="유효하지 않거나 만료된 인증 토큰입니다.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("비밀번호는 12자 이상이어야 합니다.")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32
    )
    return f"scrypt$16384$8$1${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64decode(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=32,
        )
        return hmac.compare_digest(actual, _b64decode(expected))
    except (TypeError, ValueError):
        return False


def load_token_context(payload: dict[str, object], settings: Settings) -> AuthContext:
    if not settings.database_enabled:
        raise APIError(503, "AUTH_UNAVAILABLE", "사용자 인증에는 PostgreSQL이 필요합니다.")

    from database.models.identity import (
        OrganizationMember,
        User,
        Workspace,
        WorkspaceMember,
    )
    from database.session import transaction

    try:
        user_id = UUID(str(payload["sub"]))
        workspace_id = UUID(str(payload["workspace"]))
    except (KeyError, ValueError) as error:
        raise APIError(401, "INVALID_TOKEN", "인증 토큰의 사용자 정보가 올바르지 않습니다.") from error

    with transaction() as session:
        row = session.execute(
            select(User, Workspace, WorkspaceMember, OrganizationMember)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
            .join(
                OrganizationMember,
                (OrganizationMember.user_id == User.id)
                & (OrganizationMember.organization_id == Workspace.organization_id),
            )
            .where(
                User.id == user_id,
                User.status == "ACTIVE",
                Workspace.id == workspace_id,
                Workspace.status == "ACTIVE",
                OrganizationMember.status == "ACTIVE",
            )
        ).one_or_none()
        if row is None:
            raise APIError(403, "ACCESS_DENIED", "워크스페이스 접근 권한이 없습니다.")
        user, workspace, workspace_member, _organization_member = row
        return AuthContext(
            user_id=user.id,
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            workspace_role=workspace_member.role,
            auth_type="jwt",
        )


def require_api_key(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise APIError(
            status_code=401,
            code="UNAUTHORIZED",
            message="Bearer 인증이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    supplied = credentials.credentials
    if settings.allow_legacy_api_key and secrets.compare_digest(
        supplied, settings.api_access_key.get_secret_value()
    ):
        return AuthContext(
            user_id=settings.system_user_id,
            organization_id=settings.default_organization_id,
            workspace_id=settings.default_workspace_id,
            workspace_role="ADMIN",
            auth_type="legacy_api_key",
        )
    return load_token_context(decode_access_token(supplied, settings), settings)


def require_roles(*allowed_roles: str) -> Callable[..., AuthContext]:
    allowed = set(allowed_roles)

    def dependency(
        context: Annotated[AuthContext, Depends(require_api_key)],
    ) -> AuthContext:
        if context.workspace_role not in allowed:
            raise APIError(403, "INSUFFICIENT_ROLE", "이 작업을 수행할 권한이 없습니다.")
        return context

    return dependency


require_viewer = require_roles("VIEWER", "EDITOR", "ADMIN")
require_editor = require_roles("EDITOR", "ADMIN")
require_admin = require_roles("ADMIN")


def tenant_settings(settings: Settings, context: AuthContext) -> Settings:
    return settings.model_copy(
        update={
            "system_user_id": context.user_id,
            "default_workspace_id": context.workspace_id,
            "default_organization_id": context.organization_id,
        }
    )

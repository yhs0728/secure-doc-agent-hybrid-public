from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select

from app.api_errors import APIError
from app.security import (
    AuthContext,
    create_access_token,
    hash_password,
    require_admin,
    require_api_key,
    verify_password,
)
from config.settings import Settings, get_settings
from database.models.identity import (
    AuthIdentity,
    OrganizationMember,
    User,
    Workspace,
    WorkspaceMember,
)
from database.session import transaction

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


def _normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if "@" not in normalized or len(normalized) > 320:
        raise ValueError("올바른 이메일 주소가 필요합니다.")
    return normalized


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=12, max_length=256)

    _validate_email = field_validator("email")(_normalize_email)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class CurrentUserResponse(BaseModel):
    user_id: str
    organization_id: str
    workspace_id: str
    workspace_role: str
    auth_type: str


class UserCreateRequest(BaseModel):
    email: str
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=256)
    workspace_role: str = Field(pattern="^(ADMIN|EDITOR|VIEWER)$")

    _validate_email = field_validator("email")(_normalize_email)


class UserCreateResponse(BaseModel):
    user_id: str
    email: str
    workspace_id: str
    workspace_role: str


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(min_length=12, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


@router.post("/login", response_model=TokenResponse)
def login(
    request: LoginRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    if not settings.database_enabled:
        raise APIError(503, "AUTH_UNAVAILABLE", "사용자 인증에는 PostgreSQL이 필요합니다.")
    with transaction() as session:
        row = session.execute(
            select(User, AuthIdentity, Workspace, WorkspaceMember)
            .join(AuthIdentity, AuthIdentity.user_id == User.id)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
            .where(
                User.email == request.email,
                User.status == "ACTIVE",
                AuthIdentity.provider == "LOCAL",
                AuthIdentity.provider_subject == request.email,
                Workspace.id == settings.default_workspace_id,
                Workspace.status == "ACTIVE",
            )
        ).one_or_none()
        if row is None or not verify_password(request.password, row.AuthIdentity.password_hash):
            raise APIError(401, "INVALID_CREDENTIALS", "이메일 또는 비밀번호가 올바르지 않습니다.")
        user, identity, workspace, membership = row
        user.last_login_at = datetime.now(UTC)
        identity.last_used_at = user.last_login_at
        context = AuthContext(
            user_id=user.id,
            organization_id=workspace.organization_id,
            workspace_id=workspace.id,
            workspace_role=membership.role,
            auth_type="jwt",
        )
    return TokenResponse(
        access_token=create_access_token(context, settings),
        expires_in=settings.auth_access_token_minutes * 60,
    )


@router.get("/me", response_model=CurrentUserResponse)
def me(context: Annotated[AuthContext, Depends(require_api_key)]) -> CurrentUserResponse:
    return CurrentUserResponse(
        user_id=str(context.user_id),
        organization_id=str(context.organization_id),
        workspace_id=str(context.workspace_id),
        workspace_role=context.workspace_role,
        auth_type=context.auth_type,
    )


@router.post("/change-password", status_code=204)
def change_password(
    request: PasswordChangeRequest,
    context: Annotated[AuthContext, Depends(require_api_key)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    if not settings.database_enabled:
        raise APIError(503, "AUTH_UNAVAILABLE", "사용자 인증에는 PostgreSQL이 필요합니다.")
    with transaction() as session:
        identity = session.scalar(
            select(AuthIdentity).where(
                AuthIdentity.user_id == context.user_id,
                AuthIdentity.provider == "LOCAL",
            )
        )
        if identity is None or not verify_password(
            request.current_password, identity.password_hash
        ):
            raise APIError(401, "INVALID_CREDENTIALS", "현재 비밀번호가 올바르지 않습니다.")
        if verify_password(request.new_password, identity.password_hash):
            raise APIError(400, "PASSWORD_UNCHANGED", "새 비밀번호는 기존 비밀번호와 달라야 합니다.")
        identity.password_hash = hash_password(request.new_password)


@router.post("/users", response_model=UserCreateResponse, status_code=201)
def create_user(
    request: UserCreateRequest,
    context: Annotated[AuthContext, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserCreateResponse:
    if not settings.database_enabled:
        raise APIError(503, "AUTH_UNAVAILABLE", "사용자 인증에는 PostgreSQL이 필요합니다.")
    with transaction() as session:
        if session.scalar(select(User.id).where(User.email == request.email)):
            raise APIError(409, "EMAIL_ALREADY_EXISTS", "이미 등록된 이메일입니다.")
        user = User(email=request.email, display_name=request.display_name.strip())
        session.add(user)
        session.flush()
        session.add(
            AuthIdentity(
                user_id=user.id,
                provider="LOCAL",
                provider_subject=request.email,
                password_hash=hash_password(request.password),
            )
        )
        session.add(
            WorkspaceMember(
                workspace_id=context.workspace_id,
                user_id=user.id,
                role=request.workspace_role,
            )
        )
        session.add(
            OrganizationMember(
                organization_id=context.organization_id,
                user_id=user.id,
                role="MEMBER",
                status="ACTIVE",
            )
        )
        user_id = user.id
    return UserCreateResponse(
        user_id=str(user_id),
        email=request.email,
        workspace_id=str(context.workspace_id),
        workspace_role=request.workspace_role,
    )

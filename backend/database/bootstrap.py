from uuid import UUID

from sqlalchemy import select

from config.settings import get_settings
from database.models.identity import (
    Organization,
    OrganizationMember,
    User,
    Workspace,
    WorkspaceMember,
)
from database.session import transaction

SYSTEM_USER_ID = UUID("00000000-0000-7000-8000-000000000001")
DEFAULT_ORGANIZATION_ID = UUID("00000000-0000-7000-8000-000000000002")
DEFAULT_WORKSPACE_ID = UUID("00000000-0000-7000-8000-000000000003")


def bootstrap_default_tenant() -> None:
    settings = get_settings()
    if settings.system_user_id != SYSTEM_USER_ID:
        raise ValueError("초기 마이그레이션의 SYSTEM_USER_ID와 설정값이 다릅니다.")
    if settings.default_workspace_id != DEFAULT_WORKSPACE_ID:
        raise ValueError(
            "초기 마이그레이션의 DEFAULT_WORKSPACE_ID와 설정값이 다릅니다."
        )

    with transaction() as session:
        user = session.scalar(select(User).where(User.id == SYSTEM_USER_ID))
        if user is None:
            session.add(
                User(
                    id=SYSTEM_USER_ID,
                    email="system@secure-doc.local",
                    display_name="SecureDoc System",
                    status="ACTIVE",
                )
            )

        organization = session.scalar(
            select(Organization).where(Organization.id == DEFAULT_ORGANIZATION_ID)
        )
        if organization is None:
            session.add(
                Organization(
                    id=DEFAULT_ORGANIZATION_ID,
                    name="SecureDoc Internal",
                    slug="secure-doc-internal",
                    status="ACTIVE",
                )
            )

        workspace = session.scalar(
            select(Workspace).where(Workspace.id == DEFAULT_WORKSPACE_ID)
        )
        if workspace is None:
            session.add(
                Workspace(
                    id=DEFAULT_WORKSPACE_ID,
                    organization_id=DEFAULT_ORGANIZATION_ID,
                    name="Default Workspace",
                    slug="default",
                    status="ACTIVE",
                )
            )

        session.flush()
        if (
            session.get(OrganizationMember, (DEFAULT_ORGANIZATION_ID, SYSTEM_USER_ID))
            is None
        ):
            session.add(
                OrganizationMember(
                    organization_id=DEFAULT_ORGANIZATION_ID,
                    user_id=SYSTEM_USER_ID,
                    role="OWNER",
                    status="ACTIVE",
                )
            )
        if session.get(WorkspaceMember, (DEFAULT_WORKSPACE_ID, SYSTEM_USER_ID)) is None:
            session.add(
                WorkspaceMember(
                    workspace_id=DEFAULT_WORKSPACE_ID,
                    user_id=SYSTEM_USER_ID,
                    role="ADMIN",
                )
            )


if __name__ == "__main__":
    bootstrap_default_tenant()
    print("Default organization, workspace, and system user are ready.")

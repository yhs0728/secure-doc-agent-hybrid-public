from collections.abc import Iterator
from contextlib import contextmanager
from uuid import uuid4

import pytest

from app.api_errors import APIError
from app.security import (
    AuthContext,
    create_access_token,
    decode_access_token,
    hash_password,
    require_editor,
    verify_password,
)
from config.settings import Settings


def settings() -> Settings:
    return Settings(
        llm_model="test-model",
        llm_api_key="test-llm-key",
        api_access_key="legacy-api-key",
        auth_jwt_secret="jwt-signing-key-that-is-long-enough",
    )


def test_password_hash_round_trip() -> None:
    encoded = hash_password("correct-horse-battery-staple")

    assert verify_password("correct-horse-battery-staple", encoded)
    assert not verify_password("wrong-password-value", encoded)
    assert "correct-horse" not in encoded


def test_access_token_round_trip() -> None:
    context = AuthContext(
        user_id=uuid4(),
        organization_id=uuid4(),
        workspace_id=uuid4(),
        workspace_role="EDITOR",
        auth_type="jwt",
    )

    payload = decode_access_token(create_access_token(context, settings()), settings())

    assert payload["sub"] == str(context.user_id)
    assert payload["workspace"] == str(context.workspace_id)
    assert payload["role"] == "EDITOR"


def test_access_token_rejects_tampering() -> None:
    context = AuthContext(uuid4(), uuid4(), uuid4(), "VIEWER", "jwt")
    token = create_access_token(context, settings())

    with pytest.raises(APIError):
        decode_access_token(token[:-1] + ("a" if token[-1] != "a" else "b"), settings())


@pytest.mark.parametrize("token", ["not-a-jwt", "@@@.@@@.@@@"])
def test_access_token_rejects_malformed_input(token: str) -> None:
    with pytest.raises(APIError) as raised:
        decode_access_token(token, settings())

    assert raised.value.status_code == 401


def test_viewer_cannot_use_editor_operation() -> None:
    context = AuthContext(uuid4(), uuid4(), uuid4(), "VIEWER", "jwt")

    with pytest.raises(APIError) as raised:
        require_editor(context)

    assert raised.value.status_code == 403


def test_api_error_propagates_through_context_manager() -> None:
    @contextmanager
    def transaction_scope() -> Iterator[None]:
        yield

    with pytest.raises(APIError) as raised:
        with transaction_scope():
            raise APIError(401, "INVALID_CREDENTIALS", "Invalid credentials")

    assert raised.value.status_code == 401

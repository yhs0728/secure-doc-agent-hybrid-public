# FastAPI dependency markers are intentional function defaults.
# ruff: noqa: B008
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request, Response
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field, field_validator

from .platform import create_app, db, migrate, require_role, required


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def unb64(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${b64(salt)}${b64(digest)}"


def verify_password(password, encoded):
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt" or (int(n), int(r), int(p)) != (16384, 8, 1):
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=unb64(salt), n=16384, r=8, p=1, dklen=32
        )
        return hmac.compare_digest(actual, unb64(expected))
    except (ValueError, TypeError, AttributeError):
        return False


def signing_key():
    key = required("AUTH_JWT_SECRET")
    if len(key) < 32:
        raise RuntimeError("AUTH_JWT_SECRET must be at least 32 characters")
    return key.encode()


def issue_token(user, workspace_id):
    now = int(time.time())
    payload = {
        "sub": str(user["id"]),
        "workspace": str(workspace_id),
        "ver": user["token_version"],
        "iat": now,
        "exp": now + int(os.getenv("AUTH_ACCESS_TOKEN_MINUTES", "30")) * 60,
        "iss": "secure-doc-identity",
        "aud": "secure-doc-services",
    }
    unsigned = (
        b64(b'{"alg":"HS256","typ":"JWT"}')
        + "."
        + b64(json.dumps(payload, separators=(",", ":")).encode())
    )
    return (
        unsigned
        + "."
        + b64(hmac.new(signing_key(), unsigned.encode(), hashlib.sha256).digest())
    )


def current_user(request: Request):
    try:
        scheme, token = request.headers.get("Authorization", "").split(" ", 1)
        if scheme.lower() != "bearer" or len(token) > 8192:
            raise ValueError("invalid bearer")
        head, body, sig = token.split(".")
        expected = hmac.new(
            signing_key(), f"{head}.{body}".encode(), hashlib.sha256
        ).digest()
        header = json.loads(unb64(head))
        if (
            not hmac.compare_digest(expected, unb64(sig))
            or not isinstance(header, dict)
            or header.get("alg") != "HS256"
        ):
            raise ValueError("invalid signature")
        claims = json.loads(unb64(body))
        if not isinstance(claims, dict) or not isinstance(claims.get("ver"), int):
            raise TypeError("invalid token version")
        if (
            claims["exp"] <= time.time()
            or claims["iss"] != "secure-doc-identity"
            or claims["aud"] != "secure-doc-services"
        ):
            raise ValueError("invalid claims")
        uid, wid = UUID(claims["sub"]), UUID(claims["workspace"])
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(
            401, "INVALID_TOKEN", headers={"WWW-Authenticate": "Bearer"}
        ) from exc
    with db() as conn:
        row = conn.execute(
            """SELECT u.id AS user_id,w.id AS workspace_id,w.organization_id,m.role AS workspace_role
            FROM users u JOIN memberships m ON m.user_id=u.id JOIN workspaces w ON w.id=m.workspace_id
            WHERE u.id=%s AND w.id=%s AND u.active AND w.active AND u.token_version=%s""",
            (uid, wid, claims["ver"]),
        ).fetchone()
    if not row:
        raise HTTPException(401, "INVALID_TOKEN")
    return {**{k: str(v) for k, v in row.items()}, "auth_type": "jwt"}


@asynccontextmanager
async def lifespan(app):
    signing_key()
    migrate()
    email = os.getenv("BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
    if email:
        password = required("BOOTSTRAP_ADMIN_PASSWORD")
        if not 12 <= len(password) <= 256:
            raise RuntimeError(
                "BOOTSTRAP_ADMIN_PASSWORD must contain 12 to 256 characters"
            )
        with db() as conn:
            wid = UUID(
                os.getenv(
                    "DEFAULT_WORKSPACE_ID", "00000000-0000-7000-8000-000000000003"
                )
            )
            oid = UUID(
                os.getenv(
                    "DEFAULT_ORGANIZATION_ID", "00000000-0000-7000-8000-000000000002"
                )
            )
            conn.execute(
                "INSERT INTO workspaces(id,organization_id,name) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                (wid, oid, "Default Workspace"),
            )
            user = conn.execute(
                "SELECT id FROM users WHERE email=%s", (email,)
            ).fetchone()
            if not user:
                uid = uuid4()
                conn.execute(
                    "INSERT INTO users(id,email,display_name,password_hash) VALUES(%s,%s,%s,%s)",
                    (uid, email, "Administrator", hash_password(password)),
                )
                conn.execute(
                    "INSERT INTO memberships(workspace_id,user_id,role) VALUES(%s,%s,%s)",
                    (wid, uid, "ADMIN"),
                )
    yield


app = create_app(lifespan)


class Login(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=12, max_length=256)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if "@" not in value:
            raise ValueError("invalid email")
        return value


class NewUser(Login):
    display_name: str = Field(min_length=1, max_length=200)
    workspace_role: str = Field(pattern="^(ADMIN|EDITOR|VIEWER)$")


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=12, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


@app.post("/api/v1/auth/login")
def login(body: Login):
    with db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE email=%s AND active", (body.email,)
        ).fetchone()
        if not user or not verify_password(body.password, user["password_hash"]):
            raise HTTPException(401, "INVALID_CREDENTIALS")
        workspace = conn.execute(
            """SELECT w.id FROM workspaces w JOIN memberships m ON m.workspace_id=w.id
            WHERE m.user_id=%s AND w.id=%s AND w.active""",
            (
                user["id"],
                UUID(
                    os.getenv(
                        "DEFAULT_WORKSPACE_ID", "00000000-0000-7000-8000-000000000003"
                    )
                ),
            ),
        ).fetchone()
        if not workspace:
            raise HTTPException(403, "ACCESS_DENIED")
    return {
        "access_token": issue_token(user, workspace["id"]),
        "token_type": "bearer",
        "expires_in": int(os.getenv("AUTH_ACCESS_TOKEN_MINUTES", "30")) * 60,
    }


@app.get("/api/v1/auth/me")
def me(context=Depends(current_user)):
    return context


@app.post("/api/v1/auth/users", status_code=201)
def create_user(body: NewUser, context=Depends(current_user)):
    require_role(context, "ADMIN")
    uid = uuid4()
    try:
        with db() as conn:
            conn.execute(
                "INSERT INTO users(id,email,display_name,password_hash) VALUES(%s,%s,%s,%s)",
                (uid, body.email, body.display_name, hash_password(body.password)),
            )
            conn.execute(
                "INSERT INTO memberships(workspace_id,user_id,role) VALUES(%s,%s,%s)",
                (UUID(context["workspace_id"]), uid, body.workspace_role),
            )
    except UniqueViolation as exc:
        raise HTTPException(409, "EMAIL_ALREADY_EXISTS") from exc
    return {
        "user_id": str(uid),
        "email": body.email,
        "workspace_id": context["workspace_id"],
        "workspace_role": body.workspace_role,
    }


@app.post("/api/v1/auth/change-password", status_code=204)
def change_password(body: PasswordChange, context=Depends(current_user)):
    with db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE id=%s FOR UPDATE", (UUID(context["user_id"]),)
        ).fetchone()
        if not verify_password(body.current_password, user["password_hash"]):
            raise HTTPException(401, "INVALID_CREDENTIALS")
        if body.new_password == body.current_password:
            raise HTTPException(400, "PASSWORD_UNCHANGED")
        conn.execute(
            "UPDATE users SET password_hash=%s,token_version=token_version+1 WHERE id=%s",
            (hash_password(body.new_password), UUID(context["user_id"])),
        )
    return Response(status_code=204)

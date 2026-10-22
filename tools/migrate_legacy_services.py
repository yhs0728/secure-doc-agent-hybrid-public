"""Offline, additive migration. Source is read-only; existing source volumes are untouched.

Run without --apply to validate and count. DSNs are read from environment, never CLI arguments.
Requires the new service migrations to have run, and target administrative credentials.
"""

import argparse
import hashlib
import os
from pathlib import Path
from uuid import uuid4

import boto3
import psycopg
from dotenv import dotenv_values
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]


def source_bytes(row, source_dir, legacy):
    candidate = (source_dir / row["original_filename"]).resolve()
    if candidate.parent != source_dir.resolve():
        raise ValueError("Unsafe legacy source filename")
    if candidate.is_file():
        content = candidate.read_bytes()
    elif row.get("object_key"):
        client = boto3.client(
            "s3",
            endpoint_url=os.getenv("LEGACY_OBJECT_STORAGE_ENDPOINT_URL")
            or legacy.get("OBJECT_STORAGE_ENDPOINT_URL"),
            aws_access_key_id=legacy.get("OBJECT_STORAGE_ACCESS_KEY")
            or legacy.get("MINIO_ROOT_USER"),
            aws_secret_access_key=legacy.get("OBJECT_STORAGE_SECRET_KEY")
            or legacy.get("MINIO_ROOT_PASSWORD"),
            region_name=legacy.get("OBJECT_STORAGE_REGION", "us-east-1"),
        )
        response = client.get_object(Bucket=row["bucket"], Key=row["object_key"])
        try:
            content = response["Body"].read()
        finally:
            response["Body"].close()
    else:
        raise ValueError("Legacy original is unavailable; migration stopped")
    if hashlib.sha256(content).hexdigest() != row["checksum_sha256"]:
        raise ValueError("Legacy original checksum mismatch; migration stopped")
    return content


def run(source, target, source_dir, legacy, apply=False):
    # No source writes, including accidental writes by future edits to this script.
    source.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    users = source.execute("""SELECT u.*,a.password_hash FROM identity.users u LEFT JOIN identity.auth_identities a
        ON a.user_id=u.id AND a.provider='LOCAL' """).fetchall()
    workspaces = source.execute("""SELECT w.*,o.status AS organization_status FROM identity.workspaces w
        JOIN identity.organizations o ON o.id=w.organization_id""").fetchall()
    members = source.execute("""SELECT m.* FROM identity.workspace_members m
        JOIN identity.workspaces w ON w.id=m.workspace_id JOIN identity.organization_members o
        ON o.organization_id=w.organization_id AND o.user_id=m.user_id WHERE o.status='ACTIVE' """).fetchall()
    documents = source.execute("""SELECT d.id,d.workspace_id,d.created_by_user_id,d.title,v.original_filename,
        v.checksum_sha256,v.page_count,s.bucket,s.object_key FROM content.documents d
        JOIN content.document_versions v ON v.id=d.current_version_id
        LEFT JOIN content.document_artifacts a ON a.document_version_id=v.id AND a.artifact_type='SOURCE'
        LEFT JOIN content.storage_objects s ON s.id=a.storage_object_id
        WHERE d.lifecycle_status='ACTIVE' AND d.deleted_at IS NULL""").fetchall()
    conversations = source.execute(
        "SELECT * FROM chat.conversations WHERE status='ACTIVE' AND deleted_at IS NULL"
    ).fetchall()
    messages = source.execute(
        "SELECT * FROM chat.messages WHERE status='COMPLETED' AND role IN ('USER','ASSISTANT') ORDER BY created_at,id"
    ).fetchall()
    citations = source.execute(
        "SELECT * FROM chat.message_citations ORDER BY message_id,citation_rank"
    ).fetchall()
    counts = {
        "users": len(users),
        "workspaces": len(workspaces),
        "documents": len(documents),
        "conversations": len(conversations),
        "messages": len(messages),
    }
    # Validate every original before importing anything. Do not silently discard missing documents.
    for row in documents:
        source_bytes(row, source_dir, legacy)
    if not apply:
        return counts
    for row in users:
        conflict = target.execute(
            "SELECT id FROM ms_identity.users WHERE email=%s", (row["email"],)
        ).fetchone()
        if conflict and conflict["id"] != row["id"]:
            raise ValueError(
                "Bootstrap email conflicts with a legacy user. Use a distinct bootstrap email in the empty target."
            )
        target.execute(
            """INSERT INTO ms_identity.users(id,email,display_name,password_hash,active,created_at)
            VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
            (
                row["id"],
                row["email"],
                row["display_name"],
                row["password_hash"],
                row["status"] == "ACTIVE" and row["deleted_at"] is None,
                row["created_at"],
            ),
        )
    for row in workspaces:
        target.execute(
            "INSERT INTO ms_identity.workspaces(id,organization_id,name,active) VALUES(%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING",
            (
                row["id"],
                row["organization_id"],
                row["name"],
                row["status"] == "ACTIVE"
                and row["organization_status"] == "ACTIVE"
                and row["deleted_at"] is None,
            ),
        )
    for row in members:
        target.execute(
            "INSERT INTO ms_identity.memberships(workspace_id,user_id,role) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
            (row["workspace_id"], row["user_id"], row["role"]),
        )
    for row in documents:
        content = source_bytes(row, source_dir, legacy)
        inserted = target.execute(
            """INSERT INTO ms_knowledge.documents(id,workspace_id,created_by,external_id,title,file_name,
            checksum,size_bytes,page_count,object_key,staged_content) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(id) DO NOTHING RETURNING id""",
            (
                row["id"],
                row["workspace_id"],
                row["created_by_user_id"],
                Path(row["original_filename"]).stem,
                row["title"],
                row["original_filename"],
                row["checksum_sha256"],
                len(content),
                row["page_count"],
                f"{row['workspace_id']}/{row['id']}/{row['original_filename']}",
                content,
            ),
        ).fetchone()
        if inserted:
            target.execute(
                "INSERT INTO ms_knowledge.jobs(id,document_id,workspace_id,kind) VALUES(%s,%s,%s,%s)",
                (uuid4(), row["id"], row["workspace_id"], "INDEX"),
            )
    conversation_map = {row["id"]: row for row in conversations}
    for row in conversations:
        target.execute(
            """INSERT INTO ms_conversation.conversations(id,workspace_id,user_id,title,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
            (
                row["id"],
                row["workspace_id"],
                row["created_by_user_id"],
                row["title"],
                row["created_at"],
                row["updated_at"],
            ),
        )
    citation_map = {}
    for row in citations:
        citation_map.setdefault(row["message_id"], []).append(
            {
                "source": row["filename_snapshot"],
                "document_id": str(row["document_id"]) if row["document_id"] else None,
                "chunk_id": str(row["chunk_id"]) if row["chunk_id"] else None,
                "page": row["page_start_snapshot"],
                "quote": row["quote_snapshot"],
                "score": row["relevance_score"],
            }
        )
    for row in messages:
        conversation = conversation_map.get(row["conversation_id"])
        if conversation:
            target.execute(
                """INSERT INTO ms_conversation.messages(id,conversation_id,workspace_id,user_id,role,content,
                citations,requires_human_review,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING""",
                (
                    row["id"],
                    row["conversation_id"],
                    conversation["workspace_id"],
                    conversation["created_by_user_id"],
                    row["role"],
                    row["content"],
                    Jsonb(citation_map.get(row["id"], [])),
                    row["requires_human_review"],
                    row["created_at"],
                ),
            )
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--source-dir", type=Path, default=ROOT / "backend/data/source")
    parser.add_argument("--legacy-env", type=Path, default=ROOT / ".env")
    args = parser.parse_args()
    old = os.environ["LEGACY_DATABASE_URL"].replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    new = os.environ["MICROSERVICES_ADMIN_DATABASE_URL"].replace(
        "postgresql+psycopg://", "postgresql://", 1
    )
    if old == new:
        raise SystemExit("Use a separate target database for the initial cutover")
    with (
        psycopg.connect(old, row_factory=dict_row) as source,
        psycopg.connect(new, row_factory=dict_row) as target,
    ):
        counts = run(
            source, target, args.source_dir, dotenv_values(args.legacy_env), args.apply
        )
    print(("Imported" if args.apply else "Validated only"), counts)


if __name__ == "__main__":
    main()

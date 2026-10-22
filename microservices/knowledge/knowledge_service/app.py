# FastAPI dependency markers are intentional function defaults.
# ruff: noqa: B008
import hashlib
import hmac
import os
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from uuid import UUID, uuid4

from fastapi import Depends, File, HTTPException, Request, UploadFile
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field

from . import storage
from .parsing import SUPPORTED
from .platform import authorize, create_app, db, migrate, require_role, required


@asynccontextmanager
async def lifespan(app):
    if len(required("KNOWLEDGE_SERVICE_TOKEN")) < 32:
        raise RuntimeError("KNOWLEDGE_SERVICE_TOKEN must be at least 32 characters")
    if os.getenv("APP_ENVIRONMENT") == "production":
        if (
            not required("OPENSEARCH_URL").startswith("https://")
            or os.getenv("OPENSEARCH_VERIFY_CERTS", "true") != "true"
        ):
            raise RuntimeError("Production search requires verified HTTPS")
        if not required("OBJECT_STORAGE_ENDPOINT_URL").startswith("https://"):
            raise RuntimeError("Production storage requires HTTPS")
    migrate()
    # Readiness must include the model: loading it on the first search can exceed
    # the conversation service's dependency timeout even with cached weights.
    if os.getenv("APP_ENVIRONMENT") != "test":
        storage.embedding_model()
    yield


app = create_app(lifespan)


def queue_metrics():
    with db() as conn:
        rows = conn.execute(
            "SELECT status,count(*) AS count FROM jobs GROUP BY status"
        ).fetchall()
        unresolved = conn.execute(
            """SELECT count(*) AS count FROM (
                SELECT DISTINCT ON (workspace_id,document_id) status FROM jobs
                ORDER BY workspace_id,document_id,created_at DESC,id DESC
            ) latest WHERE status='FAILED'"""
        ).fetchone()["count"]
        age = conn.execute(
            "SELECT coalesce(extract(epoch FROM now()-min(created_at)),0) AS age FROM jobs WHERE status IN ('PENDING','RUNNING')"
        ).fetchone()["age"]
        timings = conn.execute("""SELECT coalesce(avg(preparation_ms),0) AS preparation,
            coalesce(avg(publication_ms),0) AS publication,coalesce(avg(lock_wait_ms),0) AS lock_wait
            FROM jobs WHERE finished_at>now()-interval '24 hours' """).fetchone()
    return (
        "# TYPE secure_doc_knowledge_jobs gauge\n"
        + "".join(
            f'secure_doc_knowledge_jobs{{status="{row["status"]}"}} {row["count"]}\n'
            for row in rows
        )
        + "# TYPE secure_doc_knowledge_unresolved_jobs gauge\n"
        + f"secure_doc_knowledge_unresolved_jobs {unresolved}\n"
        + f"# TYPE secure_doc_knowledge_oldest_job_seconds gauge\nsecure_doc_knowledge_oldest_job_seconds {age}\n"
        + "".join(
            f"secure_doc_knowledge_job_{name}_milliseconds {value}\n"
            for name, value in timings.items()
        )
    )


app.state.extra_metrics = queue_metrics


def view(row):
    return {
        "document_id": str(row["id"]),
        "title": row["title"],
        "file_name": row["file_name"],
        "page_count": row["page_count"],
        "processing_status": row["state"],
        "error_code": row["error_code"],
    }


def find(conn, identifier, lock=False):
    return conn.execute(
        """SELECT * FROM documents WHERE (id::text=%s OR external_id=%s)
        AND state<>'DELETED' ORDER BY id LIMIT 1"""
        + (" FOR UPDATE" if lock else ""),
        (identifier, identifier),
    ).fetchone()


def enqueue(conn, document_id, workspace_id, kind):
    job_id = uuid4()
    conn.execute(
        "INSERT INTO jobs(id,document_id,workspace_id,kind) VALUES(%s,%s,%s,%s)",
        (job_id, document_id, UUID(str(workspace_id)), kind),
    )
    return job_id


def save_document(context, file_name, content, title=None, external_id=None):
    if (
        not file_name
        or "/" in file_name
        or "\\" in file_name
        or any(ord(c) < 32 for c in file_name)
        or len(file_name) > 240
    ):
        raise HTTPException(400, "UNSAFE_FILE_NAME")
    if PurePosixPath(file_name).suffix.lower() not in SUPPORTED:
        raise HTTPException(415, "UNSUPPORTED_FILE_TYPE")
    if not content:
        raise HTTPException(400, "EMPTY_FILE")
    if len(content) > int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))):
        raise HTTPException(413, "UPLOAD_TOO_LARGE")
    did = uuid4()
    checksum = hashlib.sha256(content).hexdigest()
    try:
        with db(context) as conn:
            conn.execute(
                """INSERT INTO documents(id,workspace_id,created_by,external_id,title,file_name,
                checksum,size_bytes,object_key,staged_content) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    did,
                    UUID(context["workspace_id"]),
                    UUID(context["user_id"]),
                    external_id or PurePosixPath(file_name).stem,
                    title or PurePosixPath(file_name).stem,
                    file_name,
                    checksum,
                    len(content),
                    f"{context['workspace_id']}/{did}/{file_name}",
                    content,
                ),
            )
            enqueue(conn, did, context["workspace_id"], "INDEX")
    except UniqueViolation as exc:
        raise HTTPException(409, "DUPLICATE_DOCUMENT") from exc
    return {
        "document_id": str(did),
        "file_name": file_name,
        "size_bytes": len(content),
        "status": "queued",
    }


@app.get("/api/v1/documents")
def documents(keyword: str | None = None, context=Depends(authorize)):
    with db(context) as conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE state NOT IN ('DELETED','DELETING') AND (%s::text IS NULL OR title ILIKE %s OR file_name ILIKE %s) ORDER BY created_at DESC",
            (keyword, f"%{keyword}%", f"%{keyword}%"),
        ).fetchall()
    return [view(row) for row in rows]


@app.post("/api/v1/documents/upload", status_code=201)
async def upload(file: UploadFile = File(), context=Depends(authorize)):
    require_role(context, "EDITOR", "ADMIN")
    try:
        content = bytearray()
        while block := await file.read(1024 * 1024):
            content.extend(block)
            if len(content) > int(os.getenv("MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))):
                raise HTTPException(413, "UPLOAD_TOO_LARGE")
        return save_document(context, file.filename, bytes(content))
    finally:
        await file.close()


class Ingest(BaseModel):
    document_id: str = Field(min_length=1, max_length=200, pattern=r"^[\w.-]+$")
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=20 * 1024 * 1024)
    source: str | None = None
    metadata: dict = Field(default_factory=dict)


@app.post("/api/v1/documents/ingest", status_code=201)
def ingest(body: Ingest, context=Depends(authorize)):
    require_role(context, "EDITOR", "ADMIN")
    return save_document(
        context,
        body.document_id + ".txt",
        body.content.encode("utf-8"),
        body.title,
        body.document_id,
    )


@app.get("/api/v1/documents/{document_id}")
def document(document_id: str, context=Depends(authorize)):
    with db(context) as conn:
        row = find(conn, document_id)
        if not row:
            raise HTTPException(404, "DOCUMENT_NOT_FOUND")
        return view(row)


@app.delete("/api/v1/documents/{document_id}")
def delete_document(document_id: str, context=Depends(authorize)):
    require_role(context, "EDITOR", "ADMIN")
    with db(context) as conn:
        row = find(conn, document_id, True)
        if not row:
            raise HTTPException(404, "DOCUMENT_NOT_FOUND")
        if row["state"] != "DELETING":
            conn.execute(
                "UPDATE documents SET state='DELETING',updated_at=now() WHERE id=%s",
                (row["id"],),
            )
            enqueue(conn, row["id"], context["workspace_id"], "DELETE")
    return {
        "document_id": str(row["id"]),
        "file_name": row["file_name"],
        "status": "deleting",
    }


@app.post("/api/v1/documents/{document_id}/retry", status_code=202)
def retry_document(document_id: str, context=Depends(authorize)):
    require_role(context, "EDITOR", "ADMIN")
    with db(context) as conn:
        row = find(conn, document_id, True)
        if not row or row["state"] not in ("FAILED", "DELETING"):
            raise HTTPException(409, "DOCUMENT_NOT_RETRYABLE")
        if conn.execute(
            "SELECT 1 FROM jobs WHERE document_id=%s AND status IN ('PENDING','RUNNING')",
            (row["id"],),
        ).fetchone():
            raise HTTPException(409, "JOB_ALREADY_PENDING")
        kind = "DELETE" if row["state"] == "DELETING" else "INDEX"
        if kind == "INDEX":
            conn.execute(
                "UPDATE documents SET state='PENDING',error_code=NULL WHERE id=%s",
                (row["id"],),
            )
        enqueue(conn, row["id"], context["workspace_id"], kind)
    return {"status": "queued"}


@app.get("/api/v1/index/status")
def index_status(context=Depends(authorize)):
    with db(context) as conn:
        row = conn.execute(
            "SELECT count(*) AS documents,coalesce(sum(chunk_count),0) AS chunks FROM documents WHERE state='READY'"
        ).fetchone()
        pending = conn.execute(
            "SELECT count(*) AS count FROM documents WHERE state='PENDING'"
        ).fetchone()["count"]
        pending += conn.execute(
            "SELECT count(*) AS count FROM jobs WHERE workspace_id=%s AND kind='REBUILD' AND status IN ('PENDING','RUNNING')",
            (UUID(context["workspace_id"]),),
        ).fetchone()["count"]
    return {
        "status": "indexing" if pending else "ready",
        "document_count": row["documents"],
        "chunk_count": row["chunks"],
        "embedding_model": storage.model_name(),
        "chunk_size": int(os.getenv("CHUNK_SIZE", "500")),
        "chunk_overlap": int(os.getenv("CHUNK_OVERLAP", "50")),
    }


@app.post("/api/v1/index/update", status_code=202)
def rebuild(context=Depends(authorize)):
    require_role(context, "ADMIN")
    try:
        with db(context) as conn:
            rows = conn.execute(
                "SELECT id,file_name FROM documents WHERE state='READY'"
            ).fetchall()
            job_id = enqueue(conn, None, context["workspace_id"], "REBUILD")
    except UniqueViolation as exc:
        raise HTTPException(409, "REBUILD_ALREADY_PENDING") from exc
    return {
        "status": "queued",
        "job_id": str(job_id),
        "full_rebuild": True,
        "added": [],
        "modified": [row["file_name"] for row in rows],
        "deleted": [],
        "unchanged": [],
    }


@app.get("/api/v1/index/jobs/{job_id}")
def rebuild_job(job_id: UUID, context=Depends(authorize)):
    require_role(context, "ADMIN")
    with db(context) as conn:
        row = conn.execute(
            """SELECT id,status,attempts,error_code,generation_before,generation_after
            FROM jobs WHERE id=%s AND workspace_id=%s AND kind='REBUILD'""",
            (job_id, UUID(context["workspace_id"])),
        ).fetchone()
    if not row:
        raise HTTPException(404, "REBUILD_JOB_NOT_FOUND")
    return {
        **row,
        "id": str(row["id"]),
        "active_generation": storage.active_generation(context["workspace_id"])
        if row["status"] == "DONE"
        else None,
    }


def service_access(request: Request):
    if not hmac.compare_digest(
        request.headers.get("X-Service-Key", ""), required("KNOWLEDGE_SERVICE_TOKEN")
    ):
        raise HTTPException(403, "SERVICE_ACCESS_DENIED")


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=16000)
    k: int = Field(default=3, ge=1, le=20)


@app.post("/internal/v1/search", dependencies=[Depends(service_access)])
def search(body: SearchRequest, context=Depends(authorize)):
    with db(context) as conn:
        rows = conn.execute("SELECT id FROM documents WHERE state='READY'").fetchall()
    try:
        hits = storage.retrieve(
            context["workspace_id"],
            body.query,
            body.k,
            [str(row["id"]) for row in rows],
        )
    except Exception as exc:
        raise HTTPException(503, "SEARCH_UNAVAILABLE") from exc
    # A deletion may race with OpenSearch. Recheck authoritative state before returning.
    if hits:
        with db(context) as conn:
            active = {
                str(row["id"])
                for row in conn.execute(
                    "SELECT id FROM documents WHERE state='READY' AND id=ANY(%s)",
                    ([UUID(hit["document_id"]) for hit in hits],),
                ).fetchall()
            }
        hits = [hit for hit in hits if hit["document_id"] in active]
    return {"version": 1, "chunks": hits}


class ValidateSources(BaseModel):
    document_ids: list[UUID] = Field(max_length=100)


@app.post("/internal/v1/documents/validate", dependencies=[Depends(service_access)])
def validate_sources(body: ValidateSources, context=Depends(authorize)):
    with db(context) as conn:
        rows = conn.execute(
            "SELECT id FROM documents WHERE state='READY' AND id=ANY(%s)",
            (body.document_ids,),
        ).fetchall()
    return {"version": 1, "document_ids": [str(row["id"]) for row in rows]}

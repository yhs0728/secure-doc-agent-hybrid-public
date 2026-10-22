"""Parallel document preparation with a short shared publication barrier.

Normal documents hold a per-document lock. A rebuild prepares its new generation
without blocking uploads, then catches up READY documents under an exclusive
workspace publication lock before swapping the alias.
"""

import hashlib
import time
from contextlib import contextmanager
from pathlib import PurePosixPath

from . import storage
from .parsing import parse_and_split
from .platform import db


class LeaseLost(RuntimeError):
    pass


def owned(conn, job):
    return conn.execute(
        "SELECT 1 FROM jobs WHERE id=%s AND lease_token=%s AND status='RUNNING'",
        (job["id"], job["lease_token"]),
    ).fetchone()


def defer(job):
    with db() as conn:
        conn.execute(
            "UPDATE jobs SET status='PENDING',attempts=greatest(attempts-1,0),available_at=now()+interval '1 second' WHERE id=%s AND lease_token=%s",
            (job["id"], job["lease_token"]),
        )


@contextmanager
def publication(context, exclusive=False):
    started = time.monotonic()
    with db(context) as conn:
        function = (
            "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
        )
        conn.execute(
            f"SELECT {function}(hashtext(%s))",
            ("publish:" + str(context["workspace_id"]),),
        )
        yield conn, (time.monotonic() - started) * 1000


def process(job):
    context = {
        "workspace_id": job["workspace_id"],
        "user_id": "00000000-0000-7000-8000-000000000001",
    }
    key = (
        ("rebuild:" + str(job["workspace_id"]))
        if job["kind"] == "REBUILD"
        else ("document:" + str(job["document_id"]))
    )
    with db(context) as guard:
        locked = guard.execute(
            "SELECT pg_try_advisory_lock(hashtext(%s)) AS locked", (key,)
        ).fetchone()["locked"]
        if not locked:
            defer(job)
            return
        try:
            with db() as conn:
                if not owned(conn, job):
                    return
            if job["kind"] == "REBUILD":
                rebuild(job, context)
            else:
                document_job(job, context)
        finally:
            guard.execute("SELECT pg_advisory_unlock(hashtext(%s))", (key,))


def original(document):
    staged = document["staged_content"]
    store = storage.object_store()
    if staged is not None:
        content = bytes(staged)
        if hashlib.sha256(content).hexdigest() != document["checksum"]:
            raise RuntimeError("CHECKSUM_MISMATCH")
        store.put_object(
            Bucket=storage.bucket(),
            Key=document["object_key"],
            Body=content,
            Metadata={"sha256": document["checksum"]},
        )
    else:
        response = store.get_object(Bucket=storage.bucket(), Key=document["object_key"])
        try:
            content = response["Body"].read()
        finally:
            response["Body"].close()
    if hashlib.sha256(content).hexdigest() != document["checksum"]:
        raise RuntimeError("CHECKSUM_MISMATCH")
    return content


def prepare(document):
    chunks, pages = parse_and_split(
        original(document), PurePosixPath(document["file_name"]).suffix.lower()
    )
    vectors = storage.prepare_chunks(chunks)
    return chunks, pages, vectors


def finish(conn, job, preparation_ms, publication_ms, lock_wait_ms):
    row = conn.execute(
        """UPDATE jobs SET status='DONE',leased_until=NULL,error_code=NULL,
        finished_at=now(),preparation_ms=%s,publication_ms=%s,lock_wait_ms=%s
        WHERE id=%s AND lease_token=%s AND status='RUNNING' RETURNING id""",
        (preparation_ms, publication_ms, lock_wait_ms, job["id"], job["lease_token"]),
    ).fetchone()
    if not row:
        raise LeaseLost("Job lease changed before completion")


def document_job(job, context):
    started = time.monotonic()
    with db(context) as conn:
        document = conn.execute(
            "SELECT * FROM documents WHERE id=%s", (job["document_id"],)
        ).fetchone()
    if not document:
        raise RuntimeError("DOCUMENT_NOT_FOUND")
    chunks = []
    vectors = []
    pages = 1
    if job["kind"] == "INDEX" and document["state"] not in ("DELETING", "DELETED"):
        # S3 transfer, parsing and embedding run independently for different documents.
        chunks, _pages, vectors = prepare(document)
    preparation_ms = (time.monotonic() - started) * 1000
    with publication(context) as (conn, wait_ms):
        if not owned(conn, job):
            raise LeaseLost("Job lease changed during preparation")
        current = conn.execute(
            "SELECT state FROM documents WHERE id=%s", (document["id"],)
        ).fetchone()
        publish_start = time.monotonic()
        if job["kind"] == "DELETE":
            storage.delete_chunks(document)
            storage.object_store().delete_object(
                Bucket=storage.bucket(), Key=document["object_key"]
            )
            conn.execute(
                "UPDATE documents SET state='DELETED',staged_content=NULL,chunk_count=0,error_code=NULL,updated_at=now() WHERE id=%s",
                (document["id"],),
            )
        elif chunks and current["state"] not in ("DELETING", "DELETED"):
            # Only first-index creation is exclusive; normal publications use shared locks.
            with db(context) as init:
                init.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    ("index-init:" + str(context["workspace_id"]),),
                )
                storage.ensure_alias(context["workspace_id"], len(vectors[0]))
            storage.put_prepared(document, chunks, vectors)
            conn.execute(
                "UPDATE documents SET state='READY',staged_content=NULL,chunk_count=%s,page_count=%s,error_code=NULL,updated_at=now() WHERE id=%s AND state NOT IN ('DELETING','DELETED')",
                (len(chunks), pages, document["id"]),
            )
        finish(
            conn,
            job,
            preparation_ms,
            (time.monotonic() - publish_start) * 1000,
            wait_ms,
        )


def ready_documents(conn):
    return conn.execute("SELECT * FROM documents WHERE state='READY'").fetchall()


def rebuild(job, context):
    started = time.monotonic()
    counts = {}
    physical = None
    with db(context) as conn:
        documents = ready_documents(conn)

    def prepared_documents():
        for document in documents:
            with db() as conn:
                if not owned(conn, job):
                    raise LeaseLost("Rebuild lease changed during preparation")
            try:
                chunks, _pages, vectors = prepare(document)
            except Exception:
                with db(context) as conn:
                    state = conn.execute(
                        "SELECT state FROM documents WHERE id=%s", (document["id"],)
                    ).fetchone()
                if state and state["state"] in ("DELETING", "DELETED"):
                    continue
                raise
            counts[str(document["id"])] = len(chunks)
            yield document, chunks, vectors
            # Do not retain a workspace's vectors across documents.
            del chunks, vectors

    try:
        physical = storage.stage_generation(
            context["workspace_id"], prepared_documents()
        )
        preparation_ms = (time.monotonic() - started) * 1000
        with publication(context, exclusive=True) as (conn, wait_ms):
            if not owned(conn, job):
                raise LeaseLost("Rebuild lease changed before publication")
            publish_start = time.monotonic()
            # Uploads can complete during preparation. Copy their published vectors
            # while normal READY publications are now blocked by the exclusive barrier.
            live = {str(document["id"]): document for document in ready_documents(conn)}
            for did, document in live.items():
                if did not in counts:
                    counts[did] = storage.copy_ready_document(document, physical)
            live_ids = {str(document["id"]) for document in ready_documents(conn)}
            removed = set(counts) - live_ids
            storage.remove_generation_documents(physical, removed)
            for did in removed:
                counts.pop(did)
            if not owned(conn, job):
                raise LeaseLost("Rebuild lease changed during catch-up")
            generation_before = storage.active_generation(context["workspace_id"])
            storage.publish_generation(
                context["workspace_id"],
                physical,
                sum(counts.values()),
            )
            conn.execute(
                "UPDATE jobs SET generation_before=%s,generation_after=%s WHERE id=%s AND lease_token=%s AND status='RUNNING'",
                (generation_before, physical, job["id"], job["lease_token"]),
            )
            for did, count in counts.items():
                conn.execute(
                    "UPDATE documents SET chunk_count=%s,updated_at=now() WHERE id=%s AND state='READY'",
                    (count, did),
                )
            finish(
                conn,
                job,
                preparation_ms,
                (time.monotonic() - publish_start) * 1000,
                wait_ms,
            )
    except Exception:
        if physical:
            storage.discard_generation(context["workspace_id"], physical)
        raise

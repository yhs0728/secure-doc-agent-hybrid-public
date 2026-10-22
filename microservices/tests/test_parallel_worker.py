import threading
import weakref
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import psycopg
import pytest


def test_streamed_generation_is_discarded_if_later_document_fails(monkeypatch):
    from knowledge_service import storage

    created = []
    written = []
    discarded = []
    monkeypatch.setattr(
        storage,
        "embedding_model",
        lambda: type(
            "Model", (), {"get_sentence_embedding_dimension": lambda self: 1}
        )(),
    )
    monkeypatch.setattr(
        storage, "create_physical", lambda physical, dim: created.append(physical)
    )
    monkeypatch.setattr(
        storage,
        "write_prepared",
        lambda doc, chunks, vectors, physical: written.append(doc["id"]),
    )
    monkeypatch.setattr(
        storage,
        "discard_generation",
        lambda workspace, physical: discarded.append(physical),
    )

    def documents():
        yield {"id": "first"}, [{"text": "first"}], [[1.0]]
        raise RuntimeError("second document failed")

    with pytest.raises(RuntimeError, match="second document failed"):
        storage.stage_generation("workspace", documents())
    assert written == ["first"]
    assert discarded == created


def test_rebuild_releases_each_documents_chunks_and_vectors(system, monkeypatch):
    from knowledge_service import execution

    for n in range(3):
        upload(system, n)
        system.worker.run_once()
    storage = system.apps["knowledge"].storage
    prepare = execution.prepare
    previous = []
    prepared = 0

    class Payload(list):
        pass

    def tracked_prepare(document):
        nonlocal prepared
        assert all(reference() is None for reference in previous)
        chunks, pages, vectors = prepare(document)
        chunks, vectors = Payload(chunks), Payload(vectors)
        previous[:] = [weakref.ref(chunks), weakref.ref(vectors)]
        prepared += 1
        return chunks, pages, vectors

    monkeypatch.setattr(execution, "prepare", tracked_prepare)
    monkeypatch.setattr(storage, "stage_generation", system.real_stage_generation)
    monkeypatch.setattr(
        storage,
        "embedding_model",
        lambda: type(
            "Model", (), {"get_sentence_embedding_dimension": lambda self: 1}
        )(),
    )
    monkeypatch.setattr(storage, "create_physical", lambda *args: None)
    monkeypatch.setattr(storage, "write_prepared", lambda *args: None)
    monkeypatch.setattr(storage, "publish_generation", lambda *args: None)
    response = system.clients["knowledge"].post(
        "/api/v1/index/update", headers=system.headers
    )
    system.worker.process(system.worker.claim())
    assert prepared == 3
    assert all(reference() is None for reference in previous)
    job = system.clients["knowledge"].get(
        "/api/v1/index/jobs/" + response.json()["job_id"], headers=system.headers
    )
    assert job.json()["status"] == "DONE"


def upload(system, n):
    response = system.clients["knowledge"].post(
        "/api/v1/documents/upload",
        headers=system.headers,
        files={
            "file": (
                f"parallel-{n}.txt",
                f"Unique policy {n}: change passwords every 90 days.".encode(),
                "text/plain",
            )
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["document_id"]


def test_two_documents_prepare_concurrently_in_same_workspace(system, monkeypatch):
    ids = [upload(system, n) for n in range(2)]
    jobs = [system.worker.claim(), system.worker.claim()]
    storage = system.apps["knowledge"].storage
    original = storage.prepare_chunks
    barrier = threading.Barrier(2, timeout=5)

    def prepare(chunks):
        barrier.wait()
        return original(chunks)

    monkeypatch.setattr(storage, "prepare_chunks", prepare)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(system.worker.process, job) for job in jobs]
        for future in futures:
            future.result(timeout=10)
    with psycopg.connect(**system.info) as conn:
        assert (
            conn.execute(
                "SELECT count(*) FROM ms_knowledge.documents WHERE state='READY' AND id=ANY(%s)",
                ([UUID(did) for did in ids],),
            ).fetchone()[0]
            == 2
        )
        assert (
            conn.execute(
                "SELECT count(*) FROM ms_knowledge.jobs WHERE preparation_ms IS NOT NULL AND publication_ms IS NOT NULL AND lock_wait_ms IS NOT NULL"
            ).fetchone()[0]
            == 2
        )


def staged_rebuild(system, monkeypatch):
    response = system.clients["knowledge"].post(
        "/api/v1/index/update", headers=system.headers
    )
    assert response.status_code == 202
    job = system.worker.claim()
    staged = threading.Event()
    resume = threading.Event()
    storage = system.apps["knowledge"].storage
    original = storage.stage_generation

    def stage(workspace, prepared):
        physical = original(workspace, prepared)
        staged.set()
        assert resume.wait(10)
        return physical

    monkeypatch.setattr(storage, "stage_generation", stage)
    return job, staged, resume


def test_rebuild_catches_upload_completed_during_preparation(system, monkeypatch):
    first = upload(system, 1)
    system.worker.run_once()
    job, staged, resume = staged_rebuild(system, monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rebuild = pool.submit(system.worker.process, job)
        try:
            assert staged.wait(5)
            second = upload(system, 2)
            pool.submit(system.worker.process, system.worker.claim()).result(timeout=5)
        finally:
            resume.set()
        rebuild.result(timeout=5)
    assert set(system.indexed) == {first, second}


def test_rebuild_does_not_restore_document_deleted_during_preparation(
    system, monkeypatch
):
    did = upload(system, 1)
    system.worker.run_once()
    job, staged, resume = staged_rebuild(system, monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        rebuild = pool.submit(system.worker.process, job)
        try:
            assert staged.wait(5)
            assert (
                system.clients["knowledge"]
                .delete("/api/v1/documents/" + did, headers=system.headers)
                .status_code
                == 200
            )
            pool.submit(system.worker.process, system.worker.claim()).result(timeout=5)
        finally:
            resume.set()
        rebuild.result(timeout=5)
    assert did not in system.indexed

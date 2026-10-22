from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, Lock
from time import sleep

from app import main as main_module
from app.main import QuestionRequest
from app.security import AuthContext
from config.settings import Settings
from models.ingestion import ApiDocumentIngestRequest


def admin_context(settings: Settings) -> AuthContext:
    return AuthContext(
        user_id=settings.system_user_id,
        organization_id=settings.default_organization_id,
        workspace_id=settings.default_workspace_id,
        workspace_role="ADMIN",
        auth_type="test",
    )


def test_api_ingestion_serializes_source_write_and_index_update(
    tmp_path: Path, monkeypatch
) -> None:
    settings = Settings(
        llm_model="test-model",
        llm_api_key="test-key",
        api_access_key="test-service-api-key",
        source_directory=str(tmp_path / "source"),
        index_directory=str(tmp_path / "index"),
        database_enabled=False,
    )
    state_lock = Lock()
    active = 0
    maximum_active = 0
    update_count = 0

    def fake_ingest_api_document(**kwargs):
        path = Path(kwargs["source_directory"]) / f"{kwargs['document_id']}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(kwargs["content"], encoding="utf-8")
        return path

    def fake_update_persisted_index(*, settings):
        nonlocal active, maximum_active, update_count
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
        sleep(0.05)
        with state_lock:
            update_count += 1
            active -= 1

    monkeypatch.setattr(main_module, "ingest_api_document", fake_ingest_api_document)
    monkeypatch.setattr(main_module, "update_persisted_index", fake_update_persisted_index)

    def ingest(number: int):
        return main_module.ingest_document_from_api(
            request=ApiDocumentIngestRequest(
                document_id=f"doc-{number}",
                title=f"Document {number}",
                content=f"content {number}",
            ),
            settings=settings,
            auth=admin_context(settings),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(ingest, (1, 2)))

    assert [result.status for result in results] == ["ingested", "ingested"]
    assert update_count == 2
    assert maximum_active == 1


def test_question_keeps_old_snapshot_while_index_update_completes(
    tmp_path: Path, monkeypatch
) -> None:
    """Readers are lock-free; a writer swaps the graph only after commit."""
    settings = Settings(
        llm_model="test-model",
        llm_api_key="test-key",
        api_access_key="test-service-api-key",
        source_directory=str(tmp_path / "source"),
        index_directory=str(tmp_path / "index"),
        database_enabled=False,
    )
    question_started = Event()
    release_question = Event()
    update_finished = Event()

    class ExistingGraph:
        def invoke(self, inputs):
            question_started.set()
            assert release_question.wait(timeout=2)
            return {
                "answer": "기존 스냅샷의 답변",
                "citations": ["old-policy.txt"],
                "requires_human_review": False,
            }

    def fake_ingest_api_document(**kwargs):
        path = Path(kwargs["source_directory"]) / "new-policy.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(kwargs["content"], encoding="utf-8")
        return path

    def fake_update_persisted_index(*, settings):
        update_finished.set()

    monkeypatch.setattr(main_module, "ingest_api_document", fake_ingest_api_document)
    monkeypatch.setattr(main_module, "update_persisted_index", fake_update_persisted_index)

    with ThreadPoolExecutor(max_workers=2) as executor:
        question_future = executor.submit(
            main_module.ask_question,
            QuestionRequest(question="기존 정책은?"),
            ExistingGraph(),
        )
        assert question_started.wait(timeout=1)
        update_future = executor.submit(
            main_module.ingest_document_from_api,
            ApiDocumentIngestRequest(
                document_id="new-policy",
                title="New policy",
                content="새 정책",
            ),
            settings,
            admin_context(settings),
        )

        update_result = update_future.result(timeout=1)
        assert update_finished.is_set()
        assert update_result.status == "ingested"
        release_question.set()
        question_result = question_future.result(timeout=1)

    assert question_result.answer == "기존 스냅샷의 답변"
    assert question_result.citations == ["old-policy.txt"]

import hashlib
import json
import mimetypes
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import select

from config.settings import get_settings
from database.models.content import (
    Document,
    DocumentArtifact,
    DocumentVersion,
    StorageObject,
)
from database.session import transaction

SUPPORTED_EXTENSIONS = {".txt", ".pdf", ".docx", ".csv"}


def _load_legacy_metadata(path: Path) -> dict[str, dict[str, object]]:
    if not path.is_file():
        return {}
    rows = json.loads(path.read_text(encoding="utf-8"))
    return {Path(str(row["file_name"])).stem: row for row in rows}


def _page_count(path: Path) -> int:
    if path.suffix.lower() == ".pdf":
        return max(1, len(PdfReader(str(path)).pages))
    return 1


def import_legacy_documents(
    source_directory: Path,
    metadata_path: Path,
) -> dict[str, list[str]]:
    settings = get_settings()
    metadata_by_stem = _load_legacy_metadata(metadata_path)
    imported: list[str] = []
    skipped: list[str] = []

    source_files = sorted(
        path
        for path in source_directory.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    with transaction() as session:
        for path in source_files:
            object_key = path.name
            existing = session.scalar(
                select(StorageObject).where(
                    StorageObject.provider == "LOCAL",
                    StorageObject.bucket == "data/source",
                    StorageObject.object_key == object_key,
                    StorageObject.version_id == "",
                )
            )
            if existing is not None:
                skipped.append(path.name)
                continue

            content = path.read_bytes()
            checksum = hashlib.sha256(content).hexdigest()
            legacy = metadata_by_stem.get(path.stem, {})
            title = str(legacy.get("title") or path.stem.replace("-", " ").title())

            document = Document(
                workspace_id=settings.default_workspace_id,
                created_by_user_id=settings.system_user_id,
                title=title,
                lifecycle_status="ACTIVE",
            )
            session.add(document)
            session.flush()

            version = DocumentVersion(
                document_id=document.id,
                version_no=1,
                original_filename=path.name,
                normalized_filename=path.name,
                media_type=mimetypes.guess_type(path.name)[0]
                or "application/octet-stream",
                file_extension=path.suffix.lower(),
                size_bytes=len(content),
                page_count=_page_count(path),
                checksum_sha256=checksum,
                processing_status="READY",
                parser_name="legacy-local-import",
                parser_version="1",
                created_by_user_id=settings.system_user_id,
                extra_metadata={
                    "legacy_document_id": legacy.get("document_id"),
                },
            )
            storage_object = StorageObject(
                workspace_id=settings.default_workspace_id,
                provider="LOCAL",
                bucket="data/source",
                object_key=object_key,
                size_bytes=len(content),
                checksum_sha256=checksum,
            )
            session.add_all((version, storage_object))
            session.flush()
            session.add(
                DocumentArtifact(
                    document_version_id=version.id,
                    storage_object_id=storage_object.id,
                    artifact_type="SOURCE",
                )
            )
            document.current_version_id = version.id
            imported.append(path.name)

    return {"imported": imported, "skipped": skipped}


if __name__ == "__main__":
    result = import_legacy_documents(
        source_directory=Path("data/source"),
        metadata_path=Path("data/documents.json"),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))

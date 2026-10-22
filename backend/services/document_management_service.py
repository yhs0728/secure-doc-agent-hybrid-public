from pathlib import Path


class ManagedDocumentNotFoundError(FileNotFoundError):
    pass


class AmbiguousDocumentError(ValueError):
    pass


def delete_source_document(
    *,
    source_directory: Path,
    document_id: str,
) -> Path:
    """Delete the single source file whose filename stem is ``document_id``."""
    if not document_id or Path(document_id).name != document_id:
        raise ManagedDocumentNotFoundError(document_id)

    source_directory = Path(source_directory)
    matches = [
        path
        for path in source_directory.iterdir()
        if path.is_file() and path.stem == document_id
    ] if source_directory.is_dir() else []

    if not matches:
        raise ManagedDocumentNotFoundError(document_id)

    if len(matches) > 1:
        raise AmbiguousDocumentError(
            f"문서 ID와 일치하는 파일이 여러 개입니다: {document_id}"
        )

    deleted_file = matches[0]
    deleted_file.unlink()
    return deleted_file

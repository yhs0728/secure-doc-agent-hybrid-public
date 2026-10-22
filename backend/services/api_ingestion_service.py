import json
from pathlib import Path
from typing import Any

from services.upload_service import (
    save_uploaded_document,
)


def build_api_document_text(
    title: str,
    content: str,
    source: str | None,
    metadata: dict[str, Any],
) -> str:
    blocks = [
        f"제목: {title.strip()}",
    ]

    if source:
        blocks.append(
            f"원본 출처: {source.strip()}"
        )

    if metadata:
        metadata_json = json.dumps(
            metadata,
            ensure_ascii=False,
            sort_keys=True,
        )

        blocks.append(
            f"메타데이터: {metadata_json}"
        )

    blocks.append("")
    blocks.append(
        content.strip()
    )

    return "\n".join(blocks)


def ingest_api_document(
    source_directory: Path,
    document_id: str,
    title: str,
    content: str,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Path:
    normalized_content = content.strip()

    if not normalized_content:
        raise ValueError(
            "문서 내용은 비어 있을 수 없습니다."
        )

    document_text = build_api_document_text(
        title=title,
        content=normalized_content,
        source=source,
        metadata=metadata or {},
    )

    file_name = f"{document_id}.txt"

    return save_uploaded_document(
        source_directory=source_directory,
        file_name=file_name,
        content=document_text.encode("utf-8"),
    )
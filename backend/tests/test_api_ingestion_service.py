from pathlib import Path
import pytest

from services.api_ingestion_service import (
    ingest_api_document,
)


def test_ingest_api_document(
    tmp_path: Path,
) -> None:
    saved_path = ingest_api_document(
        source_directory=tmp_path,
        document_id="external-policy-001",
        title="외부 접속 정책",
        content=(
            "외부 접속에는 다중 인증이 "
            "필요합니다."
        ),
        source="security-api",
        metadata={
            "department": "security",
            "version": "1.0",
        },
    )

    assert saved_path == (
        tmp_path / "external-policy-001.txt"
    )
    assert saved_path.exists()

    saved_content = saved_path.read_text(
        encoding="utf-8",
    )

    assert "제목: 외부 접속 정책" in (
        saved_content
    )
    assert "원본 출처: security-api" in (
        saved_content
    )
    assert (
        "외부 접속에는 다중 인증이 필요합니다."
        in saved_content
    )


def test_ingest_api_document_rejects_blank_content(
    tmp_path: Path,
) -> None:
    try:
        ingest_api_document(
            source_directory=tmp_path,
            document_id="empty-document",
            title="빈 문서",
            content="   ",
        )
    except ValueError as error:
        assert str(error) == (
            "문서 내용은 비어 있을 수 없습니다."
        )
    else:
        raise AssertionError(
            "ValueError가 발생해야 합니다."
        )
        
def test_ingest_api_document_rejects_blank_content(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        ValueError,
        match="문서 내용은 비어 있을 수 없습니다",
    ):
        ingest_api_document(
            source_directory=tmp_path,
            document_id="empty-document",
            title="빈 문서",
            content="   ",
        )
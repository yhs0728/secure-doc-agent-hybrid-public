from pathlib import Path

import pytest
from langchain_core.embeddings import (
    DeterministicFakeEmbedding,
)

from ingestion.indexing_pipeline import (
    IndexingError,
    build_retriever_from_directory,
    load_source_documents,
)


def create_text_file(
    directory: Path,
    file_name: str,
    content: str,
) -> None:
    file_path = directory / file_name   #지정된 디렉터리와 파일명을 합쳐 파일 경로를 만든 다음
    file_path.write_text(               #그 파일에 문자열을 UTF-8 형식으로 저장하는 코드
        content,
        encoding="utf-8",
    )


def test_load_source_documents_loads_txt_files(
    tmp_path: Path,
) -> None:
    create_text_file(
        directory=tmp_path,
        file_name="security-policy.txt",
        content=(
            "사용자는 비밀번호를 "
            "90일마다 변경해야 합니다."
        ),
    )

    create_text_file(
        directory=tmp_path,
        file_name="access-policy.txt",
        content=(
            "외부 접속에는 다중 인증이 필요합니다."
        ),
    )

    documents = load_source_documents(
        source_dir=tmp_path,
    )

    assert len(documents) == 2

    document_ids = {
        document.metadata["document_id"]
        for document in documents
    }

    assert document_ids == {
        "access-policy",
        "security-policy",
    }


def test_load_source_documents_rejects_empty_directory(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        IndexingError,
        match=r"인덱싱할 지원 문서가 없습니다\.",
    ):
        load_source_documents(
            source_dir=tmp_path,
        )
        

def test_build_retriever_from_directory(
    tmp_path: Path,
) -> None:
    create_text_file(
        directory=tmp_path,
        file_name="security-policy.txt",
        content=(
            "사용자는 비밀번호를 "
            "90일마다 변경해야 합니다. "
            * 10
        ),
    )

    create_text_file(
        directory=tmp_path,
        file_name="access-policy.txt",
        content=(
            "외부 접속에는 다중 인증이 필요합니다. "
            * 10
        ),
    )

    embeddings = DeterministicFakeEmbedding(
        size=32,
    )

    retriever = build_retriever_from_directory(
        source_dir=tmp_path,
        embeddings=embeddings,
        chunk_size=100,
        chunk_overlap=10,
        k=1,
    )

    results = retriever.invoke(
        "비밀번호 변경 주기는?"
    )

    assert len(results) == 1
    assert "document_id" in results[0].metadata
    assert "chunk_id" in results[0].metadata
    assert "source" in results[0].metadata
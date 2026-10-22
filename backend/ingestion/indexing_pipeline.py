from pathlib import Path

from langchain_core.documents import (
    Document as LangChainDocument,
)
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import (
    VectorStoreRetriever,
)

from ingestion.document_loader import (
    SUPPORTED_EXTENSIONS,
    load_source_document,
)
from ingestion.text_splitter import (
    split_documents,
)
from retrieval.vector_store import (
    build_vector_store,
    create_retriever,
)


class IndexingError(Exception):
    """문서 인덱싱 과정에서 발생한 오류입니다."""


def load_source_documents(
    source_dir: Path,
) -> list[LangChainDocument]:
    if not source_dir.exists():
        raise IndexingError(
            f"원본 문서 디렉터리를 찾을 수 없습니다: "
            f"{source_dir}"
        )

    if not source_dir.is_dir():
        raise IndexingError(
            f"원본 문서 경로가 디렉터리가 아닙니다: "
            f"{source_dir}"
        )

    source_files = sorted(
        file_path
        for file_path in source_dir.iterdir()
        if (
            file_path.is_file()
            and file_path.suffix.lower()
            in SUPPORTED_EXTENSIONS
        )
    )

    if not source_files:
        raise IndexingError(
            "인덱싱할 지원 문서가 없습니다."
        )

    documents: list[LangChainDocument] = []

    for source_file in source_files:
        document = load_source_document(
            file_path=source_file,
            document_id=source_file.stem,
            title=source_file.stem,
        )

        documents.append(document)

    return documents


def build_retriever_from_directory(
    source_dir: Path,
    embeddings: Embeddings,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    k: int = 3,
) -> VectorStoreRetriever:
    documents = load_source_documents(
        source_dir=source_dir,
    )

    chunks = split_documents(
        documents=documents,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )

    vector_store = build_vector_store(
        documents=chunks,
        embeddings=embeddings,
    )

    return create_retriever(
        vector_store=vector_store,
        k=k,
    )
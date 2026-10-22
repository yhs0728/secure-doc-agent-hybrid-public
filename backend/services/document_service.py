import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from models.document import Document, InvalidDocumentError


class DocumentLoadError(RuntimeError):
    """문서 목록을 불러오지 못할 때 발생하는 예외입니다."""


def load_documents(file_path: Path) -> list[Document]:
    try:
        json_text = file_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise DocumentLoadError(
            f"문서 데이터 파일을 찾을 수 없습니다: {file_path}"
        ) from error
    except OSError as error:
        raise DocumentLoadError(
            f"문서 데이터 파일을 읽을 수 없습니다: {file_path}"
        ) from error

    try:
        raw_data: Any = json.loads(json_text)
    except JSONDecodeError as error:
        raise DocumentLoadError(
            f"JSON 형식이 올바르지 않습니다: {file_path}"
        ) from error

    if not isinstance(raw_data, list):
        raise DocumentLoadError(
            "문서 데이터의 최상위 구조는 리스트여야 합니다."
        )

    documents: list[Document] = []

    for index, item in enumerate(raw_data):
        if not isinstance(item, dict):
            raise DocumentLoadError(
                f"{index}번 문서 데이터는 객체여야 합니다."
            )

        try:
            document = Document.from_dict(item)
        except InvalidDocumentError as error:
            raise DocumentLoadError(
                f"{index}번 문서 데이터가 올바르지 않습니다: {error}"
            ) from error

        documents.append(document)

    return documents


def search_documents(
    documents: list[Document],
    keyword: str | None = None,
) -> list[Document]:
    if keyword is None:
        return documents

    normalized_keyword = keyword.strip().lower()

    if not normalized_keyword:
        return documents

    matched_documents: list[Document] = []

    for document in documents:
        searchable_text = (
            f"{document.title} {document.file_name}"
        ).lower()

        if normalized_keyword in searchable_text:
            matched_documents.append(document)

    return matched_documents



def find_document_by_id(
    documents: list[Document],
    document_id: str,
) -> Document | None:
    normalized_document_id = document_id.strip()
    
    for document in documents:
        if document.document_id == normalized_document_id:
            return document
        
        
    return None
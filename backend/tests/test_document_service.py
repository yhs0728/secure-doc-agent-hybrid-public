import json
from pathlib import Path
from models.document import Document
import pytest


from services.document_service import (
    DocumentLoadError,
    find_document_by_id,
    load_documents,
    search_documents,
)


def test_load_documents(tmp_path: Path) -> None:
    file_path = tmp_path / "documents.json"
    file_path.write_text(
        json.dumps(
            [
                {
                    "document_id": "doc-001",
                    "title": "문서 관리 규정",
                    "file_name": "document-policy.pdf",
                    "page_count": 12,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    
    documents = load_documents(file_path)
    
    assert len(documents) == 1
    assert documents[0].document_id == "doc-001"
    assert documents[0].title == "문서 관리 규정"
    assert documents[0].page_count ==12

def test_load_documents_raises_error_when_file_is_missing(
    tmp_path: Path,
) -> None:
    missing_file = tmp_path / "missing.json"

    with pytest.raises(
        DocumentLoadError,
        match="찾을 수 없습니다",
    ):
        load_documents(missing_file)


def test_load_documents_rejects_invalid_page_count(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "documents.json"
    file_path.write_text(
        json.dumps(
            [
                {
                    "document_id": "doc-001",
                    "title": "문서 관리 규정",
                    "file_name": "document-policy.pdf",
                    "page_count": 0,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        DocumentLoadError,
        match="page_count는 1 이상",
    ):
        load_documents(file_path)
        
        
def test_search_documents_filters_by_keyword() -> None:
    documents = [
        Document(
            document_id="doc-001",
            title="문서 관리 규정",
            file_name="document-policy.pdf",
            page_count=12,
        ),
        Document(
            document_id="doc-002",
            title="개인정보 처리 지침",
            file_name="privacy-guide.pdf",
            page_count=8,
        ),
        Document(
            document_id="doc-003",
            title="정보보안 운영 규정",
            file_name="security-policy.pdf",
            page_count=20,
        ),
    ]
    
    result = search_documents(
        documents,
        keyword = "보안",
    )
    
    assert len(result) == 1
    assert result[0].document_id == "doc-003"
    
    
def test_search_documents_searches_file_name() -> None:
    documents = [
        Document(
            document_id="doc-001",
            title = "문서 관리 규정",
            file_name = "document-policy.pdf",
            page_count=12,
        ),
        Document(
            document_id = "doc-002",
            title = "개인정보 처리 지침",
            file_name = "privacy-guide.pdf",
            page_count =8,
        ),
    ]
    
    result = search_documents(
        documents,
        keyword="privacy",
    )
    
    
    assert len(result) == 1
    assert result[0].document_id == "doc-002"
    
def test_search_documents_returns_all_when_keyword_is_none() -> None:
    documents = [
        Document(
            document_id="doc-001",
            title="문서 관리 규정",
            file_name="document-policy.pdf",
            page_count=12,
        ),
        Document(
            document_id="doc-002",
            title="개인정보 처리 지침",
            file_name="privacy-guide.pdf",
            page_count=8,
        ),
    ]

    result = search_documents(
        documents,
        keyword=None,
    )

    assert result == documents
    
def test_find_document_by_id_returns_matching_document() -> None:
    documents = [
        Document(
                    document_id = "doc-001",
                    title = "문서 관리 규정",
                    file_name = "document-policy.pdf",
                    page_count = 12,
                ),
                
                Document(
                    document_id = "doc-002",
                    title = "개인정보 처리 지침",
                    file_name= "privacy-guide.pdf",
                    page_count=8,
                ),
    ]
        
    
    
    result = find_document_by_id(
        documents,
        document_id="doc-002",
    )
    
    
    assert result is not None
    assert result.document_id == "doc-002"
    assert result.title == "개인정보 처리 지침"
    
    
    
def test_find_document_by_id_returns_none_when_not_found() -> None :
    documents = [
        Document(
            document_id = "doc-001",
            title = "문서 관리 규정",
            file_name = "document-policy.pdf",
            page_count=12,
        )
    ]
    
    result = find_document_by_id(
        documents,
        document_id="doc-999",
    )
    
    assert result is None
    
    
from dataclasses import dataclass
from typing import Any


class InvalidDocumentError(ValueError):
    """문서 데이터가 유효하지 않을 때 발생하는 예외입니다."""
    
    
    
@dataclass(frozen=True)
class Document:
    document_id: str
    title: str
    file_name: str
    page_count: int
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Document":
        required_fields = {
            "document_id",
            "title",
            "file_name",
            "page_count",
        }
        missing_fileds = required_fields - data.keys()
        
        if missing_fileds:
            field_names = ", ".join(sorted(missing_fileds))
            raise InvalidDocumentError(
                f"필수 필드가 없습니다: {field_names}"
            )
            
            
        document_id = data["document_id"]
        title = data["title"]
        file_name = data["file_name"]
        page_count = data["page_count"]
        
        if not isinstance(document_id, str) or not document_id.strip():
            raise InvalidDocumentError(
                "document_id는 비어 있지 않은 문자열이어야 합니다."
            )

        if not isinstance(title, str) or not title.strip():
            raise InvalidDocumentError(
                "title은 비어 있지 않은 문자열이어야 합니다."
            )

        if not isinstance(file_name, str) or not file_name.strip():
            raise InvalidDocumentError(
                "file_name은 비어 있지 않은 문자열이어야 합니다."
            )

        if not isinstance(page_count, int) or isinstance(page_count, bool):
            raise InvalidDocumentError("page_count는 정수여야 합니다.")

        if page_count < 1:
            raise InvalidDocumentError(
                "page_count는 1 이상이어야 합니다."
            )

        return cls(
            document_id=document_id.strip(),
            title=title.strip(),
            file_name=file_name.strip(),
            page_count=page_count,
        )
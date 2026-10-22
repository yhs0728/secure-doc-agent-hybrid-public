from pydantic import BaseModel


class DocumentUploadResponse(BaseModel):
    file_name: str
    size_bytes: int
    status: str
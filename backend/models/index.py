from pydantic import BaseModel


class IndexUpdateResponse(BaseModel):
    status: str
    full_rebuild: bool
    added: list[str]
    modified: list[str]
    deleted: list[str]
    unchanged: list[str]


class IndexStatusResponse(BaseModel):
    status: str
    document_count: int
    chunk_count: int
    embedding_model: str
    chunk_size: int
    chunk_overlap: int


class DocumentDeleteResponse(BaseModel):
    document_id: str
    file_name: str
    status: str

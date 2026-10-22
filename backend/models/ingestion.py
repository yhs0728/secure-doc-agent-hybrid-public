from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)

class ApiDocumentIngestRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    
    document_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    title: str = Field(
        min_length=1,
        max_length=200,
    )
    content: str = Field(
        min_length=1,
        max_length=1_000_000,
    )
    source: str | None = Field(
        default=None,
        max_length=500,
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
    )
    
class ApiDocumentIngestResponse(BaseModel):
    document_id: str
    file_name: str
    status: str
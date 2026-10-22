from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
)


class IndexedDocument(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )

    document_id: str
    sha256: str

    file_size: int = Field(
        ge=0,
    )

    modified_at_ns: int = Field(
        ge=0,
    )

    chunk_ids: list[str]


class IndexManifest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )

    version: int = 1
    embedding_model: str

    chunk_size: int = Field(
        gt=0,
    )

    chunk_overlap: int = Field(
        ge=0,
    )

    documents: dict[
        str,
        IndexedDocument,
    ] = Field(
        default_factory=dict,
    )
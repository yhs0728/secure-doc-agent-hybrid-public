from functools import lru_cache

from langchain_core.embeddings import Embeddings
from langchain_huggingface import (
    HuggingFaceEmbeddings,
)

DEFAULT_EMBEDDING_MODEL = (
    "sentence-transformers/"
    "paraphrase-multilingual-MiniLM-L12-v2"
)

@lru_cache(maxsize=4)
def create_embedding_model(
    model_name: str = DEFAULT_EMBEDDING_MODEL,
    device: str = "cpu",
) -> Embeddings:
    return HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={
            "device": device,
        },
        
        encode_kwargs={
            "normalize_embeddings": True,
        },
    )

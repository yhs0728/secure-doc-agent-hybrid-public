from collections import defaultdict

from langchain_core.documents import (
    Document as LangChainDocument,
)
from langchain_text_splitters import (
    RecursiveCharacterTextSplitter,
)


def split_documents(
    documents: list[LangChainDocument],
    chunk_size: int = 500,
    chunk_overlap: int = 50,
) -> list[LangChainDocument]:
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        separators=[
            "\n\n",
            "\n",
            ". ",
            "",
        ],
    )
    
    chunks = text_splitter.split_documents(
        documents,
    )
    
    chunk_counts: dict[str, int] = defaultdict(int)
    
    
    for chunk in chunks:
        document_id = str(
            chunk.metadata["document_id"]
        )
        
        chunk_index = chunk_counts[document_id]
        chunk_counts[document_id] += 1
        
        chunk.metadata["chunk_index"] = chunk_index
        chunk.metadata["chunk_id"] = (
            f"{document_id}-chunk-{chunk_index:04d}"
        )
        
        
    return chunks
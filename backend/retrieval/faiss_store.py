from __future__ import annotations

import io
import pickle
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import faiss
import numpy as np
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore


class InMemoryDocstore:
    """Minimal document store used by the local FAISS integration."""

    def __init__(self, documents: dict[str, Document] | None = None) -> None:
        self._dict = documents or {}

    def add(self, documents: dict[str, Document]) -> None:
        overlapping = set(documents).intersection(self._dict)
        if overlapping:
            raise ValueError(f"Document IDs already exist: {sorted(overlapping)}")
        self._dict.update(documents)

    def delete(self, ids: Iterable[str]) -> None:
        for document_id in ids:
            self._dict.pop(document_id, None)

    def search(self, document_id: str) -> Document | None:
        return self._dict.get(document_id)


class _LegacyIndexUnpickler(pickle.Unpickler):
    """Load old LangChain FAISS snapshots without importing the sunset package."""

    def find_class(self, module: str, name: str) -> Any:
        if (
            module == "langchain_community.docstore.in_memory"
            and name == "InMemoryDocstore"
        ):
            return InMemoryDocstore
        return super().find_class(module, name)


class FaissVectorStore(VectorStore):
    """Small FAISS-backed VectorStore covering the application's local needs."""

    def __init__(
        self,
        embeddings: Embeddings,
        index: Any,
        docstore: InMemoryDocstore,
        index_to_docstore_id: dict[int, str],
    ) -> None:
        self.embeddings = embeddings
        self.index = index
        self.docstore = docstore
        self.index_to_docstore_id = index_to_docstore_id

    @property
    def embeddings(self) -> Embeddings:
        return self._embeddings

    @embeddings.setter
    def embeddings(self, value: Embeddings) -> None:
        self._embeddings = value

    @classmethod
    def from_texts(
        cls,
        texts: list[str],
        embedding: Embeddings,
        metadatas: list[dict[str, Any]] | None = None,
        *,
        ids: list[str] | None = None,
        **kwargs: Any,
    ) -> FaissVectorStore:
        del kwargs
        vectors = embedding.embed_documents(texts)
        if not vectors:
            raise ValueError("Cannot build a FAISS index without documents")
        index = faiss.IndexFlatL2(len(vectors[0]))
        store = cls(embedding, index, InMemoryDocstore(), {})
        documents = [
            Document(
                id=ids[position] if ids else None,
                page_content=text,
                metadata=metadatas[position] if metadatas else {},
            )
            for position, text in enumerate(texts)
        ]
        store._add_documents(documents, vectors, ids=ids)
        return store

    @classmethod
    def from_documents(
        cls,
        documents: list[Document],
        embedding: Embeddings,
        **kwargs: Any,
    ) -> FaissVectorStore:
        ids = kwargs.pop("ids", None)
        return cls.from_texts(
            [document.page_content for document in documents],
            embedding,
            [document.metadata for document in documents],
            ids=ids,
            **kwargs,
        )

    def _add_documents(
        self,
        documents: list[Document],
        vectors: list[list[float]],
        *,
        ids: list[str] | None,
    ) -> list[str]:
        resolved_ids = ids or [document.id for document in documents]
        if any(document_id is None for document_id in resolved_ids):
            raise ValueError("Every document requires an ID")
        normalized_ids = [str(document_id) for document_id in resolved_ids]
        if len(normalized_ids) != len(set(normalized_ids)):
            raise ValueError("Duplicate document IDs are not allowed")
        self.docstore.add(dict(zip(normalized_ids, documents, strict=True)))
        offset = len(self.index_to_docstore_id)
        self.index.add(np.asarray(vectors, dtype=np.float32))
        self.index_to_docstore_id.update(
            {offset + position: document_id for position, document_id in enumerate(normalized_ids)}
        )
        return normalized_ids

    def add_documents(self, documents: list[Document], **kwargs: Any) -> list[str]:
        ids = kwargs.pop("ids", None)
        if kwargs:
            raise TypeError(f"Unsupported FAISS options: {sorted(kwargs)}")
        vectors = self.embeddings.embed_documents(
            [document.page_content for document in documents]
        )
        return self._add_documents(documents, vectors, ids=ids)

    def delete(self, ids: list[str] | None = None, **kwargs: Any) -> bool:
        del kwargs
        if ids is None:
            raise ValueError("Document IDs are required")
        missing = set(ids).difference(self.index_to_docstore_id.values())
        if missing:
            raise ValueError(f"Document IDs do not exist: {sorted(missing)}")
        positions = np.asarray(
            [
                position
                for position, document_id in self.index_to_docstore_id.items()
                if document_id in ids
            ],
            dtype=np.int64,
        )
        self.index.remove_ids(positions)
        remaining_ids = [
            document_id
            for position, document_id in sorted(self.index_to_docstore_id.items())
            if position not in set(positions.tolist())
        ]
        self.index_to_docstore_id = dict(enumerate(remaining_ids))
        self.docstore.delete(ids)
        return True

    def similarity_search(self, query: str, k: int = 4, **kwargs: Any) -> list[Document]:
        del kwargs
        if k < 1 or self.index.ntotal == 0:
            return []
        query_vector = np.asarray(
            [self.embeddings.embed_query(query)], dtype=np.float32
        )
        _, positions = self.index.search(query_vector, min(k, self.index.ntotal))
        documents: list[Document] = []
        for position in positions[0]:
            if position < 0:
                continue
            document_id = self.index_to_docstore_id[int(position)]
            document = self.docstore.search(document_id)
            if document is not None:
                documents.append(document)
        return documents

    def save_local(self, folder_path: str) -> None:
        directory = Path(folder_path)
        directory.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self.index, str(directory / "index.faiss"))
        with (directory / "index.pkl").open("wb") as handle:
            pickle.dump(
                (self.docstore._dict, self.index_to_docstore_id),
                handle,
                protocol=pickle.HIGHEST_PROTOCOL,
            )

    @classmethod
    def load_local(
        cls,
        folder_path: str,
        embeddings: Embeddings,
        **kwargs: Any,
    ) -> FaissVectorStore:
        kwargs.pop("allow_dangerous_deserialization", None)
        if kwargs:
            raise TypeError(f"Unsupported FAISS options: {sorted(kwargs)}")
        directory = Path(folder_path)
        index = faiss.read_index(str(directory / "index.faiss"))
        payload = (directory / "index.pkl").read_bytes()
        stored_documents, index_to_docstore_id = _LegacyIndexUnpickler(
            io.BytesIO(payload)
        ).load()
        if hasattr(stored_documents, "_dict"):
            stored_documents = stored_documents._dict
        docstore = InMemoryDocstore(dict(stored_documents))
        return cls(embeddings, index, docstore, dict(index_to_docstore_id))

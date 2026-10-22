# FastAPI dependency markers are intentional function defaults.
# ruff: noqa: B008
import os
from contextlib import asynccontextmanager
from functools import lru_cache
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, Request
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator
from redis import RedisError

from . import finops, hybrid
from .admission import (
    CapacityBusy,
    ControlUnavailable,
    GuardedModel,
    RateLimited,
    active_lease,
    admission,
)
from .graph.workflow import build_rag_workflow
from .history import with_history
from .llm_config import provider_options
from .platform import authorize, create_app, db, migrate, remote, required

NO_ANSWER = "검색된 문서에서 질문에 대한 근거를 확인할 수 없습니다."


@lru_cache
def model():
    return ChatOpenAI(**provider_options())


@lru_cache
def capacity():
    return admission()


@asynccontextmanager
async def lifespan(app):
    if len(required("KNOWLEDGE_SERVICE_TOKEN")) < 32:
        raise RuntimeError("KNOWLEDGE_SERVICE_TOKEN must be at least 32 characters")
    workspaces = hybrid.allowed_workspaces()
    if not hybrid.external_provider() or workspaces:
        required("LLM_MODEL")
        required("LLM_API_KEY")
        provider_options()
    hybrid.circuit()
    capacity()
    if finops.enabled():
        finops.ledger()
    migrate()
    yield


app = create_app(lifespan)


def admission_ready():
    controller = capacity()
    if hasattr(controller, "client"):
        controller.client.ping()


def admission_metrics():
    controller = capacity()
    if not hasattr(controller, "client"):
        return "secure_doc_admission_available 1\n"
    try:
        seconds, micros = controller.client.time()
        active = controller.client.zcount(
            controller.key, seconds * 1000 + micros // 1000, "+inf"
        )
        return f"secure_doc_admission_available 1\nsecure_doc_llm_active_slots {active}\nsecure_doc_llm_slot_limit {controller.limit}\n"
    except RedisError:
        return "secure_doc_admission_available 0\n"


app.state.extra_ready = admission_ready
app.state.extra_metrics = lambda: admission_metrics() + hybrid.metrics() + finops.metrics()


def knowledge(path, body, authorization):
    return remote(
        "POST",
        os.getenv("KNOWLEDGE_URL", "http://knowledge:8000") + "/internal/v1/" + path,
        authorization=authorization,
        headers={"X-Service-Key": required("KNOWLEDGE_SERVICE_TOKEN")},
        json=body,
        timeout=60,
    )


class HttpRetriever:
    """Versioned search protocol. Has neither embedding model nor search credentials."""

    def __init__(self, authorization):
        self.authorization = authorization

    def invoke(self, query):
        payload = knowledge(
            "search",
            {"query": query, "k": int(os.getenv("RETRIEVAL_K", "3"))},
            self.authorization,
        )
        if payload.get("version") != 1:
            raise HTTPException(503, "SEARCH_CONTRACT_UNSUPPORTED")
        return [
            Document(
                page_content=chunk["text"],
                metadata={
                    "source": chunk["source"],
                    "document_id": chunk["document_id"],
                    "chunk_id": chunk["chunk_id"],
                    "page": chunk.get("page"),
                    "score": chunk.get("score"),
                },
            )
            for chunk in payload["chunks"]
        ]


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    conversation_id: UUID | None = None

    @field_validator("question")
    @classmethod
    def trim(cls, value):
        if not value.strip():
            raise ValueError("empty question")
        return value.strip()


def owned_conversation(conn, conversation_id, lock=False):
    row = conn.execute(
        "SELECT * FROM conversations WHERE id=%s" + (" FOR UPDATE" if lock else ""),
        (conversation_id,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "CONVERSATION_NOT_FOUND")
    return row


def generate(question, authorization, external_model=None):
    lease = active_lease.get()
    selected_model = external_model if external_model is not None else model()
    chat_model = GuardedModel(selected_model, lease) if lease else selected_model
    graph = build_rag_workflow(HttpRetriever(authorization), chat_model)
    return graph.invoke({"question": question})


def search_only(question, authorization, reason):
    """Authorized verbatim excerpts, never asserted to be a generated answer."""
    docs = HttpRetriever(authorization).invoke(question)
    ids = sorted({doc.metadata["document_id"] for doc in docs})
    if ids:
        valid = knowledge("documents/validate", {"document_ids": ids}, authorization)
        if valid.get("version") != 1:
            raise HTTPException(503, "SEARCH_CONTRACT_UNSUPPORTED")
        docs = [
            doc for doc in docs if doc.metadata["document_id"] in valid["document_ids"]
        ]
    quotes, blocks = [], []
    for index, doc in enumerate(docs[:3], 1):
        quote = doc.page_content[:500]
        quotes.append({**doc.metadata, "quote": quote})
        # Verbatim code blocks prevent document Markdown triggering remote images/links.
        source = str(doc.metadata["source"]).replace("\n", " ").replace("\r", " ")
        blocks.append(
            "\n".join(
                "    " + line for line in f"[{index}] {source}\n{quote}".splitlines()
            )
        )
    notice = (
        "이 작업공간은 외부 AI 전송을 허용하지 않아 검색 결과만 제공합니다."
        if reason == "external_policy"
        else "현재 AI 답변 생성을 사용할 수 없어 검색 결과만 제공합니다."
    )
    answer = (
        notice
        + " 아래 내용은 자동 생성 답변이 아닌 문서 발췌입니다. 원문을 확인해 주세요."
    )
    answer += "\n\n" + "\n\n".join(blocks) if blocks else "\n\n검색 결과가 없습니다."
    return {
        "answer": answer,
        "citations": quotes,
        "requires_human_review": True,
        "response_mode": "search_only",
        "response_reason": reason,
    }


def hybrid_result(question, authorization, context):
    if not hybrid.external_provider():
        return validated_result(generate(question, authorization), authorization)
    if not hybrid.external_allowed(context):
        return search_only(question, authorization, "external_policy")
    breaker = hybrid.circuit()
    try:
        permit = breaker.enter()
    except hybrid.InferenceUnavailable as error:
        return search_only(question, authorization, error.reason)
    try:
        selected = hybrid.ExternalModel(
            model(),
            context,
            budget=float(os.getenv("HYBRID_INFERENCE_BUDGET_SECONDS", "90")),
        )
        try:
            result = generate(question, authorization, external_model=selected)
        except Exception:
            if selected.failure:
                raise selected.failure from None
            raise
        if selected.failure:
            raise selected.failure
    except hybrid.InferenceUnavailable as error:
        breaker.finish(permit, failed=not error.reason.startswith("finops_"))
        return search_only(question, authorization, error.reason)
    except hybrid.InferenceDenied as error:
        breaker.finish(permit)
        raise HTTPException(503, "PROVIDER_CONFIGURATION_ERROR") from error
    except Exception:
        breaker.finish(permit)
        raise
    breaker.finish(permit)
    return validated_result(result, authorization)


def validated_result(result, authorization):
    sources = set(result.get("citations", []))
    selected = [
        doc
        for doc in result.get("documents", [])
        if doc.metadata.get("source") in sources
    ]
    if result.get("requires_human_review", True) or not selected:
        return {"answer": NO_ANSWER, "requires_human_review": True, "citations": []}
    ids = {doc.metadata["document_id"] for doc in selected}
    valid = knowledge(
        "documents/validate", {"document_ids": sorted(ids)}, authorization
    )
    if valid.get("version") != 1 or ids - set(valid["document_ids"]):
        return {"answer": NO_ANSWER, "requires_human_review": True, "citations": []}
    snapshots = []
    for source in result["citations"]:
        doc = next(
            (doc for doc in selected if doc.metadata.get("source") == source), None
        )
        if doc:
            snapshots.append(
                {
                    "source": source,
                    "document_id": doc.metadata["document_id"],
                    "chunk_id": doc.metadata["chunk_id"],
                    "page": doc.metadata.get("page"),
                    "score": doc.metadata.get("score"),
                    "quote": doc.page_content,
                }
            )
    return {
        "answer": str(result["answer"]),
        "requires_human_review": False,
        "citations": snapshots,
    }


@app.post("/api/v1/questions")
def ask(body: Question, request: Request, context=Depends(authorize)):
    question = body.question
    if body.conversation_id:
        with db(context) as conn:
            owned_conversation(conn, body.conversation_id)
            rows = conn.execute(
                "SELECT role,content FROM messages WHERE conversation_id=%s ORDER BY sequence DESC LIMIT 6",
                (body.conversation_id,),
            ).fetchall()
        question = with_history(question, rows)
    controller = capacity()
    lease = None
    lease_context = None
    try:
        controller.enforce_rate(context)
        lease = controller.acquire(
            timeout=float(os.getenv("LLM_QUEUE_TIMEOUT_SECONDS", "5"))
        )
        lease_context = active_lease.set(lease)
        authorization = request.headers["Authorization"]
        result = hybrid_result(question, authorization, context)
        lease.ensure_valid()
    except CapacityBusy as exc:
        raise HTTPException(
            429, "LLM_CAPACITY_EXCEEDED", headers={"Retry-After": "5"}
        ) from exc
    except RateLimited as exc:
        raise HTTPException(
            429,
            "RAG_RATE_LIMIT_EXCEEDED",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except ControlUnavailable as exc:
        raise HTTPException(503, "ADMISSION_CONTROL_UNAVAILABLE") from exc
    except APITimeoutError as exc:
        raise HTTPException(504, "LLM_TIMEOUT") from exc
    except APIConnectionError as exc:
        raise HTTPException(503, "LLM_UNAVAILABLE") from exc
    except RateLimitError as exc:
        raise HTTPException(
            429, "LLM_CAPACITY_EXCEEDED", headers={"Retry-After": "5"}
        ) from exc
    except APIStatusError as exc:
        raise HTTPException(
            503, "LLM_UNAVAILABLE", headers={"Retry-After": "5"}
        ) from exc
    finally:
        if lease_context is not None:
            active_lease.reset(lease_context)
        if lease:
            lease.release()
    cid = body.conversation_id or uuid4()
    with db(context) as conn:
        if body.conversation_id:
            owned_conversation(conn, cid, True)
            conn.execute(
                "UPDATE conversations SET updated_at=now() WHERE id=%s", (cid,)
            )
        else:
            conn.execute(
                "INSERT INTO conversations(id,workspace_id,user_id,title) VALUES(%s,%s,%s,%s)",
                (
                    cid,
                    UUID(context["workspace_id"]),
                    UUID(context["user_id"]),
                    body.question[:500],
                ),
            )
        for role, content, citations, review in (
            ("USER", body.question, [], False),
            (
                "ASSISTANT",
                result["answer"],
                result["citations"],
                result["requires_human_review"],
            ),
        ):
            conn.execute(
                """INSERT INTO messages(id,conversation_id,workspace_id,user_id,role,content,citations,requires_human_review,response_mode,response_reason)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    uuid4(),
                    cid,
                    UUID(context["workspace_id"]),
                    UUID(context["user_id"]),
                    role,
                    content,
                    Jsonb(citations),
                    review,
                    result.get("response_mode", "generated")
                    if role == "ASSISTANT"
                    else "generated",
                    result.get("response_reason", "") if role == "ASSISTANT" else "",
                ),
            )
    hybrid.record_outcome(
        result.get("response_mode", "generated"), result.get("response_reason", "")
    )
    return {
        "response_mode": result.get("response_mode", "generated"),
        "response_reason": result.get("response_reason", ""),
        "answer": result["answer"],
        "citations": [item["source"] for item in result["citations"]],
        "requires_human_review": result["requires_human_review"],
        "conversation_id": str(cid),
    }


def summary(row):
    return {
        "conversation_id": str(row["id"]),
        "title": row["title"],
        "updated_at": row["updated_at"],
    }


@app.get("/api/v1/conversations")
def conversations(context=Depends(authorize)):
    with db(context) as conn:
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 50"
        ).fetchall()
    return [summary(row) for row in rows]


@app.get("/api/v1/conversations/{conversation_id}")
def conversation(conversation_id: UUID, context=Depends(authorize)):
    with db(context) as conn:
        row = owned_conversation(conn, conversation_id)
        messages = conn.execute(
            "SELECT * FROM messages WHERE conversation_id=%s ORDER BY sequence",
            (conversation_id,),
        ).fetchall()
    return {
        **summary(row),
        "messages": [
            {
                "message_id": str(message["id"]),
                "role": message["role"],
                "content": message["content"],
                "citations": [item["source"] for item in message["citations"]],
                "requires_human_review": message["requires_human_review"],
                "response_mode": message["response_mode"],
                "response_reason": message["response_reason"],
                "created_at": message["created_at"],
            }
            for message in messages
        ],
    }

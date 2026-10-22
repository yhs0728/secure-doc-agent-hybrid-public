from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.runtime import build_application_graph, update_persisted_index
from config.settings import Settings
from retrieval.vector_store import create_retriever
from services.question_service import execute_rag_question


@dataclass(frozen=True)
class EvaluationResult:
    question: str
    expected_sources: list[str]
    retrieved_sources: list[str]
    citations: list[str]
    top_1_hit: bool | None
    top_3_hit: bool | None
    expected_citation_hit: bool | None
    unrelated_citation_free: bool | None
    unsupported_answer_blocked: bool | None
    requires_human_review: bool | None
    answer: str | None


def load_cases(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or len(data) < 20:
        raise ValueError("평가 세트에는 최소 20개 문항이 필요합니다.")
    return data


def source_names(documents: list[Any]) -> list[str]:
    return [
        str(document.metadata.get("source", ""))
        for document in documents
        if document.metadata.get("source")
    ]


def evaluate(*, settings: Settings, cases: list[dict[str, Any]], retrieval_only: bool) -> list[EvaluationResult]:
    indexing_result = update_persisted_index(settings=settings)
    retriever = create_retriever(indexing_result.vector_store, k=max(3, settings.retrieval_k))
    graph = None if retrieval_only else build_application_graph(settings=settings)
    results: list[EvaluationResult] = []

    for case in cases:
        question = str(case["question"])
        expected = [str(item) for item in case.get("expected_sources", [])]
        expected_set = set(expected)
        retrieved = source_names(retriever.invoke(question))

        answer: str | None = None
        citations: list[str] = []
        requires_review: bool | None = None
        if graph is not None:
            response = execute_rag_question(graph=graph, question=question)
            answer = str(response.get("answer", ""))
            citations = [str(item) for item in response.get("citations", [])]
            requires_review = bool(response.get("requires_human_review", True))

        is_answerable = bool(expected)
        expected_citation_hit = None if graph is None or not is_answerable else bool(expected_set & set(citations))
        blocked = None
        if graph is not None and bool(case.get("expect_blocked", False)):
            blocked = requires_review is True and not citations

        results.append(EvaluationResult(
            question=question,
            expected_sources=expected,
            retrieved_sources=retrieved,
            citations=citations,
            top_1_hit=(bool(retrieved) and retrieved[0] in expected_set) if is_answerable else None,
            top_3_hit=bool(set(retrieved[:3]) & expected_set) if is_answerable else None,
            expected_citation_hit=expected_citation_hit,
            unrelated_citation_free=(
                None
                if graph is None
                else (not citations or set(citations).issubset(expected_set))
            ),
            unsupported_answer_blocked=blocked,
            requires_human_review=requires_review,
            answer=answer,
        ))

    return results


def ratio(values: list[bool | None]) -> float | None:
    measured = [value for value in values if value is not None]
    return None if not measured else sum(measured) / len(measured)


def summarize(results: list[EvaluationResult]) -> dict[str, float | int | None]:
    return {
        "case_count": len(results),
        "top_1_accuracy": ratio([item.top_1_hit for item in results]),
        "top_3_accuracy": ratio([item.top_3_hit for item in results]),
        "citation_accuracy": ratio([item.expected_citation_hit for item in results]),
        "unrelated_citation_free_rate": ratio([item.unrelated_citation_free for item in results]),
        "unsupported_answer_block_rate": ratio([item.unsupported_answer_blocked for item in results]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="실제 임베딩/LLM RAG 품질 평가")
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/questions.json"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/results.json"))
    parser.add_argument("--retrieval-only", action="store_true")
    args = parser.parse_args()

    results = evaluate(
        settings=Settings(),
        cases=load_cases(args.dataset),
        retrieval_only=args.retrieval_only,
    )
    report = {"summary": summarize(results), "results": [asdict(item) for item in results]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

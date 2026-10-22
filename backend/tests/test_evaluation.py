import json
from pathlib import Path

from evaluation.evaluate_rag import EvaluationResult, load_cases, summarize


def test_evaluation_dataset_has_at_least_twenty_cases() -> None:
    cases = load_cases(Path("evaluation/questions.json"))

    assert len(cases) >= 20
    assert any(not case["expected_sources"] for case in cases)
    assert {
        Path(source).suffix
        for case in cases
        for source in case["expected_sources"]
    } >= {
        ".txt", ".pdf", ".docx", ".csv"
    }


def test_evaluation_summary_uses_only_applicable_cases(tmp_path: Path) -> None:
    results = [
        EvaluationResult(
            question="answerable",
            expected_sources=["a.txt"],
            retrieved_sources=["a.txt"],
            citations=["a.txt"],
            top_1_hit=True,
            top_3_hit=True,
            expected_citation_hit=True,
            unrelated_citation_free=True,
            unsupported_answer_blocked=None,
            requires_human_review=False,
            answer="answer",
        ),
        EvaluationResult(
            question="unsupported",
            expected_sources=[],
            retrieved_sources=["a.txt"],
            citations=[],
            top_1_hit=None,
            top_3_hit=None,
            expected_citation_hit=None,
            unrelated_citation_free=True,
            unsupported_answer_blocked=True,
            requires_human_review=True,
            answer="blocked",
        ),
    ]

    assert summarize(results) == {
        "case_count": 2,
        "top_1_accuracy": 1.0,
        "top_3_accuracy": 1.0,
        "citation_accuracy": 1.0,
        "unrelated_citation_free_rate": 1.0,
        "unsupported_answer_block_rate": 1.0,
    }


def test_committed_dataset_is_valid_json() -> None:
    assert isinstance(json.loads(Path("evaluation/questions.json").read_text("utf-8")), list)

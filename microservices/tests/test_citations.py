import pytest
from conversation_service.graph.nodes import citation_filter_node
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel


@pytest.mark.parametrize(
    "response,expected",
    [
        ('{"citations": [2]}', ["acceptance-ed6d03eabf7c.txt"]),
        ('{"citations": [2, 2, 1]}', ["acceptance-ed6d03eabf7c.txt", "other.txt"]),
        ('{"citations": [0, -1, 3, true, null, {}, "2", 2.0]}', []),
        ('{"citations": ["acceptance-ed6d03eabf17c.txt"]}', []),
        ('{"citations": []}', []),
        ('{"citations": "2"}', []),
        ("invalid JSON", []),
    ],
)
def test_citation_numbers_map_only_to_original_sources(response, expected):
    result = citation_filter_node(
        {
            "question": "How often must passwords be changed?",
            "answer": "Every 90 days.",
            "documents": [
                Document(page_content="Other policy", metadata={"source": "other.txt"}),
                Document(
                    page_content="Change every 90 days.",
                    metadata={"source": "acceptance-ed6d03eabf7c.txt"},
                ),
            ],
        },
        FakeListChatModel(responses=[response]),
    )
    assert result["citations"] == expected


def test_missing_source_does_not_shift_document_numbers():
    result = citation_filter_node(
        {
            "question": "test",
            "answer": "answer",
            "documents": [
                Document(page_content="invalid metadata"),
                Document(page_content="valid", metadata={"source": "valid.txt"}),
            ],
        },
        FakeListChatModel(responses=['{"citations": [1, 2]}']),
    )
    assert result["citations"] == ["valid.txt"]

import pytest

from langchain_core.language_models.fake_chat_models import (
    FakeListChatModel,
)

from rag.generator import (
    NO_ANSWER_MESSAGE,
    generate_answer,
)


def test_generate_answer() -> None:
    model = FakeListChatModel(
        responses=[
            (
                "사용자는 비밀번호를 "
                "90일마다 변경해야 합니다."
            ),
        ]
    )

    answer = generate_answer(
        question="비밀번호 변경 주기는?",
        context=(
            "사용자는 비밀번호를 "
            "90일마다 변경해야 합니다."
        ),
        model=model,
    )

    assert answer == (
        "사용자는 비밀번호를 "
        "90일마다 변경해야 합니다."
    )


def test_generate_answer_returns_no_answer_when_context_is_empty(
) -> None:
    model = FakeListChatModel(
        responses=[
            "이 응답은 사용되지 않아야 합니다.",
        ]
    )

    answer = generate_answer(
        question="비밀번호 변경 주기는?",
        context="   ",
        model=model,
    )

    assert answer == NO_ANSWER_MESSAGE


def test_generate_answer_rejects_blank_question() -> None:
    model = FakeListChatModel(
        responses=[
            "테스트 응답",
        ]
    )

    with pytest.raises(
        ValueError,
        match="질문은 비어 있을 수 없습니다.",
    ):
        generate_answer(
            question="   ",
            context="보안 규정 내용",
            model=model,
        )
"""Bound conversation context before passing it to retrieval and generation."""

import os


def with_history(question, newest_first):
    # A character cap is deterministic across providers; it is not a token count.
    # Keep room for retrieved evidence and the generated answer as well.
    requested = int(os.getenv("LLM_HISTORY_MAX_CHARACTERS", "2000"))
    budget = min(max(requested, 0), 8000)
    if not newest_first or not budget:
        return question
    turns = []
    for row in newest_first:
        label = row["role"] + ": "
        remaining = budget - sum(len(turn) + 1 for turn in turns) - len(label)
        if remaining <= 0:
            break
        content = row["content"]
        turns.append(label + content[-remaining:])
        if len(content) >= remaining:
            break
    if not turns:
        return question
    history = "\n".join(reversed(turns))
    return (
        "이전 대화는 질문 해석에만 사용하고 사실 근거는 검색 문서에서 찾으세요.\n"
        f"이전 대화:\n{history}\n현재 질문:\n{question}"
    )

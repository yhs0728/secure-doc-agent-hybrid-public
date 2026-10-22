from functools import partial

from langchain_core.language_models.chat_models import (
    BaseChatModel,
)
from langchain_core.vectorstores import (
    VectorStoreRetriever,
)
from langgraph.graph import (
    END,
    START,
    StateGraph,
)

from graph.nodes import (
    citation_filter_node,
    generate_node,
    groundedness_check_node,
    no_context_node,
    query_rewrite_node,
    relevance_check_node,
    retrieve_node,
    review_required_node,
    route_after_groundedness,
    route_after_relevance,
    route_after_retrieve,
)
from graph.state import GraphState


def build_rag_workflow(
    retriever: VectorStoreRetriever,
    model: BaseChatModel,
):
    workflow = StateGraph(GraphState)

    workflow.add_node(
        "retrieve",
        partial(
            retrieve_node,
            retriever=retriever,
        ),
    )

    workflow.add_node(
        "relevance_check",
        partial(
            relevance_check_node,
            model=model,
        ),
    )

    workflow.add_node(
        "query_rewrite",
        partial(
            query_rewrite_node,
            model=model,
        ),
    )

    workflow.add_node(
        "generate",
        partial(
            generate_node,
            model=model,
        ),
    )

    workflow.add_node(
        "citation_filter",
        partial(citation_filter_node, model=model),
    )

    workflow.add_node(
        "groundedness_check",
        partial(
            groundedness_check_node,
            model=model,
        ),
    )

    workflow.add_node(
        "no_context",
        no_context_node,
    )

    workflow.add_node(
        "review_required",
        review_required_node,
    )

    workflow.add_edge(
        START,
        "retrieve",
    )

    workflow.add_conditional_edges(
        "retrieve",
        route_after_retrieve,
        {
            "relevance_check": "relevance_check",
            "query_rewrite": "query_rewrite",
            "no_context": "no_context",
        },
    )

    workflow.add_conditional_edges(
        "relevance_check",
        route_after_relevance,
        {
            "generate": "generate",
            "query_rewrite": "query_rewrite",
            "no_context": "no_context",
        },
    )

    workflow.add_edge(
        "query_rewrite",
        "retrieve",
    )

    workflow.add_edge(
        "generate",
        "citation_filter",
    )

    workflow.add_edge(
        "citation_filter",
        "groundedness_check",
    )

    workflow.add_conditional_edges(
        "groundedness_check",
        route_after_groundedness,
        {
            "end": END,
            "review_required": "review_required",
        },
    )

    workflow.add_edge(
        "no_context",
        END,
    )

    workflow.add_edge(
        "review_required",
        END,
    )

    return workflow.compile()

"""Graph assembly.

The four cognitive layers wired as a state machine. Understanding runs first
and makes no decisions; planning turns observations into work; the decision
layer chooses a path; execution carries it out.

Two branches end the run without an answer, and both leave the conversation
durable and resumable at exactly the step it stopped on:

* `clarify`     — one targeted question, waiting on the customer.
* `escalate_human` — a drafted reply waiting on a reviewer.

That is what lets the customer experience a single continuous conversation
while several actors participate behind it.
"""

from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from app.core.logging import get_logger
from app.domain.enums import RoutingTier
from app.domain.policies import intent_policy
from app.graph.nodes import build_nodes
from app.graph.state import GraphState

logger = get_logger(__name__)

# A draft that fails grounding gets exactly one more attempt before it goes to
# a person. An unbounded retry loop would burn the latency budget and, more
# importantly, a model that hallucinated once usually does it again.
MAX_GROUNDING_RETRIES = 1


def route_after_plan(state: GraphState) -> Literal["clarify", "retrieve"]:
    """Gather missing facts before doing work that depends on them.

    An incomplete step executed now produces a confidently wrong answer; one
    question produces a right one. Clarification is not a failure path — for
    "is this still available?" it is the only honest response.

    Except when someone needs a person. A complaint, or an angry and urgent
    message, must never be held at the clarification gate: "Terrible service,
    get me a manager" contains a service intent with an unfilled vehicle slot,
    and asking that customer which vehicle they mean before escalating would
    turn one complaint into two. Escalation outranks information gathering.
    """
    if _needs_a_person_now(state):
        return "retrieve"

    plan = state.get("plan")
    if plan and plan.next_action and plan.next_action.startswith("ask_"):
        return "clarify"
    return "retrieve"


def _needs_a_person_now(state: GraphState) -> bool:
    """Whether the decision layer will escalate regardless of missing facts."""
    policy = intent_policy()

    for intent in state["intents"].unresolved:
        if policy.rule(intent.category).force_human:
            return True

    sentiment = state.get("sentiment")
    return bool(sentiment and sentiment.demands_human)


def route_after_decision(
    state: GraphState,
) -> Literal["generate", "escalate_human"]:
    """The confidence bands, plus every hard override."""
    decision = state.get("routing")
    if decision is None or decision.tier is RoutingTier.HUMAN:
        return "escalate_human"
    return "generate"


def route_after_grounding(
    state: GraphState,
) -> Literal["actuate", "generate", "escalate_human"]:
    """Whether the draft may proceed.

    Retry once on a soft failure; escalate immediately when a numeric claim
    is unsupported, because that is a wrong quote rather than weak prose and
    another attempt is unlikely to fix it.
    """
    report = state.get("grounding")
    if report is None or report.passes:
        return "actuate"

    if report.has_unsupported_numeric_claim:
        return "escalate_human"

    if state.get("retry_count", 0) < MAX_GROUNDING_RETRIES:
        return "generate"

    return "escalate_human"


def build_graph(deps: Any) -> StateGraph:
    """Assemble the orchestration graph."""
    nodes = build_nodes(deps)
    graph: StateGraph = StateGraph(GraphState)

    for name, fn in nodes.items():
        graph.add_node(name, fn)

    # ── Layer 1: understanding ────────────────────────────────────────
    graph.add_edge(START, "normalize")
    graph.add_edge("normalize", "detect_language")

    # Intent discovery, entity extraction and sentiment are independent
    # observations of the same text, so they fan out in parallel. Their
    # reducers merge the results — which is precisely what state reducers
    # are for.
    graph.add_edge("detect_language", "discover_intents")
    graph.add_edge("detect_language", "extract_entities")
    graph.add_edge("detect_language", "score_sentiment")

    # ── Layer 2: planning ─────────────────────────────────────────────
    # Waits for all three understanding branches to land.
    graph.add_edge("discover_intents", "build_plan")
    graph.add_edge("extract_entities", "build_plan")
    graph.add_edge("score_sentiment", "build_plan")

    graph.add_conditional_edges(
        "build_plan",
        route_after_plan,
        {"clarify": "clarify", "retrieve": "retrieve"},
    )

    # ── Layer 4a: gather evidence before deciding ─────────────────────
    # Retrieval and tools run in parallel; both inform the confidence score,
    # so neither can wait until after the decision.
    graph.add_edge("retrieve", "call_tools")
    graph.add_edge("call_tools", "score_confidence")

    # ── Layer 3: decision ─────────────────────────────────────────────
    graph.add_edge("score_confidence", "decide")
    graph.add_conditional_edges(
        "decide",
        route_after_decision,
        {"generate": "generate", "escalate_human": "escalate_human"},
    )

    # ── Layer 4b: generate, validate, act ─────────────────────────────
    graph.add_edge("generate", "validate_grounding")
    graph.add_conditional_edges(
        "validate_grounding",
        route_after_grounding,
        {
            "actuate": "actuate",
            "generate": "generate",
            "escalate_human": "escalate_human",
        },
    )

    # ── Every path persists structured memory before ending ───────────
    graph.add_edge("actuate", "persist_memory")
    graph.add_edge("clarify", "persist_memory")
    graph.add_edge("escalate_human", "persist_memory")
    graph.add_edge("persist_memory", END)

    return graph


def compile_graph(deps: Any, checkpointer: Any = None) -> Any:
    """Compile the graph with a durable checkpointer.

    The checkpointer is what makes pause-and-resume work: the intent queue,
    the plan and the exact awaited slot survive a process restart, so a
    conversation can resume days later at the step it stopped on.
    """
    graph = build_graph(deps)
    return graph.compile(checkpointer=checkpointer)

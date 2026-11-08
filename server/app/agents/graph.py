"""The workflow, wired in LangGraph.

    START -> planner -> explainer -> action -> critic --(weak and retries < max)--> action
                                                  |
                                                  +--(approved, or retries used up)--> END

The only decision in the graph is the edge after the Critic, and it is plain code
(state.needs_retry), not an AI choice. Action counts each send-back in `retries`, so the loop
can never run more than `critic_max_retries` (default 2) extra times.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..tools import NONE_SCENARIO
from . import nodes
from .state import FlowState, needs_retry, new_state

AGENTS = ("planner", "explainer", "action", "critic")


def route_after_critic(state: FlowState) -> str:
    """Weak and retries left -> back to action; otherwise finish."""
    return "action" if needs_retry(state) else END


def route_after_explainer(state: FlowState) -> str:
    """A request the guard blocked gets its fixed message only: no savings suggestions, no review."""
    guard = state.get("guard")
    return END if guard is not None and guard.level == "blocked" else "action"


def build_graph(deps: nodes.Deps):
    """Compile the workflow. `deps` supplies the model and tools (a fake in tests)."""
    graph = StateGraph(FlowState)
    for name in AGENTS:
        graph.add_node(name, partial(getattr(nodes, name), deps=deps))
    graph.add_edge(START, "planner")
    graph.add_edge("planner", "explainer")
    graph.add_conditional_edges("explainer", route_after_explainer, {"action": "action", END: END})
    graph.add_edge("action", "critic")
    graph.add_conditional_edges("critic", route_after_critic, {"action": "action", END: END})
    return graph.compile()


def initial_state(user_request: str, deps: nodes.Deps) -> FlowState:
    # The Planner rebuilds the pack once it knows the scenario; this one is the "no what-if" baseline.
    return new_state(user_request, deps.build_pack(NONE_SCENARIO))


async def run_flow(user_request: str, deps: nodes.Deps | None = None) -> FlowState:
    """Run the whole workflow once and return the final state."""
    deps = deps or nodes.default_deps()
    return await build_graph(deps).ainvoke(initial_state(user_request, deps))


async def stream_flow(user_request: str, deps: nodes.Deps | None = None) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yield (agent, what it changed) as each agent finishes, for the live progress stream."""
    deps = deps or nodes.default_deps()
    async for update in build_graph(deps).astream(initial_state(user_request, deps), stream_mode="updates"):
        for agent, changes in update.items():
            yield agent, changes

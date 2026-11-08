"""The one object that travels through the workflow.

    request -> Planner -> (simulate, risk) -> Explainer -> Action -> Critic -+-> done
                                                              ^              |
                                                              +-- weak, retries < max

Each node reads what it needs and returns ONLY the keys it changes; LangGraph merges them.
Everything in here is privacy-safe by construction: the fact pack and tool results hold aliases,
ratios and bands (see factpack_schema / tools). The one free-text field that comes from the
customer is `user_request`. It is scrubbed of private names/IDs (privacy.scrub_request) and the scrubbed
copy, `question`, is shown to the Planner (to pick a scenario) and the Explainer (to address the decision
the customer actually asked about). Action and the Critic never see it.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from ..config import settings
from ..factpack_schema import FactPack, RuleFact
from ..health import HealthResult, HealthSnapshot
from ..projection import Preview
from ..tools import RiskResult, ScenarioInput, SimulationResult

Agent = Literal["planner", "explainer", "action", "critic"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Explanation(_Model):
    """`template` is what the model wrote, with {slots}; `text` is what the customer sees."""

    template: str = Field(max_length=1500)
    text: str = Field(max_length=1500)
    used_fallback: bool = False


class Proposal(_Model):
    """One suggested change. The AI proposes the percentage; our code measures the result."""

    move: RuleFact  # from_alias -> to_alias at `percent` of each paycheck (<= 30)
    reason: str = Field(max_length=200)
    outcome: SimulationResult | None = None  # forecast re-run WITH this change, filled by code
    health: HealthSnapshot | None = None  # overall health if the customer accepts this too, by code
    preview: Preview | None = None  # UI-ONLY: graph overlay + forecast series; never sent to a model


class Verdict(_Model):
    ok: bool
    issues: list[str] = []  # what to fix; fed back to Action on a retry
    checked_by: Literal["code", "ai"] = "code"


class FlowState(TypedDict, total=False):
    # --- inputs (set once, by new_state)
    user_request: str  # e.g. "Can I afford a car?"
    fact_pack: FactPack

    # --- Planner
    question: str  # user_request with private names/IDs removed: the only form that reaches a model
    scenario: ScenarioInput  # what-if the customer asked about
    simulation: SimulationResult  # tool: forecast with and without the scenario
    risk: RiskResult  # tool: overdraft / payment-too-big / thin-buffer flags
    health: HealthResult  # tool: overall financial health now vs after the scenario
    preview: Preview  # UI-ONLY: projected graph node + forecast series for the what-if

    # --- Explainer, Action
    explanation: Explanation
    proposals: list[Proposal]  # up to 3

    # --- Critic loop
    verdict: Verdict
    retries: int  # how many times the Critic has sent work back to Action

    # --- bookkeeping (lists append across nodes via the reducer)
    fallbacks: Annotated[list[Agent], operator.add]  # agents whose AI call failed -> canned answer used
    events: Annotated[list[str], operator.add]  # progress lines for the live UI stream


MAX_PROPOSALS = 3


def new_state(user_request: str, fact_pack: FactPack) -> FlowState:
    """Starting state for one run."""
    return FlowState(
        user_request=user_request.strip()[:500],
        fact_pack=fact_pack,
        proposals=[],
        retries=0,
        fallbacks=[],
        events=[],
    )


def can_retry(state: FlowState) -> bool:
    """True while the Critic may still send proposals back to Action."""
    return state.get("retries", 0) < settings.critic_max_retries


def needs_retry(state: FlowState) -> bool:
    """The Critic's routing question: weak proposals AND retries left."""
    verdict = state.get("verdict")
    return verdict is not None and not verdict.ok and can_retry(state)


APPEND_KEYS = ("fallbacks", "events")


def merge_update(state: dict, changes: dict) -> dict:
    """Apply one node's changes the way LangGraph does: list bookkeeping appends, the rest replaces."""
    merged = dict(state)
    for key, value in changes.items():
        merged[key] = merged.get(key, []) + value if key in APPEND_KEYS else value
    return merged

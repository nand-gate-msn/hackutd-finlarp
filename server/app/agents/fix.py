"""'Suggest fixes' for one flagged problem on the graph.

The customer clicked a red node. Here the same Action agent the copilot uses is pointed at that one problem:
  * the model sees the finding's ANONYMOUS text only (aliases, ratios, bands) plus the usual fact pack;
  * it may only propose savings moves (the one change the app can apply and undo);
  * our code measures every proposal (forecast + health) and drops any that fail the Critic's code checks
    (balance stays positive, health does not fall), so no AI review is needed and the call stays cheap.
"""

from __future__ import annotations

import asyncio

from . import nodes
from .nodes import Deps, proposal_issues
from ..tools import ScenarioInput


class UnknownFinding(KeyError):
    """The problem is not (or no longer) found by the math for this question."""


async def suggest_fixes(finding_id: str, scenario: ScenarioInput, deps: Deps) -> dict:
    sim, hlth = await asyncio.gather(
        asyncio.to_thread(deps.simulate, scenario, 0.0),
        asyncio.to_thread(deps.health, scenario, 0.0),
    )
    rsk = await asyncio.to_thread(deps.risk, scenario)
    findings = await asyncio.to_thread(deps.find_problems, scenario, sim)
    finding = next((f for f in findings if f.id == finding_id), None)
    if finding is None:
        raise UnknownFinding(finding_id)

    pack = await asyncio.to_thread(deps.build_pack, scenario, hlth)
    state = {"fact_pack": pack, "scenario": scenario, "simulation": sim, "risk": rsk, "health": hlth, "finding": finding}
    update = await nodes.action(state, deps)

    do_nothing = sim.scenario.share_below_zero
    proposals = [p for p in update["proposals"] if not proposal_issues(p, pack, do_nothing, hlth.after.score)]
    return {
        "finding": finding,
        "proposals": proposals,
        "health_after": hlth.after.score,
        "ai_unavailable": "action" in update["fallbacks"],
        "dropped": len(update["proposals"]) - len(proposals),
    }

"""Turn the finished workflow state into JSON for the browser.

This is where real values come back: the model only ever saw aliases (acct_A), so account labels
are restored here, from the private database, on their way to the customer's screen. Nothing
returned from here is sent to a model.
"""

from __future__ import annotations

from ..db import private_db
from ..engine_firewall.overallFinHealth import LABELS
from .state import FlowState


def restore_labels(aliases: set[str]) -> dict[str, str]:
    """alias -> real display name (falls back to the alias itself)."""
    if not aliases:
        return {}
    marks = ",".join("?" * len(aliases))
    with private_db() as p:
        rows = p.execute(f"SELECT alias, real_name FROM alias_map WHERE alias IN ({marks})", tuple(aliases))
        names = {r["alias"]: r["real_name"] for r in rows if r["real_name"]}
    return {a: names.get(a, a) for a in aliases}


def present_health(h, scenario=None) -> dict:
    """Health before/after for the screen (display labels instead of engine names)."""
    return {
        "before": h.before.model_dump(mode="json"),
        "after": h.after.model_dump(mode="json"),
        "change": h.change,
        "drivers": [{"label": LABELS[d.indicator], "effect": d.effect, "points": d.points} for d in h.drivers],
        "what_if": scenario is not None and scenario.kind != "none",
    }


def present(state: FlowState) -> dict:
    proposals = state.get("proposals", [])
    labels = restore_labels({a for p in proposals for a in (p.move.from_alias, p.move.to_alias)})
    simulation, health = state["simulation"], state["health"]
    return {
        "health": present_health(health, state.get("scenario")),
        "preview": state["preview"].model_dump(mode="json") if state.get("preview") else None,
        "scenario": state["scenario"].model_dump(mode="json"),
        "forecast": simulation.model_dump(mode="json"),
        "risk": state["risk"].model_dump(mode="json"),
        "explanation": {
            "text": state["explanation"].text,
            "canned": state["explanation"].used_fallback,
        },
        "proposals": [
            {
                "from_alias": p.move.from_alias,
                "to_alias": p.move.to_alias,
                "from_label": labels[p.move.from_alias],
                "to_label": labels[p.move.to_alias],
                "percent": p.move.percent,
                "reason": p.reason,
                "forecast": p.outcome.model_dump(mode="json") if p.outcome else None,
                "preview": p.preview.model_dump(mode="json") if p.preview else None,
                "health": None if p.health is None else {
                    "score": p.health.score, "status": p.health.status,
                    "change_vs_scenario": round(p.health.score - health.after.score, 1),
                },
            }
            for p in proposals
        ],
        "verdict": state["verdict"].model_dump(mode="json") if state.get("verdict") else None,
        "retries": state.get("retries", 0),
        "fallbacks": state.get("fallbacks", []),
    }

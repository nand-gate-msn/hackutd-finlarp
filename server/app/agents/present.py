"""Turn the finished workflow state into JSON for the browser.

This is where real values come back: the model only ever saw aliases (acct_A), so account labels
are restored here, from the private database, on their way to the customer's screen. Nothing
returned from here is sent to a model.
"""

from __future__ import annotations

import re

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


_ALIAS = re.compile(r"\b(?:acct|merch|bill|loan)_[A-Za-z0-9]+\b")


def present_findings(findings) -> list[dict]:
    """Problem spots for the screen: aliases in the reasons become real names. The model-safe `anon` text is
    deliberately NOT returned; the server recomputes it when a fix is requested."""
    texts = [f.reason + " " + f.title for f in findings]
    labels = restore_labels({m for t in texts for m in _ALIAS.findall(t)})
    restore = lambda text: _ALIAS.sub(lambda m: labels.get(m.group(0), m.group(0)), text)  # noqa: E731
    return [
        {"id": f.id, "kind": f.kind, "severity": f.severity, "title": restore(f.title), "reason": restore(f.reason),
         "node_ids": f.node_ids}
        for f in findings
    ]


def present_proposals(proposals, health_after: float) -> list[dict]:
    """Suggestion cards for the screen: real account names restored, previews and measured outcomes attached."""
    labels = restore_labels({a for p in proposals for a in (p.move.from_alias, p.move.to_alias)})
    return [
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
                "change_vs_scenario": round(p.health.score - health_after, 1),
            },
        }
        for p in proposals
    ]


def present(state: FlowState) -> dict:
    proposals = state.get("proposals", [])
    simulation, health = state["simulation"], state["health"]
    guard = state.get("guard")
    return {
        "guard": None if guard is None or guard.level == "ok" else {"level": guard.level, "message": guard.message},
        "findings": present_findings(state.get("findings", [])),
        "health": present_health(health, state.get("scenario")),
        "preview": state["preview"].model_dump(mode="json") if state.get("preview") else None,
        "scenario": state["scenario"].model_dump(mode="json"),
        "forecast": simulation.model_dump(mode="json"),
        "risk": state["risk"].model_dump(mode="json"),
        "explanation": {
            "text": state["explanation"].text,
            "canned": state["explanation"].used_fallback,
        },
        "proposals": present_proposals(proposals, health.after.score),
        "verdict": state["verdict"].model_dump(mode="json") if state.get("verdict") else None,
        "retries": state.get("retries", 0),
        "fallbacks": state.get("fallbacks", []),
    }

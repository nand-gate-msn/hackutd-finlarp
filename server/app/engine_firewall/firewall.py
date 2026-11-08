"""Privacy boundary for constructing prompts from aggregated transaction facts."""

from __future__ import annotations

import json

from .fact_pack_build import FactPack, build_fact_pack


def build_prompt(fact_pack: FactPack) -> str:
    """Build the only supported prompt form from an allow-listed FactPack."""
    if not isinstance(fact_pack, FactPack):
        raise TypeError("build_prompt accepts only a FactPack")

    return (
        "Summarize these aggregated financial facts. Do not infer identity or invent details.\n"
        + json.dumps(fact_pack.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    )

"""Privacy boundary: the only way to turn customer facts into prompt text.

build_prompt accepts a FactPack and nothing else, so anything that is not an allow-listed,
already-aggregated fact cannot be placed in a prompt through this door.
"""

from __future__ import annotations

import json

from .fact_pack_build import FactPack, build_fact_pack, build_from_db  # noqa: F401  (re-exported)


def build_prompt(fact_pack: FactPack) -> str:
    """Build the only supported prompt form from an allow-listed FactPack."""
    if not isinstance(fact_pack, FactPack):
        raise TypeError("build_prompt accepts only a FactPack")

    return (
        "Facts about one customer's cash flow. Every value is an anonymous ratio, share or band. "
        "Do not infer identity or invent details.\n"
        + json.dumps(fact_pack.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    )

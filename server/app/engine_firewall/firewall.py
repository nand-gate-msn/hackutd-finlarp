"""Privacy boundary for constructing prompts from aggregated transaction facts."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

_FACT_PACK_PATH = Path(__file__).with_name("factPackBuild")
_FACT_PACK_LOADER = importlib.machinery.SourceFileLoader(
    "engine_firewall_fact_pack", str(_FACT_PACK_PATH)
)
_FACT_PACK_SPEC = importlib.util.spec_from_loader(_FACT_PACK_LOADER.name, _FACT_PACK_LOADER)
if _FACT_PACK_SPEC is None:
    raise ImportError(f"Unable to load FactPack model from {_FACT_PACK_PATH}")
_FACT_PACK_MODULE = importlib.util.module_from_spec(_FACT_PACK_SPEC)
sys.modules[_FACT_PACK_LOADER.name] = _FACT_PACK_MODULE
_FACT_PACK_LOADER.exec_module(_FACT_PACK_MODULE)
FactPack = _FACT_PACK_MODULE.FactPack
build_fact_pack = _FACT_PACK_MODULE.build_fact_pack


def build_prompt(fact_pack: FactPack) -> str:
    """Build the only supported prompt form from an allow-listed FactPack."""
    if not isinstance(fact_pack, FactPack):
        raise TypeError("build_prompt accepts only a FactPack")

    return (
        "Summarize these aggregated financial facts. Do not infer identity or invent details.\n"
        + json.dumps(fact_pack.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    )

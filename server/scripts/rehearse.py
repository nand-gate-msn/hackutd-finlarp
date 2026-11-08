"""Demo rehearsal: run the scripted demo questions through the LIVE workflow and grade each one.

Run from server/:   .venv/bin/python scripts/rehearse.py [--question "..."] [--quick]

* Rebuilds the pinned demo customer (DEMO_PERSONA / RANDOM_SEED / DEMO_END_DATE from .env) in a
  throwaway folder, so your real data/copilot.db and its rules are never touched.
* Calls NVIDIA for real (uses your key and a few dozen requests of the 40/min budget).
* Prints what the audience would see and flags anything that would embarrass you on stage.
"""

import argparse
import asyncio
import re
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import actions, ingest  # noqa: E402
from app.agents import graph, nodes  # noqa: E402
from app.config import settings  # noqa: E402
from app.datagen import PERSONAS, generate  # noqa: E402
from app.engine_firewall.overallFinHealth import LABELS  # noqa: E402
from app.health import health as run_health  # noqa: E402
from app.tools import NONE_SCENARIO, simulate  # noqa: E402

DEMO_QUESTIONS = [
    "Can I afford a car?",
    "What if my rent goes up?",
    "What if I lose some income?",
    "I'm thinking about a new subscription.",
    "How am I doing financially?",
]
SLOW_SECONDS = 25


def pct(x: float) -> str:
    return "<1%" if 0 < x < 0.005 else f"{x:.0%}"


def grade(state: dict, seconds: float) -> list[str]:
    """Things that would look bad live. Empty list = clean."""
    problems = []
    text = state["explanation"].text
    if "educational estimate" not in text:
        problems.append("disclaimer missing")
    if "{" in text or "n/a" in text:
        problems.append("unfilled number in the explanation")
    if re.search(r"\b(\w+) \1\b", text, re.I):
        problems.append("a word is repeated (e.g. a unit added after a slot that already has one)")
    if re.search(r"\b(thirty|sixty|ninety|twice|half|hundred|thousand)\b", text, re.I):
        problems.append("a number was written as a word")
    slots = state["fact_pack"].slots()
    if slots["health_now"] not in text:
        problems.append("the explanation never states the health score")
    if "health_after" in slots and slots["health_after"] not in text:
        problems.append("the explanation never states the health score after the decision")
    if state["fallbacks"]:
        problems.append(f"canned answer used for: {', '.join(state['fallbacks'])}")
    if not state["verdict"].ok:
        problems.append("Critic never approved (proposals trimmed)")
    if seconds > SLOW_SECONDS:
        problems.append(f"slow: {seconds:.0f}s")
    if state["scenario"].kind == "none" and "afford" in state["user_request"].lower():
        problems.append("Planner did not find a scenario in a what-if question")
    return problems


async def rehearse(questions: list[str], quick: bool) -> int:
    deps = nodes.default_deps()
    flagged = 0
    try:
        for q in questions:
            started = time.perf_counter()
            state = await graph.run_flow(q, deps)
            seconds = time.perf_counter() - started
            f = state["simulation"]
            print(f"\n? {q}")
            print(f"  {seconds:4.1f}s | scenario {state['scenario'].kind} | risk {state['risk'].overall} | "
                  f"overdraft chance {pct(f.baseline.share_below_zero)} -> {pct(f.scenario.share_below_zero)} | "
                  f"retries {state['retries']}")
            h = state["health"]
            drivers = ", ".join(f"{LABELS[d.indicator]} {d.effect}" for d in h.drivers) or "no change"
            print(f"  health {h.before.score:g} ({h.before.status}) -> {h.after.score:g} ({h.after.status}) [{drivers}]")
            print("  " + re.sub(r"\s+", " ", state["explanation"].text))
            for p in state["proposals"]:
                print(f"  * move {p.move.percent:g}% {p.move.from_alias}->{p.move.to_alias}: {p.reason} "
                      f"(overdraft chance {pct(p.outcome.scenario.share_below_zero)}, health {p.health.score:g})")
            problems = grade(state, seconds)
            flagged += bool(problems)
            print("  " + ("OK" if not problems else "CHECK: " + "; ".join(problems)))
            if quick:
                break

        # the Accept -> forecast -> Undo path the demo ends on
        print("\n? Accept then Undo on the first suggestion")
        state = await graph.run_flow(questions[0], deps)
        if state["proposals"]:
            p = state["proposals"][0]
            before, h0 = simulate(state["scenario"]), run_health(state["scenario"])
            rule = actions.accept_savings_transfer(p.move.from_alias, p.move.to_alias, p.move.percent)
            after, h1 = simulate(state["scenario"]), run_health(state["scenario"])
            actions.undo_rule(rule["rule_id"])
            restored, h2 = simulate(state["scenario"]), run_health(state["scenario"])
            ok = restored == before and h2 == h0 and h1.after.score > h0.after.score  # accepting must lift health; undo must restore both
            print(f"  overdraft chance {pct(before.scenario.share_below_zero)} -> {pct(after.scenario.share_below_zero)} "
                  f"-> undone {pct(restored.scenario.share_below_zero)} | health {h0.after.score:g} -> "
                  f"{h1.after.score:g} -> undone {h2.after.score:g}  {'OK' if ok else 'CHECK: undo did not restore'}")
            flagged += not ok
        else:
            print("  CHECK: no proposals to accept")
            flagged += 1
    finally:
        await deps.llm.aclose()
    return flagged


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--question", action="append", help="rehearse your own question(s) instead of the scripted ones")
    ap.add_argument("--quick", action="store_true", help="only the first question, then Accept/Undo")
    args = ap.parse_args()
    if not settings.nvidia_api_key.get_secret_value():
        print("NVIDIA_API_KEY missing in server/.env")
        return 2

    end = date.fromisoformat(settings.demo_end_date) if settings.demo_end_date else None
    with tempfile.TemporaryDirectory() as tmp:
        settings.sqlite_path, settings.private_db_path = f"{tmp}/work.db", f"{tmp}/private.db"
        history = generate(PERSONAS[settings.demo_persona], seed=settings.random_seed, months=24, end=end)
        ingest.load_history(history)
        print(f"Pinned demo: persona={settings.demo_persona} seed={settings.random_seed} "
              f"end={settings.demo_end_date or 'today (NOT pinned: numbers will drift daily!)'}; "
              f"{len(history.events)} events")
        if not settings.demo_end_date:
            print("WARNING: set DEMO_END_DATE in server/.env so the demo data never changes.")
        flagged = asyncio.run(rehearse(args.question or DEMO_QUESTIONS, args.quick))
    print(f"\n{'All clean. ' if not flagged else str(flagged) + ' item(s) to look at. '}"
          "Run it again: the numbers should be identical, only the wording may vary.")
    return 1 if flagged else 0


if __name__ == "__main__":
    sys.exit(main())

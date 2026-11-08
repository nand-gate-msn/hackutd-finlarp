"""The four agents as LangGraph-style nodes: async functions (state) -> the keys they change.

  planner   AI (fast model)   request -> scenario; code then runs the simulate and risk tools
  explainer AI (strong model) writes the explanation with {slots}; the server fills in the numbers
  action    AI (strong model) proposes <= 3 savings moves; code re-runs the forecast on each
  critic    code first, then AI (fast model); weak proposals go back to action (<= 2 times)

Nodes take their dependencies explicitly (`Deps`) so tests can run offline with a fake model.
Every AI call goes through app.llm (timeout, rate limit, retries, canned fallback), and every
prompt is built from a FactPack via the firewall.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass

from .. import fallbacks
from ..engine_firewall import firewall
from ..engine_firewall.fact_pack_build import build_from_db
from ..factpack_schema import FactPack, RuleFact
from ..llm import LLM
from ..tools import SIMULATE_SPEC, RiskResult, ScenarioInput, SimulationResult, risk, simulate
from . import prompts
from .privacy import scrub_request
from .state import MAX_PROPOSALS, Explanation, FlowState, Proposal, Verdict, can_retry

# --- limits the Critic enforces (provisional; Finance can tune)
SAFE_OVERDRAFT_SHARE = 0.10  # a proposal may leave at most this share of paths below zero...
SAFE_OVERDRAFT_RISE = 0.02  # ...or add at most this much over doing nothing
MIN_PERCENT, MAX_PERCENT = 1.0, 30.0

_SLOT = re.compile(r"\{(\w+)\}")


@dataclass
class Deps:
    llm: LLM
    simulate: Callable[[ScenarioInput, float], SimulationResult]  # (scenario, savings_percent)
    risk: Callable[[ScenarioInput], RiskResult]
    build_pack: Callable[[ScenarioInput], FactPack]


def default_deps(llm: LLM | None = None) -> Deps:
    return Deps(
        llm=llm or LLM(),
        simulate=lambda sc, pct=0.0: simulate(sc, savings_percent=pct),
        risk=lambda sc: risk(sc),
        build_pack=lambda sc: build_from_db(sc),
    )


# ------------------------------------------------------------------ helpers

def render(template: str, slots: dict[str, str], missing: str | None = None) -> str:
    """Fill {slots}. Unknown slots raise unless `missing` gives a stand-in."""
    def fill(m: re.Match) -> str:
        if m.group(1) in slots:
            return slots[m.group(1)]
        if missing is None:
            raise ValueError(f"unknown slot {{{m.group(1)}}}")
        return missing
    return _SLOT.sub(fill, template)


_NUMBER_WORDS = re.compile(
    r"\b(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|sixty|seventy|"
    r"eighty|ninety|hundred|thousand|million|billion|twice|thrice|double|triple|half|quarter|dozen)\b", re.I)


def _no_digits(text: str, what: str) -> None:
    if re.search(r"[\d$%]", text) or _NUMBER_WORDS.search(text):
        raise ValueError(f"{what} must not contain numbers; use {{slots}}")


def _facts(pack: FactPack, *extra: tuple[str, object]) -> str:
    """The user message: the firewall's prompt plus tool results (bands and flags only)."""
    parts = [firewall.build_prompt(pack)]
    parts += [f"{name}: {json.dumps(obj.model_dump(mode='json'), separators=(',', ':'))}" for name, obj in extra if obj]
    return "\n".join(parts)


def _event(agent: str, text: str) -> list[str]:
    return [f"{agent}: {text}"]


# ------------------------------------------------------------------ planner

async def planner(state: FlowState, deps: Deps) -> dict:
    def validate(args: dict) -> ScenarioInput:
        return ScenarioInput.model_validate(args)

    request = await asyncio.to_thread(scrub_request, state["user_request"])  # the one place free text leaves
    res = await deps.llm.call_tool(
        "planner",
        [{"role": "system", "content": prompts.PLANNER}, {"role": "user", "content": request}],
        SIMULATE_SPEC,
        fallback=ScenarioInput.model_validate(fallbacks.PLANNER),
        validate=validate,
    )
    scenario: ScenarioInput = res.data
    sim, rsk, pack = await asyncio.gather(
        asyncio.to_thread(deps.simulate, scenario, 0.0),
        asyncio.to_thread(deps.risk, scenario),
        asyncio.to_thread(deps.build_pack, scenario),
    )
    return {
        "scenario": scenario,
        "simulation": sim,
        "risk": rsk,
        "fact_pack": pack,
        "fallbacks": ["planner"] if res.used_fallback else [],
        "events": _event("planner", f"scenario {scenario.kind}; risk {rsk.overall}"),
    }


# ------------------------------------------------------------------ explainer

async def explainer(state: FlowState, deps: Deps) -> dict:
    pack = state["fact_pack"]
    slots = pack.slots()

    def validate(obj: dict) -> str:
        template = obj.get("summary")
        if template is None:  # tolerate a differently-named key when the answer is a single text field
            texts = [v for v in obj.values() if isinstance(v, str)]
            template = texts[0] if len(texts) == 1 else None
        if not isinstance(template, str) or not template.strip():
            raise ValueError("summary missing")
        template = template.strip()
        if len(template) > 1200:
            raise ValueError("summary too long")
        render(template, slots)  # raises on an unknown slot
        _no_digits(_SLOT.sub("", template), "summary")
        return template

    res = await deps.llm.call_json(
        "explainer",
        [
            {"role": "system", "content": prompts.EXPLAINER.format(slots=", ".join("{%s}" % k for k in slots))},
            {"role": "user", "content": _facts(pack, ("forecast", state.get("simulation")), ("risk", state.get("risk")))},
        ],
        fallback=fallbacks.EXPLAINER["summary"],
        validate=validate,
    )
    template = res.data
    text = render(template, slots, missing="n/a")
    if fallbacks.DISCLAIMER not in text:
        text = f"{text} {fallbacks.DISCLAIMER}"
    return {
        "explanation": Explanation(template=template, text=text, used_fallback=res.used_fallback),
        "fallbacks": ["explainer"] if res.used_fallback else [],
        "events": _event("explainer", "wrote explanation" + (" (canned)" if res.used_fallback else "")),
    }


# ------------------------------------------------------------------ action

def _parse_proposals(obj: dict, pack: FactPack) -> list[Proposal]:
    items = obj.get("proposals")
    if not isinstance(items, list) or len(items) > MAX_PROPOSALS:
        raise ValueError(f"proposals must be a list of at most {MAX_PROPOSALS}")
    types = {a.alias: a.type for a in pack.accounts}
    out, seen = [], set()
    for item in items:
        move = RuleFact(from_alias=item["from_alias"], to_alias=item["to_alias"], percent=float(item["percent"]))
        if types.get(move.from_alias) != "Checking" or types.get(move.to_alias) != "Savings":
            raise ValueError("a move must go from a Checking to a Savings account in the pack")
        if not MIN_PERCENT <= move.percent <= MAX_PERCENT:
            raise ValueError("percent out of range")
        reason = str(item["reason"]).strip()
        _no_digits(reason, "reason")
        key = (move.from_alias, move.to_alias, move.percent)
        if key in seen:
            raise ValueError("duplicate proposal")
        seen.add(key)
        out.append(Proposal(move=move, reason=reason[:200]))
    return out


async def action(state: FlowState, deps: Deps) -> dict:
    pack, scenario = state["fact_pack"], state["scenario"]
    verdict = state.get("verdict")
    is_retry = verdict is not None and not verdict.ok
    feedback = ""
    if is_retry:
        feedback = prompts.ACTION_FEEDBACK.format(issues="\n".join(f"- {i}" for i in verdict.issues))
    accounts = ", ".join(f"{a.alias} ({a.type})" for a in pack.accounts)

    res = await deps.llm.call_json(
        "action",
        [
            {"role": "system", "content": prompts.ACTION.format(accounts=accounts, feedback=feedback)},
            {"role": "user", "content": _facts(pack, ("forecast", state.get("simulation")), ("risk", state.get("risk")))},
        ],
        fallback=fallbacks.ACTION["proposals"],
        validate=lambda obj: _parse_proposals(obj, pack),
    )
    proposals: list[Proposal] = res.data
    # our code, not the AI, measures what each change would do
    outcomes = await asyncio.gather(
        *(asyncio.to_thread(deps.simulate, scenario, p.move.percent) for p in proposals)
    )
    proposals = [p.model_copy(update={"outcome": o}) for p, o in zip(proposals, outcomes)]
    return {
        "proposals": proposals,
        "retries": state.get("retries", 0) + (1 if is_retry else 0),
        "fallbacks": ["action"] if res.used_fallback else [],
        "events": _event("action", f"{len(proposals)} proposal(s)" + (" (retry)" if is_retry else "")),
    }


# ------------------------------------------------------------------ critic

def proposal_issues(p: Proposal, pack: FactPack, do_nothing_share: float) -> list[str]:
    """Code checks on one proposal: is it valid, and does the balance stay positive?"""
    types = {a.alias: a.type for a in pack.accounts}
    issues = []
    if types.get(p.move.from_alias) != "Checking" or types.get(p.move.to_alias) != "Savings":
        issues.append("use a Checking account as source and a Savings account as destination")
    if not MIN_PERCENT <= p.move.percent <= MAX_PERCENT:
        issues.append("percent must be between 1 and 30")
    if p.outcome is None:
        issues.append("forecast was not re-run for this proposal")
    else:
        share = p.outcome.scenario.share_below_zero
        if share > SAFE_OVERDRAFT_SHARE and share > do_nothing_share + SAFE_OVERDRAFT_RISE:
            issues.append(
                f"moving {p.move.percent:g}% of each paycheck leaves too many forecast paths below zero; "
                "propose a smaller percentage"
            )
    return issues


def code_checks(state: FlowState) -> tuple[list[str], list[Proposal]]:
    """Returns (issues, proposals that pass on their own)."""
    pack = state["fact_pack"]
    issues: list[str] = []
    explanation = state.get("explanation")
    if explanation is None:
        issues.append("no explanation was produced")
    else:
        if fallbacks.DISCLAIMER not in explanation.text:
            issues.append("the disclaimer is missing")
        if "{" in explanation.text:
            issues.append("the explanation has an unfilled slot")
        elif not explanation.used_fallback and render(explanation.template, pack.slots()) not in explanation.text:
            issues.append("explanation numbers do not match the fact pack")
    proposals = state.get("proposals", [])
    if len(proposals) > MAX_PROPOSALS:
        issues.append(f"at most {MAX_PROPOSALS} proposals")
    do_nothing = state["simulation"].scenario.share_below_zero
    good = []
    for p in proposals:
        problems = proposal_issues(p, pack, do_nothing)
        if problems:
            issues += problems
        else:
            good.append(p)
    return issues, good


async def critic(state: FlowState, deps: Deps) -> dict:
    pack = state["fact_pack"]
    issues, good = code_checks(state)
    checked_by = "code"
    if not issues:
        # AI pass: only judgement calls are left (is this realistic, does the text fit the numbers)
        def validate(obj: dict) -> dict:
            if not isinstance(obj.get("ok"), bool):
                raise ValueError("ok must be true or false")
            found = [str(i).strip()[:120] for i in (obj.get("issues") or [])][:3]
            if not obj["ok"] and not found:
                found = ["unspecified concern; propose safer, smaller changes"]
            return {"ok": obj["ok"], "issues": found}

        review = [
            {"move": p.move.model_dump(), "reason": p.reason, "forecast": p.outcome.scenario.model_dump()}
            for p in good
        ]
        res = await deps.llm.call_json(
            "critic",
            [
                {"role": "system", "content": prompts.CRITIC},
                {"role": "user", "content": _facts(pack) + "\nexplanation: " + state["explanation"].text
                 + "\nproposals: " + json.dumps(review, separators=(",", ":"))},
            ],
            fallback=fallbacks.CRITIC,
            validate=validate,
        )
        issues, checked_by = res.data["issues"], "ai"
        ok = res.data["ok"]
        extra = {"fallbacks": ["critic"] if res.used_fallback else []}
    else:
        ok = False
        extra = {"fallbacks": []}

    verdict = Verdict(ok=ok, issues=issues[:5], checked_by=checked_by)
    out = {"verdict": verdict, **extra,
           "events": _event("critic", "approved" if ok else f"sent back ({checked_by}): {len(issues)} issue(s)")}
    if not ok and not can_retry(state):
        out["proposals"] = good  # out of retries: keep only what passed the code checks
        out["events"] += _event("critic", f"retries used up; keeping {len(good)} safe proposal(s)")
    return out

"""The four agent nodes, run offline: a scripted fake Nemotron behind the real safe-call wrapper
(so timeouts/validation/fallbacks are exercised), real simulate/risk/fact-pack code on loaded data."""

import asyncio
import json
from datetime import date

import httpx
import pytest

from app import fallbacks, ingest, llm as llm_mod
from app.agents import nodes
from app.agents.state import Explanation, Proposal, Verdict, needs_retry, new_state
from app.config import settings
from app.datagen import PERSONAS, generate
from app.factpack_schema import RuleFact

CAR = {"kind": "car_loan", "payment_ratio_of_income": 0.15, "term_months": 60}
GOOD_SUMMARY = (
    "Housing takes {housing_share} of spending and the chance of dropping below zero over the next "
    "{horizon_days} is {share_below_zero}."
)


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(settings, "nemotron_lightning_model", "fast-model")
    monkeypatch.setattr(settings, "nemotron_super_model", "strong-model")
    monkeypatch.setattr(settings, "llm_retries", 1)
    monkeypatch.setattr(settings, "monte_carlo_runs", 1000)
    ingest.load_history(generate(PERSONAS["alex"], seed=42, months=24, end=date(2026, 11, 7)))


def tool_reply(args):
    return {"choices": [{"message": {"tool_calls": [{"function": {"name": "simulate", "arguments": json.dumps(args)}}]}}]}


def json_reply(obj):
    return {"choices": [{"message": {"content": json.dumps(obj)}}]}


ROLE_MARKS = {"planner": "You turn a customer", "explainer": "You explain", "action": "You suggest", "critic": "You review"}


class FakeNemotron:
    """replies[role] is a list; each call pops the next, the last one repeats. None = HTTP 503."""

    def __init__(self, **replies):
        self.replies = {k: list(v) for k, v in replies.items()}
        self.calls = {k: [] for k in ROLE_MARKS}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        system = body["messages"][0]["content"]
        role = next(r for r, mark in ROLE_MARKS.items() if system.startswith(mark))
        self.calls[role].append(body)
        queue = self.replies.get(role) or [None]
        reply = queue.pop(0) if len(queue) > 1 else queue[0]
        return httpx.Response(503, text="down") if reply is None else httpx.Response(200, json=reply)


def deps_for(fake: FakeNemotron) -> nodes.Deps:
    client = httpx.AsyncClient(base_url="https://x/v1", transport=httpx.MockTransport(fake))
    return nodes.default_deps(llm_mod.LLM(client, llm_mod.RateLimiter(10_000)))


def run(coro):
    return asyncio.run(coro)


def start(request="Can I afford a car?"):
    """State after the Planner has run with a car scenario (real tools, real fact pack)."""
    fake = FakeNemotron(planner=[tool_reply(CAR)])
    deps = deps_for(fake)
    state = new_state(request, nodes.default_deps().build_pack(nodes.ScenarioInput(kind="none")))
    state.update(run(nodes.planner(state, deps)))
    return state, deps, fake


def merged(state, update):
    out = dict(state)
    for k, v in update.items():
        out[k] = out.get(k, []) + v if k in ("fallbacks", "events") else v
    return out


# ------------------------------------------------------------------ planner

def test_planner_turns_a_request_into_a_scenario_and_runs_both_tools():
    state, _, fake = start("I want to buy a car")
    assert state["scenario"].kind == "car_loan" and state["scenario"].term_months == 60
    assert state["simulation"].added_share_below_zero > 0
    assert state["risk"].overall in ("watch", "risk")
    assert state["fact_pack"].scenario.kind == "car_loan"  # pack rebuilt WITH the scenario
    body = fake.calls["planner"][0]
    assert body["tool_choice"]["function"]["name"] == "simulate"
    assert body["messages"][1]["content"] == "I want to buy a car"
    assert state["fallbacks"] == []


def test_planner_falls_back_to_no_scenario_when_the_model_misbehaves():
    fake = FakeNemotron(planner=[tool_reply({"kind": "yacht", "payment_ratio_of_income": 0.1, "term_months": 5})])
    deps = deps_for(fake)
    state = new_state("buy a yacht", deps.build_pack(nodes.ScenarioInput(kind="none")))
    update = run(nodes.planner(state, deps))
    assert update["scenario"].kind == "none" and update["fallbacks"] == ["planner"]
    assert update["simulation"].added_share_below_zero == 0  # still a usable baseline


# ------------------------------------------------------------------ explainer

def test_explainer_fills_slots_server_side_and_adds_the_disclaimer():
    state, deps, _ = start()
    deps2 = deps_for(FakeNemotron(explainer=[json_reply({"summary": GOOD_SUMMARY})]))
    update = run(nodes.explainer(state, deps2))
    e = update["explanation"]
    assert "{" not in e.text and e.template == GOOD_SUMMARY and not e.used_fallback
    assert state["fact_pack"].slots()["horizon_days"] == "60 days" and "60 days is" in e.text
    assert fallbacks.DISCLAIMER in e.text and update["fallbacks"] == []


def test_explainer_never_sees_the_customers_own_words():
    state, _, _ = start("Can I afford a car? My name is Zelda Canary")
    fake = FakeNemotron(explainer=[json_reply({"summary": GOOD_SUMMARY})])
    run(nodes.explainer(state, deps_for(fake)))
    assert "Zelda" not in json.dumps(fake.calls["explainer"])


@pytest.mark.parametrize("bad", [
    "You will have about 500 dollars left.",          # a number the model made up
    "Overdraft chance is {made_up_slot}.",            # a slot that does not exist
    "Overdraft chance is 16% over {horizon_days}.",   # digits outside slots
    "Your risk over the next thirty days is {share_below_zero}.",  # a number written as a word
    "You would pay twice as much.",
    "",
])
def test_explainer_rejects_invented_numbers_and_uses_the_canned_text(bad):
    state, _, _ = start()
    update = run(nodes.explainer(state, deps_for(FakeNemotron(explainer=[json_reply({"summary": bad})]))))
    e = update["explanation"]
    assert e.used_fallback and update["fallbacks"] == ["explainer"]
    assert fallbacks.DISCLAIMER in e.text and "{" not in e.text


# ------------------------------------------------------------------ action

def proposals_reply(*items):
    return json_reply({"proposals": [
        {"from_alias": f, "to_alias": t, "percent": p, "reason": r} for f, t, p, r in items]})


def test_action_parses_proposals_and_our_code_reruns_the_forecast():
    state, _, _ = start()
    fake = FakeNemotron(action=[proposals_reply(("acct_A", "acct_B", 5, "Builds a small buffer"))])
    update = run(nodes.action(state, deps_for(fake)))
    [p] = update["proposals"]
    assert p.move.percent == 5 and p.outcome is not None
    expected = nodes.default_deps().simulate(state["scenario"], 5.0)
    assert p.outcome == expected  # measured by code, not claimed by the model
    assert update["retries"] == 0 and update["fallbacks"] == []


@pytest.mark.parametrize("bad", [
    proposals_reply(("acct_A", "acct_B", 50, "Too much")),
    proposals_reply(("acct_B", "acct_A", 5, "Wrong direction")),
    proposals_reply(("acct_A", "acct_Z", 5, "Unknown account")),
    proposals_reply(("acct_A", "acct_B", 5, "Saves 200 dollars")),
    proposals_reply(*[("acct_A", "acct_B", p, "ok") for p in (2, 4, 6, 8)]),
])
def test_action_rejects_unsafe_output_and_returns_no_proposals(bad):
    state, _, _ = start()
    update = run(nodes.action(state, deps_for(FakeNemotron(action=[bad]))))
    assert update["proposals"] == [] and update["fallbacks"] == ["action"]


def test_action_counts_a_retry_and_shows_the_critics_complaints():
    state, _, _ = start()
    state["verdict"] = Verdict(ok=False, issues=["propose a smaller percentage"])
    fake = FakeNemotron(action=[proposals_reply(("acct_A", "acct_B", 3, "Gentle step"))])
    update = run(nodes.action(state, deps_for(fake)))
    assert update["retries"] == 1
    assert "propose a smaller percentage" in fake.calls["action"][0]["messages"][0]["content"]


# ------------------------------------------------------------------ critic

def ready(percent=3.0, summary=GOOD_SUMMARY):
    """A state that has run planner, explainer and action with one proposal."""
    state, deps, _ = start()
    state.update(run(nodes.explainer(state, deps_for(FakeNemotron(explainer=[json_reply({"summary": summary})])))))
    p = Proposal(move=RuleFact(from_alias="acct_A", to_alias="acct_B", percent=percent), reason="Builds a buffer",
                 outcome=deps.simulate(state["scenario"], percent))
    state["proposals"] = [p]
    return state


def critic(state, **replies):
    fake = FakeNemotron(**replies)
    return run(nodes.critic(state, deps_for(fake))), fake


def test_critic_approves_good_work_after_both_code_and_ai_checks():
    update, fake = critic(ready(), critic=[json_reply({"ok": True, "issues": []})])
    assert update["verdict"].ok and update["verdict"].checked_by == "ai" and len(fake.calls["critic"]) == 1


def test_critic_code_checks_run_first_and_skip_the_ai_when_they_fail():
    state = ready()
    state["explanation"] = Explanation(template="x", text="Spending looks tight.")  # no disclaimer
    update, fake = critic(state)
    assert not update["verdict"].ok and update["verdict"].checked_by == "code"
    assert "the disclaimer is missing" in update["verdict"].issues
    assert fake.calls["critic"] == []  # no tokens spent on a sure failure


def test_critic_catches_a_tampered_explanation_number():
    state = ready()
    e = state["explanation"]
    state["explanation"] = Explanation(template=e.template, text=e.text.replace("%", "9%", 1))
    update, _ = critic(state)
    assert not update["verdict"].ok and "do not match" in " ".join(update["verdict"].issues)


def test_critic_rejects_a_move_that_drains_the_account():
    update, fake = critic(ready(percent=30.0))
    assert not update["verdict"].ok
    assert "below zero" in " ".join(update["verdict"].issues) and fake.calls["critic"] == []


def test_critic_passes_the_ais_objections_back_as_issues():
    update, _ = critic(ready(), critic=[json_reply({"ok": False, "issues": ["Explain the trade-off better"]})])
    assert not update["verdict"].ok and update["verdict"].issues == ["Explain the trade-off better"]
    assert update["verdict"].checked_by == "ai"


def test_critic_still_approves_when_the_ai_check_is_down():
    update, _ = critic(ready(), critic=[None])
    assert update["verdict"].ok and update["fallbacks"] == ["critic"]


def test_when_retries_run_out_only_code_safe_proposals_are_kept():
    state = ready(percent=30.0)
    state["retries"] = settings.critic_max_retries
    safe = Proposal(move=RuleFact(from_alias="acct_A", to_alias="acct_B", percent=2.0), reason="Tiny step",
                    outcome=nodes.default_deps().simulate(state["scenario"], 2.0))
    state["proposals"] = state["proposals"] + [safe]
    update, _ = critic(state)
    assert [p.move.percent for p in update["proposals"]] == [2.0]


def test_the_retry_loop_stops_after_two_sends_back():
    """Action -> Critic until approved; a Critic that always objects is heard exactly twice."""
    state = ready(percent=30.0)
    deps = deps_for(FakeNemotron(
        action=[proposals_reply(("acct_A", "acct_B", 30, "Aggressive"))],
        critic=[json_reply({"ok": False, "issues": ["too aggressive"]})],
    ))
    state = merged(state, run(nodes.critic(state, deps)))
    sends_back = 0
    while needs_retry(state):
        sends_back += 1
        state = merged(state, run(nodes.action(state, deps)))
        state = merged(state, run(nodes.critic(state, deps)))
    assert sends_back == settings.critic_max_retries == state["retries"]
    assert not state["verdict"].ok and state["proposals"] == []  # nothing unsafe survives


def test_the_explainer_prompt_tells_the_model_what_the_slots_mean_and_not_to_repeat_units():
    state, _, _ = start()
    fake = FakeNemotron(explainer=[json_reply({"summary": GOOD_SUMMARY})])
    run(nodes.explainer(state, deps_for(fake)))
    system = fake.calls["explainer"][0]["messages"][0]["content"]
    assert "WITH the scenario applied" in system and "do NOT" in system and "{cash_runway}" in system


def test_planner_and_critic_run_cool_while_the_writers_keep_the_default_temperature():
    state, _, fake = start()
    assert fake.calls["planner"][0]["temperature"] == settings.llm_temperature_precise
    run(nodes.explainer(state, deps_for(FakeNemotron(explainer=[json_reply({"summary": GOOD_SUMMARY})]))))
    f2 = FakeNemotron(explainer=[json_reply({"summary": GOOD_SUMMARY})])
    run(nodes.explainer(state, deps_for(f2)))
    assert f2.calls["explainer"][0]["temperature"] == settings.llm_temperature


def test_explainer_accepts_a_single_text_field_under_another_key():
    state, _, _ = start()
    update = run(nodes.explainer(state, deps_for(FakeNemotron(explainer=[json_reply({"explanation": GOOD_SUMMARY})]))))
    assert not update["explanation"].used_fallback and update["explanation"].template == GOOD_SUMMARY


def test_no_slot_name_contains_a_digit_for_the_model_to_copy():
    state, _, _ = start()
    assert not [name for name in state["fact_pack"].slots() if any(c.isdigit() for c in name)]
    assert "overdraft_chance_month" in state["fact_pack"].slots()

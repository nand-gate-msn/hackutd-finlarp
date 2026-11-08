"""The LangGraph wiring, offline: scripted fake model, real tools. Costs no tokens."""

import asyncio
import json
from datetime import date

import pytest

from app import ingest
from app.agents import graph, nodes
from app.config import settings
from app.datagen import PERSONAS, generate

from tests.test_nodes import (  # reuse the scripted fake Nemotron from the node tests
    CAR, GOOD_SUMMARY, FakeNemotron, deps_for, json_reply, proposals_reply, tool_reply,
)

SMALL = proposals_reply(("acct_A", "acct_B", 3, "A gentle step"))
BIG = proposals_reply(("acct_A", "acct_B", 30, "Aggressive"))
APPROVE = json_reply({"ok": True, "issues": []})
OBJECT = json_reply({"ok": False, "issues": ["make it more careful"]})


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    monkeypatch.setattr(settings, "nemotron_lightning_model", "fast-model")
    monkeypatch.setattr(settings, "nemotron_super_model", "strong-model")
    monkeypatch.setattr(settings, "llm_retries", 0)  # one model call per agent turn: easy to count
    monkeypatch.setattr(settings, "monte_carlo_runs", 1000)
    monkeypatch.setattr(settings, "critic_max_retries", 2)
    ingest.load_history(generate(PERSONAS["alex"], seed=42, months=24, end=date(2026, 11, 7)))


def fake(action, critic, explainer=None):
    return FakeNemotron(
        planner=[tool_reply(CAR)],
        explainer=[explainer or json_reply({"summary": GOOD_SUMMARY})],
        action=action,
        critic=critic,
    )


def run(f, request="Can I afford a car?"):
    return asyncio.run(graph.run_flow(request, deps_for(f)))


def test_happy_path_runs_each_agent_once_in_order():
    f = fake([SMALL], [APPROVE])
    state = run(f)
    assert [e.split(":")[0] for e in state["events"]] == ["planner", "explainer", "action", "critic"]
    assert state["verdict"].ok and state["retries"] == 0
    assert len(state["proposals"]) == 1 and state["proposals"][0].outcome is not None
    assert state["explanation"].text and state["fallbacks"] == []
    assert {r: len(c) for r, c in f.calls.items()} == {"planner": 1, "explainer": 1, "action": 1, "critic": 1}


def test_a_weak_proposal_goes_back_to_action_then_is_approved():
    f = fake([BIG, SMALL], [APPROVE])  # 30% fails the code checks, 3% passes
    state = run(f)
    assert state["retries"] == 1 and state["verdict"].ok
    assert [p.move.percent for p in state["proposals"]] == [3.0]
    assert len(f.calls["action"]) == 2 and len(f.calls["critic"]) == 1  # code rejected the first: no AI spend
    assert "below zero" in f.calls["action"][1]["messages"][0]["content"]  # the complaint reached Action


def test_ai_objections_also_loop_back():
    f = fake([SMALL], [OBJECT, APPROVE])
    state = run(f)
    assert state["retries"] == 1 and state["verdict"].ok and len(f.calls["critic"]) == 2
    assert "make it more careful" in f.calls["action"][1]["messages"][0]["content"]


def test_the_loop_ends_after_exactly_two_send_backs():
    f = fake([SMALL], [OBJECT])  # the Critic never approves
    state = run(f)
    assert state["retries"] == 2
    assert len(f.calls["action"]) == 3 and len(f.calls["critic"]) == 3  # first try + 2 retries, then stop
    assert not state["verdict"].ok
    assert [e.split(":")[0] for e in state["events"]].count("action") == 3


def test_when_retries_run_out_unsafe_proposals_are_dropped():
    state = run(fake([BIG], [OBJECT]))  # always proposes a drain, always objected to
    assert state["retries"] == 2 and not state["verdict"].ok
    assert state["proposals"] == []  # nothing unsafe survives to the customer


def test_the_retry_cap_follows_settings(monkeypatch):
    monkeypatch.setattr(settings, "critic_max_retries", 0)
    f = fake([SMALL], [OBJECT])
    state = run(f)
    assert state["retries"] == 0 and len(f.calls["action"]) == 1


def test_a_dead_model_still_produces_a_complete_answer():
    """Every agent fails: canned answers throughout, no crash, no blank screen."""
    f = FakeNemotron(planner=[None], explainer=[None], action=[None], critic=[None])
    state = run(f, "Can I afford a car?")
    assert state["scenario"].kind == "none" and state["proposals"] == []
    assert state["explanation"].used_fallback and "educational estimate" in state["explanation"].text
    assert set(state["fallbacks"]) == {"planner", "explainer", "action", "critic"}
    assert state["verdict"].ok  # nothing unsafe was proposed


def test_stream_yields_each_agent_as_it_finishes():
    async def collect():
        return [a async for a, _ in graph.stream_flow("buy a car", deps_for(fake([BIG, SMALL], [APPROVE])))]

    assert asyncio.run(collect()) == ["planner", "explainer", "action", "critic", "action", "critic"]


def test_the_graph_has_the_intended_shape():
    g = graph.build_graph(deps_for(fake([SMALL], [APPROVE]))).get_graph()
    edges = {(e.source, e.target) for e in g.edges}
    assert {("__start__", "planner"), ("planner", "explainer"), ("explainer", "action"), ("action", "critic"),
            ("critic", "action"), ("critic", "__end__")} <= edges

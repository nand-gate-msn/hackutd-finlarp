"""Projected graph overlays + forecast series: correct amounts, UI-only (never in a prompt)."""

import asyncio
import json
from datetime import date

import pytest

from app import actions, ingest, projection, tools
from app.agents import graph
from app.agents.present import present
from app.config import settings
from app.datagen import PERSONAS, generate
from app.db import work_db
from app.engine_firewall import montecarlo
from app.graph_api import build_graph

from tests.test_nodes import CAR, GOOD_SUMMARY, FakeNemotron, deps_for, json_reply, proposals_reply, tool_reply

NONE = tools.ScenarioInput(kind="none")


def car(r=0.12):
    return tools.ScenarioInput(kind="car_loan", payment_ratio_of_income=r, term_months=60)


@pytest.fixture(autouse=True)
def loaded(monkeypatch):
    monkeypatch.setattr(settings, "monte_carlo_runs", 1000)
    monkeypatch.setattr(settings, "nemotron_lightning_model", "fast-model")
    monkeypatch.setattr(settings, "nemotron_super_model", "strong-model")
    monkeypatch.setattr(settings, "llm_retries", 0)
    ingest.load_history(generate(PERSONAS["alex"], seed=42, months=24, end=date(2026, 11, 7)))


# ------------------------------------------------------------------ forecast series

def test_engine_daily_percentiles_are_ordered_and_end_where_the_summary_ends():
    with work_db() as w:
        rows = [dict(r) for r in w.execute("SELECT * FROM transactions ORDER BY date, id")]
    mc = montecarlo.run_monte_carlo(rows, 300_000, {"date": "2026-11-20", "amount_cents": 50_000},
                                    horizon_days=60, paths=500, account_alias="acct_A")
    for part in ("baseline", "scenario"):
        d = mc[part]["daily_cents"]
        assert len(d["p10"]) == len(d["p50"]) == len(d["p90"]) == 60
        assert all(a <= b <= c for a, b, c in zip(d["p10"], d["p50"], d["p90"]))
        end = mc[part]["ending_balance_cents"]
        assert (d["p10"][-1], d["p50"][-1], d["p90"][-1]) == (end["p10"], end["p50"], end["p90"])


def test_series_come_from_the_same_run_as_the_model_facing_result():
    result, series = tools.simulate_with_series(car())
    assert result == tools.simulate(car())  # the model-facing answer is unchanged
    assert len(series.baseline.p50) == len(series.scenario.p50) == result.horizon_days
    assert series.start == "2026-11-08"  # the day after the pinned demo date
    assert series.scenario.p50[-1] < series.baseline.p50[-1]  # a car payment leaves less money


def test_no_scenario_means_identical_lines():
    _, series = tools.simulate_with_series(NONE)
    assert series.scenario == series.baseline


# ------------------------------------------------------------------ projected nodes

def test_a_what_if_hangs_off_checking_with_its_monthly_cost():
    _, series = tools.simulate_with_series(car(0.12))
    pv = projection.scenario_preview(car(0.12), series)
    with work_db() as w:
        income = tools._load(w)["monthly_income_cents"]
    [node], [edge] = pv.nodes, pv.edges
    assert node.label == "Car loan (projected)" and node.type == "scenario"
    assert (edge.source, edge.target, edge.tag) == ("account:acct_A", projection.SCENARIO_NODE, "simulated")
    assert edge.monthly_cents == node.monthly_cents == round(income * 0.12)


def test_an_income_drop_hangs_off_the_paycheck():
    sc = tools.ScenarioInput(kind="income_drop", payment_ratio_of_income=0.2)
    pv = projection.scenario_preview(sc, tools.simulate_with_series(sc)[1])
    assert pv.nodes[0].label == "Lost income (projected)" and pv.edges[0].source == "income:paycheck"


def test_no_what_if_means_no_projected_node_but_still_a_forecast():
    pv = projection.scenario_preview(NONE, tools.simulate_with_series(NONE)[1])
    assert pv.nodes == [] and pv.edges == [] and pv.series.baseline.p50


def test_a_suggestion_becomes_a_rule_node_between_checking_and_savings():
    pv = projection.rule_preview(5.0, tools.simulate_with_series(car(), savings_percent=5.0)[1])
    with work_db() as w:
        amount, gap, _ = tools._paycheck(tools._load(w)["rows"], "acct_A")
    assert pv.nodes[0].label == "Save 5% of each paycheck"
    assert [(e.source, e.target) for e in pv.edges] == [("account:acct_A", "ghost:rule"), ("ghost:rule", "account:acct_B")]
    assert pv.nodes[0].monthly_cents == round(amount * 0.05 * 30 / gap)


def test_accepted_rules_appear_in_the_graph_and_leave_on_undo():
    rule = actions.accept_savings_transfer("acct_A", "acct_B", 5.0)
    g = build_graph(90)
    [node] = [n for n in g["nodes"] if n["type"] == "rule"]
    assert node["accepted"] and node["label"] == "Save 5% of each paycheck"
    edges = [(e["source"], e["target"], e["tag"]) for e in g["edges"] if e["tag"] == "proposed"]
    assert edges == [("account:acct_A", node["id"], "proposed"), (node["id"], "account:acct_B", "proposed")]
    with work_db() as w:
        monthly = projection.rule_monthly_cents(w, 5.0)
    assert node["in_cents"] == round(monthly * 90 / 30)  # sized to the graph's time window
    actions.undo_rule(rule["rule_id"])
    assert not [n for n in build_graph(90)["nodes"] if n["type"] == "rule"]


# ------------------------------------------------------------------ through the workflow

def run_flow():
    fake = FakeNemotron(planner=[tool_reply(CAR)], explainer=[json_reply({"summary": GOOD_SUMMARY})],
                        action=[proposals_reply(("acct_A", "acct_B", 3, "Gentle"), ("acct_A", "acct_B", 5, "Steady"))],
                        critic=[json_reply({"ok": True, "issues": []})])
    return asyncio.run(graph.run_flow("Can I afford a car?", deps_for(fake))), fake


def test_the_result_carries_a_preview_for_the_what_if_and_each_suggestion():
    state, _ = run_flow()
    out = present(state)
    assert out["preview"]["nodes"][0]["label"] == "Car loan (projected)"
    assert out["preview"]["series"]["scenario"]["p50"]
    three, five = out["proposals"]
    assert three["preview"]["nodes"][0]["label"] == "Save 3% of each paycheck"
    # each suggestion's line includes the what-if AND the savings move: lower than the what-if alone
    assert five["preview"]["series"]["scenario"]["p50"][-1] < out["preview"]["series"]["scenario"]["p50"][-1]


def test_previews_never_reach_a_model():
    _, fake = run_flow()
    sent = json.dumps(fake.calls)
    for marker in ("ghost:", "\"p50\"", "\"series\"", "monthly_cents", "projected"):
        assert marker not in sent, marker

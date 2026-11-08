"""Red flags on the graph: found by code, reasoned in plain words, and kept away from models (except via 'fix')."""

import asyncio
import json
import re
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import findings, ingest, main, tools
from app.agents import graph
from app.agents.present import present, present_findings
from app.config import settings
from app.datagen import PERSONAS, generate
from app.db import private_db, work_db

from tests.test_nodes import CAR, GOOD_SUMMARY, FakeNemotron, deps_for, json_reply, proposals_reply, tool_reply

NONE = tools.ScenarioInput(kind="none")


def car(r):
    return tools.ScenarioInput(kind="car_loan", payment_ratio_of_income=r, term_months=60)


def problems(sc=NONE):
    return findings.find_problems(sc, tools.simulate(sc))


@pytest.fixture(autouse=True)
def loaded(monkeypatch):
    monkeypatch.setattr(settings, "monte_carlo_runs", 1000)
    monkeypatch.setattr(settings, "nemotron_lightning_model", "fast-model")
    monkeypatch.setattr(settings, "nemotron_super_model", "strong-model")
    monkeypatch.setattr(settings, "llm_retries", 0)
    ingest.load_history(generate(PERSONAS["alex"], seed=42, months=24, end=date(2026, 11, 7)))


def by_kind(found, kind):
    return [f for f in found if f.kind == kind]


# ------------------------------------------------------------------ what gets flagged

def test_a_bill_paid_late_is_flagged_with_how_often_and_how_late():
    [late] = by_kind(problems(), "late_payment")
    assert late.node_ids == ["obligation:bill_1"] and late.severity == "watch"
    assert "paid late 1 of 24 times" in late.reason and "worst: 3 days late" in late.reason


def test_trivial_lateness_is_not_flagged():
    """The loan was one day late once in 24 payments: not worth a red node."""
    assert "obligation:loan_1" not in [n for f in problems() for n in f.node_ids]


def test_the_lowest_balance_is_flagged_and_blamed_on_the_payment_before_it():
    [low] = by_kind(problems(), "low_balance")
    assert low.node_ids == ["obligation:bill_1"]  # the rent payment three days earlier
    assert re.search(r"Checking fell to \$[\d,]+ on [A-Z][a-z]{2} \d+", low.reason) and "months of spending" in low.reason


def test_a_decision_is_flagged_only_when_it_causes_the_trouble():
    assert by_kind(problems(NONE), "decision") == []
    assert by_kind(problems(car(0.0)), "decision") == []
    [d] = by_kind(problems(car(0.12)), "decision")
    assert d.node_ids == ["ghost:scenario"] and "from 33% to 42% of income (guideline 36%)" in d.reason


def test_a_bigger_decision_is_a_bigger_problem():
    assert by_kind(problems(car(0.05)), "decision")[0].severity == "watch"
    big = by_kind(problems(car(0.30)), "decision")[0]
    assert big.severity == "risk" and "chance of overdraft" in big.reason


def test_findings_are_listed_worst_first_and_capped():
    found = problems(car(0.30))
    order = {"watch": 1, "risk": 2}
    assert [order[f.severity] for f in found] == sorted((order[f.severity] for f in found), reverse=True)
    assert found[0].kind == "decision" and len(found) <= findings.MAX_FINDINGS


def test_baseline_over_guideline_is_flagged_when_the_data_really_is_over(monkeypatch):
    """The demo customer sits just under the guidelines; lower them and the largest bills light up."""
    monkeypatch.setattr(findings, "HOUSING_GUIDELINE", 0.20)
    monkeypatch.setattr(findings, "TOTAL_GUIDELINE", 0.25)
    kinds = {f.title for f in by_kind(problems(), "over_guideline")}
    assert kinds == {"Housing over guideline", "Housing and debt over guideline"}


def test_every_flagged_node_exists_in_the_graph():
    from app.graph_api import build_graph

    ids = {n["id"] for n in build_graph(365)["nodes"]} | {"ghost:scenario"}
    assert {n for f in problems(car(0.12)) for n in f.node_ids} <= ids


# ------------------------------------------------------------------ privacy

def test_the_model_safe_text_has_no_dates_amounts_or_names():
    for f in problems(car(0.12)):
        assert not re.search(r"\d{4}-\d{2}-\d{2}|\$|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", f.anon), f.anon
        assert "Oakwood" not in f.anon and "Checking fell" not in f.anon


def test_the_screen_text_gets_real_names_back():
    with private_db() as p:
        p.execute("UPDATE alias_map SET real_name = 'Oakwood Apartments' WHERE alias = 'bill_1'")
    shown = {f["kind"]: f for f in present_findings(problems(car(0.12)))}
    assert "bill_1" not in shown["late_payment"]["reason"] and "Oakwood Apartments was paid late" in shown["late_payment"]["reason"]
    assert "Oakwood Apartments" in shown["low_balance"]["reason"]
    assert all("anon" not in f for f in shown.values())  # the model-safe text is never sent to the browser


# ------------------------------------------------------------------ through the workflow

def run_flow():
    fake = FakeNemotron(planner=[tool_reply(CAR)], explainer=[json_reply({"summary": GOOD_SUMMARY})],
                        action=[proposals_reply(("acct_A", "acct_B", 3, "Gentle"))],
                        critic=[json_reply({"ok": True, "issues": []})])
    return asyncio.run(graph.run_flow("Can I afford a car?", deps_for(fake))), fake


def test_the_planner_finds_problems_next_to_the_risk_tool_and_the_result_carries_them():
    state, _ = run_flow()
    out = present(state)
    assert [f["kind"] for f in out["findings"]][0] == "decision" and out["findings"][0]["node_ids"] == ["ghost:scenario"]
    assert {"late_payment", "low_balance"} <= {f["kind"] for f in out["findings"]}


def test_findings_never_reach_the_explainer_action_or_critic():
    _, fake = run_flow()
    sent = json.dumps(fake.calls)
    for marker in ("paid late", "Checking fell", "low_balance", "decision:ghost", "is a problem", "guideline"):
        assert marker not in sent, marker


# ------------------------------------------------------------------ suggest fixes

@pytest.fixture
def client():
    fake = FakeNemotron(action=[proposals_reply(("acct_A", "acct_B", 3, "Builds a cushion for tight months"))])
    main.app.dependency_overrides[main.get_deps] = lambda: deps_for(fake)
    c = TestClient(main.app)
    c.fake = fake
    yield c
    main.app.dependency_overrides.clear()


def fix(client, finding_id, scenario=CAR):
    return client.post("/api/fix", json={"finding_id": finding_id, "scenario": scenario})


def test_fixes_for_a_flagged_problem_are_savings_moves_measured_by_code(client):
    r = fix(client, "low_balance:obligation:bill_1")
    assert r.status_code == 200
    body = r.json()
    assert body["finding"]["kind"] == "low_balance" and not body["ai_unavailable"]
    [p] = body["proposals"]
    assert p["percent"] == 3 and p["forecast"] and p["preview"]["nodes"][0]["label"] == "Save 3% of each paycheck"
    assert p["health"]["change_vs_scenario"] > 0


def test_only_the_anonymous_text_of_the_problem_reaches_the_model(client):
    with private_db() as p:
        p.execute("UPDATE alias_map SET real_name = 'Oakwood Apartments' WHERE alias = 'bill_1'")
    fix(client, "low_balance:obligation:bill_1")
    [call] = client.fake.calls["action"]
    sent = json.dumps(call)
    assert "checking dipped to" in sent and "months of spending in reserve" in sent  # the anonymous finding
    assert "Oakwood" not in sent and "Checking fell" not in sent and not re.search(r"\$\d", sent)
    assert "clicked a problem flagged" in call["messages"][0]["content"]


def test_a_fix_that_would_make_things_worse_is_dropped(client):
    client.fake.replies["action"] = [proposals_reply(("acct_A", "acct_B", 30, "Too much"), ("acct_A", "acct_B", 3, "Gentle"))]
    body = fix(client, "late_payment:bill_1").json()
    assert [p["percent"] for p in body["proposals"]] == [3] and body["dropped"] == 1


def test_no_savings_move_helps_is_a_valid_answer(client):
    client.fake.replies["action"] = [json_reply({"proposals": []})]
    body = fix(client, "late_payment:bill_1").json()
    assert body["proposals"] == [] and not body["ai_unavailable"]


def test_a_dead_model_is_reported_not_hidden(client):
    client.fake.replies["action"] = [None]
    body = fix(client, "low_balance:obligation:bill_1").json()
    assert body["proposals"] == [] and body["ai_unavailable"]


def test_an_unknown_or_stale_problem_is_a_clean_404(client):
    assert fix(client, "late_payment:bill_999").status_code == 404
    assert fix(client, "decision:ghost", scenario={"kind": "none"}).status_code == 404  # no what-if, no decision problem
    assert sum(len(c) for c in client.fake.calls.values()) == 0  # nothing was sent to a model


def test_the_fix_request_is_validated(client):
    assert client.post("/api/fix", json={"finding_id": ""}).status_code == 422
    assert client.post("/api/fix", json={}).status_code == 422

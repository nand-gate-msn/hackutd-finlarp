"""The health tool: overall financial health now vs after a decision, built on overallFinHealth.py."""

from datetime import date

import pytest

from app import actions, health as health_mod, ingest, tools
from app.config import settings
from app.datagen import PERSONAS, generate
from app.engine_firewall.overallFinHealth import LABELS

NONE = {"kind": "none", "payment_ratio_of_income": 0, "term_months": 0}


def car(r):
    return {"kind": "car_loan", "payment_ratio_of_income": r, "term_months": 60}


@pytest.fixture(autouse=True)
def loaded(monkeypatch):
    monkeypatch.setattr(settings, "monte_carlo_runs", 1000)
    ingest.load_history(generate(PERSONAS["alex"], seed=42, months=24, end=date(2026, 11, 7)))


def test_no_decision_means_no_change_and_no_drivers():
    h = health_mod.health(NONE)
    assert h.before == h.after and h.change == 0 and h.drivers == []
    assert 0 <= h.before.score <= 100 and set(h.before.pillars) == {"Spend", "Save", "Borrow", "Plan"}


def test_a_bigger_car_payment_lowers_health_more():
    scores = [health_mod.health(car(r)).after.score for r in (0.05, 0.12, 0.25)]
    assert scores[0] > scores[1] > scores[2] and scores[2] < health_mod.health(NONE).before.score


def test_the_reason_for_a_drop_is_named():
    h = health_mod.health(car(0.2))
    assert h.drivers[0].indicator == "housing_debt_load" and h.drivers[0].effect == "worse"
    assert LABELS[h.drivers[0].indicator] == "Housing and debt load"
    assert len(h.drivers) <= 2 and all(d.points >= health_mod.MIN_DRIVER_POINTS for d in h.drivers)


def test_an_income_drop_does_not_improve_the_savings_rate():
    """Same savings on a smaller income would raise the ratio; savings shrink with income instead."""
    h = health_mod.health({"kind": "income_drop", "payment_ratio_of_income": 0.25, "term_months": 0})
    assert h.after.indicators["savings_rate"] == pytest.approx(h.before.indicators["savings_rate"], abs=0.5)
    assert all(d.indicator != "savings_rate" for d in h.drivers)


@pytest.mark.parametrize("kind,ratio", [("rent_increase", 0.08), ("income_drop", 0.25)])
def test_other_decisions_lower_health_too(kind, ratio):
    h = health_mod.health({"kind": kind, "payment_ratio_of_income": ratio, "term_months": 0})
    assert h.change < 0


def test_saving_more_raises_health_and_the_savings_rate_is_credited():
    low, high = health_mod.health(NONE, savings_percent=5), health_mod.health(NONE, savings_percent=15)
    assert health_mod.health(NONE).before.score < low.after.score < high.after.score
    assert high.drivers[0].indicator == "savings_rate" and high.drivers[0].effect == "better"


def test_a_decision_and_a_savings_move_combine():
    both = health_mod.health(car(0.12), savings_percent=5)
    assert health_mod.health(car(0.12)).after.score < both.after.score < health_mod.health(NONE).before.score + 3


def test_accepted_rules_change_todays_score_and_undo_restores_it():
    before = health_mod.health(NONE).before.score
    rule = actions.accept_savings_transfer("acct_A", "acct_B", 12.0)
    assert health_mod.health(NONE).before.score > before  # the rule is part of life now
    actions.undo_rule(rule["rule_id"])
    assert health_mod.health(NONE).before.score == before


def test_the_overdraft_indicator_uses_the_forecasts_monte_carlo_share():
    report = health_mod.current_report()
    share = tools.simulate(tools.ScenarioInput(kind="none", horizon_days=30)).scenario.share_below_zero
    assert report["indicators"]["overdraft_probability_30d"]["value"] == pytest.approx(share)


def test_the_pages_gauge_is_the_same_number_the_copilot_calls_today():
    from app.graph_api import build_metrics

    assert build_metrics()["overallFinHealth"] == health_mod.health(NONE).before.score


def test_bad_input_is_rejected():
    with pytest.raises(tools.ToolError):
        health_mod.health(NONE, savings_percent=45)
    with pytest.raises(tools.ToolError):
        health_mod.health({"kind": "yacht", "payment_ratio_of_income": 0.1, "term_months": 1})


def test_it_is_registered_as_a_tool_and_returns_plain_json():
    out = tools.run_tool("health", car(0.12))
    assert set(out) == {"before", "after", "change", "drivers", "tag"} and out["change"] < 0
    assert health_mod.HEALTH_SPEC["function"]["name"] == "health"


def test_a_health_result_carries_scores_not_money_or_names():
    import json
    import re

    text = json.dumps(tools.run_tool("health", car(0.12)))
    assert not re.search(r"\b(acct_[A-Z]|merch_\d+|bill_\d+|loan_\d+)\b|\d{4}-\d{2}-\d{2}", text)

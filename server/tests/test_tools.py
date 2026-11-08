"""simulate / risk tools: sensible answers, fact-pack numbers only, strict inputs."""

import json
import re
from datetime import date, timedelta

import pytest

from app import ingest, tools
from app.config import settings
from app.datagen import PERSONAS, generate
from app.engine_firewall import montecarlo

END = date(2026, 11, 7)
NONE = {"kind": "none", "payment_ratio_of_income": 0, "term_months": 0}


def car(ratio, **kw):
    return {"kind": "car_loan", "payment_ratio_of_income": ratio, "term_months": 60, **kw}


@pytest.fixture
def loaded(monkeypatch):
    monkeypatch.setattr(settings, "monte_carlo_runs", 1000)  # fast; the logic is the same
    ingest.load_history(generate(PERSONAS["alex"], seed=42, months=24, end=END))


def test_scenario_none_equals_baseline(loaded):
    out = tools.run_tool("simulate", NONE)
    assert out["scenario"] == out["baseline"] and out["added_share_below_zero"] == 0
    assert out["payments_in_horizon"] == 0


def test_bigger_car_payment_means_more_overdraft_risk(loaded):
    shares = [tools.run_tool("simulate", car(r))["scenario"]["share_below_zero"] for r in (0.0, 0.15, 0.30)]
    assert shares[0] <= shares[1] <= shares[2] and shares[2] > shares[0]


def test_baseline_for_the_demo_customer_is_not_in_overdraft(loaded):
    """alex is tight but was never below zero; the forecast must not say otherwise."""
    assert tools.run_tool("simulate", NONE)["baseline"]["share_below_zero"] < 0.05


def test_repeating_payments_are_counted_inside_the_horizon(loaded):
    assert tools.run_tool("simulate", car(0.1, horizon_days=90))["payments_in_horizon"] == 3
    assert tools.run_tool("simulate", car(0.1, horizon_days=30))["payments_in_horizon"] == 1
    assert tools.run_tool("simulate", car(0.1, term_months=2, horizon_days=90))["payments_in_horizon"] == 2


def test_same_seed_same_answer(loaded):
    assert tools.run_tool("simulate", car(0.15)) == tools.run_tool("simulate", car(0.15))


def test_risk_flags_a_payment_too_big_for_income(loaded):
    def status(ratio, flag):
        return {f["flag"]: f["status"] for f in tools.run_tool("risk", car(ratio))["flags"]}[flag]

    assert status(0.02, "payment_too_big") in ("ok", "watch")
    assert status(0.45, "payment_too_big") == "risk"
    assert tools.run_tool("risk", car(0.45))["overall"] == "risk"


def test_results_hold_bands_and_ratios_only(loaded):
    """No dollars, dates or names may leave the tools."""
    text = json.dumps([tools.run_tool("simulate", car(0.15)), tools.run_tool("risk", car(0.15))])
    assert not re.search(r"\d{4}-\d{2}-\d{2}", text)  # no dates
    assert not re.search(r"acct_|merch_|bill_|loan_", text)  # no aliases needed, none leaked
    assert not [n for n in re.findall(r"\d+\.?\d*", text) if float(n) > 365]  # no amounts


def test_bad_arguments_are_rejected(loaded):
    for bad in (
        {"kind": "yacht", "payment_ratio_of_income": 0.1, "term_months": 12},
        car(1.5),
        car(0.1, horizon_days=400),
        {**car(0.1), "note": "extra field"},
    ):
        with pytest.raises(tools.ToolError):
            tools.run_tool("simulate", bad)
    with pytest.raises(tools.ToolError):
        tools.run_tool("delete_everything", {})


def test_empty_database_gives_a_clear_error():
    with pytest.raises(tools.ToolError, match="load_customer"):
        tools.run_tool("simulate", NONE)


def test_tool_specs_match_the_input_model():
    props = set(tools.SIMULATE_SPEC["function"]["parameters"]["properties"])
    assert props == set(tools.ScenarioInput.model_fields)
    assert tools.RISK_SPEC["function"]["name"] == "risk"


# ---- engine changes the tools depend on

def _paychecks(gaps):
    day, rows = date(2026, 1, 2), []
    for gap in [0, *gaps]:
        day += timedelta(days=gap)
        rows.append({"account_alias": "acct_A", "date": day.isoformat(), "kind": "deposit",
                     "amount_cents": 150000, "label": "paycheck"})
    return rows


def test_recurring_detection_tolerates_one_stray_gap_but_not_chaos():
    assert montecarlo.detect_recurring_items(_paychecks([14, 14, 17, 14, 14, 11, 14, 14, 14, 14, 14]))
    assert not montecarlo.detect_recurring_items(_paychecks([14, 30, 9, 14, 40, 5]))


def test_monthly_scenario_payment_repeats_and_shifts_every_path_by_the_total():
    rows = _paychecks([14] * 12)
    result = montecarlo.run_monte_carlo(
        rows, 100_000,
        {"date": date(2026, 7, 10), "amount_cents": 20_000, "repeat_every_days": 30, "count": None},
        horizon_days=90, paths=50,
    )
    assert result["scenario_payment"]["payments_in_horizon"] == 3
    assert result["paired_final_delta_cents"] == -60_000


def test_accepted_rules_change_the_forecast_and_undo_restores_it(loaded):
    from app import actions

    before = tools.run_tool("simulate", NONE)
    rule = actions.accept_savings_transfer("acct_A", "acct_B", 12.0)
    after = tools.run_tool("simulate", NONE)
    assert after["baseline"] != before["baseline"] and after["scenario"] == after["baseline"]
    assert after["baseline"]["share_below_zero"] >= before["baseline"]["share_below_zero"]
    assert after["added_share_below_zero"] == 0  # rules are life as it is, not a scenario
    actions.undo_rule(rule["rule_id"])
    assert tools.run_tool("simulate", NONE) == before


def test_rules_stack_on_top_of_a_scenario(loaded):
    from app import actions

    plain = tools.run_tool("simulate", car(0.15))["scenario"]["share_below_zero"]
    actions.accept_savings_transfer("acct_A", "acct_B", 12.0)
    stacked = tools.run_tool("simulate", car(0.15))["scenario"]["share_below_zero"]
    assert stacked >= plain

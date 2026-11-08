"""Workflow state: shape, defaults, the retry rule, and the privacy shape of its parts."""

import operator
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.agents.state import (
    MAX_PROPOSALS,
    Explanation,
    Proposal,
    Verdict,
    can_retry,
    needs_retry,
    new_state,
)
from app.config import settings
from app.factpack_schema import FactPack, RuleFact

PACK = FactPack.model_validate_json(Path("app/factpack_sample.json").read_text())


def move(percent=10.0):
    return RuleFact(from_alias="acct_A", to_alias="acct_B", percent=percent)


def test_new_state_has_empty_defaults_and_trims_the_request():
    s = new_state("   Can I afford a car?  ", PACK)
    assert s["user_request"] == "Can I afford a car?"
    assert s["proposals"] == [] and s["retries"] == 0 and s["fallbacks"] == [] and s["events"] == []
    assert "verdict" not in s and "scenario" not in s  # filled by later nodes


def test_long_requests_are_cut_to_500_chars():
    assert len(new_state("x" * 5000, PACK)["user_request"]) == 500


def test_retry_cap_comes_from_settings(monkeypatch):
    monkeypatch.setattr(settings, "critic_max_retries", 2)
    s = new_state("q", PACK)
    s["verdict"] = Verdict(ok=False, issues=["too aggressive"])
    for used, expected in ((0, True), (1, True), (2, False), (3, False)):
        s["retries"] = used
        assert can_retry(s) is expected and needs_retry(s) is expected


def test_a_passing_or_missing_verdict_never_retries():
    s = new_state("q", PACK)
    assert not needs_retry(s)  # no verdict yet
    s["verdict"] = Verdict(ok=True)
    assert not needs_retry(s)


def test_list_keys_use_the_append_reducer():
    """LangGraph merges node outputs with these; confirm they are the append reducer."""
    from typing import get_args, get_type_hints

    from app.agents.state import FlowState

    hints = get_type_hints(FlowState, include_extras=True)
    for key in ("fallbacks", "events"):
        assert get_args(hints[key])[1] is operator.add


def test_models_reject_extra_fields_and_oversized_text():
    with pytest.raises(ValidationError):
        Proposal(move=move(), reason="ok", account_name="Jane Doe")  # no stray fields
    with pytest.raises(ValidationError):
        Proposal(move=move(), reason="x" * 201)
    with pytest.raises(ValidationError):
        Explanation(template="x" * 1501, text="y")


def test_a_proposal_cannot_ask_for_more_than_30_percent_or_use_real_names():
    with pytest.raises(ValidationError):
        move(45.0)
    with pytest.raises(ValidationError):
        RuleFact(from_alias="Jane's Checking", to_alias="acct_B", percent=10)


def test_state_parts_are_immutable():
    v = Verdict(ok=True)
    with pytest.raises(ValidationError):
        v.ok = False


def test_max_proposals_matches_the_plan():
    assert MAX_PROPOSALS == 3

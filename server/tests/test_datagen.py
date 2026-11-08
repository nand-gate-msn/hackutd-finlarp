from dataclasses import replace
from datetime import date

import pytest

from app.datagen import PERSONAS, generate
from app.datagen.generator import signed_effect

END = date(2026, 11, 7)


@pytest.mark.parametrize("key", sorted(PERSONAS))
def test_balance_identity(key):
    """opening + money in - money out = closing, exactly, for every account."""
    h = generate(PERSONAS[key], seed=7, months=24, end=END)
    for acct in ("checking", "savings"):
        assert h.opening_cents[acct] + sum(signed_effect(e, acct) for e in h.events) == h.final_cents[acct]


def test_deterministic_and_seed_sensitive():
    a = generate(PERSONAS["alex"], seed=42, months=12, end=END)
    b = generate(PERSONAS["alex"], seed=42, months=12, end=END)
    c = generate(PERSONAS["alex"], seed=43, months=12, end=END)
    assert a.events == b.events
    assert a.events != c.events


def test_events_are_in_window_and_sorted():
    h = generate(PERSONAS["alex"], seed=1, months=24, end=END)
    dates = [e.date for e in h.events]
    assert dates == sorted(dates)
    assert h.start <= dates[0] and dates[-1] <= END
    assert (END - h.start).days >= 24 * 30


def test_rent_lands_on_due_date_and_amount_is_exact():
    h = generate(PERSONAS["alex"], seed=42, months=24, end=END)
    rent = [e for e in h.events if e.obligation == "rent"]
    assert len(rent) >= 23
    assert {e.amount_cents for e in rent} == {115000}
    assert all(0 <= (e.date - e.due_date).days <= 3 for e in rent)
    assert sum(e.date == e.due_date for e in rent) >= len(rent) * 0.8  # mostly on time


def test_paychecks_are_biweekly_with_a_raise():
    h = generate(PERSONAS["alex"], seed=42, months=24, end=END)
    pay = [e for e in h.events if e.category == "income"]
    assert 50 <= len(pay) <= 53
    assert pay[0].amount_cents == 165000 and pay[-1].amount_cents == 171600  # +4% after a year


def test_savings_transfers_skip_when_checking_is_low():
    alex = PERSONAS["alex"]
    never = generate(replace(alex, savings_buffer=1_000_000), seed=3, months=12, end=END)
    always = generate(replace(alex, savings_buffer=0), seed=3, months=12, end=END)
    assert not [e for e in never.events if e.kind == "transfer"]
    assert never.ground_truth["skipped_savings_transfers"] >= 11
    assert len([e for e in always.events if e.kind == "transfer"]) >= 6
    assert always.ground_truth["skipped_savings_transfers"] < never.ground_truth["skipped_savings_transfers"]


def test_demo_persona_has_realistic_margin():
    gt = generate(PERSONAS["alex"], seed=42, months=24, end=END).ground_truth
    assert gt["min_checking_balance"] > -1000  # tight, but not absurd
    assert gt["income"]["monthly_mean"] > 3000

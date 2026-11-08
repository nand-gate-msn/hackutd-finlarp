import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from app import actions, ingest
from app.config import settings
from app.datagen import PERSONAS, generate
from app.db import private_db, work_db
from app.overview import build_overview, is_loaded

END = date(2026, 11, 7)
SERVER = Path(__file__).resolve().parent.parent


@pytest.fixture
def history():
    return generate(PERSONAS["alex"], seed=42, months=24, end=END)


@pytest.fixture
def loaded(history):
    ingest.load_history(history)
    return history


def test_nothing_loaded_until_ingest(history):
    assert not is_loaded()
    ingest.load_history(history)
    assert is_loaded()


def test_balances_reconcile_after_loading(loaded):
    """closing balance - sum of stored transactions = the opening balance we chose."""
    with work_db() as w:
        for alias, key in (("acct_A", "checking"), ("acct_B", "savings")):
            bal = w.execute("SELECT balance_cents FROM accounts WHERE alias=?", (alias,)).fetchone()[0]
            net = w.execute("SELECT SUM(amount_cents) FROM transactions WHERE account_alias=?",
                            (alias,)).fetchone()[0]
            assert bal - net == loaded.opening_cents[key]


def test_transfers_have_two_sides_and_cancel_out(loaded):
    with work_db() as w:
        out, inn = (w.execute("SELECT COUNT(*), SUM(amount_cents) FROM transactions WHERE kind=?", (k,)).fetchone()
                    for k in ("transfer_out", "transfer_in"))
    assert out[0] == inn[0] > 0 and out[1] == -inn[1]


def test_recovers_known_obligations_and_lateness(loaded):
    ov = build_overview(90)
    by_label = {o["label"]: o for o in ov["obligations"]}
    for truth in loaded.ground_truth["obligations"]:
        found = by_label[truth["payee"]]
        assert found["amount"] == pytest.approx(truth["amount"], rel=0.02)  # "recovered within 2%"
        assert found["due_day"] == truth["due_day"]
        assert found["late_payments"] == truth["late_payments"]
    assert ov["income"]["median_gap_days"] == 14
    assert ov["income"]["paychecks"] == loaded.ground_truth["income"]["count"]


@pytest.mark.parametrize("key", sorted(PERSONAS))
def test_categorizer_recovers_expected_categories(key):
    h = generate(PERSONAS[key], seed=1, months=6, end=END)
    ingest.load_history(h)
    found = {o["label"]: o["category"] for o in build_overview(30)["obligations"]}
    for o in h.persona.obligations:
        assert found[o.payee] == o.category, o.payee


def test_work_db_has_no_names_but_private_db_does(loaded):
    work, private = settings.sqlite_file.read_bytes(), settings.private_file.read_bytes()
    for name in list(loaded.merchants) + [o.payee for o in loaded.persona.obligations]:
        assert name.encode() not in work, f"leaked into work db: {name}"
    assert b"Oakwood Apartments" in private


def test_aliases_are_stable_across_reloads_and_pruned_across_personas(history):
    def aliases():
        with private_db() as p:
            return {r["real_id"]: r["alias"] for r in p.execute("SELECT * FROM alias_map")}
    ingest.load_history(history)
    first = aliases()
    ingest.load_history(history)
    assert aliases() == first and "acct_A" in first.values()
    ingest.load_history(generate(PERSONAS["jordan"], seed=1, months=6, end=END))
    assert not any(k.startswith("alex:") for k in aliases())
    assert "acct_A" in aliases().values()  # aliases restart cleanly for the new customer


def test_accept_then_undo(loaded):
    out = actions.accept_savings_transfer("acct_A", "acct_B", 5)
    assert out["amount"] == pytest.approx(1716 * 0.05)  # 5% of a $1,716 paycheck
    ov = build_overview(30)
    assert [r["status"] for r in ov["rules"]] == ["active"]
    assert actions.undo_rule(out["rule_id"])["status"] == "undone"
    assert build_overview(30)["rules"][0]["status"] == "undone"
    with pytest.raises(actions.ActionError):
        actions.undo_rule(out["rule_id"])
    with pytest.raises(actions.ActionError, match="not found"):
        actions.undo_rule(999)


@pytest.mark.parametrize("args", [("acct_A", "acct_B", 0), ("acct_A", "acct_B", 90),
                                  ("acct_A", "acct_A", 5), ("acct_A", "acct_Z", 5),
                                  ("acct_B", "acct_A", 5)])
def test_accept_rejects_bad_requests(loaded, args):
    with pytest.raises(actions.ActionError):
        actions.accept_savings_transfer(*args)


def test_overview_shape_matches_what_the_client_reads(loaded):
    ov = build_overview(90)
    assert ov["source"] == "generator:alex"
    assert {"period", "accounts", "totals", "outflow_by_group", "income", "obligations", "rules"} <= set(ov)
    acct = ov["accounts"][0]
    assert {"alias", "type", "balance", "deposits", "purchases", "bills", "spending_by_category"} <= set(acct)
    assert {"count", "total", "recent"} <= set(acct["purchases"])


def test_app_has_no_external_dependencies_at_import_time():
    """No Nessie, no Supabase, no HTTP client: loading the app must not import any of them."""
    code = ("import sys, app.main; bad = [m for m in ('httpx', 'app.nessie', 'supabase') if m in sys.modules]; "
            "print(','.join(bad))")
    out = subprocess.run([sys.executable, "-c", code], cwd=SERVER, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""

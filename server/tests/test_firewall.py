"""The privacy boundary: one FactPack shape, built from engine outputs, the only thing in a prompt."""

import asyncio
import json
import logging
import re
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app import ingest
from app.config import settings
from app.datagen import PERSONAS, generate
from app.db import work_db
from app.engine_firewall import fact_pack_build, finmetrics, firewall
from app.factpack_schema import FactPack
from app.http_log import make_client

from datetime import date

CANARIES = ["Canary Person Example", "ACCT-9918-4420-1177", "Canary Merchant Emporium"]
SAMPLE = FactPack.model_validate_json(Path("app/factpack_sample.json").read_text())


@pytest.fixture
def loaded(monkeypatch):
    monkeypatch.setattr(settings, "monte_carlo_runs", 1000)
    ingest.load_history(generate(PERSONAS["alex"], seed=42, months=24, end=date(2026, 11, 7)))


class OutgoingRequestRecorder(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def send_and_capture(prompt: str) -> str:
    """POST the prompt through the logging client; return what the request log recorded."""
    recorder = OutgoingRequestRecorder()
    logger = logging.getLogger("outgoing")
    old_level = logger.level
    logger.addHandler(recorder)
    logger.setLevel(logging.INFO)

    async def transport(request):
        return httpx.Response(200, json={"ok": True}, request=request)

    async def send():
        async with make_client(transport=httpx.MockTransport(transport)) as client:
            return await client.post("https://example.test/prompt", json={"prompt": prompt})

    try:
        assert asyncio.run(send()).status_code == 200
    finally:
        logger.removeHandler(recorder)
        logger.setLevel(old_level)
    logged = [m for m in recorder.messages if m.startswith("→ POST")]
    assert len(logged) == 1
    return logged[0]


def plant_canaries(conn):
    """Simulate identity data leaking into every free-text column of the working database."""
    conn.execute(
        "INSERT INTO transactions (account_alias, date, kind, amount_cents, category, group_name, "
        "counterparty, obligation_alias, days_late, label) VALUES (?,?,?,?,?,?,?,?,?,?)",
        ("acct_A", "2026-11-05", "purchase", -4525, CANARIES[2], "Food", CANARIES[2], None, None, CANARIES[0]),
    )
    conn.execute("UPDATE merchants SET category = ?", (CANARIES[2],))


def test_canaries_planted_in_the_database_never_reach_the_outgoing_request(loaded):
    with work_db() as conn:
        plant_canaries(conn)
    pack = firewall.build_from_db()
    prompt = firewall.build_prompt(pack)
    logged = send_and_capture(prompt)
    for canary in CANARIES:
        assert canary not in prompt and canary not in logged
    assert "share_of_outflow" in logged  # the facts did go out


def test_a_canary_used_as_an_alias_is_refused_not_passed_through(loaded):
    with work_db() as conn:
        conn.execute("UPDATE accounts SET alias = ? WHERE alias = 'acct_B'", (CANARIES[1],))
    with pytest.raises(ValidationError):
        firewall.build_from_db()


def test_prompt_accepts_only_a_fact_pack(loaded):
    for not_a_pack in ({"income_cents": 100}, "free text", None, json.loads(SAMPLE.model_dump_json())):
        with pytest.raises(TypeError, match="only a FactPack"):
            firewall.build_prompt(not_a_pack)
    assert firewall.build_prompt(SAMPLE).startswith("Facts about one customer")


def test_fact_pack_rejects_names_amounts_and_unknown_fields():
    base = json.loads(SAMPLE.model_dump_json())
    for change in (
        {"customer_name": CANARIES[0]},
        {"transactions": [{"amount_cents": 4525}]},
        {"accounts": [{"alias": CANARIES[1], "type": "Checking", "balance_band": "low"}]},
        {"accounts": [{"alias": "acct_A", "type": "Checking", "balance_band": "low", "balance_cents": 262521}]},
        {"categories": [{"group": CANARIES[2], "share_of_outflow": 0.5, "band": "high"}]},
    ):
        with pytest.raises(ValidationError):
            FactPack.model_validate({**base, **change})


def test_assembler_rejects_a_raw_transaction_row():
    row = {"id": 2, "date": "2026-10-02", "kind": "purchase", "amount_cents": -4525, "label": CANARIES[0]}
    with pytest.raises(ValidationError):
        fact_pack_build.build_fact_pack(
            accounts=[row], metrics=[], categories=[], obligations=[],
            forecast=json.loads(SAMPLE.forecast.model_dump_json()),
        )


def test_firewall_and_agents_share_one_factpack_class():
    assert firewall.FactPack is FactPack is fact_pack_build.FactPack


def test_pack_built_from_the_database_has_the_agents_shape(loaded):
    pack = firewall.build_from_db({"kind": "car_loan", "payment_ratio_of_income": 0.15, "term_months": 60})
    assert isinstance(pack, FactPack)
    assert {m.key for m in pack.metrics} == set(SAMPLE_METRIC_KEYS)  # all seven, in schema names
    assert {a.alias for a in pack.accounts} == {"acct_A", "acct_B"}
    assert all(o.alias.startswith(("bill_", "loan_")) for o in pack.obligations)
    assert pack.scenario and pack.scenario.kind == "car_loan"
    assert pack.forecast.horizon_days == 60
    assert 0.99 <= sum(c.share_of_outflow for c in pack.categories) <= 1.01
    for slot in ("housing_share", "share_below_zero", "scenario_payment_ratio", "cash_runway"):
        assert slot in pack.slots()


SAMPLE_METRIC_KEYS = [m.key for m in SAMPLE.metrics]


def test_units_are_converted_to_the_schema(loaded):
    pack = firewall.build_from_db()
    by_key = {m.key: m for m in pack.metrics}
    with work_db() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM transactions")]
        balance = conn.execute("SELECT balance_cents FROM accounts WHERE type = 'Checking'").fetchone()[0]
    engine = finmetrics.housing_debt_load(rows)["value"]
    assert by_key["housing_debt_load"].value == pytest.approx(engine / 100, abs=1e-4)  # percent -> ratio
    assert all(0 <= by_key[k].value <= 1.5 for k in by_key if k != "cash_runway")
    runway_months = finmetrics.cash_runway(rows, balance)["value"]
    assert by_key["cash_runway"].value == pytest.approx(runway_months * 30, rel=0.02)  # months -> days
    assert set(m.status for m in pack.metrics) <= {"ok", "watch", "risk"}


def test_overdraft_metric_follows_the_schema_definition(loaded):
    """It is the simulated share of paths below zero, so it matches the forecast, not history."""
    pack = firewall.build_from_db()
    metric = next(m for m in pack.metrics if m.key == "overdraft_probability_30d")
    assert metric.value < 0.05 and metric.status == "ok"


def test_active_rules_appear_and_undone_ones_do_not(loaded):
    from app import actions

    rule = actions.accept_savings_transfer("acct_A", "acct_B", 5.0)
    assert [(r.from_alias, r.to_alias, r.percent) for r in firewall.build_from_db().rules] == [("acct_A", "acct_B", 5.0)]
    actions.undo_rule(rule["rule_id"])
    assert firewall.build_from_db().rules == []


def test_prompts_contain_no_dates_and_no_dollar_sized_numbers(loaded):
    text = firewall.build_prompt(firewall.build_from_db({"kind": "car_loan", "payment_ratio_of_income": 0.2, "term_months": 48}))
    assert not re.search(r"\d{4}-\d{2}-\d{2}", text)
    assert not [n for n in re.findall(r"\d+\.?\d*", text) if float(n) > 365]

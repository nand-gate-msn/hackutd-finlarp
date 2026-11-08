import importlib.machinery
import importlib.util
import asyncio
import logging
from pathlib import Path
import sys

import httpx
import pytest
from pydantic import ValidationError

from app.http_log import make_client


FIREWALL_PATH = Path(__file__).resolve().parents[2] / "engine-firewall" / "firewall"
_LOADER = importlib.machinery.SourceFileLoader("finmetrics_firewall", str(FIREWALL_PATH))
_SPEC = importlib.util.spec_from_loader(_LOADER.name, _LOADER)
if _SPEC is None:
    raise ImportError(f"Unable to load firewall module from {FIREWALL_PATH}")
firewall = importlib.util.module_from_spec(_SPEC)
sys.modules[_LOADER.name] = firewall
_LOADER.exec_module(firewall)


class OutgoingRequestRecorder(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def test_prompt_canary_excludes_planted_identity_data(caplog):
    canaries = [
        "Canary Person Example",
        "ACCT-9918-4420-1177",
        "Canary Merchant Emporium",
    ]
    transactions = [
        {
            "id": 1,
            "date": "2026-10-01",
            "kind": "deposit",
            "amount_cents": 245000,
            "label": "paycheck",
            "account_alias": canaries[1],
            "customer_name": canaries[0],
            "counterparty": canaries[2],
        },
        {
            "id": 2,
            "date": "2026-10-02",
            "kind": "purchase",
            "amount_cents": -4525,
            "label": canaries[0],
            "account_alias": canaries[1],
            "customer_name": canaries[0],
            "counterparty": canaries[2],
            "merchant_name": canaries[2],
        },
    ]
    with pytest.raises(ValidationError):
        firewall.FactPack.model_validate(transactions[0])

    fact_pack = firewall.build_fact_pack(
        ratios={"savings_rate": 12.5, "housing_debt_load": 28.0},
        category_totals={"dining": 4525},
        aliases={"accounts": ["acct_A"], "merchants": ["merch_1"]},
        value_bands={"savings_rate": "watch", "housing_debt_load": "healthy"},
    )
    prompt = firewall.build_prompt(fact_pack)
    recorder = OutgoingRequestRecorder()
    logger = logging.getLogger("outgoing")
    logger.addHandler(recorder)
    logger.setLevel(logging.INFO)
    caplog.set_level(logging.INFO, logger="outgoing")

    async def transport(request):
        return httpx.Response(200, json={"ok": True}, request=request)

    async def send():
        async with make_client(transport=httpx.MockTransport(transport)) as client:
            return await client.post("https://example.test/prompt", json={"prompt": prompt})

    response = asyncio.run(send())
    logger.removeHandler(recorder)

    assert response.status_code == 200
    request_logs = [message for message in recorder.messages if message.startswith("→ POST")]
    assert len(request_logs) == 1
    logged_request = request_logs[0]
    for canary in canaries:
        assert canary not in logged_request
        assert canary not in prompt
    assert "4525" in logged_request


def test_prompt_accepts_only_fact_pack():
    with pytest.raises(TypeError, match="only a FactPack"):
        firewall.build_prompt({"income_cents": 100})


def test_fact_pack_rejects_names_dates_unknown_categories_and_aliases():
    with pytest.raises(ValidationError):
        firewall.FactPack.model_validate({"name": "Canary Person Example"})
    with pytest.raises(ValidationError):
        firewall.build_fact_pack(
            ratios={},
            category_totals={"Canary Merchant Emporium": 100},
            aliases={},
            value_bands={},
        )
    with pytest.raises(ValidationError):
        firewall.build_fact_pack(
            ratios={},
            category_totals={},
            aliases={"accounts": ["ACCT-9918-4420-1177"]},
            value_bands={},
        )

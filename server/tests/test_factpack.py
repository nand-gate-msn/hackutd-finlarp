import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.factpack_schema import FactPack

SAMPLE = Path(__file__).resolve().parent.parent / "app" / "factpack_sample.json"


def sample() -> dict:
    return json.loads(SAMPLE.read_text())


def test_sample_validates():
    pack = FactPack.model_validate(sample())
    assert pack.forecast.share_below_zero == 0.18


def test_extra_field_rejected():
    d = sample()
    d["accounts"][0]["owner_name"] = "Alex Rivera"
    with pytest.raises(ValidationError):
        FactPack.model_validate(d)
    d = sample()
    d["loaded_at"] = "2026-11-07"
    with pytest.raises(ValidationError):
        FactPack.model_validate(d)


@pytest.mark.parametrize("bad", ["Chase Checking", "4417-1234-1138-0001", "acct_", "merch 3"])
def test_real_looking_alias_rejected(bad):
    d = sample()
    d["accounts"][0]["alias"] = bad
    with pytest.raises(ValidationError):
        FactPack.model_validate(d)


@pytest.mark.parametrize("bad", ["2026-11-07", "Starbucks", "$1,234.56"])
def test_non_band_in_band_field_rejected(bad):
    d = sample()
    d["accounts"][0]["balance_band"] = bad
    with pytest.raises(ValidationError):
        FactPack.model_validate(d)


def test_free_text_formula_rejected():
    d = sample()
    d["metrics"][0]["formula"] = "income minus rent paid to Acme Realty"
    with pytest.raises(ValidationError):
        FactPack.model_validate(d)


def test_slots_come_from_pack():
    slots = FactPack.model_validate(sample()).slots()
    assert slots["housing_share"] == "38%"
    assert slots["share_below_zero"] == "18%"
    assert slots["scenario_payment_ratio"] == "12%"

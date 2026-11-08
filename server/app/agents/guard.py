"""Request guard: plain code that runs BEFORE any model reads the customer's typed words.

Three outcomes:
  ok       - nothing unusual; the Planner decides the scenario as usual.
  extreme  - a real purchase request that is absurd next to the customer's income ("10 cars costing 1 million
             usd each"). We do NOT let the model pick a "typical" payment for it: code sizes the monthly payment
             from the stated amounts (capped at all of income), so the forecast and score react honestly, and the
             Explainer is told to say plainly that this is far beyond their means.
  blocked  - empty/garbled text or an attempt to instruct the assistant ("ignore previous instructions...").
             No model is called; the customer gets a fixed message and their current picture.

Nothing here puts a figure from the request into a prompt: the guard only emits fixed text and a ScenarioInput.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ..tools import ScenarioInput

Level = Literal["ok", "extreme", "blocked"]

EXTREME_TOTAL_VS_ANNUAL_INCOME = 3.0  # a stated purchase above 3 years of income is not a normal what-if
MAX_BIG_TICKET_COUNT = 3  # more than this many cars/houses/boats at once is not either
MAX_UNIT_DOLLARS = 100_000_000  # no single item costs more than this
CAR_PAY_MONTHS, HOME_PAY_MONTHS = 60, 360  # how long a purchase is financed, for sizing the payment
MAX_SCENARIO_TERM = 120  # ScenarioInput limit

BLOCKED_MESSAGE = ("I couldn't turn that into a money question. Try something like \"Can I afford a car?\" "
                   "or \"What if my rent goes up?\"")
EXTREME_MESSAGE = ("That purchase is far beyond what your income can support. I've modeled it as the largest "
                   "monthly payment this tool allows so you can see the effect, but it isn't a realistic plan.")


class Guard(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    level: Level = "ok"
    message: str = ""  # shown to the customer
    scenario: ScenarioInput | None = None  # extreme only: replaces whatever the Planner chose


OK = Guard()

# ------------------------------------------------------------------ blocked

_INJECTION = re.compile(
    r"ignore (?:all |any |the |your )?(?:previous|prior|above|earlier)|disregard (?:all |any |the |your )?(?:previous|prior|above|instructions|rules)"
    r"|forget (?:all |your |the )?(?:previous|prior|instructions|rules)|(?:system|developer) (?:prompt|message|mode)"
    r"|reveal (?:your|the) (?:prompt|instructions|rules)|you are now\b|jailbreak|\bDAN\b"
    r"|override (?:the )?(?:rules|safety|limits)|</?\s*(?:system|assistant|instructions?)\s*>|```",
    re.I,
)


def _blocked(text: str) -> bool:
    letters = sum(c.isalpha() for c in text)
    if letters < 3 or letters < len(text) * 0.3:  # empty, emoji/symbol spam, or a wall of digits
        return True
    if re.search(r"(.)\1{14,}", text):  # "aaaaaaaaaaaaaaaa"
        return True
    return bool(_INJECTION.search(text))


# ------------------------------------------------------------------ amounts

_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
    "seventeen eighteen nineteen twenty".split())}
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
_MONEY = re.compile(
    r"(?P<dollar>\$)?\s*(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<scale>k|thousand|mm|million|m|bn|billion|b)?\b"
    r"\s*(?P<unit>usd|dollars?|bucks)?", re.I)
_ITEM = r"(?:cars?|vehicles?|trucks?|suvs?|motorcycles?|houses?|homes?|apartments?|condos?|yachts?|boats?|jets?|planes?|mansions?)"
_COUNT = re.compile(rf"\b(?P<n>\d{{1,4}}|{'|'.join(_WORDS)})\s+(?:[\w-]+\s+){{0,2}}?(?P<item>{_ITEM})\b", re.I)
_HOUSING = re.compile(r"house|home|apartment|condo|mansion", re.I)
_EACH = re.compile(r"\b(?:each|per|apiece|every)\b", re.I)


def _amounts(text: str) -> list[float]:
    """Dollar amounts in the text. A bare number counts only with a $, a scale (k/million) or a unit (usd)."""
    out = []
    for m in _MONEY.finditer(text):
        raw = float(m["num"].replace(",", ""))
        scale = _SCALE.get((m["scale"] or "").lower(), 1)
        marked = bool(m["dollar"] or m["scale"] or m["unit"])
        value = raw * scale
        if marked or value >= 1000:
            out.append(value)
    return out


def _count(text: str) -> tuple[int, str | None]:
    """(how many, what) for the largest "N <item>" in the text; (1, None) when there is none."""
    found = [(_WORDS[m["n"].lower()] if m["n"].lower() in _WORDS else int(m["n"]), m["item"]) for m in _COUNT.finditer(text)]
    return max(found, default=(1, None))


# ------------------------------------------------------------------ the guard

def assess(text: str, monthly_income_cents: int) -> Guard:
    """Classify the customer's typed request. `monthly_income_cents` comes from their own data."""
    if _blocked(text):
        return Guard(level="blocked", message=BLOCKED_MESSAGE)

    count, item = _count(text)
    amounts = _amounts(text)
    if item is None and not amounts:
        return OK
    unit = max(amounts, default=0.0)
    total = unit * count if (count > 1 and _EACH.search(text)) else unit
    annual_income = monthly_income_cents * 12 / 100

    too_many = item is not None and count > MAX_BIG_TICKET_COUNT
    too_pricey = unit > MAX_UNIT_DOLLARS or (total > 0 and total > EXTREME_TOTAL_VS_ANNUAL_INCOME * max(annual_income, 1))
    if not (too_many or too_pricey):
        return OK

    housing = bool(item and _HOUSING.search(item))
    pay_months = HOME_PAY_MONTHS if housing else CAR_PAY_MONTHS
    monthly_income = max(monthly_income_cents / 100, 1)
    if total > 0:
        ratio = (total / pay_months) / monthly_income
    else:  # "I want 20 cars": no price given, so scale the typical payment by how many
        ratio = 0.12 * count
    scenario = ScenarioInput(kind="car_loan", payment_ratio_of_income=round(min(1.0, ratio), 4),
                             term_months=min(pay_months, MAX_SCENARIO_TERM))
    return Guard(level="extreme", message=EXTREME_MESSAGE, scenario=scenario)

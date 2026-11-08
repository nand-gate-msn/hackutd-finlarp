"""FactPack: the only shape of data that may reach a language model.

Contract between the engines (CS #1 fills it) and the agents (CS #2 reads it).
Rules baked into the types:
  * every model forbids extra fields and is frozen;
  * no dates, names, free text or raw amounts -- only aliases, ratios and bands;
  * aliases must look like ingest aliases (acct_A, merch_3, bill_2, loan_1);
  * metric formulas must come from a fixed allow-list, never free text.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Band = Literal["very_low", "low", "moderate", "high", "very_high"]
Status = Literal["ok", "watch", "risk"]
Tag = Literal["observed", "simulated", "proposed"]
Group = Literal[
    "Housing", "Food", "Transport", "Discretionary", "Debt", "Health", "Education", "Other"
]
Ratio = Annotated[float, Field(ge=0.0, le=1.0)]
Alias = Annotated[str, StringConstraints(pattern=r"^(acct|merch|bill|loan)_[A-Za-z0-9]+$")]

MetricKey = Literal[
    "savings_rate",
    "cash_runway",
    "housing_debt_load",
    "overdraft_probability_30d",
    "income_stability",
    "spending_volatility",
    "recurring_discretionary_load",
]

# Allow-listed formula text. Engines must return exactly these strings.
METRIC_FORMULAS: dict[str, str] = {
    "savings_rate": "(income - outflow) / income",
    "cash_runway": "liquid balance / average daily outflow (days)",
    "housing_debt_load": "(housing + debt payments) / income",
    "overdraft_probability_30d": "share of simulated paths where balance < 0 within 30 days",
    "income_stability": "1 - coefficient of variation of monthly income",
    "spending_volatility": "coefficient of variation of weekly variable spending",
    "recurring_discretionary_load": "recurring discretionary payments / income",
}


# Slot names the Explainer sees. No digits in a name, or the model copies them into prose ("30-day"),
# and digits outside slots are rejected.
SLOT_NAMES = {"overdraft_probability_30d": "overdraft_chance_month"}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AccountFact(_Model):
    alias: Alias
    type: Literal["Checking", "Savings", "Credit Card"]
    balance_band: Band


class MetricFact(_Model):
    key: MetricKey
    value: float
    status: Status
    formula: str

    @model_validator(mode="after")
    def _formula_allowed(self) -> "MetricFact":
        if self.formula != METRIC_FORMULAS[self.key]:
            raise ValueError(f"formula for {self.key} must be the allow-listed text")
        return self


class CategoryFact(_Model):
    group: Group
    share_of_outflow: Ratio
    band: Band


class ObligationFact(_Model):
    alias: Alias
    kind: Literal["bill", "loan"]
    group: Group
    share_of_income: Ratio
    late_rate_band: Band


class ForecastFact(_Model):
    horizon_days: Annotated[int, Field(ge=30, le=90)]
    p10_band: Band
    p50_band: Band
    p90_band: Band
    share_below_zero: Ratio
    tag: Tag = "simulated"


class ScenarioFact(_Model):
    kind: Literal["car_loan", "rent_increase", "income_drop", "new_subscription", "none"]
    payment_ratio_of_income: Ratio
    term_months: Annotated[int, Field(ge=0, le=120)]


class RuleFact(_Model):
    from_alias: Alias
    to_alias: Alias
    percent: Annotated[float, Field(gt=0.0, le=30.0)]


class FactPack(_Model):
    schema_version: Literal[1] = 1
    accounts: list[AccountFact]
    metrics: list[MetricFact]
    categories: list[CategoryFact]
    obligations: list[ObligationFact]
    forecast: ForecastFact
    scenario: ScenarioFact | None = None
    rules: list[RuleFact] = []

    def slots(self) -> dict[str, str]:
        """Numbers the Explainer may reference as {slot}; server fills them.

        Derived only from the pack, so a slot can never name a number that is not in it.
        """
        s: dict[str, str] = {}
        for c in self.categories:
            s[f"{c.group.lower()}_share"] = f"{c.share_of_outflow:.0%}"
        for m in self.metrics:
            # runway is in days; every other metric is a 0-1 ratio and reads best as a percentage
            slot = SLOT_NAMES.get(m.key, m.key)
            s[slot] = f"{m.value:.0f} days" if m.key == "cash_runway" else f"{m.value:.0%}"
        s["share_below_zero"] = f"{self.forecast.share_below_zero:.0%}"
        s["horizon_days"] = f"{self.forecast.horizon_days} days"
        if self.scenario and self.scenario.kind != "none":
            s["scenario_payment_ratio"] = f"{self.scenario.payment_ratio_of_income:.0%}"
        return s

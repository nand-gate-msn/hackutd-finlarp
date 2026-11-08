"""Strict allow-listed prompt facts assembled from engine outputs only."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


MetricName = Literal[
    "savings_rate",
    "cash_runway_months",
    "housing_debt_load",
    "overdraft_probability_30d",
    "income_stability",
    "spending_volatility",
    "recurring_discretionary_load",
]
ValueBand = Literal["healthy", "watch", "risk", "insufficient_data"]
AliasType = Literal["accounts", "merchants", "obligations"]

ALLOWED_CATEGORIES = frozenset({
    "housing", "rent", "utilities", "internet", "groceries", "grocery",
    "dining", "restaurant", "coffee", "gas", "fuel", "transit", "auto",
    "car insurance", "subscriptions", "streaming", "shopping", "entertainment",
    "loan", "healthcare", "insurance", "other", "uncategorized", "income",
    "interest", "savings", "transfer",
})
_ALIAS_PATTERN = re.compile(r"^(?:acct_[A-Z0-9]+|merch_[A-Z0-9]+|bill_[A-Z0-9]+|loan_[A-Z0-9]+)$")


class FactPack(BaseModel):
    """The only prompt payload shape; all fields are aggregated engine outputs."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, allow_inf_nan=False)

    ratios: dict[MetricName, float | None] = Field(default_factory=dict)
    category_totals: dict[str, int] = Field(default_factory=dict)
    aliases: dict[AliasType, list[str]] = Field(default_factory=dict)
    value_bands: dict[MetricName, ValueBand] = Field(default_factory=dict)

    @field_validator("category_totals", mode="before")
    @classmethod
    def validate_categories(cls, value):
        if not isinstance(value, Mapping):
            raise TypeError("category_totals must be a mapping")
        unknown = set(value) - ALLOWED_CATEGORIES
        if unknown:
            raise ValueError(f"unsupported category keys: {sorted(unknown)}")
        return value

    @field_validator("aliases", mode="before")
    @classmethod
    def validate_aliases(cls, value):
        if not isinstance(value, Mapping):
            raise TypeError("aliases must be a mapping")
        for alias_type, values in value.items():
            if alias_type not in {"accounts", "merchants", "obligations"}:
                raise ValueError(f"unsupported alias group: {alias_type}")
            if not isinstance(values, (list, tuple)):
                raise TypeError(f"{alias_type} aliases must be a list")
            for alias in values:
                if not isinstance(alias, str) or not _ALIAS_PATTERN.fullmatch(alias):
                    raise ValueError("aliases must use anonymized account, merchant, bill, or loan IDs")
        return {key: list(values) for key, values in value.items()}


def build_fact_pack(
    *,
    ratios: Mapping[str, float | int | None],
    category_totals: Mapping[str, int],
    aliases: Mapping[str, Iterable[str]],
    value_bands: Mapping[str, str],
) -> FactPack:
    """Validate already-aggregated engine outputs; raw transaction rows are not accepted."""
    normalized_ratios = {
        key: None if value is None else float(value)
        for key, value in ratios.items()
    }
    normalized_aliases = {key: list(values) for key, values in aliases.items()}
    return FactPack(
        ratios=normalized_ratios,
        category_totals=dict(category_totals),
        aliases=normalized_aliases,
        value_bands=dict(value_bands),
    )

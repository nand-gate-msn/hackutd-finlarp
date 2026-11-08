"""Builds the FactPack (app/factpack_schema.py) from engine outputs.

The FactPack is the ONLY thing that may reach a language model, and its shape is defined in
one place: factpack_schema.FactPack. This module fills it from the engines' results and nothing
else: shares, ratios and bands, never rows, dollar amounts, dates or names.

  build_fact_pack(...)      pure assembler: already-aggregated parts in, validated FactPack out
  build_from_db(scenario, conn)  reads the anonymized SQLite data, runs the engines, calls the assembler

Unit conversions between the engines and the schema (done once, here):
  finmetrics returns percentages (4.0 = 4%)  -> schema ratios (0.04)
  finmetrics returns runway in months        -> schema runway in days (x30)
  finmetrics healthy/watch/risk              -> schema ok/watch/risk
A metric the engine could not compute (insufficient data) is left out of the pack.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from typing import Any

from ..db import work_db
from ..factpack_schema import METRIC_FORMULAS, Band, FactPack, ForecastFact, Group, HealthFact, MetricFact
from ..health import HealthResult, health as run_health
from ..tools import NONE_SCENARIO, ScenarioInput, ToolError, _load, balance_band, simulate
from . import finmetrics

__all__ = ["FactPack", "build_fact_pack", "build_from_db", "metrics_from_engine"]

_GROUPS = set(Group.__args__)
_STATUS = {"healthy": "ok", "watch": "watch", "risk": "risk"}
MONTH_DAYS = 30
RECENT_DAYS = 90


def _group(name: str | None) -> str:
    return name if name in _GROUPS else "Other"


def _share_band(share: float) -> Band:
    """How big a slice of spending / income. Provisional cut-offs for Finance to tune."""
    if share < 0.05:
        return "very_low"
    if share < 0.10:
        return "low"
    if share < 0.20:
        return "moderate"
    if share < 0.35:
        return "high"
    return "very_high"


def _late_band(rate: float) -> Band:
    if rate == 0:
        return "very_low"
    if rate <= 0.10:
        return "low"
    if rate <= 0.25:
        return "moderate"
    if rate <= 0.50:
        return "high"
    return "very_high"


def _health_fact(result: HealthResult, with_after: bool) -> dict:
    snap = lambda x: {"score": x.score, "status": x.status, "pillars": x.pillars}  # noqa: E731
    return {
        "now": snap(result.before),
        "after": snap(result.after) if with_after else None,
        "drivers": [d.model_dump() for d in result.drivers] if with_after else [],
    }


def build_fact_pack(
    *,
    accounts: Iterable[Mapping[str, Any]],
    metrics: Iterable[Mapping[str, Any]],
    categories: Iterable[Mapping[str, Any]],
    obligations: Iterable[Mapping[str, Any]],
    forecast: Mapping[str, Any],
    scenario: Mapping[str, Any] | None = None,
    rules: Iterable[Mapping[str, Any]] = (),
    health: Mapping[str, Any] | None = None,
) -> FactPack:
    """Validate already-aggregated engine outputs into a FactPack.

    Raw transaction rows are rejected by the schema (extra fields are forbidden, aliases must look
    like acct_A / merch_1 / bill_2 / loan_1, categories must be known groups).
    """
    return FactPack.model_validate({
        "accounts": list(accounts),
        "metrics": list(metrics),
        "categories": list(categories),
        "obligations": list(obligations),
        "forecast": dict(forecast),
        "scenario": None if scenario is None else dict(scenario),
        "rules": list(rules),
        "health": None if health is None else dict(health),
    })


def metrics_from_engine(
    rows: list[dict],
    balance_cents: int | None,
    account_alias: str | None = None,
    overdraft_share: float | None = None,
) -> list[MetricFact]:
    """Run the seven finmetrics functions and convert them to schema units.

    The schema defines overdraft_probability_30d as the share of simulated paths below zero, so
    pass the Monte Carlo share as `overdraft_share`; without it the historical-window estimate
    from finmetrics is used.
    """
    runway = finmetrics.cash_runway(rows, balance_cents, account_alias)
    results = {
        "savings_rate": finmetrics.savings_rate(rows, account_alias),
        "cash_runway": {**runway, "value": None if runway["value"] is None else runway["value"] * MONTH_DAYS},
        "housing_debt_load": finmetrics.housing_debt_load(rows, account_alias),
        "overdraft_probability_30d": finmetrics.overdraft_probability_30d(rows, balance_cents, account_alias),
        "income_stability": finmetrics.income_stability(rows, account_alias),
        "spending_volatility": finmetrics.spending_volatility(rows, account_alias),
        "recurring_discretionary_load": finmetrics.recurring_discretionary_load(rows, account_alias),
    }
    if overdraft_share is not None:
        percent = overdraft_share * 100
        results["overdraft_probability_30d"] = {
            "value": percent,
            "status": finmetrics._lower_is_better(percent, "overdraft_probability_30d"),
        }
    facts = []
    for key, result in results.items():
        value = result["value"]
        status = _STATUS.get(result["status"])
        if value is None or status is None:
            continue  # insufficient data: say nothing rather than guess
        if key != "cash_runway":
            value = value / 100  # percent -> ratio
        facts.append(MetricFact(key=key, value=round(value, 4), status=status, formula=METRIC_FORMULAS[key]))
    return facts


def build_from_db(
    scenario: ScenarioInput | Mapping[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
    health: HealthResult | None = None,
) -> FactPack:
    """Build the pack for the loaded customer, optionally with a what-if scenario applied."""
    if conn is None:
        with work_db() as c:
            return build_from_db(scenario, c, health)
    data = _load(conn)
    rows, income, outflow = data["rows"], data["monthly_income_cents"], data["monthly_outflow_cents"]
    last = rows[-1]["date"][:10]

    accounts = [
        {"alias": r["alias"], "type": r["type"], "balance_band": balance_band(r["balance_cents"], outflow)}
        for r in conn.execute("SELECT alias, type, balance_cents FROM accounts ORDER BY alias")
    ]

    # spending mix over the last 90 days, by group (transfers are not spending)
    since = (date.fromisoformat(last) - timedelta(days=RECENT_DAYS)).isoformat()
    by_group: dict[str, int] = defaultdict(int)
    for r in rows:
        if r["amount_cents"] < 0 and r["kind"] not in ("transfer_in", "transfer_out") and r["date"][:10] > since:
            by_group[_group(r["group_name"])] += -r["amount_cents"]
    total = sum(by_group.values())
    categories = [
        {"group": g, "share_of_outflow": round(v / total, 4), "band": _share_band(v / total)}
        for g, v in sorted(by_group.items(), key=lambda kv: -kv[1])
    ] if total else []

    late = {
        r["obligation_alias"]: (r["late"], r["n"])
        for r in conn.execute(
            "SELECT obligation_alias, SUM(days_late > 0) AS late, COUNT(*) AS n FROM transactions "
            "WHERE obligation_alias IS NOT NULL GROUP BY obligation_alias"
        )
    }
    obligations = []
    for r in conn.execute("SELECT alias, kind, group_name, amount_cents FROM obligations ORDER BY alias"):
        n_late, n = late.get(r["alias"], (0, 0))
        obligations.append({
            "alias": r["alias"],
            "kind": r["kind"],
            "group": _group(r["group_name"]),
            "share_of_income": min(1.0, round(r["amount_cents"] / income, 4)) if income > 0 else 0.0,
            "late_rate_band": _late_band((n_late or 0) / n if n else 0.0),
        })

    sc = scenario if isinstance(scenario, ScenarioInput) else (ScenarioInput.model_validate(scenario) if scenario else NONE_SCENARIO)
    sim = simulate(sc, conn)
    month = simulate(ScenarioInput(kind="none", horizon_days=30), conn)  # 30-day baseline for the metric
    forecast = ForecastFact(
        horizon_days=sim.horizon_days,
        p10_band=sim.scenario.p10_band,
        p50_band=sim.scenario.p50_band,
        p90_band=sim.scenario.p90_band,
        share_below_zero=sim.scenario.share_below_zero,
    ).model_dump()

    rules = [
        {"from_alias": r["from_alias"], "to_alias": r["to_alias"], "percent": r["percent"]}
        for r in conn.execute("SELECT from_alias, to_alias, percent FROM rules WHERE status = 'active' ORDER BY id")
    ]
    health = health or run_health(sc, conn)
    return build_fact_pack(
        health=_health_fact(health, with_after=sc.kind != "none"),
        accounts=accounts,
        metrics=[m.model_dump() for m in metrics_from_engine(
            rows, data["balance_cents"], data["account"], overdraft_share=month.baseline.share_below_zero)],
        categories=categories,
        obligations=obligations,
        forecast=forecast,
        scenario=None if sc.kind == "none" else {
            "kind": sc.kind, "payment_ratio_of_income": sc.payment_ratio_of_income, "term_months": sc.term_months,
        },
        rules=rules,
    )

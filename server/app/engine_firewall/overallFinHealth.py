"""Weighted financial-health report built from the current SQLite engines."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean
from typing import Iterable, Mapping

from . import finmetrics


ASSUMED_TAX_RATE = 0.20
PILLAR_WEIGHTS = {"Spend": 0.25, "Save": 0.25, "Borrow": 0.20, "Plan": 0.30}
INDICATOR_WEIGHTS = {
	"Spend": {
		"savings_rate": 0.40,
		"spending_volatility": 0.25,
		"recurring_discretionary_load": 0.15,
		"bill_timeliness": 0.20,
	},
	"Save": {"cash_runway_months": 1.0},
	"Borrow": {"housing_debt_load": 0.70, "credit_utilization": 0.30},
	"Plan": {"overdraft_probability_30d": 0.60, "income_stability": 0.40},
}

SAVINGS_RATE = [(0.0, 0), (0.20, 100)]
RUNWAY_MONTHS = [(0, 0), (3, 60), (6, 100)]
HOUSING_RATIO = [(0.28, 100), (0.45, 0)]
TOTAL_DEBT_RATIO = [(0.36, 100), (0.50, 0)]
CARD_UTILIZATION = [(0.30, 100), (0.90, 0)]
OVERDRAFT_PROB = [(0.0, 100), (0.05, 80), (0.20, 40), (0.50, 0)]
SPEND_VOLATILITY_CV = [(0.5, 100), (1.0, 60), (2.0, 0)]
RECURRING_SHARE = [(0.02, 100), (0.05, 70), (0.10, 0)]

LABELS = {
	"savings_rate": "Savings rate",
	"cash_runway_months": "Cash runway",
	"housing_debt_load": "Housing and debt load",
	"overdraft_probability_30d": "30-day overdraft probability",
	"income_stability": "Income stability",
	"spending_volatility": "Spending volatility",
	"recurring_discretionary_load": "Recurring discretionary load",
	"bill_timeliness": "Bill timeliness",
	"credit_utilization": "Credit utilization",
}


def _interpolate(value: float | None, points: list[tuple[float, float]]) -> float | None:
	if value is None:
		return None
	ordered = sorted(points)
	if value <= ordered[0][0]:
		return ordered[0][1]
	if value >= ordered[-1][0]:
		return ordered[-1][1]
	for (x0, y0), (x1, y1) in zip(ordered, ordered[1:]):
		if x0 <= value <= x1:
			return y0 + (y1 - y0) * (value - x0) / (x1 - x0)
	return None


def _status(score: float | None) -> str:
	if score is None:
		return "n/a"
	if score >= 80:
		return "Healthy"
	if score >= 60:
		return "Okay"
	if score >= 40:
		return "Needs attention"
	return "At risk"


def _add_indicator(
	indicators: dict[str, dict[str, object]],
	name: str,
	value: object,
	score: float | None,
	display: str,
	note: str = "",
) -> None:
	indicators[name] = {
		"label": LABELS[name],
		"value": value,
		"score": None if score is None else round(score, 1),
		"display": display,
		"note": note,
	}


def compute_overall_fin_health(
	transactions: Iterable[Mapping[str, object]],
	accounts: Iterable[Mapping[str, object]],
	overdraft_probability: float | None = None,
) -> dict[str, object]:
	"""Score available indicators from normalized SQLite engine data."""
	rows = [dict(row) for row in transactions]
	account_rows = [dict(row) for row in accounts]
	if not rows:
		raise ValueError("no transactions available to score")

	checking = next((row for row in account_rows if row.get("type") == "Checking"), None)
	checking_alias = checking.get("alias") if checking else None
	cash_balance_cents = sum(
		int(row["balance_cents"])
		for row in account_rows
		if row.get("type") in ("Checking", "Savings")
	)
	metric_values = {
		"savings_rate": finmetrics.savings_rate(rows),
		"cash_runway_months": finmetrics.cash_runway(rows, cash_balance_cents),
		"housing_debt_load": finmetrics.housing_debt_load(rows),
		"overdraft_probability_30d": finmetrics.overdraft_probability_30d(
			rows, int(checking["balance_cents"]) if checking else None, checking_alias
		),
		"income_stability": finmetrics.income_stability(rows, checking_alias),
		"spending_volatility": finmetrics.spending_volatility(rows),
		"recurring_discretionary_load": finmetrics.recurring_discretionary_load(rows),
	}
	if overdraft_probability is not None:
		metric_values["overdraft_probability_30d"] = {
			"value": float(overdraft_probability) * 100,
			"status": "engine_output",
			"formula": "Monte Carlo overdraft probability converted to percent",
		}

	indicators: dict[str, dict[str, object]] = {}
	savings = metric_values["savings_rate"]["value"]
	savings_ratio = None if savings is None else float(savings) / 100
	savings_score = _interpolate(savings_ratio, SAVINGS_RATE)
	_add_indicator(indicators, "savings_rate", savings_ratio, savings_score,
				   "n/a" if savings_ratio is None else f"{savings_ratio:.1%}",
				   "Uses recorded savings transfers divided by deposit income")

	runway = metric_values["cash_runway_months"]["value"]
	runway_value = None if runway is None else float(runway)
	_add_indicator(indicators, "cash_runway_months", runway_value,
				   _interpolate(runway_value, RUNWAY_MONTHS),
				   "n/a" if runway_value is None else f"{runway_value:.1f} months")

	income_cents = sum(
		int(row["amount_cents"]) for row in rows
		if row.get("kind") == "deposit" and row.get("label") != "interest"
	)
	housing_cents = -sum(
		int(row["amount_cents"]) for row in rows
		if int(row["amount_cents"]) < 0 and row.get("group_name") == "Housing"
	)
	debt_cents = -sum(
		int(row["amount_cents"]) for row in rows
		if int(row["amount_cents"]) < 0 and row.get("group_name") == "Debt"
	)
	if income_cents > 0:
		gross_income_cents = income_cents / (1 - ASSUMED_TAX_RATE)
		housing_ratio = housing_cents / gross_income_cents
		total_ratio = (housing_cents + debt_cents) / gross_income_cents
		h_score = _interpolate(housing_ratio, HOUSING_RATIO)
		total_score = _interpolate(total_ratio, TOTAL_DEBT_RATIO)
		housing_score = (h_score + total_score) / 2
		housing_value = (housing_ratio, total_ratio)
		housing_display = f"housing {housing_ratio:.0%}, total {total_ratio:.0%}"
		housing_note = f"Gross income estimated as net income / (1 - {ASSUMED_TAX_RATE:.0%})"
	else:
		housing_score = None
		housing_value = None
		housing_display = "n/a"
		housing_note = "No deposit income available"
	_add_indicator(indicators, "housing_debt_load", housing_value, housing_score,
				   housing_display, housing_note)

	overdraft = metric_values["overdraft_probability_30d"]["value"]
	overdraft_ratio = None if overdraft is None else float(overdraft) / 100
	_add_indicator(indicators, "overdraft_probability_30d", overdraft_ratio,
				   _interpolate(overdraft_ratio, OVERDRAFT_PROB),
				   "n/a" if overdraft_ratio is None else f"{overdraft_ratio:.1%}",
				   "Historical engine estimate unless a Monte Carlo probability is provided")

	stability = metric_values["income_stability"]["value"]
	stability_score = None if stability is None else float(stability)
	_add_indicator(indicators, "income_stability", stability_score, stability_score,
				   "n/a" if stability_score is None else f"{stability_score:.1f}/100",
				   "Uses the current engine's paycheck amount and cadence score")

	volatility = metric_values["spending_volatility"]["value"]
	volatility_cv = None if volatility is None else float(volatility) / 100
	_add_indicator(indicators, "spending_volatility", volatility_cv,
				   _interpolate(volatility_cv, SPEND_VOLATILITY_CV),
				   "n/a" if volatility_cv is None else f"CV {volatility_cv:.2f}")

	recurring = metric_values["recurring_discretionary_load"]["value"]
	recurring_share = None if recurring is None else float(recurring) / 100
	_add_indicator(indicators, "recurring_discretionary_load", recurring_share,
				   _interpolate(recurring_share, RECURRING_SHARE),
				   "n/a" if recurring_share is None else f"{recurring_share:.1%}")

	_add_indicator(indicators, "bill_timeliness", None, None, "n/a",
				   "Current SQLite schema has no reliable late-payment signal")
	_add_indicator(indicators, "credit_utilization", None, None, "n/a",
				   "Current accounts schema does not record credit limits")

	pillars = {}
	for pillar, weights in INDICATOR_WEIGHTS.items():
		available = {
			name: weight for name, weight in weights.items()
			if indicators[name]["score"] is not None
		}
		pillar_score = (
			sum(float(indicators[name]["score"]) * weight for name, weight in available.items())
			/ sum(available.values())
			if available else None
		)
		pillars[pillar] = {
			"score": None if pillar_score is None else round(pillar_score, 1),
			"weight": PILLAR_WEIGHTS[pillar],
			"status": _status(pillar_score),
			"indicators_used": f"{len(available)} of {len(weights)}",
		}

	active_pillars = {
		pillar: PILLAR_WEIGHTS[pillar]
		for pillar, result in pillars.items()
		if result["score"] is not None
	}
	overall_score = (
		sum(float(pillars[pillar]["score"]) * weight for pillar, weight in active_pillars.items())
		/ sum(active_pillars.values())
		if active_pillars else None
	)
	category_totals = defaultdict(int)
	for row in rows:
		if int(row["amount_cents"]) < 0 and row.get("category"):
			category_totals[str(row["category"])] += -int(row["amount_cents"])

	return {
		"overallFinHealth": None if overall_score is None else round(overall_score, 1),
		"status": _status(overall_score),
		"indicators_used": f"{sum(i['score'] is not None for i in indicators.values())} of {len(indicators)}",
		"pillars": pillars,
		"indicators": indicators,
		"category_totals_cents": dict(sorted(category_totals.items())),
		"assumptions": {
			"assumed_tax_rate": ASSUMED_TAX_RATE,
			"unavailable_indicators": ["bill_timeliness", "credit_utilization"],
		},
	}


def refresh_overall_fin_health(conn) -> dict[str, object]:
	"""Calculate and persist the latest score using rows from an open work DB."""
	transactions = conn.execute("SELECT * FROM transactions ORDER BY date,id").fetchall()
	accounts = conn.execute("SELECT * FROM accounts ORDER BY alias").fetchall()
	report = compute_overall_fin_health(transactions, accounts)
	updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
	conn.execute(
		"INSERT INTO overall_fin_health (id, overallFinHealth, status, report_json, updated_at) "
		"VALUES (1, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
		"overallFinHealth=excluded.overallFinHealth, status=excluded.status, "
		"report_json=excluded.report_json, updated_at=excluded.updated_at",
		(report["overallFinHealth"], report["status"], json.dumps(report, sort_keys=True), updated_at),
	)
	return report


def read_overall_fin_health() -> dict[str, object] | None:
	"""Return the latest persisted health report for another application module."""
	from ..db import work_db

	with work_db() as conn:
		row = conn.execute(
			"SELECT overallFinHealth, status, report_json, updated_at "
			"FROM overall_fin_health WHERE id=1"
		).fetchone()
	if row is None:
		return None
	return {
		"overallFinHealth": row["overallFinHealth"],
		"status": row["status"],
		"report": json.loads(row["report_json"]),
		"updated_at": row["updated_at"],
	}

"""Pure financial metrics calculated from rows in the SQLite transactions table."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import mean, pstdev
from typing import Iterable, Mapping


# Provisional bands; replace these values when the project thresholds are finalized.
THRESHOLDS = {
	"savings_rate": {"healthy_min": 20.0, "watch_min": 10.0},
	"cash_runway_months": {"healthy_min": 6.0, "watch_min": 3.0},
	"housing_debt_load": {"healthy_max": 36.0, "watch_max": 45.0},
	"overdraft_probability_30d": {"healthy_max": 5.0, "watch_max": 20.0},
	"income_stability": {"healthy_min": 85.0, "watch_min": 65.0},
	"spending_volatility": {"healthy_max": 20.0, "watch_max": 50.0},
	"recurring_discretionary_load": {"healthy_max": 10.0, "watch_max": 20.0},
}


def _rows(
	transactions: Iterable[Mapping[str, object]], account_alias: str | None = None
) -> list[dict[str, object]]:
	result = [dict(row) for row in transactions]
	if account_alias is not None:
		result = [row for row in result if row.get("account_alias") == account_alias]
	return result


def _result(value: float | None, status: str, formula: str) -> dict[str, object]:
	return {"value": round(value, 2) if value is not None else None,
			"status": status, "formula": formula}


def _higher_is_better(value: float | None, metric: str) -> str:
	if value is None:
		return "insufficient_data"
	bands = THRESHOLDS[metric]
	if value >= bands["healthy_min"]:
		return "healthy"
	if value >= bands["watch_min"]:
		return "watch"
	return "risk"


def _lower_is_better(value: float | None, metric: str) -> str:
	if value is None:
		return "insufficient_data"
	bands = THRESHOLDS[metric]
	if value <= bands["healthy_max"]:
		return "healthy"
	if value <= bands["watch_max"]:
		return "watch"
	return "risk"


def _date(row: Mapping[str, object]) -> date:
	return date.fromisoformat(str(row["date"])[:10])


def _month_keys(start: date, end: date) -> list[str]:
	months = []
	year, month = start.year, start.month
	while (year, month) <= (end.year, end.month):
		months.append(f"{year:04d}-{month:02d}")
		year, month = (year + (month == 12), month % 12 + 1)
	return months


def _monthly_totals(rows: list[dict[str, object]], predicate) -> dict[str, int]:
	if not rows:
		return {}
	dates = [_date(row) for row in rows]
	totals = dict.fromkeys(_month_keys(min(dates), max(dates)), 0)
	for row in rows:
		if predicate(row):
			totals[_date(row).strftime("%Y-%m")] += abs(int(row["amount_cents"]))
	return totals


def _coefficient_of_variation(values: list[float]) -> float | None:
	if len(values) < 2:
		return None
	average = mean(values)
	return pstdev(values) / average if average else None


def savings_rate(
	transactions: Iterable[Mapping[str, object]], account_alias: str | None = None
) -> dict[str, object]:
	"""Return savings transfers as a percentage of recorded deposit income."""
	rows = _rows(transactions, account_alias)
	income = sum(int(row["amount_cents"]) for row in rows
				 if row.get("kind") == "deposit" and row.get("label") != "interest")
	saved = -sum(int(row["amount_cents"]) for row in rows
				 if row.get("kind") == "transfer_out" and row.get("group_name") == "Savings")
	value = 100 * saved / income if income > 0 else None
	return _result(value, _higher_is_better(value, "savings_rate"),
				   "100 * savings transfer outflows / non-interest deposit income")


def cash_runway(
	transactions: Iterable[Mapping[str, object]],
	cash_balance_cents: int | None,
	account_alias: str | None = None,
) -> dict[str, object]:
	"""Return months of average historical outflows covered by the current balance."""
	rows = _rows(transactions, account_alias)
	if cash_balance_cents is None or not rows:
		return _result(None, "insufficient_data", "current cash balance / average monthly non-transfer outflows")
	monthly = _monthly_totals(
		rows, lambda row: int(row["amount_cents"]) < 0
		and row.get("kind") not in ("transfer_in", "transfer_out"))
	average_outflow_cents = mean(monthly.values()) if monthly else 0
	value = cash_balance_cents / average_outflow_cents if average_outflow_cents else None
	return _result(value, _higher_is_better(value, "cash_runway_months"),
				   "current cash balance / average monthly non-transfer outflows")


def housing_debt_load(
	transactions: Iterable[Mapping[str, object]], account_alias: str | None = None
) -> dict[str, object]:
	"""Return housing and debt outflows as a percentage of recorded income."""
	rows = _rows(transactions, account_alias)
	income = sum(int(row["amount_cents"]) for row in rows
				 if row.get("kind") == "deposit" and row.get("label") != "interest")
	required = -sum(int(row["amount_cents"]) for row in rows
					if int(row["amount_cents"]) < 0 and (
						row.get("group_name") in ("Housing", "Debt")
						or str(row.get("category", "")).lower() in ("housing", "rent", "mortgage", "loan")
					))
	value = 100 * required / income if income > 0 else None
	return _result(value, _lower_is_better(value, "housing_debt_load"),
				   "100 * housing and debt outflows / non-interest deposit income")


def overdraft_probability_30d(
	transactions: Iterable[Mapping[str, object]],
	cash_balance_cents: int | None,
	account_alias: str | None = None,
) -> dict[str, object]:
	"""Estimate overdraft probability from historical 30-day daily-balance windows."""
	rows = _rows(transactions, account_alias)
	formula = "100 * historical 30-day windows with a negative end-of-day balance / observed 30-day windows"
	if cash_balance_cents is None or not rows:
		return _result(None, "insufficient_data", formula)

	daily = defaultdict(int)
	for row in rows:
		daily[_date(row)] += int(row["amount_cents"])
	first, last = min(daily), max(daily)
	if (last - first).days < 29:
		return _result(None, "insufficient_data", formula)

	opening_balance = cash_balance_cents - sum(daily.values())
	balances = {}
	balance = opening_balance
	current_day = first
	while current_day <= last:
		balance += daily[current_day]
		balances[current_day] = balance
		current_day += timedelta(days=1)

	window_count = 0
	overdraft_count = 0
	start_day = first
	final_start = last - timedelta(days=29)
	while start_day <= final_start:
		window = (balances[start_day + timedelta(days=offset)] for offset in range(30))
		window_count += 1
		overdraft_count += min(window) < 0
		start_day += timedelta(days=1)

	value = 100 * overdraft_count / window_count
	return _result(value, _lower_is_better(value, "overdraft_probability_30d"), formula)


def income_stability(
	transactions: Iterable[Mapping[str, object]], account_alias: str | None = None
) -> dict[str, object]:
	"""Return a 0-100 stability score based on paycheck amount and timing variation."""
	paychecks = sorted(
		(row for row in _rows(transactions, account_alias)
		 if row.get("kind") == "deposit" and row.get("label") == "paycheck"),
		key=_date,
	)
	amounts = [float(int(row["amount_cents"])) for row in paychecks]
	variations = [_coefficient_of_variation(amounts)]
	if len(paychecks) >= 3:
		gaps = [float((_date(later) - _date(earlier)).days)
				for earlier, later in zip(paychecks, paychecks[1:])]
		variations.append(_coefficient_of_variation(gaps))
	available = [variation for variation in variations if variation is not None]
	score = 100 / (1 + mean(available)) if available else None
	return _result(score, _higher_is_better(score, "income_stability"),
				   "100 / (1 + mean CV of paycheck amounts and, with 3+ paychecks, days between paychecks)")


def spending_volatility(
	transactions: Iterable[Mapping[str, object]], account_alias: str | None = None
) -> dict[str, object]:
	"""Return the coefficient of variation of monthly discretionary spending, in percent."""
	rows = _rows(transactions, account_alias)
	monthly = _monthly_totals(
		rows, lambda row: int(row["amount_cents"]) < 0
		and row.get("group_name") == "Discretionary")
	variation = _coefficient_of_variation([float(value) for value in monthly.values()])
	value = variation * 100 if variation is not None else None
	return _result(value, _lower_is_better(value, "spending_volatility"),
				   "100 * population CV of monthly discretionary outflows")


def recurring_discretionary_load(
	transactions: Iterable[Mapping[str, object]], account_alias: str | None = None
) -> dict[str, object]:
	"""Return recurring discretionary outflows as a percentage of average monthly income."""
	rows = _rows(transactions, account_alias)
	if not rows:
		return _result(None, "insufficient_data",
					   "100 * average monthly recurring discretionary outflows / average monthly income")

	dated_rows = [(row, _date(row)) for row in rows]
	months = _month_keys(min(day for _, day in dated_rows), max(day for _, day in dated_rows))
	income_by_month = defaultdict(int)
	recurring_keys = defaultdict(set)
	for row, day in dated_rows:
		if row.get("kind") == "deposit" and row.get("label") != "interest":
			income_by_month[day.strftime("%Y-%m")] += int(row["amount_cents"])
		if (row.get("group_name") == "Discretionary" and int(row["amount_cents"]) < 0
				and row.get("kind") in ("purchase", "withdrawal")):
			key = row.get("counterparty") or row.get("obligation_alias")
			if key:
				recurring_keys[key].add(day.strftime("%Y-%m"))

	recurring_ids = {key for key, active_months in recurring_keys.items() if len(active_months) >= 2}
	recurring_monthly_cents = [0] * len(months)
	for row, day in dated_rows:
		key = row.get("counterparty") or row.get("obligation_alias")
		if (key in recurring_ids and row.get("group_name") == "Discretionary"
				and int(row["amount_cents"]) < 0):
			recurring_monthly_cents[months.index(day.strftime("%Y-%m"))] += -int(row["amount_cents"])

	average_income = mean(income_by_month.get(month, 0) for month in months)
	average_recurring = mean(recurring_monthly_cents)
	value = 100 * average_recurring / average_income if average_income > 0 else None
	formula = "100 * average monthly recurring discretionary outflows / average monthly income"
	return _result(value, _lower_is_better(value, "recurring_discretionary_load"), formula)

"""Paired Monte Carlo cash-flow forecasts from anonymized transaction rows."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import median
from typing import Any, Iterable, Mapping

import numpy as np


DEFAULT_PATHS = 5_000
AMOUNT_TOLERANCE = 0.05


def _as_date(value: object) -> date:
	return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _rows(
	transactions: Iterable[Mapping[str, object]], account_alias: str | None = None
) -> list[dict[str, object]]:
	rows = [dict(row) for row in transactions]
	if account_alias is not None:
		rows = [row for row in rows if row.get("account_alias") == account_alias]
	return rows


def _payee(row: Mapping[str, object]) -> str | None:
	value = row.get("counterparty") or row.get("obligation_alias") or row.get("label")
	if value and (row.get("counterparty") or row.get("obligation_alias")
				  or row.get("kind") == "deposit"):
		return str(value)
	return None


def _find_recurring(
	rows: list[dict[str, object]], amount_tolerance: float = AMOUNT_TOLERANCE
) -> tuple[list[dict[str, Any]], set[int]]:
	grouped: dict[tuple[object, str, str], list[int]] = defaultdict(list)
	for index, row in enumerate(rows):
		kind = str(row.get("kind", ""))
		payee = _payee(row)
		if kind not in {"deposit", "purchase", "withdrawal", "transfer_in", "transfer_out"} or not payee:
			continue
		if int(row.get("amount_cents", 0)) == 0:
			continue
		grouped[(row.get("account_alias"), kind, payee)].append(index)

	recurring = []
	recurring_indexes = set()
	for (account_alias, kind, payee), indexes in grouped.items():
		if len(indexes) < 3:
			continue
		indexes.sort(key=lambda index: _as_date(rows[index]["date"]))
		amounts = [int(rows[index]["amount_cents"]) for index in indexes]
		if any(amount > 0 for amount in amounts) and any(amount < 0 for amount in amounts):
			continue
		median_magnitude = median(abs(amount) for amount in amounts)
		if median_magnitude == 0 or any(
			abs(abs(amount) - median_magnitude) / median_magnitude > amount_tolerance
			for amount in amounts
		):
			continue

		dates = [_as_date(rows[index]["date"]) for index in indexes]
		gaps = [(later - earlier).days for earlier, later in zip(dates, dates[1:])]
		cadence = median(gaps)
		if cadence < 2 or cadence > 45:
			continue
		# Real payments drift (weekend/holiday shifts, a late payment), so tolerate an
		# occasional stray gap: up to 20% of gaps (never with fewer than 5 gaps).
		cadence_tolerance = max(3, cadence * 0.10)
		stray_gaps = sum(abs(gap - cadence) > cadence_tolerance for gap in gaps)
		if stray_gaps > int(0.2 * len(gaps)):
			continue

		last_index = indexes[-1]
		interval = int(round(cadence))
		recurring.append({
			"account_alias": account_alias,
			"payee": payee,
			"kind": kind,
			"category": rows[last_index].get("category"),
			"group_name": rows[last_index].get("group_name"),
			"amount_cents": int(round(median(amounts))),
			"cadence_days": interval,
			"occurrences": len(indexes),
			"first_date": dates[0],
			"last_date": dates[-1],
			"next_date": dates[-1] + timedelta(days=interval),
		})
		recurring_indexes.update(indexes)

	recurring.sort(key=lambda item: (str(item["account_alias"]), item["payee"], item["kind"]))
	return recurring, recurring_indexes


def detect_recurring_items(
	transactions: Iterable[Mapping[str, object]],
	amount_tolerance: float = AMOUNT_TOLERANCE,
	account_alias: str | None = None,
) -> list[dict[str, object]]:
	"""Find same-payee transactions with amounts within 5% and regular cadence."""
	rows = _rows(transactions, account_alias)
	recurring, _ = _find_recurring(rows, amount_tolerance)
	return [
		{**item,
		 "first_date": item["first_date"].isoformat(),
		 "last_date": item["last_date"].isoformat(),
		 "next_date": item["next_date"].isoformat()}
		for item in recurring
	]


def _summarize(path_balances: np.ndarray, starting_balance_cents: int) -> dict[str, object]:
	ending = path_balances[:, -1]
	below_zero = np.any(path_balances < 0, axis=1)
	if starting_balance_cents < 0:
		below_zero[:] = True
	p10, p50, p90 = np.percentile(ending, [10, 50, 90])
	# Per-day percentiles across paths: what a fan chart draws (UI only; the band tells the uncertainty).
	daily = np.percentile(path_balances, [10, 50, 90], axis=0)
	return {
		"daily_cents": {
			"p10": [int(round(float(v))) for v in daily[0]],
			"p50": [int(round(float(v))) for v in daily[1]],
			"p90": [int(round(float(v))) for v in daily[2]],
		},
		"ending_balance_cents": {
			"p10": int(round(float(p10))),
			"p50": int(round(float(p50))),
			"p90": int(round(float(p90))),
		},
		"share_of_paths_below_zero": round(float(np.mean(below_zero)), 4),
	}


def _as_streams(payments) -> list[Mapping[str, object]]:
	if not payments:
		return []
	return list(payments) if isinstance(payments, (list, tuple)) else [payments]


def _expand_streams(
	streams: list[Mapping[str, object]], first_day: date, final_day: date
) -> list[tuple[date, int]]:
	"""Turn payment streams into dated (day, cents) events inside the forecast window."""
	events: list[tuple[date, int]] = []
	for stream in streams:
		stream_date = _as_date(stream["date"])
		stream_cents = int(stream["amount_cents"])
		if stream_cents <= 0:
			raise ValueError("scenario payment amount_cents must be positive")
		if not first_day <= stream_date <= final_day:
			raise ValueError("scenario payment date must fall within the forecast horizon")
		days = [stream_date]
		repeat_every = stream.get("repeat_every_days")
		if repeat_every:
			if int(repeat_every) < 1:
				raise ValueError("repeat_every_days must be positive")
			total = int(stream.get("count") or 10_000)
			while len(days) < total:
				following = days[-1] + timedelta(days=int(repeat_every))
				if following > final_day:
					break
				days.append(following)
		events.extend((day, stream_cents) for day in days)
	return events


def run_monte_carlo(
	transactions: Iterable[Mapping[str, object]],
	starting_balance_cents: int,
	scenario_payment: Mapping[str, object],
	horizon_days: int = 60,
	seed: int = 42,
	paths: int = DEFAULT_PATHS,
	account_alias: str | None = None,
	as_of_date: date | str | None = None,
	baseline_payments: Mapping[str, object] | list | None = None,
) -> dict[str, object]:
	"""Report paired baseline and one-payment scenario forecasts in cents.

	Recurring cash flows are scheduled deterministically. Each future week samples
	one of the customer's historical weeks with replacement for variable spending.
	Both forecasts consume the same pre-sampled weeks so their difference is only
	the one extra scenario payment.
	"""
	if not 30 <= horizon_days <= 90:
		raise ValueError("horizon_days must be between 30 and 90")
	if paths < 1:
		raise ValueError("paths must be positive")

	rows = _rows(transactions, account_alias)
	if not rows:
		raise ValueError("transactions must contain at least one row")
	latest_transaction = max(_as_date(row["date"]) for row in rows)
	as_of = _as_date(as_of_date) if as_of_date is not None else latest_transaction
	rows = [row for row in rows if _as_date(row["date"]) <= as_of]
	if not rows:
		raise ValueError("no transactions exist on or before as_of_date")

	first_forecast_day = as_of + timedelta(days=1)
	final_forecast_day = as_of + timedelta(days=horizon_days)

	# scenario_payment is one stream (a dict) or several (a list), e.g. a car loan plus a savings
	# move. Each stream pays once, or repeats via "repeat_every_days" (+ "count" = total payments).
	streams = _as_streams(scenario_payment)
	if not streams:
		raise ValueError("scenario_payment must contain at least one payment")
	payment_events = _expand_streams(streams, first_forecast_day, final_forecast_day)
	# baseline_payments (e.g. savings rules the customer already accepted) hit BOTH forecasts, so
	# the baseline-vs-scenario difference is still only the scenario.
	baseline_events = _expand_streams(_as_streams(baseline_payments), first_forecast_day, final_forecast_day)
	payment_date = _as_date(streams[0]["date"])
	payment_cents = int(streams[0]["amount_cents"])

	recurring, recurring_indexes = _find_recurring(rows)
	recurring_calendar = []
	recurring_flows = np.zeros(horizon_days, dtype=np.int64)
	for item in recurring:
		interval = timedelta(days=item["cadence_days"])
		scheduled_day = item["next_date"]
		while scheduled_day <= as_of:
			scheduled_day += interval
		while scheduled_day <= final_forecast_day:
			if scheduled_day >= first_forecast_day:
				day_index = (scheduled_day - first_forecast_day).days
				amount_cents = item["amount_cents"]
				recurring_flows[day_index] += amount_cents
				recurring_calendar.append({
					"date": scheduled_day.isoformat(),
					"account_alias": item["account_alias"],
					"payee": item["payee"],
					"kind": item["kind"],
					"amount_cents": amount_cents,
					"category": item["category"],
				})
			scheduled_day += interval
	recurring_calendar.sort(key=lambda event: (event["date"], event["payee"]))

	dated_rows = [(_as_date(row["date"]), index, row) for index, row in enumerate(rows)]
	first_history_day = min(day for day, _, _ in dated_rows)
	last_history_day = max(day for day, _, _ in dated_rows)
	first_week = first_history_day - timedelta(days=first_history_day.weekday())
	last_week = last_history_day - timedelta(days=last_history_day.weekday())
	templates: dict[date, list[tuple[int, int]]] = {}
	week = first_week
	while week <= last_week:
		templates[week] = []
		week += timedelta(days=7)

	for day, index, row in dated_rows:
		if index in recurring_indexes or int(row["amount_cents"]) >= 0:
			continue
		if row.get("kind") not in {"purchase", "withdrawal"}:
			continue
		week = day - timedelta(days=day.weekday())
		templates[week].append((day.weekday(), int(row["amount_cents"])))

	template_weeks = sorted(templates)
	forecast_weeks = []
	week = first_forecast_day - timedelta(days=first_forecast_day.weekday())
	while week <= final_forecast_day:
		forecast_weeks.append(week)
		week += timedelta(days=7)

	rng = np.random.default_rng(seed)
	sampled_weeks = rng.integers(0, len(template_weeks), size=(paths, len(forecast_weeks)))
	variable_flows = np.zeros((paths, horizon_days), dtype=np.int64)
	for forecast_week_index, forecast_week in enumerate(forecast_weeks):
		for path_index, template_index in enumerate(sampled_weeks[:, forecast_week_index]):
			for weekday, amount_cents in templates[template_weeks[int(template_index)]]:
				event_day = forecast_week + timedelta(days=weekday)
				if first_forecast_day <= event_day <= final_forecast_day:
					day_index = (event_day - first_forecast_day).days
					variable_flows[path_index, day_index] += amount_cents

	baseline_flows = variable_flows + recurring_flows[np.newaxis, :]
	for event_day, cents in baseline_events:
		baseline_flows[:, (event_day - first_forecast_day).days] -= cents
	baseline_balances = starting_balance_cents + np.cumsum(baseline_flows, axis=1, dtype=np.int64)
	scenario_flows = baseline_flows.copy()
	for payment_day, cents in payment_events:
		scenario_flows[:, (payment_day - first_forecast_day).days] -= cents
	scenario_balances = starting_balance_cents + np.cumsum(scenario_flows, axis=1, dtype=np.int64)

	final_differences = scenario_balances[:, -1] - baseline_balances[:, -1]
	expected_difference = -sum(cents for _, cents in payment_events)
	if not np.all(final_differences == expected_difference):
		raise AssertionError("paired scenario paths differ by more than the scheduled payment")

	return {
		"as_of_date": as_of.isoformat(),
		"horizon_days": horizon_days,
		"paths": paths,
		"seed": seed,
		"recurring_items": detect_recurring_items(rows, account_alias=account_alias),
		"calendar": recurring_calendar,
		"scenario_payment": {
			"date": payment_date.isoformat(),
			"amount_cents": payment_cents,
			"payee": streams[0].get("payee"),
			"payments_in_horizon": len(payment_events),
		},
		"baseline": _summarize(baseline_balances, starting_balance_cents),
		"scenario": _summarize(scenario_balances, starting_balance_cents),
		"paired_final_delta_cents": expected_difference,
	}

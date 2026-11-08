"""Rolling-origin evaluation for the Monte Carlo cash-flow forecast."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import mean
from typing import Iterable, Mapping


_MONTE_CARLO_PATH = Path(__file__).with_name("montecarlo")
_LOADER = importlib.machinery.SourceFileLoader("engine_firewall_montecarlo", str(_MONTE_CARLO_PATH))
_SPEC = importlib.util.spec_from_loader(_LOADER.name, _LOADER)
if _SPEC is None:
    raise ImportError(f"Unable to load Monte Carlo engine from {_MONTE_CARLO_PATH}")
_monte_carlo = importlib.util.module_from_spec(_SPEC)
sys.modules[_LOADER.name] = _monte_carlo
_LOADER.exec_module(_monte_carlo)


HORIZON_DAYS = 30
WARMUP_DAYS = 90


def _as_date(value: object) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _skill_score(model_mae: float, benchmark_mae: float) -> float | None:
    if benchmark_mae == 0:
        return None
    return round(1 - model_mae / benchmark_mae, 4)


def rolling_backtest(
    transactions: Iterable[Mapping[str, object]],
    ending_balance_cents: int,
    *,
    origins: Iterable[date | str] | None = None,
    origin_step_days: int = 30,
    paths: int = 5_000,
    seed: int = 42,
    account_alias: str | None = None,
) -> dict[str, object]:
    """Forecast 30 days from earlier origins and compare against observed outcomes.

    `ending_balance_cents` is the known balance on the latest transaction date.
    Origins default to 30-day steps after a 90-day warm-up. Skill scores compare
    median ending-balance MAE against last-30-day net flow and mean monthly net
    flow over the prior 90 days. The Brier outcome is whether any actual daily
    balance in the holdout period fell below zero.
    """
    if origin_step_days < 1:
        raise ValueError("origin_step_days must be positive")
    if paths < 1:
        raise ValueError("paths must be positive")

    rows = [dict(row) for row in transactions]
    if account_alias is not None:
        rows = [row for row in rows if row.get("account_alias") == account_alias]
    if not rows:
        raise ValueError("transactions must contain at least one row")
    if any("date" not in row or "amount_cents" not in row for row in rows):
        raise ValueError("each transaction must include date and amount_cents")

    rows.sort(key=lambda row: (_as_date(row["date"]), int(row["id"]) if row.get("id") is not None else 0))
    first_day = min(_as_date(row["date"]) for row in rows)
    last_day = max(_as_date(row["date"]) for row in rows)
    earliest_origin = first_day + timedelta(days=WARMUP_DAYS - 1)
    latest_origin = last_day - timedelta(days=HORIZON_DAYS)

    if origins is None:
        origin_days = []
        origin = earliest_origin
        while origin <= latest_origin:
            origin_days.append(origin)
            origin += timedelta(days=origin_step_days)
    else:
        origin_days = sorted({_as_date(origin) for origin in origins})
        invalid = [origin for origin in origin_days
                   if origin < earliest_origin or origin > latest_origin]
        if invalid:
            raise ValueError(
                f"origins must have a full {WARMUP_DAYS}-day history and "
                f"{HORIZON_DAYS}-day holdout inside the transaction dates"
            )

    if not origin_days:
        raise ValueError(
            f"not enough transaction history: need at least "
            f"{WARMUP_DAYS + HORIZON_DAYS} days"
        )

    flow_by_day: dict[date, int] = {}
    for row in rows:
        day = _as_date(row["date"])
        flow_by_day[day] = flow_by_day.get(day, 0) + int(row["amount_cents"])

    actual_rows = []
    for origin in origin_days:
        target = origin + timedelta(days=HORIZON_DAYS)
        holdout_flow = sum(amount for day, amount in flow_by_day.items() if origin < day <= target)
        balance_at_origin = ending_balance_cents - sum(
            amount for day, amount in flow_by_day.items() if origin < day <= last_day
        )
        actual_ending_balance = balance_at_origin + holdout_flow

        daily_balance = balance_at_origin
        actual_overdraft = daily_balance < 0
        for offset in range(1, HORIZON_DAYS + 1):
            daily_balance += flow_by_day.get(origin + timedelta(days=offset), 0)
            actual_overdraft = actual_overdraft or daily_balance < 0

        prior_30_day_flow = sum(
            amount for day, amount in flow_by_day.items()
            if origin - timedelta(days=29) <= day <= origin
        )
        prior_90_day_flow = sum(
            amount for day, amount in flow_by_day.items()
            if origin - timedelta(days=89) <= day <= origin
        )
        last_month_prediction = balance_at_origin + prior_30_day_flow
        three_month_average_prediction = balance_at_origin + prior_90_day_flow / 3

        # A one-cent dummy scenario is required by the paired simulator API; its
        # baseline distribution is the forecast scored here.
        training_rows = [row for row in rows if _as_date(row["date"]) <= origin]
        forecast = _monte_carlo.run_monte_carlo(
            training_rows,
            starting_balance_cents=balance_at_origin,
            scenario_payment={
                "date": target.isoformat(),
                "amount_cents": 1,
                "payee": "backtest placeholder",
            },
            horizon_days=HORIZON_DAYS,
            seed=seed,
            paths=paths,
            account_alias=account_alias,
            as_of_date=origin,
        )["baseline"]
        interval = forecast["ending_balance_cents"]
        p10, p50, p90 = interval["p10"], interval["p50"], interval["p90"]
        overdraft_probability = float(forecast["share_of_paths_below_zero"])

        actual_rows.append({
            "origin": origin.isoformat(),
            "target_date": target.isoformat(),
            "actual_ending_balance_cents": actual_ending_balance,
            "forecast_ending_balance_cents": {"p10": p10, "p50": p50, "p90": p90},
            "actual_in_80_percent_interval": p10 <= actual_ending_balance <= p90,
            "overdraft_probability": overdraft_probability,
            "actual_overdraft": actual_overdraft,
            "last_month_prediction_cents": round(last_month_prediction),
            "three_month_average_prediction_cents": round(three_month_average_prediction),
            "absolute_error_cents": abs(p50 - actual_ending_balance),
            "last_month_absolute_error_cents": abs(last_month_prediction - actual_ending_balance),
            "three_month_average_absolute_error_cents": abs(
                three_month_average_prediction - actual_ending_balance
            ),
            "brier_contribution": (overdraft_probability - int(actual_overdraft)) ** 2,
        })

    model_mae = mean(row["absolute_error_cents"] for row in actual_rows)
    last_month_mae = mean(row["last_month_absolute_error_cents"] for row in actual_rows)
    three_month_mae = mean(row["three_month_average_absolute_error_cents"] for row in actual_rows)
    return {
        "horizon_days": HORIZON_DAYS,
        "paths_per_origin": paths,
        "origins": len(actual_rows),
        "metrics": {
            "median_forecast_mae_cents": round(model_mae, 2),
            "last_month_baseline_mae_cents": round(last_month_mae, 2),
            "three_month_average_baseline_mae_cents": round(three_month_mae, 2),
            "skill_vs_last_month": _skill_score(model_mae, last_month_mae),
            "skill_vs_three_month_average": _skill_score(model_mae, three_month_mae),
            "80_percent_interval_coverage": round(mean(
                row["actual_in_80_percent_interval"] for row in actual_rows
            ), 4),
            "overdraft_brier_score": round(mean(row["brier_contribution"] for row in actual_rows), 4),
            "mean_overdraft_probability": round(mean(
                row["overdraft_probability"] for row in actual_rows
            ), 4),
            "actual_overdraft_rate": round(mean(
                row["actual_overdraft"] for row in actual_rows
            ), 4),
        },
        "by_origin": actual_rows,
    }

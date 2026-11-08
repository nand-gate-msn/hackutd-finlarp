import importlib.machinery
import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path


BACKTEST_PATH = Path(__file__).resolve().parents[2] / "engine-firewall" / "backtest"
_LOADER = importlib.machinery.SourceFileLoader("engine_firewall_backtest_test", str(BACKTEST_PATH))
_SPEC = importlib.util.spec_from_loader(_LOADER.name, _LOADER)
if _SPEC is None:
    raise ImportError(f"Unable to load backtest module from {BACKTEST_PATH}")
backtest = importlib.util.module_from_spec(_SPEC)
sys.modules[_LOADER.name] = backtest
_LOADER.exec_module(backtest)


def test_rolling_backtest_scores_multiple_origins_without_lookahead(monkeypatch):
    start = date(2026, 1, 1)
    transactions = []
    for offset in range(240):
        day = start + timedelta(days=offset)
        if offset % 14 == 0:
            transactions.append({
                "id": offset + 1,
                "account_alias": "acct_A",
                "date": day.isoformat(),
                "kind": "deposit",
                "amount_cents": 120000,
                "label": "paycheck",
            })
        if day.day == 1:
            transactions.append({
                "id": 1000 + offset,
                "account_alias": "acct_A",
                "date": day.isoformat(),
                "kind": "withdrawal",
                "amount_cents": -65000,
                "category": "housing",
                "group_name": "Housing",
                "obligation_alias": "bill_rent",
            })
        if day.weekday() in (2, 5):
            transactions.append({
                "id": 2000 + offset,
                "account_alias": "acct_A",
                "date": day.isoformat(),
                "kind": "purchase",
                "amount_cents": -2800,
                "group_name": "Food",
                "counterparty": "merch_food",
            })

    cutoffs = []
    original = backtest._monte_carlo.run_monte_carlo

    def record_cutoff(rows, **kwargs):
        as_of = backtest._as_date(kwargs["as_of_date"])
        cutoffs.append(as_of)
        assert all(backtest._as_date(row["date"]) <= as_of for row in rows)
        return original(rows, **kwargs)

    monkeypatch.setattr(backtest._monte_carlo, "run_monte_carlo", record_cutoff)
    ending_balance = 400000 + sum(row["amount_cents"] for row in transactions)
    report = backtest.rolling_backtest(transactions, ending_balance, paths=100, seed=9)

    assert report["origins"] >= 3
    assert len(cutoffs) == report["origins"]
    assert report["metrics"]["median_forecast_mae_cents"] >= 0
    assert report["metrics"]["last_month_baseline_mae_cents"] >= 0
    assert report["metrics"]["three_month_average_baseline_mae_cents"] >= 0
    assert 0 <= report["metrics"]["80_percent_interval_coverage"] <= 1
    assert 0 <= report["metrics"]["overdraft_brier_score"] <= 1
    assert report["metrics"]["80_percent_interval_coverage"] == round(
        sum(row["actual_in_80_percent_interval"] for row in report["by_origin"])
        / report["origins"], 4
    )
    assert report["metrics"]["overdraft_brier_score"] == round(
        sum(row["brier_contribution"] for row in report["by_origin"])
        / report["origins"], 4
    )


def test_rolling_backtest_requires_full_training_and_holdout_period():
    rows = [{"date": "2026-01-01", "amount_cents": 1000}]
    try:
        backtest.rolling_backtest(rows, 1000, paths=1)
    except ValueError as exc:
        assert "need at least" in str(exc)
    else:
        raise AssertionError("short history should not produce a backtest")

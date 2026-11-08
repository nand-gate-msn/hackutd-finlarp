"""The two tools the Planner uses: simulate(scenario) and risk(scenario).

Both read the anonymized SQLite data, run the existing engines (Monte Carlo, metrics), and return
FACT-PACK NUMBERS ONLY: ratios, shares of paths and value bands. Never dollar amounts, dates, rows
or names, so a tool result is always safe to put in a prompt.

Scenario model: every scenario is a recurring monthly cash outflow of
`payment_ratio_of_income x typical monthly income`, for `term_months` (0 = ongoing).
  car_loan / new_subscription : a new monthly payment
  rent_increase               : the extra monthly rent
  income_drop                 : income lost each month (same cash effect as an extra outflow)
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from statistics import median
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import settings
from .db import work_db
from .engine_firewall import finmetrics, montecarlo
from .factpack_schema import Band, Ratio, Status
from .llm import tool_spec

MONTH_DAYS = 30
FIRST_PAYMENT_OFFSET_DAYS = 7  # the scenario's first payment lands a week after the last known day

ScenarioKind = Literal["car_loan", "rent_increase", "income_drop", "new_subscription", "none"]


class ToolError(Exception):
    """Bad arguments or missing data; the workflow turns this into a fallback or a retry."""


class ScenarioInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: ScenarioKind
    payment_ratio_of_income: Ratio = 0.0
    term_months: Annotated[int, Field(ge=0, le=120)] = 0
    horizon_days: Annotated[int, Field(ge=30, le=90)] = 60


NONE_SCENARIO = ScenarioInput(kind="none")


class PathSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    p10_band: Band
    p50_band: Band
    p90_band: Band
    share_below_zero: Ratio


class SimulationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: ScenarioKind
    horizon_days: int
    payment_ratio_of_income: Ratio
    payments_in_horizon: int
    baseline: PathSummary
    scenario: PathSummary
    added_share_below_zero: float  # scenario minus baseline; the cost of the scenario
    tag: Literal["simulated"] = "simulated"


class DailyBand(BaseModel):
    """Per-day balance percentiles in cents (index 0 = the first forecast day)."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    p10: list[int]
    p50: list[int]
    p90: list[int]


class ForecastSeries(BaseModel):
    """UI-ONLY chart data (real cents, real dates). Never put this in a prompt or a FactPack."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    start: str  # ISO date of day index 0
    baseline: DailyBand  # life as it is (accepted rules included)
    scenario: DailyBand  # with the scenario (and any proposed savings move)


class RiskFlag(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    flag: Literal["overdraft", "payment_too_big", "low_buffer"]
    status: Status
    value: float  # overdraft: share of paths; payment_too_big: housing+debt load; low_buffer: p10 band rank


class RiskResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    flags: list[RiskFlag]
    overall: Status


# ---------------------------------------------------------------- data

def _load(conn: sqlite3.Connection) -> dict[str, Any]:
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM transactions ORDER BY date, id")]
    account = conn.execute(
        "SELECT alias, balance_cents FROM accounts WHERE type = 'Checking' ORDER BY alias LIMIT 1"
    ).fetchone()
    if not rows or account is None:
        raise ToolError("no customer data loaded (run scripts/load_customer.py)")
    last = date.fromisoformat(rows[-1]["date"][:10])
    since = last - timedelta(days=90)
    income = sum(
        r["amount_cents"] for r in rows
        if r["kind"] == "deposit" and r["label"] != "interest" and date.fromisoformat(r["date"][:10]) > since
    )
    history_days = max(1, (last - date.fromisoformat(rows[0]["date"][:10])).days)
    outflow = -sum(
        r["amount_cents"] for r in rows
        if r["amount_cents"] < 0 and r["kind"] not in ("transfer_in", "transfer_out")
    )
    return {
        "rows": rows,
        "account": account["alias"],
        "balance_cents": account["balance_cents"],
        "monthly_income_cents": income // 3,
        "monthly_outflow_cents": max(1, outflow * MONTH_DAYS // history_days),
    }


def balance_band(cents: float, monthly_outflow_cents: int) -> Band:
    """Ending balance in months of typical spending. Provisional cut-offs for Finance to tune."""
    months = cents / monthly_outflow_cents
    if months < 0:
        return "very_low"
    if months < 0.5:
        return "low"
    if months < 1.5:
        return "moderate"
    if months < 3:
        return "high"
    return "very_high"


def _summary(part: dict, monthly_outflow: int) -> PathSummary:
    end = part["ending_balance_cents"]
    return PathSummary(
        p10_band=balance_band(end["p10"], monthly_outflow),
        p50_band=balance_band(end["p50"], monthly_outflow),
        p90_band=balance_band(end["p90"], monthly_outflow),
        share_below_zero=part["share_of_paths_below_zero"],
    )


# ---------------------------------------------------------------- tools

def _parse(scenario: dict | ScenarioInput) -> ScenarioInput:
    if isinstance(scenario, ScenarioInput):
        return scenario
    try:
        return ScenarioInput.model_validate(scenario)
    except ValidationError as e:
        raise ToolError(f"invalid scenario: {e.errors()[0]['msg']} ({e.errors()[0]['loc']})") from e


def _paycheck(rows: list[dict], account: str) -> tuple[int, int, date] | None:
    """(typical amount, days between paychecks, last paycheck date) from the last 6 paychecks."""
    pay = [r for r in rows if r["label"] == "paycheck" and r["account_alias"] == account][-6:]
    if not pay:
        return None
    dates = [date.fromisoformat(r["date"][:10]) for r in pay]
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    return int(median(r["amount_cents"] for r in pay)), int(median(gaps)) if gaps else 14, dates[-1]


def _savings_stream(pay: tuple[int, int, date], as_of: date, percent: float) -> dict:
    """`percent` of every paycheck leaving checking, starting with the next paycheck."""
    amount, gap, last_paycheck = pay
    next_paycheck = last_paycheck + timedelta(days=gap)
    while next_paycheck <= as_of:
        next_paycheck += timedelta(days=gap)
    return {"date": next_paycheck, "amount_cents": round(amount * percent / 100),
            "repeat_every_days": gap, "count": None}


def active_rules_percent(conn: sqlite3.Connection, account: str) -> float:
    """Total % of each paycheck that accepted (and not undone) rules move out of `account`."""
    row = conn.execute(
        "SELECT COALESCE(SUM(percent), 0) FROM rules WHERE status = 'active' AND from_alias = ?", (account,)
    ).fetchone()
    return float(row[0])


def simulate(
    scenario: dict | ScenarioInput,
    conn: sqlite3.Connection | None = None,
    *,
    savings_percent: float = 0.0,
) -> SimulationResult:
    """Forecast `horizon_days` with and without the scenario. The model-facing result: bands and shares only."""
    return simulate_with_series(scenario, conn, savings_percent=savings_percent)[0]


def simulate_with_series(
    scenario: dict | ScenarioInput,
    conn: sqlite3.Connection | None = None,
    *,
    savings_percent: float = 0.0,
) -> tuple[SimulationResult, ForecastSeries]:
    """Forecast `horizon_days` with and without the scenario (5,000 paired paths).

    `savings_percent` adds a proposed rule on top: that % of every paycheck moves out of checking.
    Rules the customer already accepted are applied to both sides, so the baseline is "life as it is
    now" and the result shows what the scenario / proposed change costs or saves.
    """
    sc = _parse(scenario)
    if not 0 <= savings_percent <= 30:
        raise ToolError("savings_percent must be between 0 and 30")
    if conn is None:
        with work_db() as c:
            return simulate_with_series(sc, c, savings_percent=savings_percent)
    data = _load(conn)
    as_of = date.fromisoformat(data["rows"][-1]["date"][:10])
    first_day = as_of + timedelta(days=FIRST_PAYMENT_OFFSET_DAYS)

    streams = []
    payment = round(data["monthly_income_cents"] * sc.payment_ratio_of_income)
    scenario_payments = 0
    if sc.kind != "none" and payment > 0:
        streams.append({
            "date": first_day, "amount_cents": payment,
            "repeat_every_days": MONTH_DAYS, "count": sc.term_months or None,
        })
        scenario_payments = (sc.horizon_days - FIRST_PAYMENT_OFFSET_DAYS) // MONTH_DAYS + 1
        if sc.term_months:
            scenario_payments = min(scenario_payments, sc.term_months)
    pay = _paycheck(data["rows"], data["account"])
    if savings_percent > 0:
        if pay is None:
            raise ToolError("no paychecks found; cannot size a savings move")
        streams.append(_savings_stream(pay, as_of, savings_percent))
    # rules the customer already accepted are part of their life now: they hit baseline AND scenario
    rules_percent = active_rules_percent(conn, data["account"])
    rule_streams = [_savings_stream(pay, as_of, rules_percent)] if rules_percent > 0 and pay else []
    if not streams:
        streams.append({"date": first_day, "amount_cents": 1})  # engine needs a payment: 1 cent

    mc = montecarlo.run_monte_carlo(
        data["rows"],
        data["balance_cents"],
        streams,
        baseline_payments=rule_streams,
        horizon_days=sc.horizon_days,
        seed=settings.random_seed,
        paths=settings.monte_carlo_runs,
        account_alias=data["account"],
        as_of_date=as_of,
    )
    out = data["monthly_outflow_cents"]
    baseline, scenario_part = _summary(mc["baseline"], out), _summary(mc["scenario"], out)
    no_change = len(streams) == 1 and streams[0]["amount_cents"] == 1
    if no_change:
        scenario_part = baseline
    series = ForecastSeries(
        start=(as_of + timedelta(days=1)).isoformat(),
        baseline=DailyBand(**mc["baseline"]["daily_cents"]),
        scenario=DailyBand(**(mc["baseline"] if no_change else mc["scenario"])["daily_cents"]),
    )
    result = SimulationResult(
        kind=sc.kind,
        horizon_days=sc.horizon_days,
        payment_ratio_of_income=sc.payment_ratio_of_income,
        payments_in_horizon=scenario_payments,
        baseline=baseline,
        scenario=scenario_part,
        added_share_below_zero=round(scenario_part.share_below_zero - baseline.share_below_zero, 4),
    )
    return result, series


_BAND_RANK = {"very_low": 0.0, "low": 0.25, "moderate": 0.5, "high": 0.75, "very_high": 1.0}
_STATUS = {"healthy": "ok", "watch": "watch", "risk": "risk", "insufficient_data": "watch"}
_ORDER = {"ok": 0, "watch": 1, "risk": 2}


def risk(scenario: dict | ScenarioInput, conn: sqlite3.Connection | None = None) -> RiskResult:
    """Flag overdraft danger, a payment too big for income, and a thin cash buffer."""
    sc = _parse(scenario)
    if conn is None:
        with work_db() as c:
            return risk(sc, c)
    sim = simulate(sc, conn)
    data = _load(conn)

    od = finmetrics.THRESHOLDS["overdraft_probability_30d"]
    share = sim.scenario.share_below_zero
    overdraft = "ok" if share * 100 <= od["healthy_max"] else "watch" if share * 100 <= od["watch_max"] else "risk"

    current = finmetrics.housing_debt_load(data["rows"])["value"]  # percent, or None
    adds = sc.payment_ratio_of_income * 100 if sc.kind in ("car_loan", "rent_increase") else 0.0
    load = None if current is None else current + adds
    too_big = _STATUS[finmetrics._lower_is_better(load, "housing_debt_load")]

    rank = _BAND_RANK[sim.scenario.p10_band]
    buffer = "risk" if rank == 0.0 else "watch" if rank == 0.25 else "ok"

    flags = [
        RiskFlag(flag="overdraft", status=overdraft, value=share),
        RiskFlag(flag="payment_too_big", status=too_big, value=round((load or 0.0) / 100, 4)),
        RiskFlag(flag="low_buffer", status=buffer, value=rank),
    ]
    return RiskResult(flags=flags, overall=max((f.status for f in flags), key=_ORDER.__getitem__))


# ---------------------------------------------------------------- LLM-facing

_SCENARIO_PARAMS = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": ["car_loan", "rent_increase", "income_drop", "new_subscription", "none"]},
        "payment_ratio_of_income": {"type": "number", "description": "monthly amount as a share of monthly income, 0 to 1"},
        "term_months": {"type": "integer", "description": "number of monthly payments; 0 = ongoing"},
        "horizon_days": {"type": "integer", "description": "30 to 90, default 60"},
    },
    "required": ["kind", "payment_ratio_of_income", "term_months"],
}
SIMULATE_SPEC = tool_spec("simulate", "Forecast the next 30-90 days with and without the scenario.", _SCENARIO_PARAMS)
RISK_SPEC = tool_spec("risk", "Flag overdraft danger and whether the payment is too big for income.", _SCENARIO_PARAMS)
TOOLS = {"simulate": simulate, "risk": risk}


def run_tool(name: str, args: dict, conn: sqlite3.Connection | None = None) -> dict:
    """Dispatch a tool call by name; returns plain JSON-able fact-pack numbers."""
    if name not in TOOLS:
        raise ToolError(f"unknown tool {name!r}")
    return TOOLS[name](args, conn).model_dump()

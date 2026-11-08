"""Overall financial health, before and after a decision (the `health` tool).

The scoring logic lives in engine_firewall/overallFinHealth.py (compute_overall_fin_health). This
module hands it the customer's data as it would look AFTER a decision, then compares:

  * a monthly payment (car loan, rent increase, new subscription): the payment is added to every month
    of history, i.e. "your budget if this were already part of it";
  * income drop: every deposit is scaled down by the scenario's share of income;
  * a savings move: that % of every paycheck becomes a transfer to savings;
  * rules the customer already accepted: applied to both sides, like the forecast does.

The overdraft indicator uses the Monte Carlo 30-day share (the same number the forecast reports),
so the score and the forecast can never disagree. Results are scores, statuses and indicator names
only: safe to put in a FactPack.
"""

from __future__ import annotations

import sqlite3
from calendar import monthrange
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .db import work_db
from .engine_firewall.overallFinHealth import INDICATOR_WEIGHTS, LABELS, PILLAR_WEIGHTS, compute_overall_fin_health
from .tools import NONE_SCENARIO, ScenarioInput, ToolError, _load, active_rules_percent, simulate

Status = Literal["Healthy", "Okay", "Needs attention", "At risk"]
MIN_DRIVER_POINTS = 0.5  # smaller shifts are noise, not worth a sentence

# scenario kind -> (group_name, category) of the synthetic monthly payment
_PAYMENT_KINDS = {
    "car_loan": ("Debt", "loan"),
    "rent_increase": ("Housing", "housing"),
    "new_subscription": ("Discretionary", "subscriptions"),
}


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HealthSnapshot(_Model):
    score: float  # overall, 0-100
    status: Status
    pillars: dict[str, float | None]  # Spend / Save / Borrow / Plan
    indicators: dict[str, float | None]  # engine indicator name -> 0-100 score


class HealthDriver(_Model):
    indicator: str  # an engine indicator name; LABELS[indicator] is its display text
    effect: Literal["better", "worse"]
    points: float  # contribution to the change in the overall score, always positive


class HealthResult(_Model):
    before: HealthSnapshot
    after: HealthSnapshot
    change: float  # after - before, in points
    drivers: list[HealthDriver]  # biggest contributors to the change, at most 2
    tag: Literal["simulated"] = "simulated"


def _snapshot(report: dict) -> HealthSnapshot:
    if report["overallFinHealth"] is None:
        raise ToolError("not enough data to score financial health")
    return HealthSnapshot(
        score=report["overallFinHealth"],
        status=report["status"],
        pillars={name: p["score"] for name, p in report["pillars"].items()},
        indicators={name: i["score"] for name, i in report["indicators"].items()},
    )


def _drivers(before: HealthSnapshot, after: HealthSnapshot) -> list[HealthDriver]:
    """Which indicators moved the overall score most (weights follow the engine's re-normalisation)."""
    active = {p: PILLAR_WEIGHTS[p] for p, s in after.pillars.items() if s is not None}
    total_pillar = sum(active.values()) or 1.0
    impacts = []
    for pillar, weights in INDICATOR_WEIGHTS.items():
        if pillar not in active:
            continue
        usable = {n: w for n, w in weights.items() if after.indicators.get(n) is not None}
        total_ind = sum(usable.values()) or 1.0
        for name, weight in usable.items():
            if before.indicators.get(name) is None:
                continue
            delta = after.indicators[name] - before.indicators[name]
            impacts.append((name, delta * (active[pillar] / total_pillar) * (weight / total_ind)))
    impacts.sort(key=lambda x: -abs(x[1]))
    return [
        HealthDriver(indicator=n, effect="better" if v > 0 else "worse", points=round(abs(v), 1))
        for n, v in impacts[:2] if abs(v) >= MIN_DRIVER_POINTS
    ]


def _synthetic(account: str, day: date, kind: str, cents: int, group: str, category: str, who: str) -> dict:
    return {
        "id": None, "account_alias": account, "date": day.isoformat(), "kind": kind, "amount_cents": cents,
        "category": category, "group_name": group, "counterparty": who, "obligation_alias": None,
        "days_late": None, "label": None,
    }


def _with_decision(
    data: dict, accounts: list[dict], sc: ScenarioInput, savings_percent: float
) -> list[dict]:
    """The customer's transaction rows as they would look with the decision in place."""
    rows = [dict(r) for r in data["rows"]]
    checking = data["account"]
    savings = next((a["alias"] for a in accounts if a["type"] == "Savings"), None)

    if sc.kind == "income_drop":
        keep = 1 - sc.payment_ratio_of_income
        for r in rows:
            # less income, proportionally less saved: otherwise the savings RATE would rise on a pay cut
            if (r["kind"] == "deposit" and r["label"] != "interest") or (
                r["kind"] in ("transfer_out", "transfer_in") and r["group_name"] == "Savings"
            ):
                r["amount_cents"] = round(r["amount_cents"] * keep)
    elif sc.kind in _PAYMENT_KINDS and sc.payment_ratio_of_income > 0:
        group, category = _PAYMENT_KINDS[sc.kind]
        payment = round(data["monthly_income_cents"] * sc.payment_ratio_of_income)
        first = date.fromisoformat(rows[0]["date"][:10])
        last = date.fromisoformat(rows[-1]["date"][:10])
        y, m = first.year, first.month
        while (y, m) <= (last.year, last.month):
            day = date(y, m, min(15, monthrange(y, m)[1]))
            if first <= day <= last:
                rows.append(_synthetic(checking, day, "withdrawal", -payment, group, category, f"scenario_{sc.kind}"))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    if savings_percent > 0 and savings:
        for r in [r for r in rows if r["label"] == "paycheck" and r["account_alias"] == checking]:
            cents = round(r["amount_cents"] * savings_percent / 100)
            day = date.fromisoformat(r["date"][:10])
            rows.append(_synthetic(checking, day, "transfer_out", -cents, "Savings", "savings", savings))
            rows.append(_synthetic(savings, day, "transfer_in", cents, "Savings", "savings", checking))
    rows.sort(key=lambda r: (r["date"], r["id"] or 0))
    return rows


def _score(conn, data, accounts, sc, savings_percent, rules_percent) -> HealthSnapshot:
    rows = _with_decision(data, accounts, sc, savings_percent + rules_percent)
    # 30-day overdraft share from the same Monte Carlo the forecast uses (rules are already inside it)
    month = ScenarioInput(kind=sc.kind, payment_ratio_of_income=sc.payment_ratio_of_income,
                          term_months=sc.term_months, horizon_days=30)
    overdraft = simulate(month, conn, savings_percent=savings_percent).scenario.share_below_zero
    return _snapshot(compute_overall_fin_health(rows, accounts, overdraft_probability=overdraft))


def current_report(conn: sqlite3.Connection | None = None) -> dict:
    """The full engine report for today's data, in the SAME terms the agents use (accepted rules applied,
    Monte Carlo overdraft), so the page's gauge and the copilot's "health now" always agree."""
    if conn is None:
        with work_db() as c:
            return current_report(c)
    data = _load(conn)
    accounts = [dict(r) for r in conn.execute("SELECT * FROM accounts ORDER BY alias")]
    rules = active_rules_percent(conn, data["account"])
    rows = _with_decision(data, accounts, NONE_SCENARIO, rules)
    overdraft = simulate(ScenarioInput(kind="none", horizon_days=30), conn).scenario.share_below_zero
    return compute_overall_fin_health(rows, accounts, overdraft_probability=overdraft)


def health(
    scenario: dict | ScenarioInput,
    conn: sqlite3.Connection | None = None,
    *,
    savings_percent: float = 0.0,
) -> HealthResult:
    """Overall financial health now, and after the scenario (and optional savings move)."""
    from .tools import _parse

    sc = _parse(scenario)
    if not 0 <= savings_percent <= 30:
        raise ToolError("savings_percent must be between 0 and 30")
    if conn is None:
        with work_db() as c:
            return health(sc, c, savings_percent=savings_percent)
    data = _load(conn)
    accounts = [dict(r) for r in conn.execute("SELECT * FROM accounts ORDER BY alias")]
    rules = active_rules_percent(conn, data["account"])

    before = _score(conn, data, accounts, NONE_SCENARIO, 0.0, rules)
    unchanged = (sc.kind == "none" or sc.payment_ratio_of_income == 0) and savings_percent == 0
    after = before if unchanged else _score(conn, data, accounts, sc, savings_percent, rules)
    return HealthResult(
        before=before, after=after, change=round(after.score - before.score, 1),
        drivers=[] if unchanged else _drivers(before, after),
    )


# --- registered as the Planner's third tool (tools.py cannot import this module: it would be circular)
from . import tools as _tools  # noqa: E402

HEALTH_SPEC = _tools.tool_spec(
    "health", "Overall financial health (0-100) now and after the scenario.", _tools._SCENARIO_PARAMS
)
_tools.TOOLS["health"] = health

"""Projected graph overlays for the money-flow graph. UI-ONLY: never put these in a prompt or a FactPack.

A "preview" is what the graph should draw for one choice:
  * ghost nodes/edges (dashed) that attach to the real graph's node ids ("account:acct_A", "income:paycheck"),
    with amounts as MONTHLY cents (the client scales them to whatever time window the graph shows);
  * the forecast series (daily percentiles) for the shared forecast card.

Choices:
  * a what-if (car loan, rent increase, new subscription): Checking -> "Car loan (projected)";
  * an income drop: Paycheck -> "Lost income (projected)" (money that would no longer arrive);
  * a suggested savings move: Checking -> "Save 5% of each paycheck" -> Savings.
Accepted rules are drawn by graph_api.build_graph from the rules table, the same way.
"""

from __future__ import annotations

import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .db import work_db
from .tools import MONTH_DAYS, ForecastSeries, ScenarioInput, ToolError, _load, _paycheck

SCENARIO_NAMES = {
    "car_loan": "Car loan",
    "rent_increase": "Rent increase",
    "new_subscription": "New subscription",
    "income_drop": "Lost income",
}
SCENARIO_NODE = "ghost:scenario"
RULE_NODE = "ghost:rule"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GhostNode(_Model):
    id: str
    type: Literal["scenario", "rule"]
    label: str
    monthly_cents: int


class GhostEdge(_Model):
    source: str  # a real graph node id or a ghost id
    target: str
    type: Literal["pays", "funds", "transfers"]
    tag: Literal["simulated", "proposed"]
    monthly_cents: int


class Preview(_Model):
    nodes: list[GhostNode] = []
    edges: list[GhostEdge] = []
    series: ForecastSeries


def account_node(alias: str) -> str:
    return f"account:{alias}"


def _savings_alias(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT alias FROM accounts WHERE type = 'Savings' ORDER BY alias LIMIT 1").fetchone()
    return row[0] if row else None


def scenario_preview(sc: ScenarioInput, series: ForecastSeries, conn: sqlite3.Connection | None = None) -> Preview:
    """The what-if as a projected node hanging off the real graph."""
    if conn is None:
        with work_db() as c:
            return scenario_preview(sc, series, c)
    data = _load(conn)
    monthly = round(data["monthly_income_cents"] * sc.payment_ratio_of_income)
    if sc.kind == "none" or monthly <= 0:
        return Preview(series=series)
    node = GhostNode(id=SCENARIO_NODE, type="scenario", label=f"{SCENARIO_NAMES[sc.kind]} (projected)", monthly_cents=monthly)
    if sc.kind == "income_drop":
        edge = GhostEdge(source="income:paycheck", target=SCENARIO_NODE, type="funds", tag="simulated", monthly_cents=monthly)
    else:
        edge = GhostEdge(source=account_node(data["account"]), target=SCENARIO_NODE, type="pays", tag="simulated",
                         monthly_cents=monthly)
    return Preview(nodes=[node], edges=[edge], series=series)


def rule_monthly_cents(conn: sqlite3.Connection, percent: float) -> int:
    """`percent` of a typical paycheck, converted to a monthly amount (paychecks per month = 30 / gap)."""
    data = _load(conn)
    pay = _paycheck(data["rows"], data["account"])
    if pay is None:
        raise ToolError("no paychecks found; cannot size a savings move")
    amount, gap, _ = pay
    return round(amount * percent / 100 * MONTH_DAYS / max(gap, 1))


def rule_preview(
    percent: float, series: ForecastSeries, conn: sqlite3.Connection | None = None, node_id: str = RULE_NODE
) -> Preview:
    """A suggested savings move as Checking -> rule -> Savings."""
    if conn is None:
        with work_db() as c:
            return rule_preview(percent, series, c, node_id)
    data = _load(conn)
    savings = _savings_alias(conn)
    monthly = rule_monthly_cents(conn, percent)
    node = GhostNode(id=node_id, type="rule", label=f"Save {percent:g}% of each paycheck", monthly_cents=monthly)
    edges = [GhostEdge(source=account_node(data["account"]), target=node_id, type="transfers", tag="proposed",
                       monthly_cents=monthly)]
    if savings:
        edges.append(GhostEdge(source=node_id, target=account_node(savings), type="transfers", tag="proposed",
                               monthly_cents=monthly))
    return Preview(nodes=[node], edges=edges, series=series)

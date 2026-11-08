"""Problem spots on the money-flow graph, found by code (never by a model).

Runs next to the risk tool: the same data and the same simulation, but pointed at the graph. Each finding names
the graph node(s) to paint red and says why. Four kinds:

  late_payment    a bill the history shows was paid late
  over_guideline  housing / housing+debt already above the guidelines the health score uses
  low_balance     the lowest point checking reached, and the payment that preceded it
  decision        the projected what-if itself, when it is what pushes a measure into the red

A finding has two texts. `reason` is for the screen (it may hold real dates, amounts and, once names are restored,
real payee names). `anon` is the only text a model may ever see: aliases, ratios and bands, no dates or amounts.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .db import work_db
from .engine_firewall.overallFinHealth import ASSUMED_TAX_RATE, HOUSING_RATIO, TOTAL_DEBT_RATIO
from .tools import RiskResult, ScenarioInput, SimulationResult, _load

# provisional thresholds, for Finance to tune
LATE_RATE_WATCH = 0.05  # late in at least 5% of payments, or ...
LATE_DAYS_WATCH = 3  # ... once by this many days
LATE_RATE_RISK = 0.20
LATE_DAYS_RISK = 7
CUSHION_MONTHS_WATCH = 0.5  # lowest balance under half a month of spending
CUSHION_MONTHS_RISK = 0.2
LOOKBACK_DAYS = 180
CULPRIT_WINDOW_DAYS = 7  # the biggest payment this many days before the low point is named as the cause
MAX_FINDINGS = 6

HOUSING_GUIDELINE = HOUSING_RATIO[0][0]  # 0.28: at or below this scores full marks
TOTAL_GUIDELINE = TOTAL_DEBT_RATIO[0][0]  # 0.36

_ORDER = {"watch": 1, "risk": 2}


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    kind: Literal["late_payment", "over_guideline", "low_balance", "decision"]
    severity: Literal["watch", "risk"]
    title: str
    reason: str  # UI text; aliases become real names at the screen
    anon: str  # the only text a model may see
    node_ids: list[str]


def _money(cents: float) -> str:
    return f"${cents / 100:,.0f}"


def _day(iso: str) -> str:
    return date.fromisoformat(iso[:10]).strftime("%b %d").replace(" 0", " ")


# ------------------------------------------------------------------ late bills

def late_payments(conn: sqlite3.Connection) -> list[Finding]:
    stats: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # payments, late, worst days
    for r in conn.execute("SELECT obligation_alias a, days_late d FROM transactions WHERE obligation_alias IS NOT NULL"):
        s = stats[r["a"]]
        s[0] += 1
        if (r["d"] or 0) > 0:
            s[1] += 1
            s[2] = max(s[2], r["d"])
    groups = {r["alias"]: r["group_name"] for r in conn.execute("SELECT alias, group_name FROM obligations")}
    out = []
    for alias, (n, late, worst) in sorted(stats.items()):
        rate = late / n if n else 0
        if not late or not (rate >= LATE_RATE_WATCH or worst >= LATE_DAYS_WATCH):
            continue
        severity = "risk" if rate >= LATE_RATE_RISK or worst >= LATE_DAYS_RISK else "watch"
        out.append(Finding(
            id=f"late_payment:{alias}", kind="late_payment", severity=severity, title="Paid late",
            reason=f"{alias} was paid late {late} of {n} times (worst: {worst} day{'s' if worst != 1 else ''} late).",
            anon=f"{alias} ({groups.get(alias, 'Other')}) was paid late in {rate:.0%} of its payments, worst {worst} days.",
            node_ids=[f"obligation:{alias}"],
        ))
    return out


# ------------------------------------------------------------------ guidelines

def over_guideline(data: dict, conn: sqlite3.Connection) -> list[Finding]:
    """The same ratios the health score uses (gross income = net / (1 - tax)), on today's data."""
    rows = data["rows"]
    income = sum(r["amount_cents"] for r in rows if r["kind"] == "deposit" and r["label"] != "interest")
    if income <= 0:
        return []
    gross = income / (1 - ASSUMED_TAX_RATE)
    spend = lambda group: -sum(r["amount_cents"] for r in rows if r["amount_cents"] < 0 and r["group_name"] == group)  # noqa: E731
    housing, debt = spend("Housing") / gross, spend("Debt") / gross
    total = housing + debt
    biggest = lambda group: conn.execute(  # noqa: E731
        "SELECT alias FROM obligations WHERE group_name = ? ORDER BY amount_cents DESC LIMIT 1", (group,)
    ).fetchone()
    out = []
    if housing > HOUSING_GUIDELINE:
        row = biggest("Housing")
        if row:
            out.append(Finding(
                id=f"over_guideline:{row['alias']}", kind="over_guideline",
                severity="risk" if housing > (HOUSING_GUIDELINE + 0.45) / 2 else "watch", title="Housing over guideline",
                reason=f"Housing is {housing:.0%} of income; the guideline is {HOUSING_GUIDELINE:.0%}. {row['alias']} is the largest part.",
                anon=f"housing is {housing:.0%} of income (guideline {HOUSING_GUIDELINE:.0%}); {row['alias']} is its largest bill.",
                node_ids=[f"obligation:{row['alias']}"],
            ))
    if total > TOTAL_GUIDELINE:
        row = biggest("Debt") or biggest("Housing")
        if row:
            out.append(Finding(
                id=f"over_guideline:total:{row['alias']}", kind="over_guideline",
                severity="risk" if total > (TOTAL_GUIDELINE + 0.50) / 2 else "watch", title="Housing and debt over guideline",
                reason=f"Housing plus debt is {total:.0%} of income; the guideline is {TOTAL_GUIDELINE:.0%}.",
                anon=f"housing plus debt is {total:.0%} of income (guideline {TOTAL_GUIDELINE:.0%}).",
                node_ids=[f"obligation:{row['alias']}"],
            ))
    return out


# ------------------------------------------------------------------ low balance

def low_balance(data: dict) -> list[Finding]:
    """The lowest checking balance of the last 180 days, blamed on the biggest payment just before it."""
    account, rows = data["account"], data["rows"]
    by_day: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r["account_alias"] == account:
            by_day[r["date"][:10]].append(r)
    if not by_day:
        return []
    last = date.fromisoformat(max(by_day))
    balance, low = data["balance_cents"], None  # walk back from today's balance
    day = last
    while day > last - timedelta(days=LOOKBACK_DAYS):
        if low is None or balance < low[0]:
            low = (balance, day)
        balance -= sum(r["amount_cents"] for r in by_day.get(day.isoformat(), []))
        day -= timedelta(days=1)
    lowest, when = low
    outflow = data["monthly_outflow_cents"]
    months = lowest / outflow
    if months >= CUSHION_MONTHS_WATCH:
        return []

    culprit, node = None, f"account:{account}"
    for back in range(CULPRIT_WINDOW_DAYS + 1):
        for r in by_day.get((when - timedelta(days=back)).isoformat(), []):
            if r["amount_cents"] < 0 and r["kind"] not in ("transfer_in", "transfer_out"):
                if culprit is None or r["amount_cents"] < culprit["amount_cents"]:
                    culprit = r
    what_real = what_anon = "spending"
    if culprit:
        if culprit["obligation_alias"]:
            node = f"obligation:{culprit['obligation_alias']}"
            what_real = what_anon = culprit["obligation_alias"]
        elif culprit["category"]:
            node = f"category:{culprit['category']}"
            what_real = what_anon = culprit["category"]
    severity = "risk" if lowest < 0 or months < CUSHION_MONTHS_RISK else "watch"
    return [Finding(
        id=f"low_balance:{node}", kind="low_balance", severity=severity, title="Low balance moment",
        reason=(f"Checking fell to {_money(lowest)} on {_day(when.isoformat())}"
                + (f", {(when - date.fromisoformat(culprit['date'][:10])).days} days after a {_money(-culprit['amount_cents'])} payment to {what_real}" if culprit else "")
                + f". That is only {months:.1f} months of spending in reserve."),
        anon=f"checking dipped to {months:.1f} months of spending in reserve" + (f", shortly after a payment to {what_anon}" if culprit else "") + ".",
        node_ids=[node],
    )]


# ------------------------------------------------------------------ the decision itself

def decision(sc: ScenarioInput, sim: SimulationResult, rsk: RiskResult) -> list[Finding]:
    """Only what the what-if CAUSES: a measure that is not already red without it."""
    if sc.kind == "none" or sc.payment_ratio_of_income <= 0:
        return []
    flags = {f.flag: f for f in rsk.flags}
    reasons, anon, worst = [], [], 0
    load = flags["payment_too_big"]
    if load.status != "ok":
        reasons.append(f"it takes housing and debt to {load.value:.0%} of income (guideline {TOTAL_GUIDELINE:.0%})")
        anon.append(f"housing and debt would be {load.value:.0%} of income (guideline {TOTAL_GUIDELINE:.0%})")
        worst = max(worst, _ORDER[load.status])
    if sim.added_share_below_zero >= 0.02:
        reasons.append(f"it adds {sim.added_share_below_zero:.0%} to the chance of overdraft")
        anon.append(f"the overdraft chance rises by {sim.added_share_below_zero:.0%}")
        worst = max(worst, 2 if sim.scenario.share_below_zero > 0.20 else 1)
    ranks = {"very_low": 0, "low": 1, "moderate": 2, "high": 3, "very_high": 4}
    if ranks[sim.scenario.p10_band] < ranks[sim.baseline.p10_band] and ranks[sim.scenario.p10_band] <= 1:
        reasons.append("it leaves the balance close to empty in a bad month")
        anon.append("the low end of the forecast would be close to empty")
        worst = max(worst, 2 if sim.scenario.p10_band == "very_low" else 1)
    if not reasons:
        return []
    label = {"car_loan": "car loan", "rent_increase": "rent increase", "income_drop": "income drop",
             "new_subscription": "new subscription"}[sc.kind]
    return [Finding(
        id="decision:ghost", kind="decision", severity="risk" if worst >= 2 else "watch",
        title=f"This {label} is a problem",
        reason=f"As modeled, {'; '.join(reasons)}.",
        anon=f"the what-if ({sc.kind}): {'; '.join(anon)}.",
        node_ids=["ghost:scenario"],
    )]


# ------------------------------------------------------------------ entry point

def find_problems(
    sc: ScenarioInput, sim: SimulationResult, rsk: RiskResult, conn: sqlite3.Connection | None = None
) -> list[Finding]:
    """Everything the graph should paint red for this question, worst first."""
    if conn is None:
        with work_db() as c:
            return find_problems(sc, sim, rsk, c)
    data = _load(conn)
    found = [*decision(sc, sim, rsk), *late_payments(conn), *over_guideline(data, conn), *low_balance(data)]
    found.sort(key=lambda f: -_ORDER[f.severity])
    return found[:MAX_FINDINGS]

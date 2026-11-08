"""Read-only summary of the loaded customer, built from the SQLite working data."""

import calendar
import statistics
from collections import defaultdict
from datetime import date, timedelta

from .db import private_db, work_db


def next_due(due_day: int, today: date) -> date:
    """The next date on or after `today` that falls on `due_day` (clamped to month length)."""
    for add in (0, 1):
        y, m = today.year + (today.month - 1 + add) // 12, (today.month - 1 + add) % 12 + 1
        d = date(y, m, min(due_day, calendar.monthrange(y, m)[1]))
        if d >= today:
            return d
    return today


def is_loaded() -> bool:
    with work_db() as w:
        return w.execute("SELECT 1 FROM meta WHERE key='loaded_at'").fetchone() is not None


def _next_due_iso(due_day):
    return next_due(due_day, date.today()).isoformat() if due_day else None


def build_overview(days: int = 90) -> dict:
    with work_db() as w, private_db() as p:
        labels = {r["alias"]: r["real_name"] for r in p.execute("SELECT alias, real_name FROM alias_map")}
        meta = {r["key"]: r["value"] for r in w.execute("SELECT key, value FROM meta")}
        last = w.execute("SELECT MAX(date) FROM transactions").fetchone()[0]
        end = date.fromisoformat(last) if last else date.today()
        start = end - timedelta(days=days)
        s, e = start.isoformat(), end.isoformat()
        obligations = [dict(r) for r in w.execute("SELECT * FROM obligations ORDER BY alias")]
        accounts, outflow_by_group = [], defaultdict(int)

        for a in w.execute("SELECT * FROM accounts ORDER BY alias").fetchall():
            rows = w.execute("SELECT * FROM transactions WHERE account_alias=? AND date>? AND date<=? "
                             "ORDER BY date DESC, id DESC", (a["alias"], s, e)).fetchall()
            dep = [r for r in rows if r["kind"] == "deposit"]
            pur = [r for r in rows if r["kind"] == "purchase"]
            paid = [r for r in rows if r["obligation_alias"]]
            t_in = sum(r["amount_cents"] for r in rows if r["kind"] == "transfer_in")
            t_out = -sum(r["amount_cents"] for r in rows if r["kind"] == "transfer_out")
            by_cat = defaultdict(int)
            for r in pur:
                by_cat[r["category"]] -= r["amount_cents"]
            for r in rows:
                if r["amount_cents"] < 0 and r["kind"] != "transfer_out":
                    outflow_by_group[r["group_name"]] -= r["amount_cents"]
            accounts.append({
                "alias": a["alias"], "type": a["type"], "balance": a["balance_cents"] / 100,
                "deposits": {"count": len(dep), "total": sum(r["amount_cents"] for r in dep) / 100},
                "purchases": {
                    "count": len(pur), "total": -sum(r["amount_cents"] for r in pur) / 100,
                    "recent": [{"date": r["date"], "amount": -r["amount_cents"] / 100,
                                "description": labels.get(r["counterparty"]) or r["category"]}
                               for r in pur[:5]]},
                "bills": {
                    "count": len(paid), "total": -sum(r["amount_cents"] for r in paid) / 100,
                    "items": [{"payee": labels.get(o["alias"], o["alias"]), "amount": o["amount_cents"] / 100,
                               "status": o["status"], "due": _next_due_iso(o["due_day"])}
                              for o in obligations if o["account_alias"] == a["alias"]]},
                "transfers": {"in": t_in / 100, "out": t_out / 100},
                "spending_by_category": {k: v / 100 for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])},
            })

        paychecks = [dict(r) for r in w.execute(
            "SELECT date, amount_cents FROM transactions WHERE label='paycheck' ORDER BY date")]
        gaps = [(date.fromisoformat(b["date"]) - date.fromisoformat(a["date"])).days
                for a, b in zip(paychecks, paychecks[1:])]
        late_by_ob = {r["obligation_alias"]: r for r in w.execute(
            "SELECT obligation_alias, COUNT(*) n, SUM(days_late>0) late, MAX(days_late) worst "
            "FROM transactions WHERE obligation_alias IS NOT NULL GROUP BY obligation_alias")}
        in_period = {r["obligation_alias"]: r["n"] for r in w.execute(
            "SELECT obligation_alias, COUNT(*) n FROM transactions WHERE obligation_alias IS NOT NULL "
            "AND date>? AND date<=? GROUP BY obligation_alias", (s, e))}
        rules = [dict(r) for r in w.execute("SELECT * FROM rules ORDER BY id DESC")]

    return {
        "source": meta.get("source"), "loaded_at": meta.get("loaded_at"),
        "period": {"start": s, "end": e, "days": days},
        "accounts": accounts,
        "totals": {
            "balance": round(sum(a["balance"] for a in accounts), 2),
            "deposits": round(sum(a["deposits"]["total"] for a in accounts), 2),
            "purchases": round(sum(a["purchases"]["total"] for a in accounts), 2),
            "bills": round(sum(a["bills"]["total"] for a in accounts), 2)},
        "outflow_by_group": {k: v / 100 for k, v in sorted(outflow_by_group.items(), key=lambda kv: -kv[1])},
        "income": {
            "paychecks": len(paychecks),
            "median_amount": statistics.median(r["amount_cents"] for r in paychecks) / 100 if paychecks else None,
            "median_gap_days": statistics.median(gaps) if gaps else None,
            "last_paycheck": paychecks[-1]["date"] if paychecks else None},
        "obligations": [{
            "alias": o["alias"], "label": labels.get(o["alias"], o["alias"]), "kind": o["kind"],
            "category": o["category"], "group": o["group_name"], "amount": o["amount_cents"] / 100,
            "due_day": o["due_day"], "next_due": _next_due_iso(o["due_day"]),
            "payments_in_period": in_period.get(o["alias"], 0),
            "late_payments": (late_by_ob[o["alias"]]["late"] or 0) if o["alias"] in late_by_ob else 0,
            "worst_days_late": (late_by_ob[o["alias"]]["worst"] or 0) if o["alias"] in late_by_ob else 0,
        } for o in obligations],
        "rules": rules,
    }

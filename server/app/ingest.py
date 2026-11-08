"""Load a generated History into SQLite: the only data path into the app.

* Real names go to the private db (alias_map). The work db only ever sees
  aliases (acct_A, merch_3, bill_2), amounts, dates and categories.
* Free-text descriptions are never stored: deposits keep a small allow-listed
  label (paycheck/interest/...), everything else keeps a category.
* Aliases are keyed on stable synthetic IDs ("alex:rent"), so reloading the same
  persona keeps every alias; loading another persona prunes the old ones.
"""

import re
import string
from datetime import datetime, timezone

from .categories import categorize
from .datagen import History
from .datagen.personas import ACCOUNT_SPECS, CHECKING, SAVINGS
from .db import private_db, rebuild_graph, work_db
from .engine_firewall.overallFinHealth import refresh_overall_fin_health

_LABELS = [
    (re.compile(r"paycheck|payroll|salary|direct deposit", re.I), "paycheck"),
    (re.compile(r"interest", re.I), "interest"),
    (re.compile(r"gig|payout|freelance|invoice", re.I), "freelance"),
    (re.compile(r"refund|reimburse", re.I), "refund"),
]


def _income_label(description: str) -> str:
    return next((label for pattern, label in _LABELS if pattern.search(description or "")), "other")


def _alias(p, kind: str, real_id: str, name: str | None, prefix: str) -> str:
    row = p.execute("SELECT alias FROM alias_map WHERE real_id=?", (real_id,)).fetchone()
    if row:
        return row["alias"]
    used = {r["alias"] for r in p.execute("SELECT alias FROM alias_map WHERE kind=?", (kind,))}
    n = 1
    while True:
        suffix = string.ascii_uppercase[n - 1] if kind == "account" and n <= 26 else str(n)
        alias = f"{prefix}_{suffix}"
        if alias not in used:
            break
        n += 1
    p.execute("INSERT INTO alias_map (alias, kind, real_id, real_name) VALUES (?,?,?,?)",
              (alias, kind, real_id, name))
    return alias


def load_history(h: History) -> dict:
    persona = h.persona
    rid = lambda *parts: ":".join((persona.key, *parts))  # noqa: E731  stable synthetic IDs

    with work_db() as w, private_db() as p:
        live = ({rid("account", k) for k in ACCOUNT_SPECS} | {rid("merchant", m) for m in h.merchants}
                | {rid("obligation", o.key) for o in persona.obligations})
        for row in p.execute("SELECT real_id FROM alias_map").fetchall():
            if row["real_id"] not in live:  # left over from another persona
                p.execute("DELETE FROM alias_map WHERE real_id=?", (row["real_id"],))

        acct = {k: _alias(p, "account", rid("account", k), ACCOUNT_SPECS[k][1], "acct") for k in ACCOUNT_SPECS}
        merch, merch_cat = {}, {}
        for name, category in h.merchants.items():
            merch[name] = _alias(p, "merchant", rid("merchant", name), name, "merch")
            merch_cat[name] = categorize(name, category)

        obligations, ob = [], {}
        for o in persona.obligations:
            alias = _alias(p, o.kind, rid("obligation", o.key), o.payee, "loan" if o.kind == "loan" else "bill")
            cat, grp = ("loan", "Debt") if o.kind == "loan" else categorize(o.payee)
            ob[o.key] = (alias, cat, grp)
            obligations.append((alias, o.kind, acct[CHECKING], cat, grp, round(o.amount * 100), o.due_day,
                                "approved" if o.kind == "loan" else "recurring"))

        txns = []
        for e in h.events:
            a, day, amt = acct[e.account], e.date.isoformat(), e.amount_cents
            if e.kind == "deposit":
                txns.append((a, day, "deposit", amt, e.category, "Income", None, None, None,
                             _income_label(e.description)))
            elif e.kind == "purchase":
                cat, grp = merch_cat[e.merchant]
                txns.append((a, day, "purchase", -amt, cat, grp, merch[e.merchant], None, None, None))
            elif e.kind == "withdrawal":
                alias, cat, grp = ob[e.obligation]
                txns.append((a, day, "withdrawal", -amt, cat, grp, alias, alias,
                             (e.date - e.due_date).days, None))
            elif e.kind == "transfer":
                dst = acct[e.to_account]
                grp = "Savings" if e.to_account == SAVINGS else "Transfer"
                txns.append((a, day, "transfer_out", -amt, "transfer", grp, dst, None, None, None))
                txns.append((dst, day, "transfer_in", amt, "transfer", grp, a, None, None, None))

        for table in ("transactions", "accounts", "merchants", "obligations"):
            w.execute(f"DELETE FROM {table}")
        w.executemany("INSERT INTO accounts VALUES (?,?,?)",
                      [(acct[k], ACCOUNT_SPECS[k][0], h.final_cents[k]) for k in ACCOUNT_SPECS])
        w.executemany("INSERT INTO merchants VALUES (?,?,?)",
                      [(merch[n], *merch_cat[n]) for n in merch])
        w.executemany("INSERT INTO obligations VALUES (?,?,?,?,?,?,?,?)", obligations)
        w.executemany("INSERT INTO transactions (account_alias,date,kind,amount_cents,category,group_name,"
                      "counterparty,obligation_alias,days_late,label) VALUES (?,?,?,?,?,?,?,?,?,?)", txns)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        source = f"generator:{persona.key}"
        w.executemany("INSERT OR REPLACE INTO meta VALUES (?,?)", [
            ("loaded_at", now), ("source", source), ("persona", persona.key),
            ("seed", str(h.seed)), ("months", str(h.months)), ("end", h.end.isoformat())])
        graph_counts = rebuild_graph(w)
        health_report = refresh_overall_fin_health(w)
    return {"source": source, "accounts": len(acct), "transactions": len(txns),
            "obligations": len(obligations), "loaded_at": now,
            "overallFinHealth": health_report["overallFinHealth"], **graph_counts}

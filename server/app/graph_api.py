"""Read models for the UI: an aggregated money-flow graph and the health metrics.

The raw graph (graph_nodes / graph_edges) has one edge per transaction, which is far
too dense to draw. This module collapses it to one weighted edge per (source, target,
type) over a time window. Everything here is alias-only, same as the work db.
"""

from collections import defaultdict
from datetime import date, timedelta

from .db import private_db, rebuild_graph, work_db
from .health import current_report
from .projection import account_node, rule_monthly_cents
from .tools import MONTH_DAYS

# Map a deposit's label to a readable income source node.
_INCOME_NAMES = {"paycheck": "Paycheck", "interest": "Interest"}


def _income_key(label: str | None) -> tuple[str, str]:
    label = (label or "deposit").lower()
    return f"income:{label}", _INCOME_NAMES.get(label, label.replace("_", " ").title())


def _add_accepted_rules(out_nodes: dict, agg: dict, days: int) -> None:
    """Accepted savings rules are part of the forecast and health score, so the graph shows them too:
    a dashed rule node between the two accounts, sized to what it moves over this window."""
    with work_db() as w:
        rules = [dict(r) for r in w.execute("SELECT * FROM rules WHERE status = 'active' ORDER BY id")]
        if not rules:
            return
        monthly = {r["id"]: rule_monthly_cents(w, r["percent"]) for r in rules}
    for r in rules:
        node_id = f"rule:{r['id']}"
        cents = round(monthly[r["id"]] * days / MONTH_DAYS)
        out_nodes[node_id] = {
            "id": node_id, "type": "rule", "label": f"Save {r['percent']:g}% of each paycheck", "alias": None,
            "account_type": None, "group": None, "category": None, "due_day": None, "bill_cents": None,
            "in_cents": cents, "out_cents": cents, "tag": "proposed", "accepted": True, "rule_id": r["id"],
        }
        for src, dst in ((account_node(r["from_alias"]), node_id), (node_id, account_node(r["to_alias"]))):
            if src not in out_nodes or dst not in out_nodes:
                continue  # an account with no activity in this window is not drawn
            agg[(src, dst, "transfers", "proposed")] = {
                "source": src, "target": dst, "type": "transfers", "tag": "proposed", "amount_cents": cents, "count": 0,
            }


def build_graph(days: int = 90, include_coverage: bool = False) -> dict:
    """UI-ONLY: node labels use real payee names from the private db. Never feed this to a model."""
    with work_db() as w, private_db() as p:
        names = {r["alias"]: r["real_name"] for r in p.execute("SELECT alias, real_name FROM alias_map")}
        if w.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0] == 0:
            rebuild_graph(w)  # data was loaded before the graph existed
        last = w.execute("SELECT MAX(date) FROM transactions").fetchone()[0]
        end = date.fromisoformat(last[:10]) if last else date.today()
        start = (end - timedelta(days=days)).isoformat()

        nodes = {r["node_id"]: dict(r) for r in w.execute("SELECT * FROM graph_nodes")}
        income_label = {r["id"]: r["label"] for r in w.execute(
            "SELECT id, label FROM transactions WHERE kind='deposit'")}
        has_obligation = {r["id"] for r in w.execute(
            "SELECT id FROM transactions WHERE obligation_alias IS NOT NULL")}
        edges = [dict(r) for r in w.execute(
            "SELECT * FROM graph_edges WHERE date > ? ORDER BY date", (start,))]

    agg: dict[tuple, dict] = {}
    out_nodes: dict[str, dict] = {}

    def keep(node_id: str) -> None:
        if node_id in out_nodes:
            return
        n = nodes[node_id]
        out_nodes[node_id] = {
            "id": node_id, "type": n["node_type"], "label": names.get(n.get("node_key")) or n["label"],
            "alias": n.get("node_key"),
            "account_type": n["label"] if n["node_type"] == "account" else None,
            "group": n["group_name"], "category": n["category"],
            "due_day": n["due_day"], "bill_cents": n["amount_cents"] if n["node_type"] == "obligation" else None,
            "in_cents": 0, "out_cents": 0,
        }

    for e in edges:
        src, dst, etype, tag = e["source_node_id"], e["target_node_id"], e["edge_type"], e["tag"]
        cents = e["amount_cents"] or 0
        if src.startswith("income:"):
            key, name = _income_key(income_label.get(e["transaction_id"]))
            if key not in nodes:
                nodes[key] = {"node_id": key, "node_type": "income", "label": name,
                              "group_name": None, "category": None, "due_day": None, "amount_cents": None}
            if etype == "pays":  # heuristic paycheck -> bill coverage
                if not include_coverage:
                    continue
            src = key
        elif etype == "pays" and dst.startswith("category:") and e["transaction_id"] in has_obligation:
            continue  # a bill payment already has its own account -> bill edge
        keep(src), keep(dst)
        k = (src, dst, etype, tag)
        a = agg.setdefault(k, {"source": src, "target": dst, "type": etype, "tag": tag,
                               "amount_cents": 0, "count": 0})
        a["amount_cents"] += cents
        a["count"] += 1
        out_nodes[src]["out_cents"] += cents
        out_nodes[dst]["in_cents"] += cents

    _add_accepted_rules(out_nodes, agg, days)
    edge_list = sorted(agg.values(), key=lambda a: -a["amount_cents"])
    return {
        "period": {"start": start, "end": end.isoformat(), "days": days},
        "nodes": list(out_nodes.values()),
        "edges": edge_list,
    }


def build_metrics() -> dict:
    """Weighted health report over the full history, from the same engine ingest uses."""
    with work_db() as w:
        transactions = w.execute("SELECT * FROM transactions ORDER BY date,id").fetchall()
        accounts = w.execute("SELECT * FROM accounts ORDER BY alias").fetchall()
    report = current_report()  # same definition the agents use: accepted rules applied, Monte Carlo overdraft
    cash = sum(a["balance_cents"] for a in accounts if a["type"] in ("Checking", "Savings"))
    # Income / spend over the same 90-day window the rest of the UI defaults to.
    last = max(t["date"] for t in transactions)[:10]
    since = (date.fromisoformat(last) - timedelta(days=90)).isoformat()
    flow = defaultdict(int)
    for t in transactions:
        if t["date"] <= since:
            continue
        if t["kind"] == "deposit":
            flow["income"] += t["amount_cents"]
        elif t["amount_cents"] < 0 and t["kind"] != "transfer_out":
            flow["spend"] -= t["amount_cents"]
        elif t["kind"] == "transfer_out" and t["group_name"] == "Savings":
            flow["saved"] -= t["amount_cents"]
    report["cash_cents"] = cash
    report["flow_90d"] = {k: flow[k] for k in ("income", "spend", "saved")}
    return report

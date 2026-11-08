"""SQLite graph schema and graph rebuild from anonymized loaded transactions."""

from __future__ import annotations

import calendar
from datetime import date
from typing import Any


GRAPH_SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id TEXT PRIMARY KEY,
    node_type TEXT NOT NULL CHECK (node_type IN ('income', 'account', 'obligation', 'category')),
    node_key TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    date TEXT,
    amount_cents INTEGER,
    account_alias TEXT,
    obligation_alias TEXT,
    category TEXT,
    group_name TEXT,
    due_day INTEGER,
    tag TEXT NOT NULL CHECK (tag IN ('observed', 'simulated', 'proposed'))
);
CREATE TABLE IF NOT EXISTS graph_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_node_id TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    edge_type TEXT NOT NULL CHECK (edge_type IN ('funds', 'pays', 'transfers')),
    amount_cents INTEGER,
    date TEXT,
    due_date TEXT,
    transaction_id INTEGER,
    tag TEXT NOT NULL CHECK (tag IN ('observed', 'simulated', 'proposed'))
);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_type_tag ON graph_nodes (node_type, tag);
CREATE INDEX IF NOT EXISTS idx_graph_edges_source ON graph_edges (source_node_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_graph_edges_target ON graph_edges (target_node_id, edge_type);
"""


def _add_node(
    conn,
    node_id: str,
    node_type: str,
    node_key: str,
    label: str,
    *,
    date_value: str | None = None,
    amount_cents: int | None = None,
    account_alias: str | None = None,
    obligation_alias: str | None = None,
    category: str | None = None,
    group_name: str | None = None,
    due_day: int | None = None,
    tag: str = "observed",
) -> None:
    conn.execute(
        "INSERT INTO graph_nodes (node_id,node_type,node_key,label,date,amount_cents,account_alias,"
        "obligation_alias,category,group_name,due_day,tag) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (node_id, node_type, node_key, label, date_value, amount_cents, account_alias,
         obligation_alias, category, group_name, due_day, tag),
    )


def _add_edge(
    conn,
    source_node_id: str,
    target_node_id: str,
    edge_type: str,
    *,
    amount_cents: int | None = None,
    date_value: str | None = None,
    due_date: str | None = None,
    transaction_id: int | None = None,
    tag: str = "observed",
) -> None:
    conn.execute(
        "INSERT INTO graph_edges (source_node_id,target_node_id,edge_type,amount_cents,date,due_date,"
        "transaction_id,tag) VALUES (?,?,?,?,?,?,?,?)",
        (source_node_id, target_node_id, edge_type, amount_cents, date_value, due_date,
         transaction_id, tag),
    )


def _due_instances(obligations: list[Any], transactions: list[Any]) -> list[dict[str, Any]]:
    if not obligations or not transactions:
        return []
    transaction_dates = [date.fromisoformat(row["date"][:10]) for row in transactions]
    first, last = min(transaction_dates), max(transaction_dates)
    instances = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        month_end = calendar.monthrange(year, month)[1]
        for obligation in obligations:
            if obligation["due_day"] is None:
                continue
            due = date(year, month, min(max(int(obligation["due_day"]), 1), month_end))
            instances.append({
                "account_alias": obligation["account_alias"],
                "obligation_alias": obligation["alias"],
                "due_date": due,
                "remaining_cents": max(0, int(obligation["amount_cents"] or 0)),
            })
        year, month = (year + (month == 12), month % 12 + 1)
    return sorted(instances, key=lambda item: (item["due_date"], item["obligation_alias"]))


def rebuild_graph(conn) -> dict[str, int]:
    """Rebuild observed graph rows and heuristic paycheck-to-bill links."""
    conn.execute("DELETE FROM graph_edges")
    conn.execute("DELETE FROM graph_nodes")

    accounts = conn.execute("SELECT * FROM accounts ORDER BY alias").fetchall()
    obligations = conn.execute("SELECT * FROM obligations ORDER BY alias").fetchall()
    transactions = conn.execute("SELECT * FROM transactions ORDER BY date,id").fetchall()
    account_ids = {row["alias"]: f"account:{row['alias']}" for row in accounts}
    obligation_ids = {row["alias"]: f"obligation:{row['alias']}" for row in obligations}

    for account in accounts:
        _add_node(conn, account_ids[account["alias"]], "account", account["alias"],
                  account["type"] or account["alias"], account_alias=account["alias"])
    for obligation in obligations:
        _add_node(
            conn, obligation_ids[obligation["alias"]], "obligation", obligation["alias"],
            obligation["alias"], amount_cents=obligation["amount_cents"],
            account_alias=obligation["account_alias"], obligation_alias=obligation["alias"],
            category=obligation["category"], group_name=obligation["group_name"],
            due_day=obligation["due_day"],
        )

    categories = {}
    for row in transactions:
        if row["category"]:
            categories.setdefault(row["category"], row["group_name"])
    for obligation in obligations:
        if obligation["category"]:
            categories.setdefault(obligation["category"], obligation["group_name"])
    for category, group_name in sorted(categories.items()):
        _add_node(conn, f"category:{category}", "category", category, category,
                  category=category, group_name=group_name)

    income_ids = {}
    for transaction in transactions:
        if transaction["kind"] != "deposit":
            continue
        node_id = f"income:{transaction['id']}"
        income_ids[transaction["id"]] = node_id
        _add_node(
            conn, node_id, "income", str(transaction["id"]),
            transaction["label"] or "deposit", date_value=transaction["date"],
            amount_cents=transaction["amount_cents"], account_alias=transaction["account_alias"],
            category=transaction["category"], group_name=transaction["group_name"],
        )
        account_id = account_ids.get(transaction["account_alias"])
        if account_id:
            _add_edge(conn, node_id, account_id, "funds",
                      amount_cents=transaction["amount_cents"], date_value=transaction["date"],
                      transaction_id=transaction["id"])

    transfer_pairs = set()
    for transaction in transactions:
        kind = transaction["kind"]
        if kind == "transfer_out":
            source_alias, target_alias = transaction["account_alias"], transaction["counterparty"]
        elif kind == "transfer_in":
            source_alias, target_alias = transaction["counterparty"], transaction["account_alias"]
        else:
            continue
        source_id, target_id = account_ids.get(source_alias), account_ids.get(target_alias)
        if not source_id or not target_id:
            continue
        pair = (transaction["date"], source_alias, target_alias, abs(transaction["amount_cents"]))
        if pair in transfer_pairs:
            continue
        transfer_pairs.add(pair)
        _add_edge(conn, source_id, target_id, "transfers",
                  amount_cents=abs(transaction["amount_cents"]), date_value=transaction["date"],
                  transaction_id=transaction["id"])

    for transaction in transactions:
        if transaction["kind"] not in ("purchase", "withdrawal") or transaction["amount_cents"] >= 0:
            continue
        account_id = account_ids.get(transaction["account_alias"])
        if not account_id:
            continue
        obligation_id = obligation_ids.get(transaction["obligation_alias"])
        if obligation_id:
            _add_edge(conn, account_id, obligation_id, "pays",
                      amount_cents=-transaction["amount_cents"], date_value=transaction["date"],
                      transaction_id=transaction["id"])
        category_id = f"category:{transaction['category']}" if transaction["category"] else None
        if category_id:
            _add_edge(conn, account_id, category_id, "pays",
                      amount_cents=-transaction["amount_cents"], date_value=transaction["date"],
                      transaction_id=transaction["id"])

    bill_instances = _due_instances(obligations, transactions)
    deposits = [row for row in transactions if row["kind"] == "deposit" and row["amount_cents"] > 0]
    for deposit in deposits:
        available_cents = int(deposit["amount_cents"])
        for bill in bill_instances:
            if available_cents <= 0:
                break
            if bill["account_alias"] != deposit["account_alias"] or bill["remaining_cents"] <= 0:
                continue
            allocation = min(available_cents, bill["remaining_cents"])
            if allocation <= 0:
                continue
            _add_edge(
                conn, income_ids[deposit["id"]], obligation_ids[bill["obligation_alias"]], "pays",
                amount_cents=allocation, date_value=deposit["date"],
                due_date=bill["due_date"].isoformat(), transaction_id=deposit["id"], tag="simulated",
            )
            available_cents -= allocation
            bill["remaining_cents"] -= allocation

    return {
        "graph_nodes": conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()[0],
        "graph_edges": conn.execute("SELECT COUNT(*) FROM graph_edges").fetchone()[0],
    }

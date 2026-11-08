"""Two SQLite files, on purpose:

* work db    (SQLITE_PATH)     anonymized data the engines and agents read.
                               Only aliases (acct_A, merch_3, bill_2) and amounts.
* private db (PRIVATE_DB_PATH) level-0 lookup: alias <-> real name. Never exported,
                               logged or sent to a model.

Schemas are created on first use. There are no migrations: during development,
delete the .db files and re-run scripts/load_customer.py.
WAL mode lets the API read while a load is writing.
"""

import sqlite3
from contextlib import contextmanager

from .config import settings
from .engine_firewall.graph_tables import GRAPH_SCHEMA, rebuild_graph

WORK_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    alias TEXT PRIMARY KEY, type TEXT, balance_cents INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS merchants (
    alias TEXT PRIMARY KEY, category TEXT, group_name TEXT);
CREATE TABLE IF NOT EXISTS obligations (
    alias TEXT PRIMARY KEY, kind TEXT, account_alias TEXT, category TEXT, group_name TEXT,
    amount_cents INTEGER, due_day INTEGER, status TEXT);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_alias TEXT NOT NULL, date TEXT NOT NULL,
    kind TEXT NOT NULL,            -- deposit | purchase | withdrawal | transfer_in | transfer_out
    amount_cents INTEGER NOT NULL, -- signed: inflow > 0, outflow < 0
    category TEXT, group_name TEXT, counterparty TEXT,
    obligation_alias TEXT, days_late INTEGER, label TEXT);
CREATE INDEX IF NOT EXISTS idx_txn_acct_date ON transactions (account_alias, date);
CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
    from_alias TEXT, to_alias TEXT, percent REAL, amount_cents INTEGER,
    status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, undone_at TEXT);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS overall_fin_health (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    overallFinHealth REAL,
    status TEXT NOT NULL,
    report_json TEXT NOT NULL,
    updated_at TEXT NOT NULL);
""" + GRAPH_SCHEMA

PRIVATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS alias_map (
    alias TEXT PRIMARY KEY, kind TEXT NOT NULL, real_id TEXT NOT NULL UNIQUE, real_name TEXT);
"""


@contextmanager
def _open(path, schema):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(schema)
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def work_db():
    return _open(settings.sqlite_file, WORK_SCHEMA)


def private_db():
    return _open(settings.private_file, PRIVATE_SCHEMA)


def reset_demo_state() -> None:
    """Forget accepted rules (part of resetting the demo)."""
    with work_db() as w:
        w.execute("DELETE FROM rules")

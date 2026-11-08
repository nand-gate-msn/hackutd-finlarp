"""Accept / Undo. The agent proposes in aliases and percentages; a button click
saves the rule here. The rule lives in SQLite and the forecast engine applies it
going forward, so nothing is written into the transaction history."""

import statistics
from datetime import datetime, timezone

from .db import work_db

MAX_PERCENT = 30.0


class ActionError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _typical_paycheck_cents(w, account_alias: str) -> int:
    rows = w.execute("SELECT amount_cents FROM transactions WHERE account_alias=? AND label='paycheck' "
                     "ORDER BY date DESC LIMIT 6", (account_alias,)).fetchall()
    if not rows:
        raise ActionError(f"No paychecks found on {account_alias}; can't size a percentage of income.")
    return int(statistics.median(r["amount_cents"] for r in rows))


def accept_savings_transfer(from_alias: str, to_alias: str, percent: float) -> dict:
    if not 0 < percent <= MAX_PERCENT:
        raise ActionError(f"percent must be above 0 and at most {MAX_PERCENT:g}")
    if from_alias == to_alias:
        raise ActionError("from_alias and to_alias must differ")
    with work_db() as w:
        accts = {r["alias"]: r for r in w.execute("SELECT * FROM accounts")}
        if from_alias not in accts or to_alias not in accts:
            raise ActionError("Unknown account alias")
        if accts[to_alias]["type"] != "Savings":
            raise ActionError("Destination must be a savings account")
        amount = round(_typical_paycheck_cents(w, from_alias) * percent / 100)
        if amount <= 0 or amount > accts[from_alias]["balance_cents"]:
            raise ActionError("Not enough balance for this transfer")
        cur = w.execute("INSERT INTO rules (kind, from_alias, to_alias, percent, amount_cents, status, "
                        "created_at) VALUES ('savings_transfer',?,?,?,?, 'active', ?)",
                        (from_alias, to_alias, percent, amount, _now()))
        return {"rule_id": cur.lastrowid, "amount": amount / 100}


def revert_to(rule_id: int | None) -> dict:
    """Rewind to a checkpoint: keep `rule_id` and everything accepted before it, undo everything accepted after.

    `rule_id=None` rewinds to the start (no accepted changes at all). Like rewinding a chat: the order is the
    order the changes were accepted in (rule ids only ever grow), so "later" is unambiguous.
    """
    with work_db() as w:
        if rule_id is not None:
            rule = w.execute("SELECT status FROM rules WHERE id=?", (rule_id,)).fetchone()
            if not rule:
                raise ActionError("Change not found", 404)
            if rule["status"] != "active":
                raise ActionError("That change is no longer active, so it can't be a checkpoint", 409)
        later = [r["id"] for r in w.execute(
            "SELECT id FROM rules WHERE status='active' AND id > ? ORDER BY id DESC", (rule_id or 0,))]
        now = _now()
        w.executemany("UPDATE rules SET status='undone', undone_at=? WHERE id=?", [(now, i) for i in later])
    return {"reverted": later, "kept_through": rule_id}


def undo_rule(rule_id: int) -> dict:
    with work_db() as w:
        rule = w.execute("SELECT status FROM rules WHERE id=?", (rule_id,)).fetchone()
        if not rule:
            raise ActionError("Rule not found", 404)
        if rule["status"] != "active":
            raise ActionError("Rule was already undone", 409)
        w.execute("UPDATE rules SET status='undone', undone_at=? WHERE id=?", (_now(), rule_id))
    return {"rule_id": rule_id, "status": "undone"}

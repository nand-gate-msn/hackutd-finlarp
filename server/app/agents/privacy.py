"""Scrub the customer's own typed words before the Planner (the only agent that reads them).

Everything else the models see is built from a FactPack. The typed request is free text, so it is the
one door a real name could slip through: "move money out of Everyday Checking at Oakwood Apartments".
Known private names and IDs are replaced here, plus anything shaped like an account number or email.
"""

from __future__ import annotations

import re

from ..db import private_db

REDACTED = "[redacted]"
_LONG_NUMBER = re.compile(r"\b\d[\d -]{6,}\d\b")  # account / card / phone style digit runs
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def private_terms() -> list[str]:
    with private_db() as p:
        rows = p.execute("SELECT real_id, real_name FROM alias_map").fetchall()
    terms = {t.strip() for r in rows for t in (r["real_id"], r["real_name"]) if t and len(t.strip()) >= 4}
    return sorted(terms, key=len, reverse=True)  # longest first, so "Rainy Day Savings" beats "Savings"


def scrub_request(text: str) -> str:
    for term in private_terms():
        text = re.sub(re.escape(term), REDACTED, text, flags=re.IGNORECASE)
    text = _EMAIL.sub(REDACTED, text)
    return _LONG_NUMBER.sub(REDACTED, text)

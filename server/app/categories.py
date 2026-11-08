"""Spending categories: merchant category first, then a small keyword table.
Each category rolls up into a group used by the graph and metrics."""

import re

GROUP_BY_CATEGORY = {
    "housing": "Housing", "rent": "Housing", "utilities": "Housing", "internet": "Housing",
    "groceries": "Food", "grocery": "Food", "dining": "Food", "restaurant": "Food", "coffee": "Food",
    "gas": "Transport", "fuel": "Transport", "transit": "Transport", "auto": "Transport",
    "car insurance": "Transport",
    "subscriptions": "Discretionary", "streaming": "Discretionary", "shopping": "Discretionary",
    "entertainment": "Discretionary",
    "loan": "Debt",
    "healthcare": "Health", "insurance": "Health",
    "other": "Other", "uncategorized": "Other",
}

# Order matters: first match wins.
KEYWORDS = [
    (re.compile(r"car insurance|auto insurance", re.I), "car insurance"),
    (re.compile(r"apartment|landlord|\brent\b|property|leasing|realty", re.I), "housing"),
    (re.compile(r"electric|energy|water|utilit|internet|broadband|fiber|wireless", re.I), "utilities"),
    (re.compile(r"insurance", re.I), "insurance"),
    (re.compile(r"loan|servicing|mortgage|lending", re.I), "loan"),
    (re.compile(r"stream|subscription|cloud|music|fitness|gym", re.I), "subscriptions"),
    (re.compile(r"grocer|market|supermarket", re.I), "groceries"),
    (re.compile(r"cafe|coffee|restaurant|diner|pizza|grill|kitchen|eats", re.I), "dining"),
]


def categorize(text: str = "", merchant_category: str | None = None) -> tuple[str, str]:
    """Return (category, group)."""
    if merchant_category:
        c = merchant_category.strip().lower()
        if c in GROUP_BY_CATEGORY:
            return c, GROUP_BY_CATEGORY[c]
    for pattern, category in KEYWORDS:
        if pattern.search(text or ""):
            return category, GROUP_BY_CATEGORY[category]
    return (merchant_category or "uncategorized").strip().lower(), "Other"

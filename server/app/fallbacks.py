"""Canned answers used when a model call fails, so the screen is never blank.

They contain no numbers of their own: the Explainer fallback uses the same {slots} the real
Explainer does, which the server fills from the FactPack. Shapes match what each agent returns.
"""

DISCLAIMER = "This is an educational estimate, not financial advice."

PLANNER = {"kind": "none", "payment_ratio_of_income": 0.0, "term_months": 0}  # = no what-if, just the baseline

EXPLAINER = {
    "summary": (
        "Over the next {horizon_days}, about {share_below_zero} of simulated outcomes "
        "drop below zero. Housing takes about {housing_share} of your spending. "
        + DISCLAIMER
    ),
    "used_fallback": True,
}

ACTION = {"proposals": []}  # no suggestion is better than an unchecked one

CRITIC = {"ok": True, "issues": []}  # AI check unavailable: the code checks already passed


def canned_summary(slots: dict[str, str]) -> str:
    """The canned explanation, extended with whichever health slots the pack has."""
    parts = [
        "Over the next {horizon_days}, about {share_below_zero} of simulated outcomes drop below zero."
    ]
    if "health_now" in slots:
        parts.append("Your overall financial health score is {health_now} out of 100 ({health_status}).")
    if "health_after" in slots:
        parts.append("With this decision it would be {health_after}, which is {health_change}.")
    if "housing_share" in slots:
        parts.append("Housing takes about {housing_share} of your spending.")
    parts.append(DISCLAIMER)
    return " ".join(parts)

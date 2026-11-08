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

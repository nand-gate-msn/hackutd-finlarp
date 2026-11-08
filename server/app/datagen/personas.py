"""A persona is the ground truth: the paycheck, rent, bills and spending habits
we *choose*. The generator turns it into a history; tests check the app
recovers these same numbers from the data."""

from dataclasses import dataclass

DEMO_LAST_NAME = "Copilot-Demo"  # marks customers created by our generator
CHECKING, SAVINGS = "checking", "savings"
ACCOUNT_SPECS = {
    CHECKING: ("Checking", "Everyday Checking"),
    SAVINGS: ("Savings", "Rainy Day Savings"),
}


@dataclass(frozen=True)
class IncomeStream:
    description: str
    kind: str = "fixed"  # "fixed" (regular paycheck) | "gig" (irregular deposits)
    amount: float = 0.0  # fixed: net pay per paycheck
    every_days: int = 14
    weekday: int = 4  # Mon=0 .. Fri=4
    noise_sd: float = 0.0  # fraction of amount
    late_prob: float = 0.0
    max_late_days: int = 3
    skip_prob: float = 0.0
    raise_pct: float = 0.0
    raise_after_months: int = 12
    per_month: float = 0.0  # gig: average deposits per month
    median: float = 0.0
    sigma: float = 0.5


@dataclass(frozen=True)
class Obligation:
    key: str
    payee: str
    category: str  # expected category (ground truth for the categorizer)
    amount: float
    due_day: int
    kind: str = "bill"  # "bill" | "loan"
    amount_sd: float = 0.0  # utilities vary; rent doesn't
    late_prob: float = 0.0
    max_late_days: int = 3
    loan_type: str = ""
    principal: float = 0.0


@dataclass(frozen=True)
class SpendCategory:
    name: str  # also the merchant category (drives spending groups)
    merchants: tuple[str, ...]
    trips_per_week: float
    median: float
    sigma: float = 0.5  # lognormal spread: most trips small, a few big
    weekday_weights: tuple[float, ...] = (1, 1, 1, 1, 1, 1, 1)  # Mon..Sun
    payday_boost: float = 1.0  # multiplier for the 2 days after a paycheck


@dataclass(frozen=True)
class OneOff:
    name: str
    category: str
    merchants: tuple[str, ...]
    per_year: float
    low: float
    high: float


@dataclass(frozen=True)
class Persona:
    key: str
    first_name: str
    opening_checking: float
    opening_savings: float
    incomes: tuple[IncomeStream, ...]
    obligations: tuple[Obligation, ...]
    spending: tuple[SpendCategory, ...]
    one_offs: tuple[OneOff, ...] = ()
    savings_transfer: float = 0.0  # monthly, checking -> savings
    savings_day: int = 3
    savings_buffer: float = 400.0  # skip the transfer if checking would drop below this
    savings_apr: float = 0.03
    last_name: str = DEMO_LAST_NAME


_GROCERY_W = (0.8, 0.7, 0.8, 0.9, 1.1, 1.8, 1.5)
_DINING_W = (0.5, 0.6, 0.7, 0.8, 1.6, 1.9, 1.4)
_GAS_W = (1.0, 0.8, 0.8, 0.9, 1.4, 1.2, 0.9)
_SHOP_W = (0.6, 0.6, 0.7, 0.8, 1.2, 1.9, 1.6)
_FUN_W = (0.3, 0.3, 0.4, 0.6, 1.5, 2.2, 1.4)


def _spending(scale: float = 1.0) -> tuple[SpendCategory, ...]:
    return (
        SpendCategory("groceries", ("Fresh Basket Grocers", "Corner Market Foods", "Greenfield Supermarket"),
                      2.2 * scale, 62, 0.45, _GROCERY_W, 1.3),
        SpendCategory("dining", ("Maple Street Cafe", "Blue Door Kitchen", "Tony's Pizza Grill", "Daily Grind Coffee"),
                      2.0 * scale, 24, 0.5, _DINING_W, 1.2),
        SpendCategory("gas", ("Northway Fuel", "Quick Stop Gas"), 1.0, 41, 0.25, _GAS_W),
        SpendCategory("shopping", ("Homestead Goods", "Urban Threads", "Everything Depot"),
                      1.2 * scale, 38, 0.8, _SHOP_W, 1.2),
        SpendCategory("entertainment", ("Starlight Cinemas", "Pinball Palace"), 0.5 * scale, 30, 0.5, _FUN_W),
    )


_ONE_OFFS = (
    OneOff("car repair", "auto", ("Reliable Auto Works",), 2, 150, 600),
    OneOff("medical", "healthcare", ("Riverside Clinic", "CareFirst Pharmacy"), 3, 40, 220),
    OneOff("gift", "shopping", ("Homestead Goods", "Urban Threads"), 3, 30, 120),
)

PERSONAS: dict[str, Persona] = {
    # Tight budget: thin margin, occasional late bill, some overdraft risk.
    "alex": Persona(
        key="alex", first_name="Alex", opening_checking=1400, opening_savings=3000,
        incomes=(IncomeStream("Paycheck - Brightwave Inc", amount=1650, noise_sd=0.0,
                              late_prob=0.05, raise_pct=0.04, raise_after_months=12),),
        obligations=(
            Obligation("rent", "Oakwood Apartments", "housing", 1150, 1, late_prob=0.05),
            Obligation("electric", "Lone Star Electric", "utilities", 92, 14, amount_sd=0.15),
            Obligation("internet", "FiberNet Internet", "utilities", 60, 18),
            Obligation("car_ins", "SafeDrive Car Insurance", "car insurance", 138, 22),
            Obligation("streaming", "Streamly Plus Subscription", "subscriptions", 15.99, 5),
            Obligation("cloud", "CloudBox Storage Subscription", "subscriptions", 2.99, 9),
            Obligation("gym", "Pulse Fitness Gym", "subscriptions", 29.0, 3),
            Obligation("student_loan", "Granite Student Loan Servicing", "loan", 215, 25,
                       kind="loan", late_prob=0.03, loan_type="student", principal=14500),
        ),
        spending=_spending(1.2), one_offs=_ONE_OFFS,
        savings_transfer=250, savings_buffer=450,
    ),
    # Comfortable saver: stable pay, big monthly transfer to savings.
    "jordan": Persona(
        key="jordan", first_name="Jordan", opening_checking=4200, opening_savings=9000,
        incomes=(IncomeStream("Paycheck - Northlake Health", amount=2450, noise_sd=0.0, raise_pct=0.03),),
        obligations=(
            Obligation("rent", "Cedar Ridge Apartments", "housing", 1450, 1),
            Obligation("electric", "Lone Star Electric", "utilities", 105, 12, amount_sd=0.12),
            Obligation("internet", "FiberNet Internet", "utilities", 65, 16),
            Obligation("car_ins", "SafeDrive Car Insurance", "car insurance", 120, 20),
            Obligation("streaming", "Streamly Plus Subscription", "subscriptions", 15.99, 6),
        ),
        spending=_spending(0.8), one_offs=_ONE_OFFS,
        savings_transfer=2200, savings_buffer=4000, savings_apr=0.04,
    ),
    # Irregular gig income: lumpy deposits, a late rent now and then.
    "sam": Persona(
        key="sam", first_name="Sam", opening_checking=900, opening_savings=1200,
        incomes=(IncomeStream("Gig payout - RideLoop", kind="gig", per_month=8, median=300, sigma=0.55),),
        obligations=(
            Obligation("rent", "Willow Court Apartments", "housing", 950, 1, late_prob=0.15, max_late_days=5),
            Obligation("electric", "Lone Star Electric", "utilities", 70, 15, amount_sd=0.2),
            Obligation("phone", "Skyline Wireless", "utilities", 45, 21),
            Obligation("streaming", "Streamly Plus Subscription", "subscriptions", 15.99, 8),
        ),
        spending=_spending(0.8), one_offs=_ONE_OFFS,
        savings_transfer=100, savings_buffer=500,
    ),
}

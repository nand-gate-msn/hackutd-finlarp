"""Deterministic history generator.

generate(persona, seed, months, end) is a pure function: the same inputs give
the same events. A seeded PRNG (random.Random) adds the realistic wobble around
the patterns the persona defines. All money is integer cents, so the balance
identity (opening + in - out = closing) holds exactly, by construction.
"""

import calendar
import math
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from .personas import CHECKING, SAVINGS, Persona

DAYS_PER_MONTH = 30.4375


@dataclass(frozen=True)
class Event:
    date: date
    account: str  # "checking" | "savings"
    kind: str  # deposit | purchase | withdrawal | transfer
    amount_cents: int  # always positive
    description: str
    category: str = ""
    merchant: str = ""
    to_account: str = ""  # transfers only
    obligation: str = ""  # bill/loan key for obligation payments
    due_date: date | None = None


@dataclass
class History:
    persona: Persona
    seed: int
    months: int
    start: date
    end: date
    events: list[Event]
    opening_cents: dict[str, int]
    final_cents: dict[str, int]
    merchants: dict[str, str]  # merchant name -> category
    ground_truth: dict = field(default_factory=dict)


def cents(x: float) -> int:
    return int(round(x * 100))


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def _clamp(x: float, sd: float) -> float:
    return max(-3 * sd, min(3 * sd, x))


def signed_effect(e: Event, account: str) -> int:
    """How an event changes one account's balance, in cents."""
    if e.kind == "deposit":
        return e.amount_cents if e.account == account else 0
    if e.kind in ("purchase", "withdrawal"):
        return -e.amount_cents if e.account == account else 0
    if e.kind == "transfer":
        if e.account == account:
            return -e.amount_cents
        if e.to_account == account:
            return e.amount_cents
    return 0


def generate(persona: Persona, seed: int = 42, months: int = 24, end: date | None = None) -> History:
    end = end or date.today()
    start = end - timedelta(days=round(months * DAYS_PER_MONTH))
    rng = random.Random(seed)
    raw: list[Event] = []
    paydays: set[date] = set()
    skipped_paychecks = 0

    # --- income -----------------------------------------------------------
    for s in persona.incomes:
        raise_date = start + timedelta(days=round(s.raise_after_months * DAYS_PER_MONTH))
        if s.kind == "fixed":
            d = start + timedelta(days=(s.weekday - start.weekday()) % 7)
            while d <= end:
                # Always draw, so the random stream doesn't depend on which branch runs.
                skip = rng.random() < s.skip_prob
                noise = _clamp(rng.gauss(0, s.noise_sd), s.noise_sd)
                late = rng.random() < s.late_prob
                delay = rng.randint(1, max(1, s.max_late_days))
                if skip:
                    skipped_paychecks += 1
                else:
                    amount = s.amount * (1 + noise) * (1 + (s.raise_pct if d >= raise_date else 0))
                    paid = d + timedelta(days=delay if late else 0)
                    if paid <= end:
                        raw.append(Event(paid, CHECKING, "deposit", cents(amount), s.description, "income"))
                        paydays.add(paid)
                d += timedelta(days=s.every_days)
        else:  # gig
            d = start
            while d <= end:
                for _ in range(_poisson(rng, s.per_month / DAYS_PER_MONTH)):
                    amount = rng.lognormvariate(math.log(s.median), s.sigma)
                    raw.append(Event(d, CHECKING, "deposit", cents(amount), s.description, "income"))
                d += timedelta(days=1)

    # --- obligations (bills and loan payments) -------------------------------
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        last = calendar.monthrange(y, m)[1]
        for o in persona.obligations:
            due = date(y, m, min(o.due_day, last))
            late = rng.random() < o.late_prob
            delay = rng.randint(1, max(1, o.max_late_days))
            noise = _clamp(rng.gauss(0, o.amount_sd), o.amount_sd)
            if due < start or due > end:
                continue
            paid = due + timedelta(days=delay) if late else due
            if paid <= end:
                raw.append(Event(paid, CHECKING, "withdrawal", cents(o.amount * (1 + noise)), o.payee,
                                 o.category, obligation=o.key, due_date=due))
        m += 1
        if m > 12:
            y, m = y + 1, 1

    # --- variable spending and one-off expenses -------------------------------
    merchants: dict[str, str] = {}
    d = start
    while d <= end:
        recent_payday = d in paydays or (d - timedelta(days=1)) in paydays
        for c in persona.spending:
            w = c.weekday_weights[d.weekday()] / (sum(c.weekday_weights) / 7)
            boost = c.payday_boost if recent_payday else 1.0
            for _ in range(_poisson(rng, c.trips_per_week / 7 * w * boost)):
                amount = rng.lognormvariate(math.log(c.median), c.sigma)
                merchant = rng.choice(c.merchants)
                merchants[merchant] = c.name
                raw.append(Event(d, CHECKING, "purchase", max(100, cents(amount)), merchant, c.name, merchant))
        for o in persona.one_offs:
            if rng.random() < o.per_year / 365:
                amount = rng.uniform(o.low, o.high)
                merchant = rng.choice(o.merchants)
                merchants[merchant] = o.category
                raw.append(Event(d, CHECKING, "purchase", cents(amount), merchant, o.category, merchant))
        d += timedelta(days=1)

    # --- walk the calendar: savings transfers depend on the running balance ---
    by_day: dict[date, list[Event]] = defaultdict(list)
    for e in raw:
        by_day[e.date].append(e)

    opening = {CHECKING: cents(persona.opening_checking), SAVINGS: cents(persona.opening_savings)}
    bal = dict(opening)
    events: list[Event] = []
    skipped_transfers = 0
    min_checking, days_below_zero = bal[CHECKING], 0

    def apply(e: Event) -> None:
        for acct in bal:
            bal[acct] += signed_effect(e, acct)
        events.append(e)

    d = start
    while d <= end:
        last_day = calendar.monthrange(d.year, d.month)[1]
        for e in by_day.get(d, []):
            apply(e)
        if persona.savings_transfer > 0 and d.day == min(persona.savings_day, last_day):
            amt = cents(persona.savings_transfer)
            if bal[CHECKING] - amt >= cents(persona.savings_buffer):
                apply(Event(d, CHECKING, "transfer", amt, "Transfer to savings", "savings", to_account=SAVINGS))
            else:
                skipped_transfers += 1
        if persona.savings_apr > 0 and d.day == last_day:
            interest = cents(bal[SAVINGS] / 100 * persona.savings_apr / 12)
            if interest > 0:
                apply(Event(d, SAVINGS, "deposit", interest, "Interest", "interest"))
        min_checking = min(min_checking, bal[CHECKING])
        days_below_zero += bal[CHECKING] < 0
        d += timedelta(days=1)

    history = History(persona, seed, months, start, end, events, opening, dict(bal), merchants)
    history.ground_truth = _ground_truth(history, skipped_paychecks, skipped_transfers,
                                         min_checking, days_below_zero)
    return history


def _ground_truth(h: History, skipped_paychecks: int, skipped_transfers: int,
                  min_checking: int, days_below_zero: int) -> dict:
    p = h.persona
    paychecks = [e for e in h.events if e.kind == "deposit" and e.category == "income"]
    span_months = max(1, (h.end - h.start).days / DAYS_PER_MONTH)
    obligations = []
    for o in p.obligations:
        pays = [e for e in h.events if e.obligation == o.key]
        obligations.append({
            "key": o.key, "payee": o.payee, "kind": o.kind, "category": o.category,
            "amount": o.amount, "due_day": o.due_day, "payments": len(pays),
            "late_payments": sum(1 for e in pays if e.date > e.due_date),
        })
    spending = {}
    for c in {e.category for e in h.events if e.kind == "purchase"}:
        total = sum(e.amount_cents for e in h.events if e.kind == "purchase" and e.category == c)
        spending[c] = {"total": total / 100, "mean_weekly": round(total / 100 / (span_months * 4.345), 2)}
    return {
        "persona": p.key, "seed": h.seed, "months": h.months,
        "start": h.start.isoformat(), "end": h.end.isoformat(),
        "opening": {k: v / 100 for k, v in h.opening_cents.items()},
        "final": {k: v / 100 for k, v in h.final_cents.items()},
        "income": {
            "count": len(paychecks),
            "mean_amount": round(statistics.mean(e.amount_cents for e in paychecks) / 100, 2) if paychecks else 0,
            "monthly_mean": round(sum(e.amount_cents for e in paychecks) / 100 / span_months, 2),
            "skipped_paychecks": skipped_paychecks,
        },
        "obligations": obligations,
        "spending_by_category": spending,
        "skipped_savings_transfers": skipped_transfers,
        "min_checking_balance": min_checking / 100,
        "days_below_zero": days_below_zero,
        "event_counts": {k: sum(1 for e in h.events if e.kind == k)
                         for k in ("deposit", "purchase", "withdrawal", "transfer")},
    }

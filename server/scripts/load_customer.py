"""Load the demo customer into SQLite from the fixed-seed generator. Run from server/:

    python scripts/load_customer.py --dry-run     # generate + summarize, change nothing
    python scripts/load_customer.py               # load (replaces the previous customer)
    python scripts/load_customer.py --persona sam --months 18 --seed 7

Also rewrites data/ground_truth.json (the answers the engine should recover) and
clears accepted rules, so it doubles as the "reset the demo" command.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import SERVER_DIR, settings  # noqa: E402
from app.datagen import PERSONAS, generate  # noqa: E402
from app.db import reset_demo_state  # noqa: E402
from app.ingest import load_history  # noqa: E402


def summarize(h) -> None:
    gt = h.ground_truth
    print(f"persona={h.persona.key} seed={h.seed} {gt['start']} -> {gt['end']} ({h.months} months)")
    print("events:", gt["event_counts"])
    print(f"income: {gt['income']['count']} paychecks, mean ${gt['income']['mean_amount']:,.2f}, "
          f"${gt['income']['monthly_mean']:,.2f}/mo, {gt['income']['skipped_paychecks']} skipped")
    for o in gt["obligations"]:
        print(f"  {o['payee']:<34} ${o['amount']:>8,.2f} on day {o['due_day']:<2} "
              f"{o['payments']} paid, {o['late_payments']} late")
    print(f"opening {gt['opening']}  ->  final {gt['final']}")
    print(f"checking min ${gt['min_checking_balance']:,.2f}, {gt['days_below_zero']} days below zero, "
          f"{gt['skipped_savings_transfers']} savings transfers skipped")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--persona", default=settings.demo_persona, choices=sorted(PERSONAS))
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--seed", type=int, default=settings.random_seed)
    ap.add_argument("--end", type=date.fromisoformat, default=None, help="last day of history (default DEMO_END_DATE, else today)")
    ap.add_argument("--dry-run", action="store_true", help="summarize only; write nothing")
    args = ap.parse_args()

    end = args.end or (date.fromisoformat(settings.demo_end_date) if settings.demo_end_date else None)
    h = generate(PERSONAS[args.persona], seed=args.seed, months=args.months, end=end)
    summarize(h)
    if args.dry_run:
        return 0
    gt_path = SERVER_DIR / "data" / "ground_truth.json"
    gt_path.parent.mkdir(exist_ok=True)
    gt_path.write_text(json.dumps(h.ground_truth, indent=2))
    reset_demo_state()
    summary = load_history(h)
    print(f"wrote {gt_path.relative_to(SERVER_DIR)}")
    print("loaded into SQLite:", summary)
    return 0


sys.exit(main())

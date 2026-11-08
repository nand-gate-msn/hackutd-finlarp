# FinLARP layout refinement

- Renamed the header and browser title to FinLARP. The balance leads the summary with an accent-tinted surface and larger numeral; provenance and privacy details are available without occupying the headline.
- The desktop copilot takes its natural content height and grows up to the viewport when needed. Drag the left edge to resize it from 320 to 640px, subject to available space. The separator supports arrow keys, Home, End and double-click reset. The existing mobile sheet remains available.
- Financial health now separates the overall score, four pillars, and cash-flow summary. Secondary measurements expand under “Explore health indicators.”
- Accounts use independent, full-width sections with balance allocation, transfer activity, explicit table columns, and bills ordered by next due date. A quiet savings account remains compact rather than inheriting the checking account's height.
- Copilot suggestions are previews. Saving requires “Review change” followed by “Confirm & save change.” Requests are protected against double submission. Older saved rules are explicitly identified as existing changes; they are not erased on a new question. This does not initiate bank transfers.

Verification passed:

- Build and lint, with the same two existing graph effect warnings.
- 632 contrast pairs in both themes; no palette changes were required.
- Light/dark at 1440, 1280 and 390px: no page overflow, natural savings-card height, desktop pointer/keyboard resizing, accessible indicator expansion.
- Browser request assertions: asking, previewing, opening review, cancelling, reloading and asking again never send an acceptance request. Explicit confirmation sends exactly one. Browser acceptance responses were mocked to avoid mutating local saved rules.
- Mobile review Escape leaves the copilot sheet open; failed saves can be cancelled and retried; the half-height footer stays visible. Preference material fallbacks remain solid.
- 24 existing API tests passed. Three new regression cases verify that advice preserves both the overview and saved rules, including no existing rule and existing matching/nonmatching rules. Test databases are isolated.
- Existing graph edge-drag, pan momentum, pinch and reduced-motion checks were rerun after scrolling the target into view in the taller layout.

Screenshots are named by theme, width and section in this folder. Reproduce with Vite at port 5173 and the existing local API:

```sh
NODE_PATH=/private/tmp/finlarp-qa/node_modules node docs/ui-overhaul/refinement/verify-layout.cjs
NODE_PATH=/private/tmp/finlarp-qa/node_modules node docs/ui-overhaul/refinement/verify-mobile.cjs
cd server
.venv/bin/python -m pytest tests/test_api_advise.py -q
```

The scripts use the offline advice fixture from the parent QA instructions, with `FINLARP_QA_ADVICE` available to override its path. No runtime dependency was added. Existing unrelated server edits and the Advisor guard notice were preserved.

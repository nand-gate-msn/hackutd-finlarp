# UI overhaul verification

Completed in the audit's nine-commit order. Runtime styles remain in `client/src/index.css` and `client/src/App.css`; the design reference stylesheets are not imported. No runtime dependency was added.

| Step | Commit | Change |
| --- | --- | --- |
| 1 | `76bf07d` | Root type and layout tokens, self-hosted latin Inter Variable, metric-adjusted fallback, preload |
| 2 | `a56a7f3` | Type scale, heading hierarchy, SVG and canvas font |
| 3 | `0cc7054` | Tabular numerals, wrapping, measure, titles, punctuation |
| 4 | `92ef999` | Reconciled palette, text contrast, 12px CSS type floor |
| 5 | `1b7738e` | Press states, preference foundations, transform bars, spring helper |
| 6 | `5ada21b` | Retained enter/exit states for dialogs, panels and notices |
| 7 | `7b5b2aa` | Glass chrome, static ambient layer, spring segmented thumb |
| 8 | `7647931` | Grab offsets, spring zoom/fit, bounded momentum, two-pointer pinch |
| 9 | `ui: mobile copilot bottom sheet` | Mobile sheet, snap points, velocity handoff, keyboard/focus handling; final spacing and preference QA |

## Overrides applied

- The reference blue and accent-subtle colors were replaced in `design/DESIGN.md`, its contrast appendix and `design/tokens.css`, as well as the runtime tokens. Light accent `#3668b8` with white labels: **5.484:1**. Dark accent `#6794dc` with `#0e0f11` labels: **6.252:1**. The remaining design palette is retained; primary figures are neutral and status tones are confined to data, words and badges.
- Self-hosted Inter replaces the design system's system-only font rule. The audit's sizes, leading, tracking, headings and tabular numerals supersede the design reference type classes. The system mono stack is retained.
- The audit's text-only caution token is `#8a5a00` in light and `#facc15` in dark. Its proposed light warning text `#b45309` failed on track (4.166:1), accent-subtle (4.298:1) and warning-subtle (4.329:1). It was adjusted to **`#a14a08`**. Warning fills and borders retain the design system's warning color. Dark warning text is `#fb923c`.
- Glass extends beyond the design system's drawer-only material to the sidebar/sheet, segmented tray and a single shared graph toolbar. Header/footer regions share the sidebar material rather than layering another blur. Dense data, notices, flags, graph nodes and canvas remain solid. The segmented thumb is solid and slides rather than crossfading.
- Controls use light alpha **.90**, dark **.94**; text panels use **.97** in both themes. These exceed the audit's 70% proposal and original 80% material because text must pass over worst-case backdrops. Large/small blur is 20px/12px with saturation 1.6, prefixed for WebKit. Edges are inset highlights, with hairlines and elevation-2 shadows. Focus rings use a solid surface buffer so bright graph marks cannot meet the accent ring directly.
- Opening a drawer makes the segmented tray solid; opening a modal makes underlying chrome solid. At most three glass surfaces are visible, with no nested glass. Reduced transparency, more contrast, forced colors and missing-filter support fall back to a solid surface and control border. Scroll masks are also disabled in preference fallbacks.
- One static ambient layer uses accent and neutral radial fields. This is the approved exception to the reference's no-gradient rule; scroll-edge masks affect alpha only. The ambient layer disappears under reduced transparency and higher contrast.
- Glass panels/sidebar/sheet use the new 20px large radius with inner 8px/12px corners; the rest keep the design radii. Spacing uses the design's 4px tokens. Shadows never exceed elevation-2 and flagged-node glows were removed.
- Press scale is **.98**, superseding the audit's .97. The shared hand-rolled rAF spring uses response .4 and critical damping 1; only a sheet flick uses .8 damping. The audit's optional dependency/decision gate and optional mobile sheet were superseded: no dependency or additional decision was needed, and the sheet is implemented with closed, half and expanded snaps.

## Checks performed

- `npm run build && npm run lint` after each commit. Lint retains the two graph effect warnings present at baseline; no new warnings.
- `node client/scripts/check-contrast.mjs`: **632 pairs** across both themes, including button states, tone text/subtle surfaces, control borders, glass over black/white and every graph mark, and accent focus against glass. Minimum checked text ratio: **4.504:1**. All individual results are in [ui-contrast.json](../ui-contrast.json).
- Chrome at 1280px and 390px, light and dark: no horizontal overflow; visible computed text sizes at least 12px. SVG font declarations use the same floor; graph zoom scales the coordinate system as before.
- Forecast tooltip scrubbing: identical rendered width for `$1,111` and `$8,888`, tabular feature enabled. Long account aliases wrap and truncated categories expose full titles.
- Modal focus moves inside; closing and reopening mid-exit retains one dialog and retargets its current transform. Exit paths delay removal rather than dropping the subtree immediately.
- Node edge-drag preserves its offset; flick-pan continues after release and settles within bounds; pinch increases scale and can hand off to a one-finger pan. Reduced-motion zoom settles immediately.
- Sheet snaps, a footer that stays visible at half height, flick dismissal, focus/scroll release, Escape, keyboard height adjustment and reopening mid-exit pass in both themes. Reduced-motion sheet movement is immediate. Ask/Working label widths are equal. Rapid segment changes settle the spring thumb on the selected button.
- DevTools protocol emulation verified `prefers-reduced-motion`, `prefers-reduced-transparency`, `prefers-contrast: more` and `forced-colors` in both themes. Missing-backdrop-filter fallback was inspected in CSS; this Chrome supports the filter.
- No browser runtime errors. Advice was supplied using the existing offline fake-model fixture with real local financial tools, so no paid model calls or accepted-rule mutations were needed. This UI pass does not retest model/provider behavior.

## Screenshots

Dark is the default capture theme. These use matched real overview data and the same offline advice response.

| State at 1280px | Before | After |
| --- | --- | --- |
| Dashboard top | [Before](screenshots/before-dark-1280-dashboard.png) | [After](screenshots/after-dark-1280-dashboard.png) |
| Graph with selected node | [Before](screenshots/before-dark-1280-graph.png) | [After](screenshots/after-dark-1280-graph.png) |
| Modal open | [Before](screenshots/before-dark-1280-modal.png) | [After](screenshots/after-dark-1280-modal.png) |
| Copilot panel | [Before](screenshots/before-dark-1280-copilot.png) | [After](screenshots/after-dark-1280-copilot.png) |

Additional [dark mobile dashboard](screenshots/after-dark-390-dashboard.png), [dark mobile sheet](screenshots/after-dark-390-copilot.png), [light desktop](screenshots/after-light-1280-dashboard.png), [light mobile dashboard](screenshots/after-light-390-dashboard.png), and [light mobile sheet](screenshots/after-light-390-copilot.png) captures are included.

## Repeating browser QA

Use the app's Vite server at port 5173 and the unchanged baseline (`8ee3e16`) at 5174, both proxying the existing local API. Browser QA uses Playwright installed outside the client; it is not an app dependency. Chrome's executable path in the scripts is the local macOS installation.

```sh
npm install --prefix /private/tmp/finlarp-qa playwright
server/.venv/bin/python docs/ui-overhaul/make-fixture.py /private/tmp/finlarp-qa/advise.sse
NODE_PATH=/private/tmp/finlarp-qa/node_modules node docs/ui-overhaul/verify-ui.cjs
NODE_PATH=/private/tmp/finlarp-qa/node_modules node docs/ui-overhaul/verify-graph.cjs
NODE_PATH=/private/tmp/finlarp-qa/node_modules node docs/ui-overhaul/verify-controls.cjs
```

`FINLARP_QA_ADVICE` and `FINLARP_QA_OUTPUT` override the fixture/screenshot paths for the main verification script. `results.json` records its assertions. Existing user edits to Advisor's guard notice and server files were preserved outside the UI commits.

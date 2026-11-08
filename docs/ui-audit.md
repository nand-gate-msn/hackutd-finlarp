# Audit: typography + Apple-design (read-only, no files edited)

## Context and assumptions

The brief's paths, stack and known problems are template placeholders. What is actually here:

| Brief said | Reality | What I did |
| --- | --- | --- |
| `src/components`, `src/styles/globals.css` | `client/src/*.jsx` (flat), `index.css` (tokens) + `App.css` (all rules) | Audited those |
| Next.js + Tailwind + Motion | Vite 8 + React 19 + **plain CSS**. No Tailwind, no Motion (deps: react, d3-force) | Fixes expressed as plain CSS in the existing files. Adding Tailwind would be the "second styling approach" you ruled out |
| Known problems: `[e.g. sheet laggy, headings loose, nav opaque]` | Not filled in | Inferred from code: there is no sheet; closest are `Modal`, `.gdetail`/`.gflags` panels, and the sticky `.sidebar` (opaque) |

Division of labor held: typography decides every type value; apple-design never overrides one (its §15 "use system font" is superseded by your "change the brand font as needed").

Brand font: system-ui renders differently per OS (no shared optical sizing, different numeral widths). Proposal: self-hosted **Inter Variable (`.woff2`)** in `client/public/fonts/`, system-ui stack as fallback. One `--font` token, swappable.

## 1. Typography findings (Before / After)

### Format, synthesis, smoothing, root
| Before | After |
| --- | --- |
| `index.css:10` `font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif` on `:root` | `--font: 'Inter Variable', system-ui, sans-serif` + `@font-face { src: url(/fonts/InterVariable.woff2) format('woff2'); font-weight: 100 900; font-display: swap }` |
| No `font-synthesis`; weights 400/500/600/700/**800** used (`.gflag text`, `.problem-sev`, `.gflags-dot`) | `:root { font-synthesis: none }`; 800 → 700 (4 weights total) |
| No smoothing on root | `:root { -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; font-optical-sizing: auto }` |
| Same system stack hard-coded 9× in SVG text rules (`.gpill text`, `.gcard-*`, `.faxis`, `.ftip-*`, `.gflag text`, `.gtitle`) and in `GraphView.jsx:21` canvas `ctx.font` | `font-family: var(--font)` / `font: inherit`; canvas reads `getComputedStyle(...).fontFamily` so measurement matches rendering |

### Type scale (one-off sizes → tokens)
~20 distinct sizes today: `.68 .7 .72 .75 .8 .82 .85 .86 .88 .9 1.05 1.1 1.25 1.35 1.4 1.5 1.6 1.8 1.9 2.2 2.4rem` + SVG `9.5/10.5/11/11.5/12px`.

| Before | After |
| --- | --- |
| `.68rem` `.7` `.72` `.75` (`.problem-sev`, `.tl-tag`, `.accepted-label`, `.badge`, `.ghint`) | `--text-xs: .75rem` (12px, the floor) |
| `.8` `.82` `.85` `.86` `.88` `.9` (stat-label, mini-stats, bar-row, table, notice, problem-why, drivers) | `--text-sm: .8125rem` (13px) for captions/labels; `--text-ui: .875rem` (14px) for rows, tables, buttons, notices |
| `1` default body / `1.05` (modal h3, gdetail h4) | `--text-base: 1rem` / `--text-md: 1.0625rem` |
| `1.25` (h2 ×3) `1.4` `1.35` `1.5` `1.6` | `--text-lg: 1.25rem` (h2, balance) / `--text-xl: 1.5rem` (stat-value, chance b) |
| `1.8` (h1) `1.9` `2.2` `2.4` (score numerals) | `--text-2xl: 1.875rem` (h1) / `--text-3xl: 2.25rem` (score numerals, one size) |
| SVG `9.5px italic` `.gcard-note` | `12px` min (scale with the card) or drop the note |
| SVG `10.5px` `11px` `11.5px` | `12px`; 11.5px `.gcard-title` becomes 12px/600 |

### Heading hierarchy
| Before | After |
| --- | --- |
| `.card-head h3` no size → UA `1.17em`, monospace; `.modal-head h3` `1.05rem`; `.gdetail h4` `1.05rem`; `.section h4` `.8rem` | Descending map: h1 `text-2xl` > h2 `text-lg` > h3 `text-md` > h4 `text-sm` uppercase label. Card alias and modal title both `text-md`/600 |
| `.advice h4`, `.suggestions h4` unstyled (UA bold 1em) under the copilot `h2`, skipping h3 | Make them `h3` in `Advisor.jsx`/`Suggestions` markup, styled `text-md` |
| `.gdetail h5` `.72rem` uppercase | `h4`-level style token (`text-xs` uppercase, 600) |

### Line-height by role
| Before | After |
| --- | --- |
| No root `line-height` (UA ~1.2 on body copy) | `:root { line-height: 1.5 }` |
| h1/h2/h3 no line-height | `h1,h2 { line-height: 1.1 }`, `h3 { 1.2 }` |
| `1.45` `.panel-head p`, `1.4` `.notice` `.confirm p`, `1.55` `.explanation`, `1.35` `.gflag-item` | `1.5` body; `1.4` dense UI via one `--leading-ui` |
| Big numerals `.health-numbers b` `1.1`, `.gauge-text b` `1` | keep `1` (single-line display numerals) |

### Letter-spacing by size
| Before | After |
| --- | --- |
| `h1` `1.8rem`, numerals `2.2–2.4rem` no tracking | `letter-spacing: -0.02em` on h1 and `text-2xl/3xl` numerals; `-0.01em` on h2 |
| Uppercase labels `.04em` / `.05em` mixed (`.stat-label`, `.section h4`, `.accepted-label`, `.gdetail h5`, `.problem-sev`) | one `--tracking-caps: .05em` |

### Tabular numbers
Only `td.num` has it today.

| Before | After |
| --- | --- |
| `.stat-value`, `.balance`, `.bar-amt`, `.chance b`, `.flow b`, `.indicator b`, `.pill`, `.delta`, `.health-numbers b`, `.gauge-text b`, `.mini-stats`, `.drivers`, `.notice` | add `font-variant-numeric: tabular-nums` (single `.stat-value, .balance, … {}` rule) |
| SVG `.ftip-value`, `.gcard-value`, `.faxis text`, `.fzero-label` (hover tooltip values jitter while scrubbing) | `font-variant-numeric: tabular-nums` |

### Measure
| Before | After |
| --- | --- |
| `.panel-head p { max-width: 640px }` at `.9rem` ≈ 85–90 chars | `max-width: 65ch` |
| `.page-head p` no cap (full page width) | `max-width: 65ch` |

### Wrapping
| Before | After |
| --- | --- |
| No `text-wrap` anywhere | `h1,h2,h3 { text-wrap: balance }`; `.page-head p, .panel-head p, .explanation, .problem-why, .notice { text-wrap: pretty }` |
| `.badge .flag .chip .tl-tag .pill .problem-sev .see-others` can wrap | `white-space: nowrap` |
| Long alias/payee/reason strings (`.card-head h3`, `.pick-head`, `.gdetail li`, `.tl-title`) | `overflow-wrap: anywhere` (+ `min-width: 0` on flex children) |

### Truncation
| Before | After |
| --- | --- |
| `.bar-name` ellipsis (`App.jsx:50`) with no way to read the full category | add `title={name}` |
| `.accepted-latest` ellipsis | full text already in the modal timeline: keep, add `title` |
| `.gflag-item span` `-webkit-line-clamp: 3` | `line-clamp: 3` too; full text is in the detail panel: keep |

### Smart punctuation and copy
| Before | After |
| --- | --- |
| `Couldn't load…` (`App.jsx:143`, `Metrics.jsx:51`) straight apostrophe | `Couldn’t` |
| `{retries}×`, `−`, `→`, `…` | already correct, no change |
| `Last {n} days` / `next {n} days` / `{n} deposits · …` may break between number and unit | `&nbsp;` between number and unit |

### Size and contrast floors
Ratios computed from the hex values; re-check with a tool before shipping.

| Before | After |
| --- | --- |
| `--ok #ca8a04` as text on `--card` (`.flag.ok`, `.tone-ok`, `.pill.t-ok`, `.gauge-text span`) ≈ **2.9:1** | text-only token `--ok-text: #8a5a00` (≥4.5:1); keep `#ca8a04` for fills/borders |
| `--tone` warn `#ea580c` text ≈ **3.6:1**; `.tone-warn #d97706` ≈ **3.2:1** at 12–13px | `--warn-text: #b45309` (≈5:1) |
| Text under 12px: `.68rem`, `.7rem`, `.72rem`, SVG 9.5/10.5/11px | floor 12px (scale above) |
| `--muted #667085` on `--bg` ≈ 4.6:1 | passes: leave |

### Selection
| Before | After |
| --- | --- |
| Button/chip/segment labels selectable; no `::selection` | `user-select: none` on `.btn .chip .seg button .gctl button .gforecast .accepted-bar`; `::selection { background: color-mix(in srgb, var(--accent) 30%, transparent) }` |

Reviewed, no change: inputs (already `font: inherit` = 16px, no iOS zoom), underlines (no links), logical properties (LTR-only, `lang="en"`; revisit if RTL is wanted).

## 2. Apple-design findings, ranked by user-visible impact

| # | Finding | File | Principle violated | Fix |
| --- | --- | --- | --- | --- |
| 1 | Dialogs appear and vanish instantly: no enter, no exit, no origin. Backdrop blur is a token `2px` | `Modal.jsx`, `App.css:295-310` | Spatial consistency (anchor to source), "materialize, don't just fade", interruptibility | Mount with `opacity 0, scale .96, blur` → rest; `transform-origin` from the opener's rect (already captured in `opener.current`). Exit plays before unmount; reopening mid-exit retargets from the live value. CSS `@starting-style` + `transition` is enough (transitions retarget from the current value), no new dependency |
| 2 | Floating panels pop in/out on conditional render (`.gdetail`, `.gflags`, `.accepted` bar, `.notice`, `.confirm`, Advisor `Result`) | `GraphView.jsx`, `Advisor.jsx`, `AcceptedChanges.jsx` | Continuity, hint in the direction of the gesture | Same enter/exit pattern; `.gdetail` grows from the clicked node; symmetric exit path (in from right → out to right) |
| 3 | Node drag snaps the node's centre to the cursor on grab | `GraphView.jsx:330-338` (`d.node.fx = g.x`) | Direct manipulation: respect the grab offset | Store `grab = nodePos − pointerPos` at pointerdown; add it back on move |
| 4 | Pan stops dead on release; wheel zoom is unsmoothed; fit/zoom buttons jump (`setView` direct); pan can lose the graph off-canvas | `GraphView.jsx:283-362` | Velocity handoff, momentum projection, rubber-banding, interruptibility | Track last ~100 ms of pointer samples; on release project with `(v/1000)·d/(1−d)`, `d=.998`, decay by rAF from the live `view`; rubber-band past `model.bounds`; animate `fit()`/`zoomBy` as a critically damped spring (any new input retargets from the current value). Add two-pointer pinch (canvas has `touch-action:none` but no pinch) |
| 5 | Press feedback is hover-only. No `:active` state on buttons | `.btn .chip .pick .seg button .gctl button .see-others .accepted-bar .gforecast` | Response: feedback on pointer-down | `:active { transform: scale(.97); transition: transform 100ms ease-out }`; list `transition-property` explicitly, never `all` |
| 6 | Opaque chrome: `.sidebar` + `.copilot-foot`/`-head` hard borders; `.gdetail`, `.gflags`, `.gctl`, `.gforecast` are flat `--card` with generic drop shadows over the canvas | `App.css:96-163, 248-262, 349-368` | Materials & depth, scroll edge effects, size → thickness | Translucent `color-mix(in srgb, var(--card) 70%, transparent)` + `backdrop-filter: blur(20px) saturate(180%)`, bright 1px top edge; replace `.copilot-foot` border with a gradient scroll-edge mask; larger surfaces (`.gdetail`, modal) get stronger blur/shadow than chips. Never stack two translucent layers (`.gflags` vs `.gdetail` overlap risk: keep one opaque). Muted text on glass gets weight 500 |
| 7 | Only one `prefers-reduced-motion` guard (the pulse dot); no reduced-transparency or contrast handling | `App.css:201` | Reduced motion/transparency/contrast | Global block: reduced-motion → opacity cross-fades, no scale/slide, no momentum; reduced-transparency → solid `--card`, `backdrop-filter:none`; `prefers-contrast: more` → solid + visible border. Must land with #1/#2/#6, not after |
| 8 | `.bar-fill` animates `width` (layout) with default easing; gauge arc (`.g-fill`) jumps | `App.css:73`, `Metrics.jsx` | Frame-level smoothness (compositor-only props) | `transform: scaleX()` with `transform-origin: left`; gauge via `transition: stroke-dasharray` |
| 9 | Narrow screens: copilot becomes `order:-1` static block, pushing all content below it | `App.css:250-253` | Wayfinding, flexibility | Collapse to a bottom sheet with drag-to-dismiss (velocity-projected snap points, rubber-band, damping 0.8 / response 0.3 since the flick carries momentum). Needs Motion or hand-rolled rAF spring; defer until #1–#7 are in |
| 10 | "Working…" swaps button label so the Ask button changes width | `Advisor.jsx:282` | Craft | Reserve width (`min-inline-size`) |

Motion dependency: #1, #2, #5–#8 are pure CSS. #3 is logic only. #4 and #9 want a spring: either add `motion` (small, matches your stated stack) or a ~30-line rAF spring helper. **Needs your call before that commit.**

## 3. Order of work (one commit each, `npm run build && npm run lint` between)

1. `type: root tokens` — `--font`, `@font-face` (woff2), synthesis, smoothing, root line-height, scale/tracking/leading tokens in `index.css`.
2. `type: apply scale and heading hierarchy` — replace one-off sizes with tokens in `App.css`; h1–h4 sizes, line-height, tracking; markup h4→h3 in `Advisor`/`Suggestions`; SVG text via `var(--font)` and canvas font in `GraphView.jsx:21`.
3. `type: numbers, wrapping, measure, truncation` — tabular-nums, balance/pretty, nowrap, `overflow-wrap`, `65ch`, `title` on truncated names, curly apostrophes, nbsp.
4. `a11y: text contrast tokens` — `--ok-text`, `--warn-text`, 12px floor, `user-select`, `::selection`.
5. `motion: press feedback + preference foundations` — `:active` states, explicit transitions, reduced-motion/transparency/contrast blocks, `bar-fill`/gauge to compositor props.
6. `motion: dialogs and panels` — Modal enter/exit with origin from opener; `.gdetail`, `.gflags`, notices, accepted bar, Result.
7. `ui: translucent materials` — chrome, panels, scroll-edge fade, material weight by size.
8. `graph: direct manipulation` — grab offset on node drag, animated fit/zoom, pan momentum + rubber-band, pinch. (Spring decision.)
9. `ui: mobile copilot sheet` (optional) — drag-to-dismiss with velocity projection.

Order rationale: type tokens first so later commits reuse them; reduced-motion foundations (5) before any new motion (6, 8, 9); materials after motion so blur is animated once, not retrofitted.

## Verification (when implementing)
- `cd client && npm run build && npm run lint` after each commit.
- `npm run dev`, check light + dark, 1280px and 390px widths; DevTools "Emulate prefers-reduced-motion / reduced-transparency / forced contrast".
- Typography: scrub the forecast tooltip (no digit jitter), resize the sidebar text, long alias strings, contrast check on `--ok-text`/`--warn-text`.
- Motion: open a modal and close/reopen it during the animation (no jump); drag a node by its edge (no snap); flick-pan the graph (coasts, rubber-bands at the edge); slow-motion DevTools animation panel.

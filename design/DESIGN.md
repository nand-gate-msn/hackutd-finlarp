# Finlarp Design System

Finlarp is a professional cash flow app for bank customers: accounts, bills, spending, advice from a copilot, and a graph of where money goes. This file is the single reference for how it looks and why. Pair it with `tokens.css` (every token as a CSS variable, light and dark) and `components.css` (the component styles). Nothing in the app has been migrated yet; see **Migration** for the checklist.

## 1. Direction and reasoning

**Calm, precise, quiet, like a well-made native Apple app. Numbers are the hero.**

| Decision | Why |
| --- | --- |
| Hierarchy comes from type weight, size and spacing, not borders, colour or shadow. | A banking screen is dense with figures. Boxes and colour add noise; size and weight let the eye find the number that matters first. |
| One display-size figure per view; money is large, in `ink`, tabular. | The customer opens the app to answer "how much?". Tabular numerals keep columns and live values from jittering. |
| One brand colour, a muted banking blue, plus neutral grays and four status tones. | A minimal palette keeps the brand recognisable and stops colour from competing with data. Blue reads as trustworthy and is not a status colour. |
| Orange is reserved for the `warning` tone. | If orange were also brand, a warning would look like branding. Keeping it exclusive makes it a signal. |
| Every status has a word; colour only reinforces it. | Colour-only status fails colour-blind users and screenshots. A word plus tone works everywhere. |
| Cards at rest are a tint, not a border or shadow. | Quiet surfaces keep attention on content. Elevation is saved for things that actually float. |
| Never nest a card in a card. | Nesting multiplies edges and padding; spacing, eyebrows and divider rows group more calmly. |
| Matte surfaces; the detail drawer is the only translucent layer. | One material signals one floating thing. Stacked translucency destroys legibility. |
| Motion starts on press, stays interruptible, never locks input. | Directness is what makes an interface feel native; lag or a locked transition feels broken. |
| System fonts. | They match the device, ship their own optical sizing and need no loading. |
| 4px spacing grid, three radii, two elevations. | Fewer, named choices mean consistent screens and cheap decisions. |

## 2. Content fundamentals

- Write sentence case. Titles name what the thing is ("Where your money goes"); buttons say what happens ("Accept", "Add account"). Real copy from the product: "Ask the copilot", "Couldn't load accounts", "Saved. Forecast re-run: overdraft chance 9% → 4%."
- Speak to the customer as "you" and "your". Use "we" never; the system is "the copilot" when it advises.
- Be plain about privacy and limits: "The AI sees only anonymous summaries; your names and numbers stay here."
- Money: US dollars with cents (`$4,210.18`) through `Intl.NumberFormat`; compact (`$12.5K`) only in graph labels. Use the true minus "−" and an explicit "+" on changes. Dates are short and local.
- Store copy in natural case. Uppercase comes from the `text-eyebrow` style, never from typed capitals.
- No emoji, no exclamation marks, no decorative symbols.

## 3. Colour

A deliberately small palette: **20 tokens**. Two themes, `light` and `dark`, from one set. The accent is **#3668b8** in light and **#6794dc** in dark (a lighter tint so it keeps contrast on dark surfaces). It works as button fill, as text and as the focus ring, so no separate hover, text or focus colours exist: hover and press are the `state-hover` and `state-pressed` overlays on any fill.

| Token | Light | Dark | Role |
| --- | --- | --- | --- |
| `canvas` | `#f5f5f6` | `#0e0f11` | Page background behind every card. Neutral gray. Replaces `--bg`. |
| `surface` | `#ffffff` | `#17191c` | Cards, inputs, graph nodes and the segmented-control thumb. Text on it uses `ink` and `ink-muted`. Replaces `--card`. |
| `track` | `#e8eaed` | `#2a2d32` | The one quiet gray fill and divider: bar and gauge tracks, segmented tray, chips, neutral badges, skeletons, 1px row dividers. Replaces `--border` (fills and dividers). |
| `line-control` | `#7b8089` | `#6f757e` | Borders of controls (input, account and bill nodes), unselected stepper marks, payment edges, node handles. At least 3:1 on `canvas` and `surface`. Replaces `--edge-pay` and `--border` on controls. |
| `ink` | `#1b1d21` | `#e8eaed` | Primary text and figures on `canvas`, `surface`, `track`, `accent-subtle`; also the bill marker. Replaces `--text`. |
| `ink-muted` | `#596068` | `#9aa0a8` | Secondary text, eyebrows, helper text, placeholders and the spending marker on `canvas`, `surface`, `track`. Replaces `--muted`. |
| `accent` | `#3668b8` | `#6794dc` | The one brand colour, a muted banking blue. Primary button fill, links and accent text, focus ring, selected outlines, transfer edges, account marker. At least 4.5:1 as text on `canvas`, `surface`, `track` and `accent-subtle`. Replaces `--accent`, `--n-account`. |
| `on-solid` | `#ffffff` | `#0e0f11` | Text on `accent` and `negative` fills. White on light; near-black on dark because the dark accent is a light tint. Replaces literal `#fff`. |
| `accent-subtle` | `#e6eefa` | `#14233a` | Selected chip, selected table row and accent badge background. Text on it uses `accent` or `ink`. |
| `positive` | `#127436` | `#4ade80` | Positive tone: figures and words on `surface`, `canvas`, `positive-subtle` (4.5:1), and bar, gauge, income-marker and completed-step fills (3:1 on `track`). Replaces `--good`, `--n-income`. |
| `positive-subtle` | `#e6f4ea` | `#12301f` | Background of a positive badge. |
| `caution` | `#854d0e` | `#facc15` | Caution tone (score 60-79): words and figures at 4.5:1 and fills at 3:1. An amber-brown in light so text reads. Replaces `--ok`. |
| `caution-subtle` | `#fdf3d6` | `#3a2f08` | Background of a caution badge. |
| `warning` | `#b93c0a` | `#fb923c` | Warning tone (score 40-59), the only orange in the system. Words, figures and fills. Replaces the raw `#ea580c`. |
| `warning-subtle` | `#fdebdd` | `#3b2210` | Background of a warning badge. |
| `negative` | `#b42318` | `#f87171` | Negative tone and danger: errors, at-risk words, danger button fill, error borders. Replaces `--bad`. |
| `negative-subtle` | `#fdeceb` | `#3b1816` | Background of a negative badge. |
| `material` | `rgba(255, 255, 255, 0.8)` | `rgba(23, 25, 28, 0.8)` | Translucent fill of the detail drawer only, over a 20px blur. Falls back to `surface` under reduced transparency. Text on it uses `ink`. |
| `state-hover` | `rgba(27, 29, 33, 0.06)` | `rgba(255, 255, 255, 0.07)` | Overlay laid over any filled control or row on hover. Replaces per-colour hover tokens. |
| `state-pressed` | `rgba(27, 29, 33, 0.12)` | `rgba(255, 255, 255, 0.13)` | Overlay laid over any filled control while pressed. |

**Rules**
- Page is `canvas`, containers are `surface`, the one quiet fill and divider is `track`, control edges are `line-control`.
- Text is `ink`; secondary text is `ink-muted`. Use `ink-muted`, not lower opacity.
- Status: 80-100 `positive`, 60-79 `caution`, 40-59 `warning`, 0-39 `negative`. Each tone is one colour for words, figures and fills, plus a `-subtle` background for badges.
- Graph markers: income `positive`, account `accent`, bill `ink`, spending `ink-muted`; kinds also differ by silhouette and label.
- Never use a coloured left or top edge, a tinted card, or colour alone to mark state. No gradients, no glows.

**Contrast.** Every text and graphic pair was computed with the WCAG 2 formula and passes in both themes: text at least 4.5:1, graphics, control borders and the focus ring at least 3:1. Full ratios are in Appendix A.

## 4. Typography

One sans stack and one mono stack, both system fonts, so the interface matches the device. Eight styles: `text-display` (hero figure), `text-title`, `text-heading`, `text-headline`, `text-body`, `text-label`, `text-caption` and the one `text-eyebrow` small-label style. Large styles track tighter and small ones looser; line-height is unitless and tightest on the largest. Apply tabular figures (`num`) to every money value, count and percentage. `text-mono` is for account aliases only. Cap running text at `measure`. Set `text-wrap: balance` on headings and `pretty` on descriptions.

| Style | Size | Line height | Weight | Tracking | Use |
| --- | --- | --- | --- | --- | --- |
| `text-display` | 2.5rem (40px) | 1.1 (44px) | 600 | -0.022em | The hero figure of a view: total balance, health score. One per view. |
| `text-title` | 1.75rem (28px) | 1.143 (32px) | 600 | -0.018em | Page title and metric values in a stat. Replaces h1 1.8rem, 1.5rem and 1.6rem values. |
| `text-heading` | 1.25rem (20px) | 1.2 (24px) | 600 | -0.012em | Card and section titles (h2). Replaces 1.25rem and 1.05rem headings. |
| `text-headline` | 1rem (16px) | 1.25 (20px) | 600 | -0.005em | Row titles, account names, emphasised figures in a row. |
| `text-body` | 1rem (16px) | 1.5 (24px) | 400 | 0 | Running text, input text (16px stops iOS zoom). Limit to the measure token. |
| `text-label` | 0.875rem (14px) | 1.43 (20px) | 500 | 0.005em | Buttons, chips, segmented items, badges, table cells, helper copy. Replaces 0.85rem and 0.9rem. |
| `text-caption` | 0.75rem (12px) | 1.333 (16px) | 400 | 0.01em | Footnotes, meta lines, node sub-lines. Replaces 0.64-0.8rem micro sizes. |
| `text-eyebrow` | 0.75rem (12px) | 1.333 (16px) | 600 | 0.06em | The one small-label style: stat labels, section labels, table headers, node kinds. Set in sentence case; bundle.css applies uppercase. Replaces four variants. |
| `text-mono` | 0.875rem (14px) | 1.43 (20px) | 400 | 0 | Account aliases and identifiers only. Never for money. |

**Why:** large type tracks tighter and small type looser because letters read too far apart as they grow; line height is tightest on the largest sizes. Weight does most of the hierarchy work: five of the eight styles are 600 so size steps stay modest. Input text is 16px so iOS does not zoom. Eyebrows are stored in sentence case and uppercased by CSS, so copy never has to be retyped. Every money value, count and percentage uses tabular numerals (`font-variant-numeric: tabular-nums`, the `num` class).

## 5. Spacing and layout

| Token | Value | Use |
| --- | --- | --- |
| `space-1` | `4px` | Inline gaps inside badges and keys; small bar height; micro gaps. |
| `space-2` | `8px` | Gap between a control and its label; bar height; table compact row padding. |
| `space-3` | `12px` | Control padding (small); table cell padding; gap between related blocks. |
| `space-4` | `16px` | Default control padding; compact card padding; gap in a stat grid row. |
| `space-5` | `20px` | Default card padding; page side gutter. |
| `space-6` | `24px` | Roomy card padding; gap between cards and sections. |
| `space-8` | `32px` | Gap between stat columns; empty-state padding; page top padding. |
| `space-10` | `40px` | Space reserved for a trailing spinner in an input. |
| `space-12` | `48px` | Gap between page-level sections. |
| `space-16` | `64px` | Page bottom padding. |

Nothing sits off the 4px grid. Controls are `control-sm` 32px or `control-md` 40px and grow to `touch-min` 44px on coarse pointers.

| Token | Value | Use |
| --- | --- | --- |
| `control-sm` | `32px` | Small button, chip and segmented item height. |
| `control-md` | `40px` | Default button, input and segmented-control height. |
| `touch-min` | `44px` | Minimum height of every control on coarse pointers. |
| `drawer-width` | `320px` | Detail drawer width above 640px. |
| `measure` | `640px` | Maximum width of running text. |
| `page-max` | `1120px` | Maximum page width. Replaces the duplicated 1100/1200px widths. |

Pages are centred at `page-max` with a `space-5` gutter; sections are `space-6` apart inside a view and `space-12` between regions. Stats sit on the canvas in an auto-fit grid; cards sit in an auto-fit grid with a 22rem minimum. Breakpoints: 640px (drawer becomes a bottom sheet) and 960px (gutters widen).

## 6. Radii

| Token | Value | Use |
| --- | --- | --- |
| `radius-sm` | `8px` | Buttons, inputs, segmented items, bill and spending nodes, table skeletons. Replaces 3/4/8/10px. |
| `radius-md` | `12px` | Cards, panels, segmented tray, account node, detail drawer. Replaces 10/12/14px. |
| `radius-pill` | `9999px` | Badges, chips, bars, gauge caps, markers, income node. Replaces 999px and 50%. |

**Why:** three radii give a clear rule: small controls, larger containers, fully round for things that are labels or markers.

## 7. Elevation and material

| Token | Light value | Use |
| --- | --- | --- |
| `elevation-1` | `0 0 0 1px rgba(16, 24, 40, 0.06), 0 1px 2px rgba(16, 24, 40, 0.08)` | Selected segmented thumb and small popovers: a raised control. Cards at rest use no shadow. |
| `elevation-2` | `0 0 0 1px rgba(16, 24, 40, 0.06), 0 8px 24px rgba(16, 24, 40, 0.1)` | The detail drawer and menus: something floating above content. Dark theme uses a light ring because black shadows vanish. |

Each has a separate dark value (a light ring plus a deep shadow), because black shadows disappear on dark surfaces. Cards at rest have no shadow. The detail drawer uses `material` over a 20px blur and becomes solid `surface` under `prefers-reduced-transparency`, `prefers-contrast: more`, or where `backdrop-filter` is missing.

## 8. Motion

| Token | Value | Use |
| --- | --- | --- |
| `duration-fast` | `120ms` | Press, hover and focus feedback. Feedback starts on pointer-down. |
| `duration-base` | `200ms` | Selection changes, fades, node dimming. |
| `duration-slow` | `320ms` | Bar and gauge fills, drawer travel. |
| `ease-standard` | `cubic-bezier(0.2, 0, 0, 1)` | Everything entering or changing: starts fast, settles without overshoot (damping 1.0). |
| `ease-exit` | `cubic-bezier(0.4, 0, 1, 1)` | Things leaving. Pairs with ease-standard so a panel exits along the path it entered. |

- Feedback starts on pointer-down, not on release.
- Enter and change with `ease-standard` (critically damped, no overshoot); leave with `ease-exit` along the path it entered.
- Animate only `transform`, `opacity`, colour and bar/gauge fills.
- Use CSS transitions on state: they retarget from the current value, so a second input mid-flight redirects instead of waiting. Never lock input during a transition.
- For drag-driven motion use a spring (damping 1.0, response 0.4; bounce near 0.8 only when a flick carried momentum).
- `prefers-reduced-motion: reduce`: slides, scales and pulses stop; opacity and colour changes remain.

## 9. Theming

There is one source of truth for theme: the `data-theme` attribute on `<html>`, with the values `light` and `dark`. Tokens switch on that attribute; nothing in components reads `prefers-color-scheme` directly. Resolve the attribute once, before first paint, and keep it in sync with the OS:

```html
<script>
  (function () {
    var mq = matchMedia('(prefers-color-scheme: dark)');
    var apply = function () { document.documentElement.dataset.theme = mq.matches ? 'dark' : 'light'; };
    apply();
    mq.addEventListener('change', apply);   // live update when the OS theme changes
  })();
</script>
```

For a stored override, set `data-theme` from the stored value and skip the listener. Components that need the theme in JavaScript read the attribute and subscribe to it, never to a second media query:

```js
const useTheme = () => {
  const root = document.documentElement;
  const [theme, setTheme] = useState(root.dataset.theme);
  useEffect(() => {
    const mo = new MutationObserver(() => setTheme(root.dataset.theme));
    mo.observe(root, { attributes: true, attributeFilter: ['data-theme'] });
    return () => mo.disconnect();
  }, []);
  return theme;
};
// <ReactFlow colorMode={useTheme()} />
```

Map React Flow's variables to tokens once, so the graph follows the theme with no extra code: `--xy-background-color` → `canvas`, `--xy-minimap-background-color` and `--xy-controls-button-background-color` → `surface`, `--xy-controls-button-color` → `ink`, `--xy-edge-stroke` → `line-control`, `--xy-attribution-background-color` → `surface`. Style edges with `line-control` (payment, solid), `positive` (deposit, dotted) and `accent` (transfer, dashed) so line style, not only hue, identifies them.

## 10. Iconography

There is no icon set and no decorative iconography. Six functional glyphs exist, drawn as inline SVG on a 16px grid with a 1.5 stroke, round caps and joins, `currentColor` and no fill: close, retry, add, undo, check, and the sort arrow (a text arrow set by `aria-sort`). Every glyph is paired with a visible word. Graph and legend markers are plain geometric shapes (circle, square, diamond, triangle) that carry meaning with the node kind.

**Product mark.** No mark was supplied, so the name is set in plain type: "Finlarp" in `text-title`. Do not draw a logo.

**Favicon.** The current `public/favicon.svg` and `public/icons.svg` are unmodified Vite template files in purple (#863bff, #7e14ff, #aa3bff, #47bfff). They are not brand. Replace the favicon with a mark built from `accent` and `ink` once a mark exists, and delete `icons.svg`, which nothing references. No purple is used anywhere in this system.

## 11. Component rules

Every interactive component defines default, hover, active, focus-visible and disabled, and loading and error where they apply. Specimens for each state are in the design-system artifact; `components.css` implements them, with forced classes (`.is-hover`, `.is-active`, `.is-focus`, `.is-selected`) for specimens and tests.

### Button

Button is the single control for commands; four variants set emphasis, two sizes set density.

#### When to use
- `primary` is the one main action of a view or card ("Accept", "Ask"). Use at most one per view.
- `secondary` is any other command ("Retry", "Edit"). `ghost` is a low-emphasis follow-up beside a primary ("Undo", "Cancel").
- `danger` only for destructive, hard-to-undo commands, and always beside a clear way back.
- Navigation that changes the URL is a link, not a Button.

#### Consumer provides
A `<button>` with classes `btn btn--{variant} text-label`, a verb label in sentence case ("Add account", not "Add"), and optionally `btn--sm`, `btn--block` and a leading `btn__glyph` SVG (16px, stroke `currentColor`). Set `aria-busy="true"` and swap the label to a present-tense progress label ("Saving…") with a `spinner`; ignore clicks while busy.

#### States
| State | Treatment |
| --- | --- |
| Default | Variant fill: `accent`, `track`, transparent, `negative` |
| Hover | Every variant gets the `state-hover` overlay on its fill |
| Active | `state-pressed` overlay, and scales to 0.98 immediately on pointer-down |
| Focus-visible | 2px `accent` ring, 2px offset; never removed |
| Disabled | `disabled-opacity`, `not-allowed` cursor, native `disabled` attribute |
| Loading | `aria-busy`, spinner and progress label, press feedback off |

#### Sizes
`md` 40px (44px on coarse pointers), `sm` 32px for dense rows. Radius `radius-sm`. Label is `text-label`.

#### Rules
- Label says what happens. Never "OK", "Submit" or "Click here".
- A button that only shows an icon is not offered; see IconButton.
- Do not put a primary and a danger button side by side; make the destructive one secondary-weight text.
- Transitions run on press and release and can be interrupted; nothing locks input while they play.


### IconButton

IconButton is a Button that pairs a 16px glyph with a text label; there is no icon-only form.

#### When to use
Use it where a glyph speeds recognition of a command that already has a clear name: "Close" on the detail drawer, "Retry" on an error, "Undo" after an accepted change. If the label alone is clear, use a plain Button.

#### Consumer provides
A `<button class="btn btn--ghost btn--sm text-label">` containing a `btn__glyph` SVG (`aria-hidden="true"`, 16px viewBox, `stroke-width 1.5`, round caps) followed by the visible label. The glyph set is intentionally small: close, retry, add, undo, check, sort.

#### States
Identical to Button: default, hover, active, focus-visible, disabled, loading. In loading the glyph is replaced by the `spinner` and the label changes to a progress label.

#### Sizes
`md` 40px and `sm` 32px, same as Button. The hit area is the whole button, never only the glyph.

#### Rules
- The label is always visible. A bare "×" or a glyph with only `aria-label` fails this system: sighted users still need the word.
- Glyphs are functional, never decorative: do not add one to a button that does not need it.
- One glyph style: 1.5 stroke, round caps and joins, `currentColor`, no fills, no emoji.


### Chip

Chip is a small pill button that applies a suggestion or toggles a filter.

#### When to use
Suggested questions ("Can I afford a car?"), quick filters, or toggling a view option. For choosing exactly one of a few views, use SegmentedControl.

#### Consumer provides
`<button class="chip text-label">` with a short phrase in sentence case. For a toggle, add `aria-pressed="true|false"`; the selected chip shows `accent-subtle`, `accent` and a leading check, so selection is not colour alone.

#### States
Default, hover (`state-hover`), active (`state-pressed`, 0.97 scale on pointer-down), focus-visible, selected, disabled (`disabled-opacity`), loading (`aria-busy` with spinner and progress label).

#### Sizes
One size: `control-sm` 32px (44px on coarse pointers). Radius `radius-pill`, label `text-label`.

#### Rules
- Chips never navigate and never submit a form.
- Keep the phrase under about 40 characters; chips wrap, they do not truncate.
- Disable the whole set while a request they trigger is running.


### SegmentedControl

SegmentedControl chooses one option from two to five, and the choice changes the view in place.

#### When to use
Time windows (30d / 90d / 180d / 365d), list vs. table, income vs. spending. For more than five options use a select; for independent toggles use Chips.

#### Consumer provides
A `role="group"` container named by `aria-label`, holding `<button class="seg__item text-label" aria-pressed>` items with short labels. Exactly one item is `aria-pressed="true"`. Arrow keys may move the selection; Tab enters and leaves the group once.

#### States
Item: default, hover (text to `ink`), active (0.97 scale), focus-visible, selected (`surface` thumb with `elevation-1`, text `ink`), disabled. Group: disabled, loading (`aria-busy`: unselected items dim and ignore input while the new data loads).

#### Sizes
`md` 40px tray, `sm` 32px tray via `seg--sm`. Tray `radius-md`, items `radius-sm`. 44px item height on coarse pointers.

#### Motion
Selection fades the thumb in 200ms with `ease-standard`. Because it is a property transition from the current value, choosing a second option mid-fade redirects cleanly. A sliding thumb is optional; if added, drive it with a critically damped spring and never lock input.

#### Rules
- Selected is shown by thumb, text colour and `aria-pressed`, not by hue.
- Labels are 1-4 characters or one short word; they never wrap.


### TextInput

TextInput is a single-line text field with a visible label, optional hint and an inline error.

#### When to use
Free text or numbers typed by the person: a question to the copilot, an amount, an alias. Choices from a short fixed list use SegmentedControl or Chips.

#### Consumer provides
A `field` wrapper with: `field__label` (`text-label`, a real `<label for>`), `input-wrap` > `<input class="input text-body">`, optional `field__hint` and `field__error` (`text-caption`). Put the action beside it in an `input-group`.

#### States
| State | Treatment |
| --- | --- |
| Default | `surface` fill, 1px `line-control` border (3:1), `radius-sm` |
| Hover | Border to `ink-muted` |
| Focus-visible | Border `accent` plus 2px `accent` ring |
| Filled | `ink` text; placeholder is `ink-muted` |
| Error | `aria-invalid`, `negative` border, message below beginning "Error:" in `negative` |
| Disabled | `track` fill, `disabled-opacity` |
| Read-only | Transparent with a `track` border |
| Loading | `aria-busy`, trailing spinner, hint explains the wait |

#### Sizes
`control-md` 40px (44px on coarse pointers). Input text is `text-body` 16px so iOS does not zoom.

#### Rules
- Every field has a visible label; a placeholder is an example, not a label. Only a field with an adjacent action may hide its label (`sr-only`).
- Validate inline on blur, with the fix in the message ("enter a number, like 1200.00").
- Errors use words plus the border; colour alone never signals them.


### Card

Card is the one container in the system. It replaces the old card, panel, stat tile, indicator, chance and proposal boxes.

#### When to use
Wrap one self-contained topic: an account, the health summary, the advisor, the money-flow graph. Group content inside it with spacing, a `card__section` with an eyebrow, or divider-separated `card__row` items. Pull a figure out of a box and show it as a Stat on the canvas instead of framing it.

#### Variants
| Class | Use |
| --- | --- |
| `card` | Default. `surface` tint on `canvas`, `radius-md`, 20px padding, no border, no shadow |
| `card--compact` / `card--roomy` | 16px / 24px padding |
| `card--flush` | No padding; a table or list runs edge to edge |
| `card--outline` | No fill, 1px `track`. For empty or placeholder areas |
| `card--interactive` | The whole card is one target: hover tint, press scale, selected 2px `accent` ring |

#### Consumer provides
A `<section>` or `<article>` with a heading. Slots: `card__header` (title `text-heading` or `text-headline`, optional `card__desc` with `text-label`), `card__section`, `card__rows` / `card__row`, `card__footer`. Interactive cards are a `<button>` or `<a>`, or carry `tabindex="0"` and `role="button"`.

#### States (interactive only)
Default, hover (`state-hover` overlay), active (`state-pressed` + 0.995 scale), focus-visible (2px `accent` ring), selected (`aria-pressed="true"`, 2px `accent` ring), disabled (`aria-disabled`, `disabled-opacity`), loading (`aria-busy`, skeleton lines), error (a State with Retry inside).

#### Rules
- A Card never contains a Card. Inside, separate with spacing and divider rows.
- Status is shown with a Badge or words, never with a coloured edge, stripe or tinted card.
- Cards at rest have no shadow. Elevation belongs to floating things only.
- One heading per card, matching the document outline.


### DetailDrawer

DetailDrawer shows the flows in and out of the selected graph node, floating over the graph on a translucent material.

#### When to use
Inside the graph canvas, to explain one selected node. It is non-modal: the graph stays interactive and there is no scrim. For anything that must block the page, use a dialog (not part of this system).

#### Consumer provides
An `<aside class="drawer" data-state="open|closed" aria-labelledby>` with `drawer__header` (`drawer__kind` in `text-eyebrow`, `drawer__title` in `text-heading`, a Close IconButton with the visible word "Close"), then `drawer__section` blocks: an eyebrow with the total, then a `drawer__list` of "name · count · amount" rows (`num`).

#### Material and elevation
Fill `material` (80% of `surface`) over a 20px blur and 1.8 saturation, `radius-md`, `elevation-2`. It is the only translucent surface in the system. It becomes solid `surface` under `prefers-reduced-transparency`, `prefers-contrast: more` and where `backdrop-filter` is missing. Text on it is `ink`, which holds at least 4.5:1 over any backdrop (see Contrast).

#### Motion
Opens by fading in and travelling 16px from the right over `duration-slow` with `ease-standard`; closes along the same path with `ease-exit` (spatial symmetry). Both are CSS transitions on `opacity` and `transform`, so a second toggle mid-flight reverses from the current position and nothing is locked. Reduced motion keeps only the opacity fade. Below 640px it becomes a bottom sheet entering and leaving along the bottom edge.

#### Behaviour
Opening moves focus to the title; Escape and Close dismiss and return focus to the node. Clicking the canvas also closes it.

#### States
Open, closed (`visibility: hidden` after the exit finishes), loading (a State inside), empty ("No activity for this node"), error (State with Retry).

#### Rules
- One drawer at a time.
- Do not stack translucent layers.
- Width is `drawer-width` (320px); content scrolls, the drawer does not resize.


### State

State is the one component for loading, empty and error. It always tells the person what is happening and, on error, what to do next.

#### When to use
Wherever data is not yet, not at all, or not successfully available: a whole page region, a Card, a table, the graph canvas, the drawer. Do not invent a new message box.

#### Variants
| Variant | Role | Content |
| --- | --- | --- |
| `state--loading` | `role="status"`, `aria-busy` | Spinner, present-tense words ("Loading accounts…"), two or three skeleton lines |
| (empty) | none | `text-headline` title naming what is missing, one `text-label` line saying when it will appear |
| `state--error` | `role="alert"` | "Error" eyebrow, title "Couldn't load X", one line saying what happened and that data is safe, a secondary **Retry** Button with the retry glyph |
| `state--inline` | any | Left-aligned, smaller padding, for use inside a Card, table or list |

#### Consumer provides
Title, description, and for error an `onClick` retry handler. While a retry runs set `aria-busy="true"` on the button and change its label to "Retrying…".

#### Rules
- Error is shown by the word "Error", the title and the button, with `negative` only on the eyebrow; never by a red box.
- Use plain language: "Couldn't load accounts", not "Request failed: 503" as the title. The status goes in the description.
- Empty is not an error: no eyebrow, no Retry.
- Never show a spinner for longer than the words explain; after ten seconds say what is taking time.


### Stat

Stat shows one figure with its label and, optionally, what changed. Numbers are the hero, so a Stat has no box.

#### When to use
Any single money amount, count or percentage: totals, balances, chance of overdraft. Place Stats on the canvas in a `stat-grid`, or inside a Card as a group. Use `stat-list` (a `<dl>`) when several figures share one block ("Income / Spent / Saved / Net").

#### Consumer provides
`stat__label` (`text-eyebrow`), `stat__value` (`text-display` for the hero figure of a view, `text-title` in a grid, `text-headline` inline) with `num`, and an optional `stat__delta` (`text-label`). Format money with `Intl.NumberFormat` and keep the value in `ink`.

#### Tones
`stat--positive`, `stat--caution`, `stat--warning`, `stat--negative` colour only the delta line. The delta text must still carry an explicit sign (+ or the true minus "−") and words ("vs. last month"), so colour is never the only signal.

#### States
Default; loading (`stat--loading` with `aria-busy`: the value becomes a pulsing placeholder); empty (value "—" and a caption saying why); error (value "—" and "Couldn't load" in `negative`). Stats are not interactive; wrap in a Card with `card--interactive` if one must open detail.

#### Rules
- All figures are tabular (`num` or inherited from `.stat`) so columns and live values do not jitter.
- One `text-display` per view.
- Never colour the value itself red or green; sign and words do that work.


### Badge

Badge labels a thing or states its status in a word. Flag is the same component with a status in the text.

#### When to use
- Neutral: a category ("Checking").
- Tone: a status band. The tone must match the word: positive "Healthy", caution "Watch", warning "Weak", negative "At risk".
- Flag: "`Name: status`" for risk checks ("Overdraft: ok").

#### Consumer provides
`<span class="badge badge--{tone} text-label">Label</span>`. Tones: `neutral` (default), `accent`, `positive`, `caution`, `warning`, `negative`. Small: `badge--sm` with `text-caption`. The label is always words, 1-3 of them.

#### Colour pairs
Each tone is its `-subtle` background with the tone colour as text; every pair is at least 4.5:1 in both themes (see Contrast).

#### States
Static: no hover, active, focus, disabled or loading. In a loading list, show a `skeleton` pill instead. Errors are not badges; use a State.

#### Rules
- Never rely on colour: the word carries the meaning, the tone reinforces it.
- No icon inside a Badge.
- Not clickable. A clickable pill is a Chip.


### Bar

Bar compares a value to a whole or to its peers; Meter adds the label, score and status word that make it readable alone.

#### When to use
- `bar-row`: rank categories against each other, with the amount at the end.
- `meter`: a 0-100 score band (pillars, indicators) with its status word.
Use Gauge for the single overall score.

#### Consumer provides
`<span class="bar" role="meter" aria-valuenow aria-label style="--value:62%"><span class="bar__fill"></span></span>`. Fill tones: default `accent`, `neutral`, `positive`, `caution`, `warning`, `negative` via `bar--{tone}`. In a bar row use `text-label`; in a meter use `text-headline` for name and score, `text-caption` for the hint.

#### Tone from score
80-100 positive, 60-79 caution, 40-59 warning, 0-39 negative. Always print the number and the word beside the bar.

#### States
Default; loading (`bar--loading`, a pulsing neutral segment, `aria-busy`); empty (0%, track only, amount shown as "$0.00"); error (replace the row with an inline State). Bars are not interactive.

#### Sizes
`md` 8px, `sm` 4px (`bar--sm`). Both fully rounded. Fill width animates over `duration-slow` and is interruptible.

#### Rules
- The track is `track` and the fill is at least 3:1 against it in both themes.
- Tabular numerals for every amount.
- Bars start at zero and are never truncated.


### Gauge

Gauge shows the one overall score as a ring, with the number and a status word at its centre.

#### When to use
Only for the overall financial-health score (0-100). One per view. Pillar and indicator scores use Meter.

#### Consumer provides
An SVG ring (`viewBox 0 0 160 160`, r 74, `pathLength="100"`) with `gauge__track` and `gauge__fill`; set the score as `style="--pct:86"`. Centre text: `gauge__value` (`text-display`, `num`) and `gauge__word` (`text-label`). Provide `role="img"` and an `aria-label` that includes score and word. Tone class `gauge--{positive|caution|warning|negative}` follows the score bands.

#### States
Default; loading (`gauge--loading`: a short neutral arc pulses, word "Loading"); no data (empty ring, "—" and "Not scored yet"); error (replace with an inline State and Retry). The fill animates over `duration-slow` and retargets from its current value.

#### Sizes
One size, 160px (10rem), 12-unit stroke with round caps. Do not scale below 128px; the word becomes unreadable.

#### Rules
- The word must come from the same band as the tone; colour only reinforces it.
- The fill is at least 3:1 against `surface` in both themes.
- No gradient fills, no tick marks, no glow.


### DataTable

DataTable lists records in rows and columns; numbers align right and use tabular figures.

#### When to use
Bills, purchases and any list where each row has the same fields. For one record's details use a Card with `stat-list`. Not for layout.

#### Consumer provides
A real `<table class="table text-label">` with a `<caption>`, `<th scope="col">` headers in `text-eyebrow`, and numeric cells with `is-num`. Wrap in `table-wrap` for horizontal scroll on narrow screens. Sortable headers contain a `table__sort` button and the header carries `aria-sort`.

#### Variants
`table--compact` (8px vertical cell padding), `table--interactive` (rows are targets; add `tabindex="0"` and a key handler). Place inside a `card--flush` or a padded Card; the first and last cells lose their outer padding so text aligns with the card edge.

#### States
Row: default, hover (`state-hover` tint), selected (`accent-subtle`, `aria-selected`), focus-visible (inset 2px ring). Header sort: default, hover, sorted (arrow glyph added by `aria-sort`). Table: loading, empty and error use State inside the Card, not inside the table.

#### Rules
- Only horizontal `track` dividers between rows. No vertical lines, no zebra, no outer border.
- Money columns right-aligned, same decimals, true minus for negatives.
- Muted columns (`is-muted`) for secondary text; the amount stays `ink`.


### Stepper

Stepper shows where a multi-step task is while the person waits.

#### When to use
The copilot's four agents (understanding, explaining, finding improvements, double-checking). Any process of two to six sequential steps with a known order.

#### Consumer provides
An `<ol class="stepper">` of `<li class="step step--{state}">` items: `step__mark` (`aria-hidden`), the step label, and `step__state`, a word. The running item carries `aria-current="step"`. Announce changes through the surrounding `role="status"`.

#### States
| State | Mark | Word |
| --- | --- | --- |
| waiting | hollow ring, `line-control` | Waiting |
| running | `accent` ring with a pulsing dot | Working |
| done | filled `positive` circle with a check | Done |
| canned | filled `caution` diamond | Standard answer |
| error | filled `negative` square | Couldn't finish |
Each state differs by shape and by word as well as colour.

#### Motion
Only the running dot pulses (1s, opacity). Reduced motion stops the pulse; the word "Working" still says it.

#### Rules
- Steps never reorder, and finished steps never disappear.
- On error, offer Retry from the surrounding State.


### Legend

Legend names every shape and line style a chart or graph uses, so none depends on colour.

#### When to use
Directly above the money-flow graph and any chart with more than one kind of mark. Not for a single series; label that directly.

#### Consumer provides
A `<ul class="legend text-label">` of `legend__item` entries holding a key and a word. Keys: `key--income` (circle), `key--account` (square), `key--bill` (diamond), `key--spend` (triangle); lines: `stroke--payment` (solid), `stroke--deposit` (dotted), `stroke--transfer` (dashed). The same shape appears in the matching GraphNode's kind label.

#### States
Static: no hover, press or focus. Loading and error follow the graph: show the legend only once there are nodes.

#### Rules
- Shape and word always; hue is a third cue.
- Keys are 12px; lines are 24px wide and at least 2px thick.
- Order matches the left-to-right flow of the graph: income, account, bill, spending.


### GraphNode

GraphNode is one box on the money-flow graph. Four kinds are told apart by silhouette, label and marker shape, with hue as a third cue.

#### When to use
Only as a custom React Flow node. Layout sizes are the widths below; heights hug the content.

#### Kinds
| Kind | Silhouette | Marker | Amount |
| --- | --- | --- | --- |
| Income | pill (`radius-pill`), 176px | circle, `positive` | "+$4,800" |
| Account | `radius-md` with a 1px `line-control` border, 208px | square, `accent` | "$4,800 in · $2,861 out" |
| Bill | `radius-sm` with a dashed `line-control` border, 192px | diamond, `ink` | "$1,050" |
| Spending | `radius-sm`, `track` fill, no border, 176px | triangle, `ink-muted` | "$842" |

#### Consumer provides
A `<button class="gnode gnode--{kind}">` with `gnode__kind` (`text-eyebrow` and the matching `key` marker), `gnode__title` (`text-label`), optional `gnode__sub` (`text-mono`, the account alias) and `gnode__amount` (`text-label`, `num`). Handles are `gnode__handle` dots.

#### States
Default, hover (`state-hover`), focus-visible (2px ring), selected (2px `accent` ring plus `aria-pressed`), dimmed (35% opacity while another node is selected; remains focusable), disabled (`aria-disabled`), loading (`aria-busy`: title and amount become placeholders).

#### React Flow theming
Set `colorMode` from the theme hook, not from a one-off media query, and map `--xy-background-color` to `canvas`, minimap and controls to `surface`, edges to `line-control` (payment), `positive` (deposit, dotted) and `accent` (transfer, dashed). See the README's Theming section.

#### Rules
- No coloured left or top stripes; the silhouette and label do that job.
- Truncated titles keep the full label in `title` and in the drawer.
- Nodes are 56px or taller to stay a comfortable target.


## 12. Usage rules

### One primary action per view
Each view has at most one `btn--primary`. On the dashboard that is "Ask" in the advisor; inside a proposal it is "Accept". Everything else is secondary or ghost. A destructive command is `danger` only when it sits alone; beside a primary it is a secondary button.

### When to use what
| Need | Use | Not |
| --- | --- | --- |
| Run a command | Button | Chip, link |
| A glyph helps a command | IconButton (glyph + visible word) | Icon-only button |
| Suggest a question or toggle a filter | Chip | Badge, Button |
| Pick one view of a few | SegmentedControl | Row of Chips |
| Type text or a number | TextInput with a label | Placeholder-as-label |
| Group a topic | Card | Nested Cards, tinted boxes |
| One figure and its change | Stat on the canvas | A Card per figure |
| A word for a status or category | Badge / Flag | Coloured text alone |
| Compare categories | Bar row | Pie chart |
| A 0-100 score with its word | Meter (Gauge for the overall score only) | Bare coloured bar |
| Records with the same fields | DataTable | Grid of Cards |
| Progress of a multi-step task | Stepper | Spinner alone |
| Explain what shapes mean | Legend | Colour only |
| A node on the flow graph | GraphNode | Custom boxes |
| Details of the selected node | DetailDrawer | Modal dialog |
| Loading, empty, error | State | Ad-hoc messages |

### Status and colour
- Every status is a word plus a tone. "Healthy" in `positive`, "Watch" in `caution`, "Weak" in `warning`, "At risk" in `negative`.
- Score bands: 80-100 positive, 60-79 caution, 40-59 warning, 0-39 negative.
- Changes carry a sign and words: "+$320.00 vs. last month". Do not colour the figure itself.
- Never use a coloured left or top edge, a tinted card, or colour alone to mark state.

### Hierarchy
- Use size and weight before colour: one `text-display`, titles `text-title` or `text-heading`, rows `text-headline`, supporting copy `text-label`.
- Use spacing to group: `space-2` inside a group, `space-6` between groups.
- Small labels are always `text-eyebrow`; do not invent a new one.
- Use `ink-muted` for secondary text, not lower opacity.

### Numbers
- Money, counts and percentages are tabular (`num`) and right-aligned in columns.
- Keep decimals consistent within a column. Use the true minus for negatives.

### Accessibility
- Body text is 16px; UI text is not below 14px except captions at 12px.
- Every control has a visible label, a focus-visible ring and a 44px target on coarse pointers.
- Text meets 4.5:1 and graphics and control edges meet 3:1 in both themes (see Contrast).
- Respect reduced motion, reduced transparency and increased contrast.
- Provide `aria-busy`, `role="status"` and `role="alert"` on loading and error.

### Motion
- Feedback on pointer-down, not on release.
- Never block input during a transition; use transitions that retarget from the current value.
- Enter with `ease-standard`, leave with `ease-exit` along the same path.


## 13. Migration

Old names on the left, the new system on the right. Nothing is changed in the app yet; this is the checklist for the restyle.

### Colour tokens
The palette drops from 30 colour tokens to 20: neutral grays, one blue, four tones. Hover and press colours, the separate accent text colour, the focus colour, the divider colour and the bill colour are gone.

| Old | New | Note |
| --- | --- | --- |
| `--bg` | `canvas` | Now a true neutral gray |
| `--card` | `surface` | |
| `--text` | `ink` | |
| `--muted` | `ink-muted` | |
| `--border` | `track` (fills, dividers), `line-control` (control edges) | One quiet gray; dividers share it |
| `--accent` (#2563eb / #60a5fa) | `accent` (#3668b8 / #6794dc) | Muted banking blue; also used as text |
| `--n-account` | `accent` | Merged |
| `--good`, `--n-income` | `positive` | One colour for text and fill |
| `--bad` | `negative` | |
| `--ok` | `caution` | |
| `#ea580c` (raw) | `warning` | The only orange |
| `#fff` on accent | `on-solid` | |
| `--edge-pay` | `line-control` | |
| `--n-obligation` | `ink` | Bill is told apart by its diamond marker and dashed outline |
| `--n-category` | `ink-muted` | |
| (new in earlier pass) hover, pressed, focus, accent text, divider, bill tokens | `state-hover` / `state-pressed` overlays, `accent`, `track`, `ink` | Removed again to keep the palette small |
| `rgb(0 0 0 / .x)` shadows | `elevation-1`, `elevation-2` | Dark values added |
| two `:root` dark blocks | one `[data-theme="dark"]` block | |
| `prefers-color-scheme` in CSS and `matchMedia` in JS | `data-theme` on `<html>` | See Theming in the README |

### Type
| Old | New |
| --- | --- |
| h1 `1.8rem` | `text-title` |
| `2.4rem` gauge number | `text-display` |
| `1.4rem` balance, `1.5rem` stat value, `1.6rem` chance value | `text-title` (hero figure: `text-display`) |
| `1.25rem` h2 / `.section-title`, `1.05rem` h4 | `text-heading` / `text-headline` |
| `1rem`, `.9rem` body in cards | `text-body` / `text-label` |
| `.85rem`, `.9rem` table, controls | `text-label` |
| `.8rem`, `.75rem`, `.72rem`, `.7rem`, `.64rem` | `text-caption` |
| uppercase `.stat-label`, `.section h4`, `.gdetail h5`, `.gnode-kind`, `th` | `text-eyebrow` (one style) |
| `ui-monospace, monospace` (two places) | `text-mono` / `--font-mono` |
| system stack on `:root` | `--font-sans` |
| `td.num` tabular only | `num` on every figure |

### Spacing
Old pixel values snap to the nearest step: 1-5 → `space-1` (4) · 6-8 → `space-2` (8) · 10-12 → `space-3` (12) · 14-16 → `space-4` (16) · 18-20 → `space-5` (20) · 22-26 → `space-6` (24) · 28-32 → `space-8` (32) · 64 → `space-16`. Duplicated `.app` widths 1100/1200 → `page-max` (1120).

### Radii
3, 4, 8 → `radius-sm` (bars and dots → `radius-pill`) · 10, 12, 14 → `radius-md` · 999px and 50% → `radius-pill`.

### Classes and patterns
| Old | New |
| --- | --- |
| `.app` / `.page-head` | `.page`; title `text-title`, description `text-label` with `text-muted` |
| `.state` / `.state.error` / `.error-text` | State (loading, empty, error with Retry) |
| `.stats` / `.stat` / `.stat-label` / `.stat-value` | `.stat-grid` / `.stat` / `.stat__label` / `.stat__value` (no box) |
| `.stat-value.good` / `.bad`, `.good` / `.bad` | `.stat--positive` etc. on the delta, or `.text-positive` / `.text-negative` with a sign and words |
| `.grid` | `.grid-auto` |
| `.card` / `.card-head` | Card / `.card__header` |
| `.balance` | `.stat__value` with `text-title` |
| `.badge` / `.flag` / `.flag.good` | Badge / Flag (`badge--positive` etc.) |
| `.mini-stats` | `text-caption` line with `num` |
| `.section` / `.section h4` | `.card__section` / `text-eyebrow` |
| `.bar-row` / `.bar-name` / `.bar-track` / `.bar-fill` / `.bar-amt` | `.bar-row` / `.bar-row__name` / `.bar` / `.bar__fill` / `.bar-row__amount` (one definition) |
| `table` / `td.num` / `.muted` | DataTable `.table` / `.is-num` / `.is-muted` |
| `.panel` / `.panel-head` | Card / `.card__header` |
| `.small` / `.muted` | `text-caption` / `.text-muted` |
| `.seg` / `.seg button.on` | SegmentedControl `.seg` / `.seg__item[aria-pressed=true]` |
| `.t-*`, `.f-*` | `.gauge--{tone}`, `.bar--{tone}`, `.badge--{tone}`, `.stat--{tone}` |
| `.health`, `.gauge`, `.g-track`, `.g-fill`, `.gauge-text` | Gauge (`.gauge`, `.gauge__track`, `.gauge__fill`, `.gauge__text`) |
| `.pillars` / `.pillar` / `.pill` | Meter (`.meter`) with the status word |
| `.flow` / `.flow-net` | `.stat-list` / `.is-total` |
| `.indicators` / `.indicator` (top stripe) | Meter in a `.stat-grid`, status word beside the score |
| `.chances` / `.chance` | Stat |
| `.legend` / `.sw` / `.ln` | Legend (`.legend__item`, `.key--*`, `.stroke--*`) |
| `.gcanvas` / `.gnode*` (left stripe) / `.ghandle` | GraphNode (silhouette + marker); `.gnode__handle` |
| `.gminimap` and `react-flow` overrides | token-mapped `--xy-*` variables |
| `.gdetail` / `.gclose` / bare "×" | DetailDrawer / Close IconButton with the word "Close" |
| `.advisor` / `.ask` | Card + `.input-group` (TextInput + primary Button) |
| `.btn` / `.btn.ghost` | Button `btn--primary` / `btn--ghost` |
| `.ideas` / `.chip` | Chip |
| `.steps` / `.step` / `.dot` | Stepper (`.stepper`, `.step`, `.step__mark`, shape + word per state) |
| `.advice` / `.explanation` | `.stack` with `text-body` capped at `measure` |
| `.proposals` / `.proposal` (a card in a card) | `.card__rows` / `.card__row` with a Button |
| `.saved` / `.error-text` | `.text-positive` / `.text-negative` message with words |
| `@keyframes pulse` | `fl-pulse` (bundle) with a reduced-motion override |

### Removed
- The coloured top stripe on `.indicator` and the left stripe on `.gnode`.
- The unused `public/icons.svg`; replace `favicon.svg` (see Iconography).
- Duplicate rules in `App.css`: `.app`, `.bar-fill`, `.bar-track`, `.muted`, `.small`.


## Appendix A. Contrast ratios

Every text and graphic pair the components paint was computed with the WCAG 2 formula. All pairs pass in both themes. Minimums: 4.5 for text under 24px, 3 for graphics, control borders and the focus ring. The accent is #3668b8 in light, a lighter tint in dark; in both it works as button fill, as text and as focus ring.

### Light
| Pair | Foreground | Background | Ratio | Minimum |
| --- | --- | --- | --- | --- |
| Body text on canvas | `ink` #1b1d21 | `canvas` #f5f5f6 | 15.49 | 4.5 (text) |
| Body text on surface | `ink` #1b1d21 | `surface` #ffffff | 16.88 | 4.5 (text) |
| Body text on track | `ink` #1b1d21 | `track` #e8eaed | 14.00 | 4.5 (text) |
| Body text on accent-subtle | `ink` #1b1d21 | `accent-subtle` #e6eefa | 14.45 | 4.5 (text) |
| Secondary text on canvas | `ink-muted` #596068 | `canvas` #f5f5f6 | 5.84 | 4.5 (text) |
| Secondary text on surface | `ink-muted` #596068 | `surface` #ffffff | 6.37 | 4.5 (text) |
| Secondary text on track | `ink-muted` #596068 | `track` #e8eaed | 5.28 | 4.5 (text) |
| Accent text on canvas | `accent` #3668b8 | `canvas` #f5f5f6 | 5.03 | 4.5 (text) |
| Accent text on surface | `accent` #3668b8 | `surface` #ffffff | 5.48 | 4.5 (text) |
| Accent text on track | `accent` #3668b8 | `track` #e8eaed | 4.55 | 4.5 (text) |
| Accent text on accent-subtle | `accent` #3668b8 | `accent-subtle` #e6eefa | 4.69 | 4.5 (text) |
| Button label on accent fill | `on-solid` #ffffff | `accent` #3668b8 | 5.48 | 4.5 (text) |
| Button label on negative fill | `on-solid` #ffffff | `negative` #b42318 | 6.57 | 4.5 (text) |
| positive text on positive-subtle (badge) | `positive` #127436 | `positive-subtle` #e6f4ea | 5.17 | 4.5 (text) |
| positive text on surface | `positive` #127436 | `surface` #ffffff | 5.87 | 4.5 (text) |
| positive text on canvas | `positive` #127436 | `canvas` #f5f5f6 | 5.39 | 4.5 (text) |
| positive text on track | `positive` #127436 | `track` #e8eaed | 4.87 | 4.5 (text) |
| caution text on caution-subtle (badge) | `caution` #854d0e | `caution-subtle` #fdf3d6 | 6.19 | 4.5 (text) |
| caution text on surface | `caution` #854d0e | `surface` #ffffff | 6.85 | 4.5 (text) |
| caution text on canvas | `caution` #854d0e | `canvas` #f5f5f6 | 6.29 | 4.5 (text) |
| caution text on track | `caution` #854d0e | `track` #e8eaed | 5.68 | 4.5 (text) |
| warning text on warning-subtle (badge) | `warning` #b93c0a | `warning-subtle` #fdebdd | 4.88 | 4.5 (text) |
| warning text on surface | `warning` #b93c0a | `surface` #ffffff | 5.65 | 4.5 (text) |
| warning text on canvas | `warning` #b93c0a | `canvas` #f5f5f6 | 5.19 | 4.5 (text) |
| warning text on track | `warning` #b93c0a | `track` #e8eaed | 4.69 | 4.5 (text) |
| negative text on negative-subtle (badge) | `negative` #b42318 | `negative-subtle` #fdeceb | 5.75 | 4.5 (text) |
| negative text on surface | `negative` #b42318 | `surface` #ffffff | 6.57 | 4.5 (text) |
| negative text on canvas | `negative` #b42318 | `canvas` #f5f5f6 | 6.03 | 4.5 (text) |
| negative text on track | `negative` #b42318 | `track` #e8eaed | 5.45 | 4.5 (text) |
| positive fill on track (bar, gauge) | `positive` #127436 | `track` #e8eaed | 4.87 | 3 (graphic) |
| caution fill on track (bar, gauge) | `caution` #854d0e | `track` #e8eaed | 5.68 | 3 (graphic) |
| warning fill on track (bar, gauge) | `warning` #b93c0a | `track` #e8eaed | 4.69 | 3 (graphic) |
| negative fill on track (bar, gauge) | `negative` #b42318 | `track` #e8eaed | 5.45 | 3 (graphic) |
| positive fill on surface | `positive` #127436 | `surface` #ffffff | 5.87 | 3 (graphic) |
| caution fill on surface | `caution` #854d0e | `surface` #ffffff | 6.85 | 3 (graphic) |
| warning fill on surface | `warning` #b93c0a | `surface` #ffffff | 5.65 | 3 (graphic) |
| negative fill on surface | `negative` #b42318 | `surface` #ffffff | 6.57 | 3 (graphic) |
| Control border on surface | `line-control` #7b8089 | `surface` #ffffff | 3.97 | 3 (graphic) |
| Focus ring on surface | `accent` #3668b8 | `surface` #ffffff | 5.48 | 3 (graphic) |
| Control border on canvas | `line-control` #7b8089 | `canvas` #f5f5f6 | 3.64 | 3 (graphic) |
| Focus ring on canvas | `accent` #3668b8 | `canvas` #f5f5f6 | 5.03 | 3 (graphic) |
| Text on drawer over black backdrop | `ink` #1b1d21 | #cccccc | 10.51 | 4.5 (text) |
| Text on drawer over white backdrop | `ink` #1b1d21 | #ffffff | 16.88 | 4.5 (text) |

### Dark
| Pair | Foreground | Background | Ratio | Minimum |
| --- | --- | --- | --- | --- |
| Body text on canvas | `ink` #e8eaed | `canvas` #0e0f11 | 15.91 | 4.5 (text) |
| Body text on surface | `ink` #e8eaed | `surface` #17191c | 14.61 | 4.5 (text) |
| Body text on track | `ink` #e8eaed | `track` #2a2d32 | 11.46 | 4.5 (text) |
| Body text on accent-subtle | `ink` #e8eaed | `accent-subtle` #14233a | 13.09 | 4.5 (text) |
| Secondary text on canvas | `ink-muted` #9aa0a8 | `canvas` #0e0f11 | 7.28 | 4.5 (text) |
| Secondary text on surface | `ink-muted` #9aa0a8 | `surface` #17191c | 6.68 | 4.5 (text) |
| Secondary text on track | `ink-muted` #9aa0a8 | `track` #2a2d32 | 5.24 | 4.5 (text) |
| Accent text on canvas | `accent` #6794dc | `canvas` #0e0f11 | 6.25 | 4.5 (text) |
| Accent text on surface | `accent` #6794dc | `surface` #17191c | 5.74 | 4.5 (text) |
| Accent text on track | `accent` #6794dc | `track` #2a2d32 | 4.50 | 4.5 (text) |
| Accent text on accent-subtle | `accent` #6794dc | `accent-subtle` #14233a | 5.14 | 4.5 (text) |
| Button label on accent fill | `on-solid` #0e0f11 | `accent` #6794dc | 6.25 | 4.5 (text) |
| Button label on negative fill | `on-solid` #0e0f11 | `negative` #f87171 | 6.93 | 4.5 (text) |
| positive text on positive-subtle (badge) | `positive` #4ade80 | `positive-subtle` #12301f | 8.21 | 4.5 (text) |
| positive text on surface | `positive` #4ade80 | `surface` #17191c | 10.11 | 4.5 (text) |
| positive text on canvas | `positive` #4ade80 | `canvas` #0e0f11 | 11.00 | 4.5 (text) |
| positive text on track | `positive` #4ade80 | `track` #2a2d32 | 7.93 | 4.5 (text) |
| caution text on caution-subtle (badge) | `caution` #facc15 | `caution-subtle` #3a2f08 | 8.62 | 4.5 (text) |
| caution text on surface | `caution` #facc15 | `surface` #17191c | 11.50 | 4.5 (text) |
| caution text on canvas | `caution` #facc15 | `canvas` #0e0f11 | 12.52 | 4.5 (text) |
| caution text on track | `caution` #facc15 | `track` #2a2d32 | 9.02 | 4.5 (text) |
| warning text on warning-subtle (badge) | `warning` #fb923c | `warning-subtle` #3b2210 | 6.52 | 4.5 (text) |
| warning text on surface | `warning` #fb923c | `surface` #17191c | 7.78 | 4.5 (text) |
| warning text on canvas | `warning` #fb923c | `canvas` #0e0f11 | 8.47 | 4.5 (text) |
| warning text on track | `warning` #fb923c | `track` #2a2d32 | 6.10 | 4.5 (text) |
| negative text on negative-subtle (badge) | `negative` #f87171 | `negative-subtle` #3b1816 | 5.72 | 4.5 (text) |
| negative text on surface | `negative` #f87171 | `surface` #17191c | 6.37 | 4.5 (text) |
| negative text on canvas | `negative` #f87171 | `canvas` #0e0f11 | 6.93 | 4.5 (text) |
| negative text on track | `negative` #f87171 | `track` #2a2d32 | 5.00 | 4.5 (text) |
| positive fill on track (bar, gauge) | `positive` #4ade80 | `track` #2a2d32 | 7.93 | 3 (graphic) |
| caution fill on track (bar, gauge) | `caution` #facc15 | `track` #2a2d32 | 9.02 | 3 (graphic) |
| warning fill on track (bar, gauge) | `warning` #fb923c | `track` #2a2d32 | 6.10 | 3 (graphic) |
| negative fill on track (bar, gauge) | `negative` #f87171 | `track` #2a2d32 | 5.00 | 3 (graphic) |
| positive fill on surface | `positive` #4ade80 | `surface` #17191c | 10.11 | 3 (graphic) |
| caution fill on surface | `caution` #facc15 | `surface` #17191c | 11.50 | 3 (graphic) |
| warning fill on surface | `warning` #fb923c | `surface` #17191c | 7.78 | 3 (graphic) |
| negative fill on surface | `negative` #f87171 | `surface` #17191c | 6.37 | 3 (graphic) |
| Control border on surface | `line-control` #6f757e | `surface` #17191c | 3.79 | 3 (graphic) |
| Focus ring on surface | `accent` #6794dc | `surface` #17191c | 5.74 | 3 (graphic) |
| Control border on canvas | `line-control` #6f757e | `canvas` #0e0f11 | 4.13 | 3 (graphic) |
| Focus ring on canvas | `accent` #6794dc | `canvas` #0e0f11 | 6.25 | 3 (graphic) |
| Text on drawer over black backdrop | `ink` #e8eaed | #121416 | 15.32 | 4.5 (text) |
| Text on drawer over white backdrop | `ink` #e8eaed | #454749 | 7.74 | 4.5 (text) |

### Palette notes
- 20 colour tokens: 6 neutrals (`canvas`, `surface`, `track`, `line-control`, `ink`, `ink-muted`), the accent family (`accent`, `accent-subtle`, `on-solid`), four tones with a subtle background each (8), and three overlays (`material`, `state-hover`, `state-pressed`).
- Each tone is one colour that works as text and as fill, so it needs 4.5:1 on its subtle background, `surface`, `canvas` and `track`, and 3:1 as a fill on `track`.
- Orange exists only as `warning` (#b93c0a light, #fb923c dark). Caution is an amber-brown in light (#854d0e) so it reads as text, and is not orange.
- Disabled controls are exempt from contrast rules; their labels stay legible at `disabled-opacity`.
- Status is never colour-only: each tone is paired with a word, and node kinds with a silhouette and marker shape.


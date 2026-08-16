# UI / UX Design Specification

**Product:** DriftGuard — Multi-User ML Model Monitoring & Data Drift Detection Platform

| Field | Value |
|---|---|
| Document | UIUX_DESIGN |
| Version | 1.0 |
| Direction | Light-first professional SaaS, with a dark-mode toggle |
| Screens | Defined in [APP_FLOW.md](APP_FLOW.md) §1 — this document specifies how they look |
| Depends on | [PRD.md](PRD.md) FR-07 (charts), NFR-10 (offline), NFR-12 (accessibility) |

---

## 1. Design principles

1. **Status is never colour alone.** This product is built out of traffic lights, and red/green is
   the single most common colour-vision deficiency. Every status carries **icon + text label +
   colour**, always all three. Non-negotiable, everywhere.
2. **A number always shows its provenance.** A health score of 74 is meaningless alone, so the
   component breakdown is one click away — never a black box (PRD FR-09.4).
3. **Light-first, because of projectors.** College demo rooms have washed-out projectors where
   dark UIs turn to mud. Light is the default; the dark toggle exists for screenshots and for
   working at night.
4. **Density without clutter.** This is an operator tool. Tables are compact; whitespace is spent
   on grouping, not on decoration.
5. **Offline by construction.** Every font, script and stylesheet is vendored (PRD NFR-10). No
   `<link>` or `<script>` ever points at a remote host.

---

## 2. Design tokens

Declared once as CSS custom properties. Every component references roles, never raw hex.

### 2.1 Theme scaffolding

```css
/* Light is the base definition — never define a colour only inside a media query */
:root {
  color-scheme: light;

  --bg-page:        #F7F8FA;
  --bg-surface:     #FFFFFF;   /* chart surface — the validator ran against this */
  --bg-subtle:      #F2F4F7;
  --bg-hover:       #F9FAFB;

  --border:         #E4E7EC;
  --border-strong:  #D0D5DD;

  --text-primary:   #101828;
  --text-secondary: #475467;
  --text-muted:     #667085;
  --text-inverse:   #FFFFFF;

  --brand:          #4F46E5;
  --brand-hover:    #4338CA;
  --brand-subtle:   #EEF2FF;

  --focus-ring:     #4F46E5;

  --shadow-sm: 0 1px 2px rgba(16,24,40,.05);
  --shadow-md: 0 4px 8px -2px rgba(16,24,40,.10);
  --shadow-lg: 0 12px 16px -4px rgba(16,24,40,.08);
}

/* OS dark, only when the user has not explicitly chosen light */
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { /* …dark values, §2.2… */ }
}

/* Explicit toggle wins in both directions */
:root[data-theme="dark"] { /* …dark values, §2.2… */ }
```

Both dark scopes carry the identical block. This is the three-state rule: an explicit choice
stamps `data-theme`, and the unstamped default falls through to `prefers-color-scheme`.

### 2.2 Dark values

```css
color-scheme: dark;

--bg-page:        #0F1117;
--bg-surface:     #171A21;   /* chart surface — the validator ran against this */
--bg-subtle:      #1D212A;
--bg-hover:       #20242E;

--border:         #262A33;
--border-strong:  #343A45;

--text-primary:   #E6E8EC;
--text-secondary: #A0A6B1;
--text-muted:     #8A909B;
--text-inverse:   #0F1117;

--brand:          #7C82F0;
--brand-hover:    #9299F5;
--brand-subtle:   #1E2130;

--focus-ring:     #7C82F0;
```

### 2.3 Status palette — reserved, never themed, never reused as a series colour

The four status steps are mode-invariant. What changes per mode is the **text** step used when a
status colour must carry small type.

| Role | Maps to | Colour | Light text step | Dark text step |
|---|---|---|---|---|
| good | `NONE` drift · `HEALTHY` · resolved | `#0ca30c` | `#046104` | `#0ca30c` |
| warning | `MODERATE` drift · `WARNING` band | `#fab219` | `#8A5A00` | `#fab219` |
| serious | degraded quality · `ADVISED` retrain | `#ec835a` | `#9A4A22` | `#ec835a` |
| critical | `HIGH` drift · `CRITICAL` band · urgent | `#d03b3b` | `#A32A2A` | `#E86B6B` |

On the light surface, `warning` (1.79:1) and `serious` (2.57:1) sit below 3:1 **by design** — the
icon + label pairing is the mitigation, which is why principle §1.1 is absolute rather than
stylistic. Small text never uses the raw status hex; it uses the text step above.

### 2.4 Categorical series palette — validated, fixed order, never cycled

Used only for data marks that represent **identity** (which series is which).

| Slot | Hue | Light | Dark | Used for |
|---|---|---|---|---|
| 1 | blue | `#2a78d6` | `#3987e5` | Accuracy · Baseline distribution · first class |
| 2 | orange | `#eb6834` | `#d95926` | Precision · Current distribution · second class |
| 3 | aqua | `#1baf7a` | `#199e70` | Recall · third class |
| 4 | yellow | `#eda100` | `#c98500` | F1 · fourth class |

Validator result against this product's own surfaces:

```
light (surface #ffffff): lightness PASS · chroma PASS
                         CVD worst adjacent #eda100↔#1baf7a ΔE 9.1 (protan) PASS
                         normal-vision worst ΔE 22.9 PASS
                         contrast WARN — #1baf7a 2.82:1, #eda100 2.17:1
dark  (surface #171A21): all five checks PASS
```

**The light-mode contrast WARN is an obligation, not a note.** It is discharged by two rules that
are therefore mandatory, not optional:

- every multi-series chart carries **visible direct labels** on its series, and
- every chart has an **accessible table view** of the same data (already PRD FR-07.8).

Hard rules carried from the visualization standard:

- Assign slots in fixed order. A 5th series folds into "Other" — never generate a new hue.
- **No dual-axis charts, anywhere.** Two measures of different scale become two charts.
- Colour follows the entity, not its rank — filtering out a series never repaints the survivors.
- Series colour never carries meaning in text; values and labels wear text tokens.

### 2.5 Sequential ramp (magnitude)

Single hue, blue, light → dark. Used for magnitude encodings such as histogram intensity.

`#cde2fb · #9ec5f4 · #6da7ec · #3987e5 · #2a78d6 · #256abf · #184f95 · #0d366b`

### 2.6 Chart chrome

| Role | Light | Dark |
|---|---|---|
| Gridline (hairline) | `#E4E7EC` | `#262A33` |
| Axis / baseline | `#D0D5DD` | `#343A45` |
| Axis labels | `#667085` | `#8A909B` |
| Tooltip surface | `#101828` | `#E6E8EC` |
| Tooltip text | `#FFFFFF` | `#0F1117` |

### 2.7 Typography

System sans everywhere — no webfont download, no display face, no serif:

```css
--font-sans: system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
--font-mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace;
```

| Token | Size / line-height | Weight | Use |
|---|---|---|---|
| `--fs-hero` | 48 / 56 | 600 | Health score hero figure |
| `--fs-h1` | 28 / 36 | 600 | Page title |
| `--fs-h2` | 20 / 28 | 600 | Section heading |
| `--fs-h3` | 16 / 24 | 600 | Card heading |
| `--fs-body` | 14 / 20 | 400 | Default |
| `--fs-sm` | 13 / 18 | 400 | Table cells, secondary |
| `--fs-xs` | 12 / 16 | 500 | Badges, axis ticks, captions |

`font-variant-numeric: tabular-nums` on table cells, axis ticks and any column of numbers that
must align vertically. The hero figure uses default proportional figures.

### 2.8 Spacing, radius, motion

4px base unit; use 4 · 8 · 12 · 16 · 24 · 32 · 48 · 64.
Radius: `--r-sm 4px` (badges, inputs) · `--r-md 8px` (cards, buttons) · `--r-lg 12px` (modals) · `--r-full` (pills).
Motion: 150 ms `ease-out` for hover and colour, 200 ms for panels. Everything inside
`@media (prefers-reduced-motion: reduce) { animation: none; transition: none; }`.

---

## 3. Layout

```
┌────────────────────────────────────────────────────────────────────────────┐
│ ▣ DriftGuard    [search models]              🔔 3   ◐ theme   ▾ ns (Admin) │ 56px
├────────────┬───────────────────────────────────────────────────────────────┤
│            │  Models / Customer Churn Model / Drift        ← breadcrumb     │
│ ▦ Dashboard│                                                                │
│ ▤ Models   │  ┌─────────────────────────────────────────────────────────┐  │
│ ⚑ Alerts   │  │                                                          │  │
│            │  │            content · max-width 1400px · 24px gutters     │  │
│ ── Admin ──│  │                                                          │  │
│ ⚙ Users    │  └─────────────────────────────────────────────────────────┘  │
│ ⚿ Access   │                                                                │
│ ⏱ Activity │                                                                │
│            │                                                                │
│ ── ─────── │                                                                │
│ ⊙ Profile  │                                                                │
└────────────┴───────────────────────────────────────────────────────────────┘
    240px
```

Sidebar 240px, collapsible to 64px (icons + tooltips). The Admin group renders only for Admin.

**Breakpoints**

| Width | Behaviour |
|---|---|
| ≥ 1280px | Full sidebar; 3-column card grids; charts 2-up |
| 1024–1279 | Full sidebar; 2-column grids |
| 768–1023 | Sidebar collapses to icons; single-column charts |
| < 768 | Sidebar becomes an off-canvas drawer; all cards stack; tables scroll horizontally inside their own `overflow-x:auto` container — **the page body never scrolls horizontally** |

---

## 4. Component inventory

### 4.1 Status badge — the most-used component in the product

```
 ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
 │ ✓  No Drift      │  │ ▲  Moderate      │  │ ✕  High          │
 └──────────────────┘  └──────────────────┘  └──────────────────┘
    good                  warning               critical
```

- Background: status colour at 12% alpha · Border: 1px status at 35% · Icon: full status colour ·
  Text: the mode's status **text step** from §2.3
- Height 24px, radius `--r-full`, padding 2px 10px, `--fs-xs` weight 500
- Icons are distinct **shapes**, not just colours: `✓` circle-check, `▲` warning-triangle,
  `✕` octagon-cross, `–` dash for `INSUFFICIENT_DATA`
- `aria-label` repeats the full status text

Under `forced-colors` and in the exported/print view, the badge falls back to icon + text with a
1px border and no fill.

### 4.2 Stat tile

For a single current value. Never a one-bar bar chart.

```
┌────────────────────────────┐
│ Accuracy                   │  label   --fs-xs muted
│ 0.913            ▼ 2.4 pts │  value   --fs-h1 tabular
│ ▁▂▃▅▆▅▄▃▂▁                 │  sparkline, last 20 runs
└────────────────────────────┘
```
Delta uses the good/critical text steps plus an arrow glyph — never colour alone.

### 4.3 Health score display

Hero figure + meter, because it is a single ratio against a limit.

```
┌──────────────────────────────────────────────┐
│  Model Health                                │
│                                              │
│      74            ▲ Warning                 │
│      ─────                                   │
│      /100                                    │
│                                              │
│  ██████████████████░░░░░░░  74               │
│  0        60      80      100                │
│                                              │
│  Performance   82  ████████████████░░░░  ×40 │
│  Drift         61  ████████████░░░░░░░░  ×30 │
│  Data quality  88  █████████████████░░░  ×20 │
│  Stability     93  ██████████████████░░  ×10 │
│                                              │
│  Weighting: labels present                   │
└──────────────────────────────────────────────┘
```

The meter track is the sequential ramp, not a rainbow. Band boundaries at 60 and 80 are marked on
the axis. The component rows discharge PRD FR-09.4; the weighting line discharges FR-09.5.

### 4.4 Feature drift table

The densest and most important table in the product.

```
┌──────────────────┬────────────┬───────┬──────────┬─────────┬───────┬───────┬──────────────┐
│ Feature        ▲ │ Type       │ Test  │ Statistic│ p-value │ PSI   │ JSD   │ Status       │
├──────────────────┼────────────┼───────┼──────────┼─────────┼───────┼───────┼──────────────┤
│ MonthlyCharges   │ Numeric    │ K-S   │   0.284  │ < 0.001 │ 0.341 │ 0.229 │ ✕ High       │
│ Contract         │ Categorical│ Chi²  │  84.210  │ < 0.001 │ 0.182 │ 0.141 │ ▲ Moderate   │
│ tenure           │ Numeric    │ K-S   │   0.061  │   0.093 │ 0.042 │ 0.031 │ ✓ No Drift   │
│ customerID       │ —          │ —     │      —   │      —  │   —   │   —   │ – Excluded   │
└──────────────────┴────────────┴───────┴──────────┴─────────┴───────┴───────┴──────────────┘
```

- Sortable on every column; default sort worst-drift-first (PRD FR-08.2)
- Numeric columns `tabular-nums`, right-aligned; p-values below 0.001 render as `< 0.001`
- Row hover tints `--bg-hover`; the whole row is a link to S14
- Sticky header on scroll; horizontal scroll inside the card below 1024px

### 4.5 Alert card

```
┌─────────────────────────────────────────────────────────┐
│ ✕ CRITICAL   DRIFT                        16 Aug, 14:05 │
│ Data Drift Detected                                     │
│ Customer Churn Model · MonthlyCharges                   │
│ PSI 0.341 (threshold 0.25)              seen ×14        │
│ [ Acknowledge ]  [ View run → ]                         │
└─────────────────────────────────────────────────────────┘
```
Left border 3px in the severity colour. The occurrence counter makes deduplication (PRD §9.3)
visible rather than merely implemented.

### 4.6 Others

| Component | Specification |
|---|---|
| Button | 36px; primary = `--brand` fill; secondary = surface + border; danger = critical fill; ghost = text only. Disabled 40% opacity + `cursor:not-allowed` |
| Input / select | 36px, 1px `--border`, radius `--r-sm`, focus = 2px `--focus-ring` offset 1px. Errors: critical border + message below, never colour alone |
| File upload | Drag-and-drop zone, dashed 2px border, shows filename + size + a client-side type check before submit |
| Tabs | Underline style, 2px `--brand` on the active tab, keyboard arrow-key navigable |
| Toast | Top-right, `--shadow-lg`, auto-dismiss 5s, inside `aria-live="polite"` |
| Modal | Centred, max-width 560px, focus-trapped, Esc to close, backdrop `rgba(16,24,40,.5)` |
| Empty state | Centred icon + one-line explanation + primary action (copy per [APP_FLOW.md](APP_FLOW.md) §6.3) |
| Progress panel | Indeterminate bar + status text, polls every 2s, offers manual refresh after 120s |
| Pagination | 25 rows/page default, first/prev/next/last, "showing X–Y of Z" |

---

## 5. Chart specifications

Form chosen before colour, in every case.

| PRD | Chart | Form + why | Colour job |
|---|---|---|---|
| FR-07.1 | Performance over time | Multi-line — trend, series are the subject | Categorical slots 1–4 (Accuracy, Precision, Recall, F1) |
| FR-07.2 | Drift over time | Stacked column of feature counts by status + a max-PSI line beneath it — **two charts, never one dual-axis chart** | Status palette (stack); slot 1 blue (line) |
| FR-07.3 | Distribution comparison | Numeric → overlaid histogram on the baseline's bin edges; Categorical → grouped bars of proportions | 2 series: slot 1 = Baseline, slot 2 = Current |
| FR-07.4 | Prediction trend | Stacked area of predicted-class share over time | Categorical, ≤ 4 classes then "Other" |
| FR-07.5 | Alerts over time | Stacked column by severity | INFO = `--text-muted`, WARNING = warning, CRITICAL = critical |
| FR-07.6 | Health over time | Single line with the 60/80 bands as background regions | Slot 1 blue line; bands at 8% alpha status fills |
| — | Feature status trend (S14) | Sparkline of the last 30 runs | Status colour per point |

### 5.1 Mark and anatomy rules

- Lines 2px; markers ≥ 8px on hover; bar data-ends 4px rounded, anchored to the baseline
- 2px surface-coloured gap between stacked segments and between adjacent bars
- Gridlines hairline and recessive — horizontal only, never vertical, never both
- Y-axis starts at zero for bars and counts; line charts may use a fitted range **only** when the
  axis is labelled and the fitted origin is stated
- Selective direct labels: latest point on line charts, largest segment on stacks. **Never a
  number on every point.**
- Legend present whenever ≥ 2 series; absent for one series (the title names it)

### 5.2 Interaction (default, not optional)

- Line/area: crosshair + a single tooltip listing every series at that x
- Bar/column/cell: per-mark hover tooltip
- Tooltip contents: x value, series name, value, and units — values in text tokens with a colour
  swatch carrying identity
- Hit targets larger than the mark
- Filters — the shared time-range control (24h / 7d / 30d / All) — sit in **one row above** the
  chart grid and apply to every time-series chart on the page at once
- Every chart has a **"View as table"** disclosure rendering the same data as an accessible
  `<table>`. This is required (PRD FR-07.8) and additionally discharges the §2.4 contrast
  obligation.

### 5.3 Rendering rules

- Chart.js, vendored at `static/vendor/chartjs/`
- Colours read from CSS custom properties at construction; on theme toggle, charts are re-themed
  and `update()` is called — never destroyed and rebuilt
- Server caps series at 500 points and down-samples beyond that (TRD §10)
- Empty datasets render the empty-state message inside the card, never a blank axis frame
- All canvases live inside a container with an explicit height, so nothing collapses to 0px

### 5.4 Anti-patterns — rejected by name

Dual-axis anything · pie charts (a stacked bar or a table instead) · rainbow sequential ramps ·
a hue at the midpoint of a diverging scale · more than 8 series · generating a 9th colour ·
3D effects · truncated bar baselines · red/green as the sole differentiator · status colours
reused as series colours.

---

## 6. Key screen wireframes

### 6.1 Dashboard — Data Scientist (S2)

```
Dashboard                                          [ 24h | 7d | 30d | All ]

┌─ My Models ──────────────────────────────────────────────────────────────┐
│ ┌──────────────────────┐ ┌──────────────────────┐                         │
│ │ Customer Churn Model │ │ Income Prediction    │                         │
│ │                      │ │                      │                         │
│ │   74  ▲ Warning      │ │   91  ✓ Healthy      │                         │
│ │   ████████████░░░░   │ │   ██████████████████ │                         │
│ │                      │ │                      │                         │
│ │ Drift    ✕ High      │ │ Drift    ✓ No Drift  │                         │
│ │ Version  V2 (active) │ │ Version  V1 (active) │                         │
│ │ Last run 2 min ago   │ │ Last run 5 min ago   │                         │
│ └──────────────────────┘ └──────────────────────┘                         │
└──────────────────────────────────────────────────────────────────────────┘

┌─ Retraining Recommendations ─────────────────────────────────────────────┐
│ ✕ URGENT · Customer Churn Model                                          │
│   3 triggers fired — high drift, accuracy −7.2 pts, health < 60 ×2 runs   │
│   [ Review → ]                                                            │
└──────────────────────────────────────────────────────────────────────────┘

┌─ Health Trend · Customer Churn Model ───────┐ ┌─ Recent Alerts ──────────┐
│ 100 ┤▁▁▁▂▂▁▁                                │ │ ✕ High drift  Monthly…   │
│  80 ┤───────▔▔▔▔▚▖────────── healthy        │ │ ▲ Moderate    Contract   │
│  60 ┤             ▝▚▄▖────── warning        │ │ ▲ Quality degraded       │
│   0 ┤                 ▝▀▄▄                  │ │ ✕ Accuracy −7.2 pts      │
│     └──────────────────────────────────     │ │            [ All → ]     │
│      [ View as table ▾ ]                    │ └──────────────────────────┘
└─────────────────────────────────────────────┘
```

### 6.2 Monitoring run detail (S13) — the centre of gravity

```
Models / Customer Churn Model / Run #218

┌──────────────────────────────────────────────────────────────────────────┐
│  Run #218   ·   16 Aug 2026, 14:05   ·   Scheduled   ·   V2   ·   1.8 s   │
├────────────────┬────────────────┬────────────────┬───────────────────────┤
│ Health         │ Drift          │ Data quality   │ Rows                  │
│ 74 ▲ Warning   │ ✕ High         │ 88 ✓           │ 500  (labels present) │
└────────────────┴────────────────┴────────────────┴───────────────────────┘

┌─ Health breakdown ───────────────────────────────────────────────────────┐
│ Performance 82 ×40 │ Drift 61 ×30 │ Quality 88 ×20 │ Stability 93 ×10     │
└──────────────────────────────────────────────────────────────────────────┘

┌─ Feature Drift  (19 features · 1 high · 3 moderate) ─────────────────────┐
│ …the §4.4 table…                                                         │
└──────────────────────────────────────────────────────────────────────────┘

┌─ Performance ────────────────────────┐ ┌─ Data Quality ──────────────────┐
│ Accuracy  0.842   ▼ 7.2 pts          │ │ Missing        1.8%             │
│ Precision 0.791   Recall  0.706      │ │ Duplicates     4.0%             │
│ F1        0.746   Error   0.158      │ │ Outliers       3.1%             │
│ [confusion matrix]                   │ │ Unseen categories   1 column    │
└──────────────────────────────────────┘ └─────────────────────────────────┘
```

### 6.3 Feature drift detail (S14) — where FR-14 lands

```
Models / Customer Churn Model / Run #218 / MonthlyCharges          ✕ High

┌─ Distribution: baseline vs current ──────────────────────────────────────┐
│                                                                          │
│   ▇▇▇                        ▁▁▂                    ● Baseline (slot 1)  │
│   ▇▇▇▆▆▄▂                  ▂▄▆▇▇▇▆▄                 ● Current  (slot 2)  │
│  ─────────────────────────────────────────────────                       │
│   20    40    60    80   100   120                                       │
│                                     [ View as table ▾ ]                  │
└──────────────────────────────────────────────────────────────────────────┘

┌─ Summary ────────────────┐  ┌─ Scores ─────────────────────────────────┐
│            Base   Current│  │ K-S statistic  0.284                     │
│ Mean      64.80   89.32  │  │ p-value        < 0.001                   │
│ Std       30.09   41.57  │  │ PSI            0.341   (high > 0.25)      │
│ Median    70.35   92.10  │  │ JSD            0.229   (high > 0.20)      │
│ Missing    0.0%    0.2%  │  │                                          │
└──────────────────────────┘  └──────────────────────────────────────────┘

┌─ Why this is flagged ────────────────────────────────────────────────────┐
│ High drift detected in MonthlyCharges. The average rose from 64.80 in the │
│ baseline to 89.32 in this batch (+37.8%), and the spread widened          │
│ (std 30.09 → 41.57). PSI is 0.341, above the high-drift threshold of      │
│ 0.25. The K-S test returns p < 0.001, confirming the distributions differ.│
└──────────────────────────────────────────────────────────────────────────┘

┌─ This feature across the last 30 runs ───────────────────────────────────┐
│ ✓✓✓✓✓✓✓✓✓✓▲▲▲▲▲▲✕✕✕✕✕✕✕✕✕✕✕✕✕✕                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Accessibility

| Requirement | Implementation |
|---|---|
| Contrast | Body text ≥ 4.5:1, large text and UI borders ≥ 3:1, verified in both themes |
| Colour independence | Status = icon + text + colour, always. Charts carry direct labels and a table view |
| Colour-vision deficiency | Series palette validated with the CVD simulator (§2.4). Status shapes differ, not only hues |
| Keyboard | Every interactive element reachable and operable; visible 2px focus ring; logical tab order; modals focus-trapped; skip-to-content link |
| Screen readers | Semantic landmarks; `<table>` with `<caption>` and `<th scope>`; charts carry `role="img"` + `aria-label` summarising the trend, with the table view as the real accessible path |
| Live regions | Toasts and run-status updates in `aria-live="polite"` |
| Motion | All animation suppressed under `prefers-reduced-motion` |
| Zoom | Usable at 200% without horizontal page scroll |
| Forced colours | Status badges fall back to bordered icon + text |

---

## 8. Theme toggle implementation

```html
<!-- in <head>, before any stylesheet — prevents the flash of wrong theme -->
<script>
  (function () {
    var t = localStorage.getItem('driftguard-theme');
    if (t) document.documentElement.setAttribute('data-theme', t);
  })();
</script>
```

Three states: `data-theme="light"`, `data-theme="dark"`, or absent (follow the OS). The header
control cycles Light → Dark → System and writes to `localStorage`. On change it re-reads the
custom properties into every live Chart.js instance and calls `update()`.

---

## 9. Asset inventory (all vendored — PRD NFR-10)

```
static/
├── css/
│   ├── tokens.css        # §2 — the only file containing raw hex
│   ├── base.css          # reset, typography, layout
│   ├── components.css    # §4
│   └── charts.css        # §5
├── js/
│   ├── theme.js          # §8
│   ├── charts.js         # Chart.js factories, token reader, table-view builder
│   ├── polling.js        # run-status polling (APP_FLOW §6.2)
│   └── tables.js         # sorting, sticky headers
└── vendor/
    ├── chartjs/chart.umd.min.js
    └── alpine/alpine.min.js
```

No `<link>` or `<script>` in any template may reference an external host. Fonts are the system
stack, so nothing is downloaded. **Verification step before the demo: disable networking and
load every screen** — this is a checklist item in [APP_FLOW.md](APP_FLOW.md) §8.

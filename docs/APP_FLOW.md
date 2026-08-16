# Application Flow

**Product:** DriftGuard — Multi-User ML Model Monitoring & Data Drift Detection Platform

| Field | Value |
|---|---|
| Document | APP_FLOW |
| Version | 1.0 |
| Scope | What the user sees and does, screen by screen. Server-side mechanics live in [BACKEND_FLOW.md](BACKEND_FLOW.md); visual specification lives in [UIUX_DESIGN.md](UIUX_DESIGN.md) |
| Depends on | [PRD.md](PRD.md) §5 (roles, permission matrix), §6 (functional requirements) |

---

## 1. Screen inventory

Every screen in the product. Nothing else gets built.

| # | Screen | Route | Admin | Data Scientist | ML Engineer |
|---|---|---|---|---|---|
| S1 | Login | `/login/` | ✅ | ✅ | ✅ |
| S2 | Dashboard (role-aware) | `/` | ✅ | ✅ | ✅ |
| S3 | Models list | `/models/` | all | granted | granted |
| S4 | Create / edit model | `/models/new/`, `/models/<slug>/edit/` | ✅ | ✅ | ❌ |
| S5 | Model detail — Overview | `/models/<slug>/` | ✅ | ✅ | ✅ |
| S6 | Model detail — Versions | `/models/<slug>/versions/` | ✅ | ✅ | view only |
| S7 | Upload version | `/models/<slug>/versions/new/` | ✅ | ✅ | ❌ |
| S8 | Upload baseline dataset | `/models/<slug>/baseline/new/` | ✅ | ✅ | ❌ |
| S9 | Model detail — Drift | `/models/<slug>/drift/` | ✅ | ✅ | ✅ |
| S10 | Model detail — Performance | `/models/<slug>/performance/` | ✅ | ✅ | ✅ |
| S11 | Model detail — Data quality | `/models/<slug>/quality/` | ✅ | ✅ | ✅ |
| S12 | Model detail — History | `/models/<slug>/history/` | ✅ | ✅ | ✅ |
| S13 | Monitoring run detail | `/runs/<id>/` | ✅ | ✅ | ✅ |
| S14 | Feature drift detail | `/runs/<id>/features/<name>/` | ✅ | ✅ | ✅ |
| S15 | Upload production batch | `/models/<slug>/batches/new/` | ✅ | ✅ | ✅ |
| S16 | Version comparison | `/models/<slug>/compare/` | ✅ | ✅ | ✅ |
| S17 | Alerts list | `/alerts/` | all | granted | granted |
| S18 | Alert detail | `/alerts/<id>/` | ✅ | ✅ | ✅ |
| S19 | Threshold settings | `/models/<slug>/thresholds/` | ✅ | ✅ | ❌ |
| S20 | Simulator scenarios | `/models/<slug>/simulator/` | ✅ | ✅ | ❌ |
| S21 | Admin — users | `/admin-panel/users/` | ✅ | ❌ | ❌ |
| S22 | Admin — create / edit user | `/admin-panel/users/new/`, `/<id>/edit/` | ✅ | ❌ | ❌ |
| S23 | Admin — model access grants | `/admin-panel/access/` | ✅ | ❌ | ❌ |
| S24 | Admin — login activity | `/admin-panel/activity/` | ✅ | ❌ | ❌ |
| S25 | Profile & password | `/profile/` | ✅ | ✅ | ✅ |
| S26 | Retraining recommendations | `/models/<slug>/recommendations/` | ✅ | ✅ | view only |

S5–S12 share one tabbed shell — the model detail page. Tabs: **Overview · Versions · Drift ·
Performance · Data Quality · History**, plus **Thresholds** and **Simulator** for users with
MANAGE.

---

## 2. Navigation map

```
                            ┌─────────┐
                            │ S1 Login│
                            └────┬────┘
                                 ▼
                         ┌───────────────┐
                    ┌────┤ S2 Dashboard  ├────┐
                    │    └───────┬───────┘    │
                    ▼            ▼            ▼
             ┌────────────┐ ┌─────────┐ ┌───────────┐
             │ S3 Models  │ │S17 Alert│ │S21–24 Admin│ (Admin only)
             └─────┬──────┘ │  list   │ └───────────┘
                   │        └────┬────┘
                   ▼             ▼
        ┌──────────────────┐  ┌──────────┐
        │  Model detail    │  │S18 Alert │──┐
        │  shell (S5–S12)  │  │  detail  │  │
        └───┬──────────────┘  └──────────┘  │
            │                                │
            ├─► S6 Versions ─► S7 Upload version
            ├─► S8 Upload baseline
            ├─► S15 Upload batch ──────┐    │
            ├─► S16 Compare versions   │    │
            ├─► S19 Thresholds         │    │
            ├─► S20 Simulator ─────────┤    │
            ├─► S26 Recommendations    │    │
            └─► S12 History ───────────┤    │
                                       ▼    ▼
                              ┌──────────────────┐
                              │ S13 Run detail   │
                              └────────┬─────────┘
                                       ▼
                              ┌──────────────────┐
                              │ S14 Feature drift│
                              └──────────────────┘
```

Every path that produces or references a monitoring result funnels into **S13**. It is the
centre of gravity of the whole application.

---

## 3. The role-aware dashboard (S2)

One route, three compositions. The role decides which blocks render.

### Admin
1. **Platform summary strip** — total users, active users today, total models, models with an
   unresolved CRITICAL alert
2. **Models needing attention** — models whose latest run is `WARNING` or `CRITICAL`, worst first
3. **Recent login activity** — last 10 events
4. **Recent alerts** — last 10 across all models

> Note: this is the operational summary implied by PRD FR-01 ("Admin can manage users and
> models"). It is **not** the excluded extra E7 admin analytics panel — no fleet-wide trend
> charts, no historical analytics, no per-user usage reporting.

### Data Scientist
1. **My models** — card per granted model: health score gauge, drift status, last run time, active version
2. **Open retraining recommendations** across their models
3. **Health trend** — last 30 runs for the most recently active model
4. **Recent alerts** on their models

### ML Engineer
1. **Model health strip** — one status tile per granted model
2. **Alert queue** — unresolved alerts on granted models, `NEW` first, CRITICAL first
3. **Recent monitoring runs** across granted models
4. **Quick actions** — Upload batch · Run check now

**Empty state (any role, no granted models):** *"No models yet."* Data Scientist and Admin see a
**Create model** button; ML Engineer sees *"Ask an administrator to grant you access to a model."*

---

## 4. Primary user journeys

### J1 — Data Scientist onboards a model (the setup path)

```
S3 Models list
  └─ "New model" → S4
       name, description, problem type, target column, positive class
       └─ Save → model created, creator auto-granted MANAGE
            └─ Redirect S8 Upload baseline dataset
                 upload CSV
                 ├─ parse → infer schema → preview table (first 20 rows)
                 ├─ user confirms/overrides per column: numeric | categorical | exclude
                 │    (IDs and timestamps are auto-suggested for exclusion)
                 ├─ confirm target column
                 └─ Save → profile computed, reference sample stored
                      └─ Redirect S7 Upload version
                           artifact file, changelog, optional training accuracy
                           └─ Save → VALIDATION GATE (PRD §4.3)
                                ├─ FAIL → stay on S7, show which of the 5 checks failed,
                                │         no version record created
                                └─ PASS → version created, status INACTIVE
                                     └─ "Activate" → becomes ACTIVE,
                                                     baseline prediction distribution computed
                                          └─ Model is now monitorable
                                               └─ Redirect S5 Overview
```

**Ordering is enforced:** baseline before version (validation needs baseline rows to test
`.predict()` against), version active before any batch is accepted. The UI blocks out-of-order
steps with an explanatory message rather than a disabled button with no reason given.

### J2 — ML Engineer submits a production batch (the manual path)

```
S5 Overview → "Upload batch" → S15
  ├─ select CSV
  ├─ client-side: extension + size check
  ├─ server: schema validation against the active version's feature_schema
  │    ├─ required feature column missing → REJECTED, batch not processed,
  │    │                                     BATCH_REJECTED alert, reason names the columns
  │    ├─ extra columns → accepted, ignored, noted on the run
  │    └─ target column present → has_labels = true
  └─ accepted → run QUEUED
       └─ progress view polls run status every 2s
            └─ COMPLETED → redirect S13 Run detail
            └─ FAILED    → error panel with the message + RUN_FAILED alert raised
```

### J3 — Unattended monitoring (the scheduled path)

```
S20 Simulator
  ├─ create scenario: name, interval, batch size, include labels?, drift plan
  │     drift plan editor: phases, each with a batch index and a list of transformations
  ├─ "Start" → status RUNNING, first tick scheduled
  └─ live panel (polls every 5s): status, next batch index, last tick, last run result
       │
       ▼  every interval, with no user present
   tick → build batch from holdout + phase transformations
        → ingest_batch()  (identical path to J2 from here on)
        → run persisted, alerts evaluated
        → dashboards reflect it on next poll/reload
```

Controls: **Start · Pause · Resume · Stop · Run one batch now**. Pause preserves
`next_batch_index`; Stop resets it to 0 only if the user confirms.

### J4 — Alert triage (the ML Engineer's daily loop)

```
Header alert badge (count of unresolved)  or  S17 Alerts list
  ├─ filter: model · severity · category · status
  └─ open S18 Alert detail
       ├─ what fired, measured value vs threshold, occurrence count, first/last seen
       ├─ link → S13 Run detail (the run that raised it)
       ├─ link → S14 Feature detail (if feature-scoped)
       └─ actions: Acknowledge → Resolve  (each records actor + timestamp)
```

An alert whose condition clears for N consecutive runs is auto-resolved by the sweep job and
annotated *"Auto-resolved — condition cleared."*

### J5 — Drift investigation (the analytical path, and the demo centrepiece)

```
S13 Run detail
  ├─ header: health score gauge · overall drift badge · quality score · run metadata
  ├─ component breakdown of the health score (never a black box)
  ├─ FEATURE DRIFT TABLE — one row per feature, worst first
  │     Feature | Type | Test | Statistic | p-value | PSI | JSD | Status
  │     (sortable on every column; status = icon + text + colour, never colour alone)
  ├─ data quality panel
  ├─ performance panel (or "No labels in this batch")
  └─ click a feature → S14
        ├─ baseline vs current distribution chart
        │     numeric     → overlaid histograms on the baseline's bin edges
        │     categorical → grouped bars of category proportions
        ├─ side-by-side summary statistics table
        ├─ THE PLAIN-ENGLISH EXPLANATION (PRD FR-14)
        └─ this feature's status across the last 30 runs (sparkline)
```

### J6 — Version comparison

```
S16 Compare
  ├─ two dropdowns, both scoped to this model's versions
  ├─ schema compatibility check
  │     incompatible → notice shown, drift rows suppressed, metric rows still compared
  └─ comparison table: training accuracy · latest metrics · mean metrics ·
     mean health · drifted-feature counts · run count · alert count
     each row marks the better value and the delta
  └─ verdict line: "V2 outperforms V1 on accuracy by 3.1 points across 42 runs."
```

### J7 — Admin manages users and access

```
S21 Users list
  ├─ "New user" → S22 (username, email, role, initial password, active?)
  ├─ row actions: edit · deactivate · reactivate   (never delete — history integrity)
  └─ S23 Access grants
       ├─ grant: user × model × permission (VIEW | MANAGE)
       └─ revoke: immediate; the affected user's next request loses access
S24 Login activity
  └─ table: user · event · IP · user agent · timestamp
     filters: user · event type · date range · paginated
```

---

## 5. State machines

### 5.1 Batch

```
PENDING ─► VALIDATING ─┬─► REJECTED    (schema violation — terminal, no run created)
                       └─► PROCESSING ─┬─► COMPLETED   (run exists)
                                       └─► FAILED      (engine error, run marked FAILED)
```

### 5.2 Monitoring run

```
QUEUED ─► RUNNING ─┬─► COMPLETED
                   └─► FAILED   (error_message stored, RUN_FAILED alert raised)
```

### 5.3 Model version

```
             upload
               │
               ▼
        (validation gate)
          ├─ FAIL → no record created, error shown on the upload form
          └─ PASS → INACTIVE ⇄ ACTIVE ─► ARCHIVED
```
- Exactly one `ACTIVE` per model; activating another demotes the incumbent in the same transaction
- `ARCHIVED` is terminal — readable and comparable, never activatable

### 5.4 Alert

```
NEW ─► ACKNOWLEDGED ─► RESOLVED
 │                        ▲
 └────────────────────────┘  (direct resolve permitted)

Re-fire while unresolved and inside cooldown → occurrence_count += 1, last_seen_at updated
Condition clear for N consecutive runs → auto-resolved by the sweep job
```

### 5.5 Retraining recommendation

```
OPEN ─┬─► ACKNOWLEDGED ─► DISMISSED
      └─► DISMISSED
```
One `OPEN` per model at a time; new triggers update the existing record rather than stacking.

### 5.6 Simulation scenario

```
STOPPED ─► RUNNING ⇄ PAUSED
   ▲          │        │
   └──────────┴────────┘   (Stop from either state)
```

---

## 6. Cross-cutting behaviours

### 6.1 Authorisation failures

| Situation | Behaviour |
|---|---|
| Not logged in | Redirect to `/login/?next=<path>` |
| Logged in, wrong role | 403 page: *"Your role does not permit this action."* |
| Logged in, no grant on the model | 403 page: *"You do not have access to this model."* — **identical page whether or not the model exists**, so URL probing reveals nothing (PRD FR-01.7) |
| Session expired mid-action | Redirect to login preserving `next`; unsaved form data is not recovered (documented limitation) |

### 6.2 Long-running actions

Monitoring runs are asynchronous. The pattern everywhere:

1. Action returns immediately with a run ID and `QUEUED` status
2. A progress panel polls `GET /runs/<id>/status/` every 2 seconds
3. On `COMPLETED`, redirect to S13; on `FAILED`, render the error inline
4. Polling stops after 120 seconds and offers a manual refresh — the page never spins forever

### 6.3 Empty states

Every list defines one. No blank screens.

| Screen | Empty state |
|---|---|
| S3 Models | "No models yet" + Create (if permitted) |
| S9 Drift | "No monitoring runs yet — upload a batch or start the simulator" |
| S10 Performance | "No labelled runs yet. Performance metrics need batches containing the target column." |
| S12 History | "No runs recorded" |
| S17 Alerts | "No alerts — all monitored models are within thresholds" |
| S16 Compare | "This model has only one version. Upload a second version to compare." |
| S26 Recommendations | "No retraining recommended" |

### 6.4 Global elements

- **Header:** product name · global search (models) · unresolved alert badge · theme toggle · user menu
- **Sidebar:** Dashboard · Models · Alerts · (Admin section if Admin) · Profile
- **Breadcrumbs:** on every model-scoped page, e.g. `Models / Customer Churn Model / Drift`
- **Toasts:** success and error confirmations, auto-dismiss after 5s, with an ARIA live region
- The alert badge refreshes with each page load; it is not polled continuously

---

## 7. Form validation rules

| Form | Client-side | Server-side (authoritative) |
|---|---|---|
| Login | required fields | credentials, active flag, lockout state |
| Create model | required name, target column | name unique per owner; target must not collide with a feature name |
| Upload version | extension `.pkl`/`.joblib`, ≤ 100 MB | full PRD §4.3 five-check gate |
| Upload baseline | extension `.csv`, ≤ 50 MB | parseable, target column present, ≥ 100 rows, ≥ 2 classes in target |
| Upload batch | extension `.csv`, ≤ 50 MB | all required feature columns present, ≥ 1 row |
| Thresholds | numeric ranges | moderate < high for every band; α ∈ (0, 1) |
| Scenario | interval 10 s – 24 h, batch size 10 – 10,000 | drift plan references columns that exist in the schema |
| Create user | required, email format | username unique, password policy |

Client-side validation is convenience only. Every rule is re-checked server-side.

---

## 8. Demo script

The sequence to run in a viva. Roughly 8 minutes.

| Step | Action | What it demonstrates |
|---|---|---|
| 1 | Log in as `admin`, show S21/S23/S24 | FR-01 — roles, grants, login audit |
| 2 | Log in as `dsci` — Income model is absent from their list; hit its URL directly → 403 | FR-01.7 — real access control, not hidden buttons |
| 3 | Show S6 Versions: V1, V2, V3 with one ACTIVE | FR-02 |
| 4 | S16 Compare V1 vs V2, read the verdict line | FR-12 |
| 5 | S15 upload a clean test batch → S13 shows all 🟢, health ~90 | FR-04, FR-09, FR-11 — the healthy baseline |
| 6 | S20 start the drift scenario at the demo interval | FR-05 |
| 7 | Watch S5 Overview for ~2 min: health falls, drift badge turns 🟡 then 🔴 | **The centrepiece** — FR-03, FR-05, FR-08 |
| 8 | S13 latest run → feature table, sorted worst-first | FR-08 |
| 9 | S14 on `MonthlyCharges` → distribution chart + plain-English explanation | **FR-14 — the differentiator** |
| 10 | Header badge → S17 → S18: one alert, occurrence count 14, not 14 alerts | FR-06 + dedup |
| 11 | S26 retraining recommendation, listing every trigger with measured vs threshold | FR-10 |
| 12 | S11 Data quality: injected nulls and duplicates detected | FR-11 |
| 13 | S12 History → reopen an early run, show it still reads 🟢 | FR-13.4 — immutable history |
| 14 | Toggle dark mode | UI polish |

**Pre-demo checklist:** scheduler running, interval set to the demo preset, alerts cleared,
scenario reset to batch 0, both browser theme states checked, Wi-Fi off to prove the
no-CDN claim.

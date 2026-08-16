# Implementation Plan

**Product:** DriftGuard — Multi-User ML Model Monitoring & Data Drift Detection Platform

| Field | Value |
|---|---|
| Document | IMPLEMENTATION_PLAN |
| Version | 1.0 |
| Sequencing | Phase-based and dependency-ordered. No calendar dates — effort is expressed in relative points |
| Depends on | [PRD.md](PRD.md), [TRD.md](TRD.md), [APP_FLOW.md](APP_FLOW.md), [UIUX_DESIGN.md](UIUX_DESIGN.md), [BACKEND_FLOW.md](BACKEND_FLOW.md) |

---

## 1. Build strategy

### 1.1 The ordering principle: engine before interface

The statistical engine is built and fully tested **before** any monitoring UI exists. Three
reasons, all practical:

1. **It is the project.** Drift detection is the graded contribution; everything else is
   scaffolding around it. If it is built last it gets built badly.
2. **It is the only part that can be wrong silently.** A broken button is obvious. A PSI that
   divides by zero and returns `inf` looks like a working number until someone checks.
3. **It has no dependencies.** DataFrames in, dicts out — it can be built and tested before a
   single template exists.

### 1.2 Vertical slices after the engine

Once the engine exists, each phase delivers a **complete working slice** — model, service, view,
template, test — rather than "all models, then all views". At the end of every phase the
application runs and demonstrates something new.

### 1.3 Effort points

Relative units, 1 point ≈ half a focused working day. Total **74 points**, of which
**64 are the 14 required features** and 10 are polish and optional work.

---

## 2. Phase overview

| # | Phase | Delivers | Points | Depends on |
|---|---|---|---|---|
| 0 | Foundation | Runnable Django project, tokens, base layout | 4 | — |
| 1 | Auth & users | FR-01 | 6 | 0 |
| 2 | Model registry | FR-02 | 6 | 1 |
| 3 | Datasets & profiling | Baselines, schema, profiles | 5 | 2 |
| 4 | **Drift engine** ⭐ | FR-03, FR-08 (engine half) | 8 | 3 |
| 5 | Quality · performance · health · explain | FR-11, FR-04, FR-09, FR-14 (engine half) | 8 | 4 |
| 6 | Pipeline & batch upload | Ingestion path (a); FR-03/04/08/09/11/14 visible | 7 | 5 |
| 7 | Alerts & retraining | FR-06, FR-10 | 6 | 6 |
| 8 | Simulator & scheduler | FR-05, ingestion path (b) | 7 | 6 |
| 9 | Dashboard & charts | FR-07 | 8 | 7, 8 |
| 10 | Comparison & history | FR-12, FR-13 | 5 | 9 |
| 11 | Polish, seed data, hardening | Demo readiness, a11y, dark mode | 6 | 10 |
| 12 | REST ingestion *(optional)* | ADD-1, path (c) | 4 | 6 |

**Critical path:** 0 → 1 → 2 → 3 → **4 → 5 → 6** → 7/8 → 9 → 10 → 11.
Phases 7 and 8 are independent of each other and can be reordered.

---

## 3. Phases in detail

### Phase 0 — Foundation · 4 pts

**Goal:** an empty but correct skeleton that runs, so no later phase pays setup cost.

- Django project per [TRD.md](TRD.md) §3; settings split `base`/`dev`/`prod`; `.env` handling
- All apps created and registered: `core`, `accounts`, `registry`, `datasets`, `monitoring`, `alerts`, `simulator`, `dashboard`, `apiv1`
- `TimeStampedModel`, `core/constants.py` (every enum in the system, defined once)
- Base template: header, sidebar, breadcrumbs, toast region, theme toggle
- `tokens.css`, `base.css`, `components.css` per [UIUX_DESIGN.md](UIUX_DESIGN.md) §2
- Chart.js and Alpine.js **vendored** into `static/vendor/` — never a CDN link
- pytest + pytest-django + factory_boy configured; ruff + black
- `logs/` rotating handler configured

**Acceptance:** `runserver` serves a themed empty shell; the theme toggle persists across reloads
and survives a hard refresh with no flash; `pytest` runs green with zero tests; the page loads
with networking disabled.

---

### Phase 1 — Authentication, roles, users · 6 pts → **FR-01**

- Custom `User` with `role`; `LoginActivity`; `ModelAccess`
- Login / logout views with lockout (5 failures → 15 min) and identical failure responses
- `LoginActivityMiddleware`
- `RoleRequiredMixin`, `ModelAccessRequiredMixin`, `visible_models()` helper
- Screens S21 (users), S22 (create/edit), S23 (grants), S24 (activity), S25 (profile)
- 403 page that is identical for "no access" and "does not exist"

**Acceptance**
- Every row of the [PRD.md](PRD.md) §5.2 permission matrix has a passing test
- A deactivated user cannot log in
- Six failed logins produce a lockout with the correct message
- Login activity records success, failure and logout with IP and user agent
- Direct-URL access to an ungranted model returns the generic 403

> **Do not move past this phase with permissions "to be tightened later."** Retrofitting
> object-level access control across finished views is where this kind of project leaks.

---

### Phase 2 — Model registry and versions · 6 pts → **FR-02**

- `MLModel`, `ModelVersion`, `ModelAuditLog`
- CRUD for models (S3, S4); creator auto-granted MANAGE
- Version upload (S7) with the **[PRD.md](PRD.md) §4.3 five-check validation gate**
- Activate / deactivate / archive with the single-ACTIVE transaction and partial unique index
- Model history timeline (S5, S6)
- Upload validators: extension, size, MIME sniff, SHA-256

**Acceptance**
- A corrupt `.pkl` is rejected naming the failed check, and creates no version row
- A valid artifact whose `.predict()` fails on baseline columns is rejected at upload, not at run time
- Activating V2 demotes V1 in one transaction; no state exists with two ACTIVE versions
- Every state change appears in the audit timeline with actor and timestamp

---

### Phase 3 — Datasets and profiling · 5 pts

- `BaselineDataset`; CSV upload (S8) with preview of the first 20 rows
- Schema inference: numeric vs categorical by dtype **and** cardinality (> 10 unique → numeric),
  with per-column user override and auto-suggested exclusions for ID/timestamp columns
- `engine/profiling.py`: quantile bins (10) with **stored edges**, category frequencies, summary stats
- Reference sample: ≤ 50,000 rows, `random_state=42`, parquet
- `DataBatch` model (upload UI comes in Phase 6)

**Acceptance**
- Uploading the Telco CSV produces a correct schema with `SeniorCitizen` classified categorical
  and `customerID` auto-suggested for exclusion
- The stored profile round-trips through JSON with no precision loss
- Re-profiling the same file twice produces byte-identical output

---

### Phase 4 — Drift engine ⭐ · 8 pts → **FR-03, FR-08 (engine)**

**The most important phase in the project.** Pure Python, no Django, no UI.

- `engine/drift.py` complete: `ks_test`, `chi_square_test`, `population_stability_index`,
  `jensen_shannon_divergence`, `classify_feature`, `analyse_features`, `rollup`
- ε-smoothing on PSI; `__OTHER__` merging for low-expected-count Chi-Square categories;
  batches binned on **baseline** edges; both sides capped at 50k with a fixed seed
- [PRD.md](PRD.md) §7.3 combination rule and §7.4 roll-up implemented exactly
- All nine mandatory engine tests from [TRD.md](TRD.md) §11
- The import-guard test asserting `engine/` imports no Django

**Acceptance**
- ≥ 90% line coverage on `engine/drift.py`
- Identical baseline and batch → PSI 0.0, JSD 0.0, `NONE`
- 2σ mean shift → `HIGH`, PSI > 0.25, KS p < 0.05
- Empty bins → finite PSI, no `inf`, no `NaN`
- 100k-row batch with a 0.001 mean difference → p < 0.05 but status `NONE`
  *(this test is the proof that §7.3 works — keep it visible for the viva)*
- n < 30 → `INSUFFICIENT_DATA` and excluded from the roll-up

---

### Phase 5 — Quality, performance, health, explanations · 8 pts → **FR-11, FR-04, FR-09, FR-14 (engine)**

- `engine/quality.py` — all six checks; IQR bounds from **baseline** quartiles; §8.5 score
- `engine/performance.py` — scoring, metrics with `zero_division=0`, positive-class **and** macro,
  confusion matrix, prediction distribution always computed
- `engine/health.py` — §8 exactly, including the labels-absent weight redistribution
- `engine/explain.py` — deterministic numeric and categorical templates
- `engine/pipeline.py` — `run_monitoring()`, the single convergence point

**Acceptance**
- Quality: an injected 5% null rate and 4% duplicate rate are both detected with correct percentages
- Performance: a batch with no target column returns `None` metrics, never `0`
- Health: the same inputs with and without labels produce different, correctly-weighted scores,
  and the returned dict names the weighting used
- Explanations: identical inputs produce byte-identical sentences on repeated calls
- `run_monitoring()` executes end-to-end on real Telco data in a plain pytest, with no database

---

### Phase 6 — Pipeline wiring and batch upload · 7 pts → ingestion path (a)

The phase where the project becomes visible.

- `monitoring` models: `MonitoringRun`, `FeatureDriftResult`, `DataQualityReport`, `PerformanceSnapshot`
- `monitoring/services.py::ingest_batch()` — the full [BACKEND_FLOW.md](BACKEND_FLOW.md) §4 sequence,
  including transaction boundaries, per-model lock, and `thresholds_snapshot`
- Artifact LRU cache
- Batch upload UI (S15) with schema validation and rejection messaging
- Run detail (S13) and feature detail (S14) screens
- Status polling endpoint and progress panel

**Acceptance**
- Upload a drifted CSV → run completes → S13 shows the feature table with correct statuses
- S14 shows the distribution chart and the generated explanation
- A batch missing a required column is REJECTED with the column named, and no run is created
- A run that raises is marked FAILED with the message stored; the app stays up
- Two simultaneous uploads for one model do not run concurrently
- A run's stored `thresholds_snapshot` is populated and non-empty

---

### Phase 7 — Alerts and retraining · 6 pts → **FR-06, FR-10**

- `ThresholdProfile` with global → model → code-default resolution; settings UI (S19)
- `Alert` with the full lifecycle; `alerts/services.py::evaluate()` with dedup + cooldown
- Alerts list (S17) and detail (S18); header badge
- Auto-resolution sweep
- `RetrainRecommendation`, trigger evaluation, screen S26
- Email: console backend by default, SMTP behind config, CRITICAL only, failures swallowed

**Acceptance**
- 20 consecutive high-drift runs produce **one** alert with `occurrence_count == 20`
- An alert auto-resolves after 3 clean runs and is annotated as auto-resolved
- A retraining recommendation lists every trigger with measured value and threshold
- A second trigger event updates the existing OPEN recommendation instead of creating a second
- With `EMAIL_ENABLED=False` everything works and nothing is sent
- With SMTP misconfigured, the run still completes and the failure is logged only

---

### Phase 8 — Simulator and scheduler · 7 pts → **FR-05**, ingestion path (b)

- `SimulationScenario` + drift-plan JSON schema and validation
- All six transformation types
- APScheduler wiring with the `RUN_MAIN` guard, `max_instances=1`, `coalesce=True`
- Scenario UI (S20): create, edit drift plan, start / pause / resume / stop, live status panel
- **"Run check now"** action available from S5, S15 and S20
- Seeded batch generation so replays are reproducible

**Acceptance**
- A scenario configured to shift `MonthlyCharges` from batch 10 produces runs progressing
  `NONE → MODERATE → HIGH` with no user interaction
- Restarting the server mid-scenario resumes at the correct `next_batch_index`
- Exactly one tick fires per interval under `runserver` **with** the reloader active
- A tick arriving during an in-progress run is skipped and logged, not queued
- An exception inside a tick does not stop the scheduler; the next tick runs

---

### Phase 9 — Dashboard and charts · 8 pts → **FR-07**

- Seven JSON chart endpoints ([BACKEND_FLOW.md](BACKEND_FLOW.md) §10) with 500-point down-sampling
- `static/js/charts.js`: factories reading CSS custom properties, tooltip config, table-view builder
- All six required charts per [UIUX_DESIGN.md](UIUX_DESIGN.md) §5
- Role-aware dashboard (S2) in its three compositions
- Model tabs S9, S10, S11
- Shared time-range control
- **"View as table"** on every chart

**Acceptance**
- Unlabelled runs appear as **gaps** in performance charts, never interpolated and never zero
- Theme toggle re-themes live charts via `update()`, with no rebuild and no flash
- No chart uses two y-axes anywhere
- Every chart has a hover tooltip and a working table view
- Dashboard renders in under 3 s with 500 runs in the database

---

### Phase 10 — Version comparison and history · 5 pts → **FR-12, FR-13**

- Comparison service and screen (S16), including the schema-compatibility check
- Verdict line generation
- History tab (S12) with filters, pagination, and CSV export
- Immutability verification: a historical run re-read after a threshold change is unchanged

**Acceptance**
- V1 vs V2 compares correctly, marks the better value per row, and states the delta
- Comparing incompatible schemas shows the notice and suppresses drift rows
- Changing a threshold does not alter any stored historical status
- CSV export opens correctly in a spreadsheet

---

### Phase 11 — Polish, seed data, hardening · 6 pts

- `scripts/prepare_datasets.py` — fetch and split Telco + Adult (60/20/20)
- `scripts/train_demo_models.py` — Telco V1 LogReg, V2 RandomForest, V3 GradientBoosting;
  Adult V1 RandomForest. **All exported as sklearn `Pipeline` objects accepting raw columns**
  (PRD assumption A2 — get this wrong and every artifact fails the §4.3 gate)
- `scripts/seed_demo.py` — users of all three roles, models, grants, baselines, versions,
  thresholds, a ready drift scenario
- Accessibility pass: contrast in both themes, keyboard traversal, focus rings, ARIA labels,
  status badges verified as icon + text + colour everywhere
- Responsive pass at 1280 / 1024 / 768 / 375
- Empty states for every list ([APP_FLOW.md](APP_FLOW.md) §6.3)
- README with setup, demo script, and architecture notes
- **Offline verification: disable networking, load every screen**

**Acceptance**
- A clean clone reaches a fully seeded, demo-ready state in five commands
- Every screen renders correctly in both themes at all four breakpoints
- The [APP_FLOW.md](APP_FLOW.md) §8 demo script runs start to finish without a hitch
- The whole application works with networking disabled

---

### Phase 12 — REST ingestion *(optional)* · 4 pts → ADD-1

- Per-model API keys, hashed at rest, shown once
- `POST /api/v1/models/<uuid>/batches/` calling the **same** `ingest_batch`
- Rate limiting, 10k-row cap, error contract
- Endpoint documentation with a `curl` example

**Cut this first if effort runs short.** It is not one of the 14 required features.

---

## 4. Definition of done

A phase is complete only when **all** of the following hold:

1. Every acceptance criterion in the phase passes
2. Tests written in the same phase, not deferred — engine ≥ 90%, services ≥ 75%
3. `ruff` and `black` clean
4. No `TODO`, no commented-out code, no `print()`
5. Every new view has a permission test
6. Migrations committed and applied from a clean database without error
7. The relevant document is updated if the phase changed a decision

---

## 5. Testing gates

| Gate | Point | Blocks |
|---|---|---|
| Engine unit tests | End of Phase 5 | Phase 6 |
| Permission matrix tests | End of Phase 1 | Phase 2 |
| Pipeline integration test | End of Phase 6 | Phase 7 |
| Scheduler restart test | End of Phase 8 | Phase 9 |
| Full demo-script run | End of Phase 11 | Delivery |

---

## 6. Risk register

| # | Risk | Phase | Mitigation |
|---|---|---|---|
| I1 | Demo artifacts are bare estimators, not Pipelines → every upload fails the §4.3 gate | 11 | Training script exports Pipelines; a Phase 11 test uploads each artifact through the real gate |
| I2 | Scheduler double-fires under the autoreloader | 8 | `RUN_MAIN` guard; explicit acceptance test with the reloader **on** |
| I3 | PSI returns `inf` on empty bins | 4 | ε-smoothing + a dedicated test |
| I4 | KS flags trivial differences on large batches | 4 | §7.3 combination rule + the 100k-row acceptance test |
| I5 | Alert flood from a fast simulator | 7 | Dedup + cooldown; the 20-run acceptance test |
| I6 | Charts unreadable in dark mode | 9 | Palette validated against both surfaces before any chart is coded (done — [UIUX_DESIGN.md](UIUX_DESIGN.md) §2.4) |
| I7 | SQLite lock contention between scheduler and web | 6, 8 | WAL, short transactions, engine outside transactions, one worker |
| I8 | Object-level permissions retrofitted late | 1 | Built in Phase 1; `visible_models()` used by every queryset from then on |
| I9 | A 1-hour interval makes the demo unwatchable | 8 | Demo preset + "Run check now" + configurable interval |
| I10 | Dataset download fails on the demo machine | 11 | Datasets committed to the repo, or the prepare script caches locally with a documented fallback |

---

## 7. Descoping ladder

If effort runs short, cut **strictly in this order**. Everything above the line is one of the 14
required features and is not negotiable without the client's agreement.

| Order | Cut | Cost of cutting |
|---|---|---|
| 1 | Phase 12 REST endpoint | None — explicitly optional |
| 2 | CSV export of history (FR-13.5) | Minor |
| 3 | Email delivery (FR-06.6, already optional) | Minor — in-app alerts unaffected |
| 4 | Sidebar collapse and the 375px breakpoint | Cosmetic |
| 5 | Auto-resolution sweep | Alerts must be resolved manually |
| ——— | **line — below here requires client sign-off** | |
| 6 | Adult Income second model | Weakens the access-control demonstration |
| 7 | Third Telco version (V3) | FR-12 still works with two versions |

**Never cut:** the drift engine, feature-level analysis, the health score, explanations, alerts,
or the periodic monitoring loop. Those are the graded contribution.

---

## 8. Delivery checklist

- [ ] All 14 numbered features implemented and individually demonstrable
- [ ] Permission matrix fully enforced and tested
- [ ] Engine coverage ≥ 90%
- [ ] Demo script ([APP_FLOW.md](APP_FLOW.md) §8) runs clean end to end
- [ ] Both themes verified at all breakpoints
- [ ] Application verified working with networking disabled
- [ ] Seed script produces a demo-ready state from a clean database
- [ ] README complete: setup, demo script, architecture
- [ ] Known limitations documented — pickle risk, single worker, labels assumption
- [ ] All six foundation documents updated to match what was actually built

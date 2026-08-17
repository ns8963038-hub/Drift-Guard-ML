# Work Split — Two Developers

**Product:** DriftGuard — Multi-User ML Model Monitoring & Data Drift Detection Platform

| Field | Value |
|---|---|
| Document | WORK_SPLIT |
| Version | 1.0 |
| Track A — Data & Detection | **Nandan** |
| Track B — Platform & Presentation | **Suhas** |
| Total effort | 76 points (38 each), 1 point ≈ half a focused working day |

> **Suhas — read this document first, then §2 for your reading list.** You do not need to read the
> whole specification before starting. §5 tells you exactly what to build, in order.

---

## 1. What the product is (60 seconds)

A web platform where a team uploads trained ML models along with the data those models were
trained on, then feeds in new production data over time. For every new batch of data the platform
answers four questions:

1. Is the incoming data clean? *(data quality)*
2. Does it still look like the training data? *(**data drift** — the core feature)*
3. Is the model still accurate? *(performance)*
4. Overall, how healthy is this model right now? *(0–100 health score)*

…then raises alerts when thresholds break, explains *why* in plain English, and recommends
retraining. It never trains or retrains anything itself.

Full detail: [PRD.md](PRD.md) §1.

---

## 2. Reading list for Track B

Read in this order. You can skip everything else for now.

| Order | Document | Sections | Why |
|---|---|---|---|
| 1 | [PRD.md](PRD.md) | §4 glossary, §5 roles & permission matrix | The vocabulary and the access rules you implement |
| 2 | [APP_FLOW.md](APP_FLOW.md) | All of it | Every screen you build is listed here |
| 3 | [UIUX_DESIGN.md](UIUX_DESIGN.md) | All of it | Design tokens, components, chart specs — this is your build spec |
| 4 | [TRD.md](TRD.md) | §1 stack, §3 structure, §4 data model | What to install, where files go, what the tables are |
| 5 | [BACKEND_FLOW.md](BACKEND_FLOW.md) | §2 request lifecycle, §3 auth, §5 alerts | How your layers fit together |
| 6 | [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Phases 0, 1, 2, 7, 9, 10 | Your phases, with acceptance criteria |

**Do not read** [PRD.md](PRD.md) §7–§10 (drift maths, health formulas) or
[BACKEND_FLOW.md](BACKEND_FLOW.md) §4 (the monitoring pipeline). That is Track A's half and you
never need to touch it.

---

## 3. Directory ownership

**The rule that stops two people fighting in git: you own whole directories. Never edit the other
person's folders.**

| Track B — Suhas owns | Track A — Nandan owns |
|---|---|
| `config/` (project settings, urls) | `monitoring/` (including `engine/`) |
| `core/` | `datasets/` |
| `accounts/` | `simulator/` |
| `registry/` | `scripts/` |
| `alerts/` | |
| `dashboard/` | |
| `templates/`, `static/` | |

**Shared files** — `config/settings/`, `config/urls.py`, `core/constants.py`,
`templates/base.html`. Suhas owns these, but Track A depends on them. Changes go in **small,
dedicated commits with a message saying what changed**, never buried inside a large feature
commit.

Track A adds its own templates under `templates/monitoring/`, `templates/datasets/`,
`templates/simulator/` — separate files, extending `base.html`. No conflict.

---

## 4. The two tracks at a glance

| | Track A — Nandan | Track B — Suhas |
|---|---|---|
| **Theme** | The statistics and the data pipeline | The application and everything the user sees |
| **Skills** | pandas, numpy, scipy, scikit-learn | Django views, forms, templates, CSS, Chart.js |
| **Phases** | 3, 4, 5, 6, 8 + data scripts | 0, 1, 2, 7, 9, 10 + polish |
| **Points** | 38 | 38 |
| **Builds** | Profiling, drift engine, quality, performance, health score, explanations, `ingest_batch()`, run + feature detail screens, simulator, scheduler | Foundation, auth & roles, model registry, alerts & retraining, dashboard & all charts, version comparison, history |

---

## 5. Track B — Suhas's work, phase by phase

### Phase 0 — Foundation · 4 points · **DO THIS FIRST**

**Everything else in the project waits on this.** Build it, get it green, push it the same day if
you can. Track A can start in parallel — the drift engine is plain Python with no Django — but
nobody can integrate until Phase 0 lands.

**Build:**

```
manage.py
requirements.txt          .env.example          pytest.ini
config/settings/base.py   config/settings/dev.py  config/settings/prod.py
config/urls.py            config/wsgi.py
core/models.py            core/constants.py       core/mixins.py  core/validators.py
templates/base.html
static/css/tokens.css     static/css/base.css     static/css/components.css
static/js/theme.js
static/vendor/chartjs/    static/vendor/alpine/
logs/
```

**Tasks:**

1. Django project + **all nine apps** created and registered in `INSTALLED_APPS`:
   `core`, `accounts`, `registry`, `datasets`, `monitoring`, `alerts`, `simulator`, `dashboard`, `apiv1`
   — create Track A's apps too, empty. It costs you five minutes and unblocks them immediately.
2. `core/models.py` → `TimeStampedModel` abstract base (`created_at`, `updated_at`).
3. **`core/constants.py` — every enum in the whole system, defined once.** See §5.1 below. Both
   tracks import from here, so a missing enum blocks Track A.
4. `templates/base.html` — header (product name, search box, alert badge, theme toggle, user
   menu), sidebar nav, breadcrumbs block, toast region, content block.
5. CSS from [UIUX_DESIGN.md](UIUX_DESIGN.md) §2 — `tokens.css` is the **only** file allowed to
   contain raw hex values. Everything else references custom properties.
6. `static/js/theme.js` + the inline head script from [UIUX_DESIGN.md](UIUX_DESIGN.md) §8 (prevents
   the flash of wrong theme on load).
7. **Download and commit Chart.js and Alpine.js into `static/vendor/`.** Never a CDN link — the
   demo must work with Wi-Fi switched off.
8. pytest + pytest-django + factory_boy; ruff + black; rotating log handler.

**Acceptance:**
- `runserver` serves a themed empty shell with working sidebar and header
- Theme toggle cycles Light → Dark → System, persists across reloads, no flash on hard refresh
- `pytest` runs green (zero tests is fine)
- **Every page loads with networking disabled**

#### 5.1 The enums for `core/constants.py`

Define all of these in Phase 0. Track A imports them on day one.

| Enum | Values |
|---|---|
| `Role` | `ADMIN`, `DATA_SCIENTIST`, `ML_ENGINEER` |
| `Permission` | `VIEW`, `MANAGE` |
| `ProblemType` | `BINARY`, `MULTICLASS` |
| `VersionStatus` | `INACTIVE`, `ACTIVE`, `ARCHIVED` |
| `ValidationStatus` | `PENDING`, `PASSED`, `FAILED` |
| `BatchSource` | `UPLOAD`, `SIMULATOR`, `API` |
| `BatchStatus` | `PENDING`, `VALIDATING`, `PROCESSING`, `COMPLETED`, `FAILED`, `REJECTED` |
| `RunStatus` | `QUEUED`, `RUNNING`, `COMPLETED`, `FAILED` |
| `TriggerSource` | `MANUAL`, `SCHEDULED`, `UPLOAD`, `API` |
| `FeatureType` | `NUMERIC`, `CATEGORICAL` |
| `TestName` | `KS`, `CHI2` |
| `DriftStatus` | `NONE`, `MODERATE`, `HIGH`, `INSUFFICIENT_DATA` |
| `HealthBand` | `HEALTHY`, `WARNING`, `CRITICAL` |
| `AlertSeverity` | `INFO`, `WARNING`, `CRITICAL` |
| `AlertCategory` | `DRIFT`, `PERFORMANCE`, `QUALITY`, `HEALTH`, `RETRAIN`, `SYSTEM` |
| `AlertStatus` | `NEW`, `ACKNOWLEDGED`, `RESOLVED` |
| `RetrainSeverity` | `ADVISED`, `URGENT` |
| `RetrainStatus` | `OPEN`, `ACKNOWLEDGED`, `DISMISSED` |
| `ScenarioStatus` | `STOPPED`, `RUNNING`, `PAUSED` |
| `LoginEvent` | `LOGIN_SUCCESS`, `LOGIN_FAILED`, `LOGOUT` |

---

### Phase 1 — Authentication, roles, permissions · 6 points → PRD FR-01

> ⚠️ **Set `AUTH_USER_MODEL = "accounts.User"` in settings BEFORE running your first
> `migrate`.** Django makes this extremely painful to change after any migration has been applied.
> If you have already migrated, delete `db.sqlite3` and all migration files and start over — it is
> far quicker than the alternative.

**Build:**

- `accounts/models.py`
  - `User(AbstractUser)` — `role`, `failed_login_count`, `locked_until`
  - `LoginActivity` — `user` (nullable), `username_attempted`, `event`, `ip_address`, `user_agent`, `occurred_at`
  - `ModelAccess` — `user`, `ml_model` (use the string reference `"registry.MLModel"`), `permission`, `granted_by`, `granted_at`, `unique_together(user, ml_model)`
- Login / logout views with the flow in [BACKEND_FLOW.md](BACKEND_FLOW.md) §3
- Account lockout: 5 failures → 15 minutes
- `LoginActivityMiddleware`
- `core/mixins.py`:
  - `RoleRequiredMixin` — checks role against the [PRD.md](PRD.md) §5.2 matrix
  - `ModelAccessRequiredMixin` — checks the grant
  - `visible_models(user)` — **the single helper every model-scoped queryset in the project uses**
- Screens: S21 users list · S22 create/edit user · S23 access grants · S24 login activity · S25 profile
- A 403 page that is **identical** whether the model does not exist or the user lacks access

**Two things that are easy to get wrong:**

1. Login failure messages must be **identical** for "no such user" and "wrong password", or the
   form becomes a username enumerator.
2. Filter querysets with `visible_models()`. Do not check permissions only in the template — a
   hidden button is not access control, and list views leak objects that way.

**Acceptance:**
- Every row of the [PRD.md](PRD.md) §5.2 permission matrix has a passing test
- A deactivated user cannot log in
- Six failed logins produce a lockout with the right message
- An ML Engineer granted Model A and not Model B gets a 403 on Model B **by direct URL**
- Login activity records success, failure and logout with IP and user agent

---

### Phase 2 — Model registry and versions · 6 points → PRD FR-02

**Build:**

- `registry/models.py` — `MLModel`, `ModelVersion`, `ModelAuditLog` ([TRD.md](TRD.md) §4.2)
- Model CRUD — S3 list, S4 create/edit. Creator is auto-granted `MANAGE`.
- Version upload S7 with the **five-check validation gate** ([PRD.md](PRD.md) §4.3):
  1. Deserialises via `joblib.load`
  2. Has a callable `.predict()`
  3. Predicts successfully on 50 baseline rows
  4. Output length equals input length
  5. Output classes are a subset of the baseline target's classes
- Activate / deactivate / archive with the single-`ACTIVE` transaction + partial unique index
- Model history timeline (S5 overview, S6 versions)
- Upload validators: extension allowlist (`.pkl`, `.joblib`), 100 MB cap, MIME sniff, SHA-256

**Cross-track dependency — read carefully.** Checks 3 and 5 need baseline data, which lives in
Track A's `datasets/` app. Do not read those files yourself. Call:

```python
from datasets.services import get_validation_sample
sample_df, target_classes = get_validation_sample(ml_model, n=50)
```

Track A owns and delivers that function (contract C1 in §6). Until it exists, stub it locally and
carry on — do not block.

Version **activation** also has to compute the baseline prediction distribution. Again, call
Track A's function, do not implement it:

```python
from monitoring.services import compute_baseline_prediction_distribution
compute_baseline_prediction_distribution(version)   # contract C2
```

**Acceptance:**
- A corrupt `.pkl` is rejected naming the failed check, and **creates no version row**
- A valid artifact whose `.predict()` fails on baseline columns is rejected at upload, not later
- Activating V2 demotes V1 in one transaction; no state ever has two `ACTIVE` versions
- Every state change appears in the audit timeline with actor and timestamp

---

### Phase 7 — Alerts and retraining · 6 points → PRD FR-06, FR-10

**Build:**

- `alerts/models.py` — `ThresholdProfile`, `Alert`, `RetrainRecommendation` ([TRD.md](TRD.md) §4.5)
- Threshold resolution order: **model profile → global profile → code defaults**
- `alerts/services.py::evaluate(run)` — the rules in [PRD.md](PRD.md) §9.1, with **deduplication
  and cooldown** ([BACKEND_FLOW.md](BACKEND_FLOW.md) §5.1)
- `alerts/services.py::sweep()` — auto-resolve alerts whose condition cleared for 3 runs
- `alerts/retrain.py::evaluate_retrain(run)` — triggers in [PRD.md](PRD.md) §10
- Screens: S17 alerts list · S18 alert detail · S19 threshold settings · S26 recommendations
- Header alert badge (unresolved count)
- Email: console backend by default, SMTP behind config, `CRITICAL` only, **failures logged and
  swallowed — never raise**

**Deduplication is not optional.** Track A's simulator produces a batch every 30 seconds. Without
dedup you get hundreds of identical alerts within minutes and the alerts screen becomes useless.
Key on `(model, category, feature_name)`; while an unresolved alert with that key exists inside
the cooldown window, increment `occurrence_count` and update `last_seen_at` instead of inserting
a new row.

**Cross-track:** Track A calls your `evaluate(run)` and `evaluate_retrain(run)` at the end of the
monitoring pipeline (contracts C5, C6). You expose them; Track A wires them. Track A also
registers your `sweep()` on its scheduler.

**Acceptance:**
- 20 consecutive high-drift runs produce **one** alert with `occurrence_count == 20`
- An alert auto-resolves after 3 clean runs, annotated "Auto-resolved — condition cleared"
- A retraining recommendation lists every trigger with its measured value **and** its threshold
- A second trigger event updates the existing `OPEN` recommendation instead of creating a second
- With `EMAIL_ENABLED=False` everything works and nothing is sent
- With SMTP deliberately misconfigured, the run still completes and only a warning is logged

---

### Phase 9 — Dashboard and charts · 8 points → PRD FR-07

The most visible phase in the project. Build spec is [UIUX_DESIGN.md](UIUX_DESIGN.md) §5.

**Build:**

- Seven JSON endpoints ([BACKEND_FLOW.md](BACKEND_FLOW.md) §10), each capped at 500 points with
  server-side down-sampling
- `static/js/charts.js` — Chart.js factories that read colours from CSS custom properties, shared
  tooltip config, and the "View as table" builder
- Six charts: performance over time · drift over time · distribution comparison · prediction trend
  · alerts over time · health over time
- Role-aware dashboard S2 in its **three** compositions (Admin / Data Scientist / ML Engineer —
  [APP_FLOW.md](APP_FLOW.md) §3)
- Model detail tabs S9 Drift · S10 Performance · S11 Data Quality
- Shared time-range control (24h / 7d / 30d / All) applying to every chart on the page

**Non-negotiable chart rules** (from [UIUX_DESIGN.md](UIUX_DESIGN.md) §2.4 and §5.1 — these were
validated with a colour-blindness checker, so please don't substitute your own palette):

1. **No dual-axis charts anywhere.** Two measures of different scale = two charts.
2. Use the categorical palette in **fixed slot order**: blue → orange → aqua → yellow. Never cycle,
   never generate a 5th colour — fold extras into "Other".
3. Status colours (green/amber/red) are **reserved** for drift and health status. Never reuse one
   as a series colour.
4. **Status is never colour alone** — always icon + text label + colour. Roughly 8% of men have
   red-green colour deficiency, and this product is built entirely out of traffic lights.
5. Every chart needs a hover tooltip **and** a "View as table" disclosure. The table is a hard
   requirement, not a nice-to-have — two of the light-mode palette colours sit below 3:1 contrast
   and the table view is what makes that acceptable.
6. Unlabelled runs render as **gaps** in performance charts — never interpolated, never zero.

**Cross-track:** you read Track A's `MonitoringRun`, `FeatureDriftResult`, `DataQualityReport`,
`PerformanceSnapshot` models directly via the ORM (contract C3). You do not call the engine.

**Acceptance:**
- Theme toggle re-themes live charts via `update()` — no rebuild, no flash
- Unlabelled runs appear as gaps
- Every chart has a tooltip and a working table view
- Dashboard renders in under 3 seconds with 500 runs in the database

---

### Phase 10 — Version comparison and history · 5 points → PRD FR-12, FR-13

**Build:**

- S16 comparison — two versions of the **same** model, side by side
  ([BACKEND_FLOW.md](BACKEND_FLOW.md) §9)
- Schema-compatibility check: if the two versions' feature schemas differ, show a notice and
  suppress the drift rows, but still compare the metrics
- Mark the better value in each row, with the delta
- Verdict line: *"V2 outperforms V1 on accuracy by 3.1 points across 42 runs."*
- S12 history — filters (date, status, drift status, trigger source), pagination, CSV export

**Immutability:** historical runs must never change. Each run stores the thresholds it was judged
under, so editing a threshold today leaves last week's results exactly as they were. Write a test
for this.

**Acceptance:**
- Comparison marks the better value per row and states the delta
- Incompatible schemas show the notice and suppress drift rows
- Changing a threshold alters **no** stored historical status
- CSV export opens cleanly in a spreadsheet
- Rows where a version has no labelled runs show "insufficient data", never `0`

---

### Phase 11 (Track B share) — polish · 3 points

- Accessibility pass: contrast in both themes, keyboard traversal, visible focus rings, ARIA
  labels, every status badge verified as icon + text + colour
- Responsive pass at 1280 / 1024 / 768 / 375 px
- Empty states for every list ([APP_FLOW.md](APP_FLOW.md) §6.3) — no blank screens anywhere
- `scripts/seed_demo.py` — users of all three roles, models, grants, thresholds
  *(depends on Track A's dataset and model-training scripts)*
- README: setup, demo script, architecture notes

---

## 6. The interface between the two tracks

Everything crossing the boundary goes through these seven contracts. Agree on them once; then
neither person needs to read the other's code.

### What Track A provides to Track B

| # | Signature | Used by B for |
|---|---|---|
| C1 | `datasets.services.get_validation_sample(ml_model, n=50) -> (DataFrame, list)` | The Phase 2 upload validation gate |
| C2 | `monitoring.services.compute_baseline_prediction_distribution(version) -> dict` | Called on version activation |
| C3 | ORM models `MonitoringRun`, `FeatureDriftResult`, `DataQualityReport`, `PerformanceSnapshot` | Charts, alerts, history, comparison |
| C4 | `monitoring.services.ingest_batch(...)` | Not called by B — listed so you know it exists |

### What Track B provides to Track A

| # | Signature | Used by A for |
|---|---|---|
| C5 | `alerts.services.evaluate(run) -> list[Alert]` | Called at the end of every monitoring run |
| C6 | `alerts.retrain.evaluate_retrain(run) -> RetrainRecommendation \| None` | Same |
| C7 | `alerts.services.sweep()` | Registered on A's scheduler, runs every 5 minutes |
| C8 | `registry.models.MLModel`, `ModelVersion` | Foreign keys from A's tables |
| C9 | `core.constants.*` | Every enum |
| C10 | `core.mixins.RoleRequiredMixin`, `ModelAccessRequiredMixin`, `visible_models()` | A's views and querysets |
| C11 | `templates/base.html` | A's templates extend it |

**The unblocking trick:** on day one, stub every contract you depend on so you are never waiting.
A one-line function returning a hardcoded dict is enough to build an entire screen against. The
signatures above are the agreement — as long as both sides honour them, the real implementations
drop in without changing any calling code.

---

## 7. Order of work

```
Day 1  ── Suhas: Phase 0 foundation
       └─ Nandan: engine/drift.py as plain Python + pytest (needs no Django at all)

H0 ────── Phase 0 pushed to main ── Nandan moves the engine into monitoring/engine/

Then, in parallel:
   Suhas:  Phase 1 auth ─► Phase 2 registry ─► Phase 7 alerts ─► Phase 9 charts ─► Phase 10
   Nandan: Phase 4 drift ─► Phase 5 scoring ─► Phase 3 datasets ─► Phase 6 pipeline ─► Phase 8 simulator

Handshakes along the way:
   H1  Suhas pushes MLModel + ModelVersion early in Phase 2   → unblocks Nandan's foreign keys
   H2  Nandan pushes MonitoringRun + children early in Phase 6 → unblocks Suhas's charts & alerts
   H3  Nandan's ingest_batch() works end to end                → Suhas's alert evaluation goes live
   H4  Integration checkpoint: upload a batch, see a run, see an alert, see a chart

Finally: both ── Phase 11 polish ── demo rehearsal
```

**H1 and H2 are the two that matter.** Push those model definitions early and thin — before the
views, before the services. A migration with the right fields unblocks the other person for days.

---

## 8. Git rules

1. **Merge to `main` at least once a day.** Two branches diverging for a week is how this project
   fails. Nothing else on this list matters as much.
2. Short-lived feature branches: `feat/auth`, `feat/drift-engine`. **Not** long-lived `suhas` and
   `nandan` branches.
3. Never push a broken `main`. `pytest` green before every push.
4. Changes to shared files (`config/settings/`, `config/urls.py`, `core/constants.py`,
   `templates/base.html`) go in **small dedicated commits**, and tell the other person.
5. Migrations: only create migrations for **your own** apps. If you get a migration conflict,
   don't hand-merge it — talk first, then one person regenerates.
6. Never commit `db.sqlite3`, `.env`, `media/`, or `*.pkl`. `.gitignore` covers these; don't
   force-add past it.

**Pushing:** this repo belongs to the `ns8963038-hub` GitHub account. If `git push` asks for a
password, the wrong account is active — run `gh auth switch --user ns8963038-hub`.

---

## 9. Definition of done (both tracks)

A phase is complete only when **all** of these hold:

1. Every acceptance criterion in the phase passes
2. Tests written in the same phase, not deferred
3. `ruff` and `black` clean
4. No `TODO`, no commented-out code, no `print()`
5. Every new view has a permission test
6. Migrations apply cleanly from an empty database
7. The relevant document is updated if the phase changed a decision

---

## 10. Questions

If anything in the specification is ambiguous, **ask before assuming**. The six documents were
written specifically so that neither developer has to guess, and a wrong assumption discovered in
Phase 9 is expensive. If a document is genuinely wrong or missing something, say so — it gets
fixed, and the fix is committed.

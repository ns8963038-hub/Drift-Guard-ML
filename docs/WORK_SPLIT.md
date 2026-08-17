# Work Split — Two Developers

**Product:** DriftGuard — Multi-User ML Model Monitoring & Data Drift Detection Platform

| Field | Value |
|---|---|
| Document | WORK_SPLIT |
| Version | 2.0 |
| Track A — Data & Detection | **Nandan** |
| Track B — Platform & Presentation | **Suhas** |
| Total effort | 76 points (38 each), 1 point ≈ half a focused working day |

> **Suhas — start here.** §2 is your reading list, §5 is the complete screen ownership map, §6 is
> your work phase by phase, and **§7 is every single thing you depend on Nandan for**, including
> how to stub each one so you are never blocked waiting.
>
> ⛔ **Before you run a single `startapp`:** `monitoring/` and `simulator/` already exist and
> hold Track A's engine and drift transforms. `startapp` will fail on both, and deleting either
> directory would destroy his work. The correct commands are in **§6, Phase 0, task 1**. Read
> that box first.

---

## 1. What the product is (60 seconds)

A web platform where a team uploads trained ML models along with the data those models were
trained on, then feeds in new production data over time. For every new batch the platform answers
four questions:

1. Is the incoming data clean? *(data quality)*
2. Does it still look like the training data? *(**data drift** — the core feature)*
3. Is the model still accurate? *(performance)*
4. Overall, how healthy is this model? *(0–100 health score)*

…then raises alerts when thresholds break, explains *why* in plain English, and recommends
retraining. It never trains or retrains anything itself.

Full detail: [PRD.md](PRD.md) §1.

---

## 2. Reading list for Track B

Read in this order. You can skip everything else for now.

| Order | Document | Sections | Why |
|---|---|---|---|
| 1 | [PRD.md](PRD.md) | §4 glossary, §5 roles & permission matrix, §9 alert rules, §10 retrain triggers | The vocabulary, the access rules, and the alert logic you implement |
| 2 | [APP_FLOW.md](APP_FLOW.md) | All of it | Every screen, journey, state machine and empty state |
| 3 | [UIUX_DESIGN.md](UIUX_DESIGN.md) | All of it | Design tokens, components, chart specs — your build spec |
| 4 | [TRD.md](TRD.md) | §1 stack, §3 structure, §4.1/4.2/4.5 data model, §8 security | What to install, where files go, your tables |
| 5 | [BACKEND_FLOW.md](BACKEND_FLOW.md) | §2 request lifecycle, §3 auth, §5 alerts, §9 comparison, §10 chart endpoints | How your layers fit together |
| 6 | [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | Phases 0, 1, 2, 7, 9, 10 | Your phases with acceptance criteria |

**You never need to read** [PRD.md](PRD.md) §7 (drift maths), §8 (scoring formulas), or
[BACKEND_FLOW.md](BACKEND_FLOW.md) §4 (the monitoring pipeline). That is Track A's half.

---

## 3. Directory ownership

**The rule that stops two people fighting in git: you own whole directories. Never edit the other
person's folders.**

| Track B — Suhas owns | Track A — Nandan owns |
|---|---|
| `config/` — settings, root urls | `monitoring/` — including `engine/` |
| `core/` — constants, mixins, validators, base model | `datasets/` |
| `accounts/` | `simulator/` |
| `registry/` | |
| `alerts/` | |
| `dashboard/` | |
| `apiv1/` — optional Phase 12 | |
| `templates/` — base, and B's own screen templates | `templates/monitoring/`, `templates/datasets/`, `templates/simulator/` |
| `static/` — all CSS and JS | |

### 3.1 Shared paths — per-file ownership

Neither person owns these outright. Ownership is **per file**, so you still never
edit the same file as the other person.

| Path | Rule |
|---|---|
| `scripts/` | Nandan: `prepare_datasets.py`, `train_demo_models.py`. Suhas: `seed_demo.py`. |
| `templates/` | Suhas owns `base.html` and the model-detail tab shell. Nandan adds his own subdirectories that `{% extends %}` them. |
| `tests/` | Named after what it tests. Nandan: `test_profiling.py`, `test_drift.py`, `test_quality.py`, `test_performance.py`, `test_health.py`, `test_explain.py`, `test_pipeline.py`, `test_simulator.py`. Suhas: `test_permissions.py`, `test_auth.py`, `test_registry.py`, `test_alerts.py`, `test_charts.py`, `test_comparison.py`. `conftest.py` is shared — coordinate. |
| `requirements.txt` | Split into blocks by comment. Edit only your own block. **Already created** with the full stack for both tracks, so Phase 0 does not need to author it. |
| `pytest.ini` | **Already created.** Track B extends it in Phase 0 with `DJANGO_SETTINGS_MODULE`. |

> `monitoring/` and `simulator/` already contain Track A code. Phase 0 must **not**
> run `django-admin startapp` on either — it fails on a non-empty directory. Create
> `apps.py`, `admin.py` and `migrations/__init__.py` by hand instead. Full commands
> in §6, Phase 0, task 1.

### 3.2 Shared files needing coordination

`config/settings/`, `config/urls.py`, `core/constants.py`, `templates/base.html`.

Suhas owns all four, but Track A depends on them. Changes go in **small dedicated commits with a
message saying what changed** — never buried inside a large feature commit.

---

## 4. The two tracks at a glance

| | Track A — Nandan | Track B — Suhas |
|---|---|---|
| **Theme** | The statistics and the data pipeline | The application and everything the user sees |
| **Skills** | pandas, numpy, scipy, scikit-learn | Django views, forms, templates, CSS, Chart.js |
| **Phases** | 3, 4, 5, 6, 8 + data scripts | 0, 1, 2, 7, 9, 10 + polish (+ optional 12) |
| **Points** | 38 | 38 |
| **Screens** | 5 | 21 |
| **Builds** | Profiling, drift engine, quality, performance, health score, explanations, `ingest_batch()`, run + feature detail, batch/baseline upload, simulator, scheduler | Foundation, auth & roles, model registry, alerts & retraining, dashboard & all charts, version comparison, history |

---

## 5. Screen ownership — all 26

Suhas builds 21 of the 26 screens. This table is authoritative; screen numbers match
[APP_FLOW.md](APP_FLOW.md) §1.

| # | Screen | Route | Owner | Phase |
|---|---|---|---|---|
| S1 | Login | `/login/` | **B** | 1 |
| S2 | Dashboard (role-aware, 3 compositions) | `/` | **B** | 9 |
| S3 | Models list | `/models/` | **B** | 2 |
| S4 | Create / edit model | `/models/new/` | **B** | 2 |
| S5 | Model detail — Overview | `/models/<slug>/` | **B** | 2 |
| S6 | Model detail — Versions | `…/versions/` | **B** | 2 |
| S7 | Upload version | `…/versions/new/` | **B** | 2 |
| S8 | Upload baseline dataset | `…/baseline/new/` | A | 3 |
| S9 | Model detail — Drift | `…/drift/` | **B** | 9 |
| S10 | Model detail — Performance | `…/performance/` | **B** | 9 |
| S11 | Model detail — Data quality | `…/quality/` | **B** | 9 |
| S12 | Model detail — History | `…/history/` | **B** | 10 |
| S13 | Monitoring run detail | `/runs/<id>/` | A | 6 |
| S14 | Feature drift detail | `/runs/<id>/features/<name>/` | A | 6 |
| S15 | Upload production batch | `…/batches/new/` | A | 6 |
| S16 | Version comparison | `…/compare/` | **B** | 10 |
| S17 | Alerts list | `/alerts/` | **B** | 7 |
| S18 | Alert detail | `/alerts/<id>/` | **B** | 7 |
| S19 | Threshold settings | `…/thresholds/` | **B** | 7 |
| S20 | Simulator scenarios | `…/simulator/` | A | 8 |
| S21 | Admin — users list | `/admin-panel/users/` | **B** | 1 |
| S22 | Admin — create / edit user | `…/users/new/` | **B** | 1 |
| S23 | Admin — access grants | `…/access/` | **B** | 1 |
| S24 | Admin — login activity | `…/activity/` | **B** | 1 |
| S25 | Profile & password | `/profile/` | **B** | 1 |
| S26 | Retraining recommendations | `…/recommendations/` | **B** | 7 |

### 5.1 The model-detail tab shell — a coordination point

S5–S12 plus S19 and S20 share one tabbed page shell:

```
Overview │ Versions │ Drift │ Performance │ Data Quality │ History │ Thresholds │ Simulator
   B         B          B         B             B            B          B          A
```

**Suhas builds the shell**, including the tab for Simulator that points at Nandan's screen.
Nandan's `templates/simulator/` page extends the shell. Suhas: render tabs the user is permitted
to see — Thresholds and Simulator only for `MANAGE` and Admin.

---

## 6. Track B — Suhas's work, phase by phase

### Phase 0 — Foundation · 4 points · **DO THIS FIRST**

**The whole project waits on this.** Build it, get it green, push it the same day if you can.
Nandan can start in parallel — the drift engine is plain Python with no Django — but nobody can
integrate until Phase 0 lands.

**Build:**

```
manage.py                 requirements.txt        .env.example       pytest.ini
config/settings/{base,dev,prod}.py                config/urls.py     config/wsgi.py
core/models.py            core/constants.py       core/mixins.py     core/validators.py
templates/base.html       templates/403.html      templates/404.html
static/css/{tokens,base,components,charts}.css
static/js/{theme,charts,tables,polling}.js
static/vendor/chartjs/    static/vendor/alpine/
logs/
```

**Tasks:**

1. Django project + **all nine apps** created and registered in `INSTALLED_APPS`:
   `core`, `accounts`, `registry`, `datasets`, `monitoring`, `alerts`, `simulator`, `dashboard`,
   `apiv1` — create Nandan's apps too, empty. Five minutes, unblocks him immediately.

   > ### ⛔ `startapp monitoring` and `startapp simulator` WILL FAIL — read first
   >
   > Track A started before Phase 0, so **`monitoring/` and `simulator/` already
   > exist** — they hold the drift engine and the drift-injection transforms.
   > `django-admin startapp` refuses to run on a non-empty directory:
   >
   > ```
   > CommandError: '/path/to/ML PROJECT/monitoring' already exists
   > ```
   >
   > This is expected, not a broken repo. **Do not delete the directory** — you would
   > destroy Track A's work. Create the app files by hand instead:
   >
   > ```bash
   > # These do not exist yet, so startapp is fine:
   > python manage.py startapp core
   > python manage.py startapp accounts
   > python manage.py startapp registry
   > python manage.py startapp datasets
   > python manage.py startapp alerts
   > python manage.py startapp dashboard
   > python manage.py startapp apiv1
   >
   > # monitoring/ and simulator/ exist already — hand-create only the Django
   > # app files inside them:
   > for app in monitoring simulator; do
   >   touch $app/models.py $app/admin.py $app/views.py
   >   mkdir -p $app/migrations && touch $app/migrations/__init__.py
   > done
   > ```
   >
   > …then write `monitoring/apps.py`:
   >
   > ```python
   > from django.apps import AppConfig
   >
   >
   > class MonitoringConfig(AppConfig):
   >     default_auto_field = "django.db.models.BigAutoField"
   >     name = "monitoring"
   > ```
   >
   > …and the same for `simulator/apps.py` with `SimulatorConfig` / `name = "simulator"`.
   >
   > Register both in `INSTALLED_APPS` like any other app. **Never touch
   > `monitoring/engine/` or `simulator/transforms.py` — those are Track A's.**
   >
   > **General rule:** if any app directory already exists when you get to Phase 0,
   > Track A got there first. Hand-create the Django files around it; never `startapp`
   > over it and never delete it. Check with `ls` before each `startapp`.
2. `core/models.py` → `TimeStampedModel` abstract base (`created_at`, `updated_at`).
3. **`core/constants.py` — every enum in the system, defined once.** See §6.1. Both tracks import
   from here; a missing enum blocks Nandan.
4. `core/validators.py` — upload validators (extension allowlist, size cap, MIME sniff, SHA-256).
   **Nandan uses these for his CSV uploads too** (contract C9).
5. `templates/base.html` — header (product name, model search, alert badge, theme toggle, user
   menu), sidebar nav, breadcrumbs block, toast region, content block.
6. CSS from [UIUX_DESIGN.md](UIUX_DESIGN.md) §2. **`tokens.css` is the only file allowed to
   contain raw hex.** Everything else references custom properties.
7. `static/js/theme.js` + the inline head script from [UIUX_DESIGN.md](UIUX_DESIGN.md) §8
   (prevents the flash of wrong theme on load).
8. **JS utilities Nandan's screens consume** — build the shells now, fill them in Phase 9:
   - `charts.js` — chart factories (S14 uses your distribution factory)
   - `tables.js` — sortable, sticky-header tables (S13's feature drift table uses this)
   - `polling.js` — run-status polling (S15's progress panel uses this)
9. **Download and commit Chart.js and Alpine.js into `static/vendor/`.** Never a CDN link — the
   demo must work with Wi-Fi off.
10. pytest + pytest-django + factory_boy; ruff + black; rotating log handler.

**Acceptance:**
- `runserver` serves a themed empty shell with working sidebar and header
- Theme toggle cycles Light → Dark → System, persists across reloads, no flash on hard refresh
- `pytest` runs green (zero tests is fine)
- **Every page loads with networking disabled**

**Depends on Track A:** nothing. This phase is fully independent.

#### 6.1 The enums for `core/constants.py`

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
| `AuditAction` | `MODEL_CREATED`, `VERSION_UPLOADED`, `VERSION_ACTIVATED`, `VERSION_DEACTIVATED`, `VERSION_ARCHIVED`, `BASELINE_UPLOADED`, `THRESHOLDS_CHANGED`, `MODEL_DEACTIVATED` |

---

### Phase 1 — Authentication, roles, permissions · 6 points → PRD FR-01

> ⚠️ **Set `AUTH_USER_MODEL = "accounts.User"` in settings BEFORE your first `migrate`.**
> Django makes this extremely painful to change afterwards. If you have already migrated, delete
> `db.sqlite3` and all migration files and start again — far quicker than the alternative.

**Build:**

- `accounts/models.py`
  - `User(AbstractUser)` — `role`, `failed_login_count`, `locked_until`
  - `LoginActivity` — `user` (nullable), `username_attempted`, `event`, `ip_address`,
    `user_agent`, `occurred_at`
  - `ModelAccess` — `user`, `ml_model` (string reference `"registry.MLModel"`), `permission`,
    `granted_by`, `granted_at`, `unique_together(user, ml_model)`
- S1 login / logout, flow per [BACKEND_FLOW.md](BACKEND_FLOW.md) §3
- Account lockout: 5 failures → 15 minutes
- `LoginActivityMiddleware`
- `core/mixins.py`:
  - `RoleRequiredMixin` — role against the [PRD.md](PRD.md) §5.2 matrix
  - `ModelAccessRequiredMixin` — the grant
  - `visible_models(user)` — **the single helper every model-scoped queryset in the project uses,
    including Nandan's**
- S21 users · S22 create/edit · S23 grants · S24 login activity · S25 profile
- A 403 page **identical** whether the model does not exist or access is denied

**Two things that are easy to get wrong:**

1. Login failure messages must be **identical** for "no such user" and "wrong password", or the
   form becomes a username enumerator.
2. Filter querysets with `visible_models()`. Permission checks in templates are not access
   control — a hidden button still leaves the URL reachable, and list views leak objects.

**Acceptance:**
- Every row of the [PRD.md](PRD.md) §5.2 permission matrix has a passing test
- A deactivated user cannot log in
- Six failed logins produce a lockout with the right message
- An ML Engineer granted Model A and not Model B gets 403 on Model B **by direct URL**
- Login activity records success, failure and logout with IP and user agent

**Depends on Track A:** nothing. `ModelAccess` points at `registry.MLModel`, which is your own
Phase 2 — use the string reference and Django resolves it later.

---

### Phase 2 — Model registry and versions · 6 points → PRD FR-02

**Build:**

- `registry/models.py` — `MLModel`, `ModelVersion`, `ModelAuditLog` ([TRD.md](TRD.md) §4.2)
- S3 models list, S4 create/edit. Creator auto-granted `MANAGE`.
- S5 overview, S6 versions list, S7 upload version
- The **five-check validation gate** ([PRD.md](PRD.md) §4.3):
  1. Deserialises via `joblib.load`
  2. Has a callable `.predict()`
  3. Predicts successfully on 50 baseline rows
  4. Output length equals input length
  5. Output classes are a subset of the baseline target's classes
- Activate / deactivate / archive with the single-`ACTIVE` transaction + partial unique index
- Model history timeline
- Upload validators from `core/validators.py`: `.pkl`/`.joblib`, 100 MB cap, MIME sniff, SHA-256

**⚠ Depends on Track A — two contracts.** Checks 3 and 5 need baseline data, which lives in
Nandan's `datasets/` app. **Do not read those files yourself.**

```python
# Contract C1 — Nandan provides
from datasets.services import get_validation_sample
sample_df, target_classes = get_validation_sample(ml_model, n=50)

# Contract C2 — Nandan provides; call on activation
from monitoring.services import compute_baseline_prediction_distribution
compute_baseline_prediction_distribution(version)
```

Stub both on day one (§7.2) and carry on — **do not block waiting.**

**Also note:** activation must fail cleanly if no baseline dataset exists yet, because a user can
create a model and try to upload a version before uploading baseline data.

**Acceptance:**
- A corrupt `.pkl` is rejected naming the failed check, and **creates no version row**
- A valid artifact whose `.predict()` fails on baseline columns is rejected at upload, not later
- Activating V2 demotes V1 in one transaction; no state ever has two `ACTIVE` versions
- Activation with no baseline dataset fails with a clear message
- Every state change appears in the audit timeline with actor and timestamp

---

### Phase 7 — Alerts and retraining · 6 points → PRD FR-06, FR-10

**Build:**

- `alerts/models.py` — `ThresholdProfile`, `Alert`, `RetrainRecommendation` ([TRD.md](TRD.md) §4.5)
- `alerts/services.py::resolve_thresholds(ml_model) -> dict` — resolution order **model profile →
  global profile → code defaults**. **Nandan's pipeline calls this on every run** (contract C14) —
  build it early and keep the return shape stable.
- `alerts/services.py::evaluate(run)` — rules in [PRD.md](PRD.md) §9.1, with **deduplication and
  cooldown** ([BACKEND_FLOW.md](BACKEND_FLOW.md) §5.1)
- `alerts/services.py::sweep()` — auto-resolve alerts whose condition cleared for 3 runs
- `alerts/retrain.py::evaluate_retrain(run)` — triggers in [PRD.md](PRD.md) §10
- S17 list · S18 detail · S19 threshold settings · S26 recommendations
- Header alert badge (unresolved count)
- Email: console backend by default, SMTP behind config, `CRITICAL` only, **failures logged and
  swallowed — never raise**

**Deduplication is not optional.** Nandan's simulator produces a batch every 30 seconds. Without
dedup you get hundreds of identical alerts within minutes and the alerts screen is useless. Key on
`(model, category, feature_name)`; while an unresolved alert with that key exists inside the
cooldown window, increment `occurrence_count` and update `last_seen_at` instead of inserting.

**⚠ Depends on Track A:** you read `MonitoringRun` and its children to evaluate rules (contract
C3). Nandan calls your `evaluate()`, `evaluate_retrain()` and `sweep()` — you expose them, he
wires them (C15, C16, C17).

**Acceptance:**
- 20 consecutive high-drift runs produce **one** alert with `occurrence_count == 20`
- An alert auto-resolves after 3 clean runs, annotated "Auto-resolved — condition cleared"
- A retraining recommendation lists every trigger with measured value **and** threshold
- A second trigger event updates the existing `OPEN` recommendation instead of creating a second
- With `EMAIL_ENABLED=False` everything works and nothing is sent
- With SMTP deliberately misconfigured, the run still completes and only a warning is logged

---

### Phase 9 — Dashboard and charts · 8 points → PRD FR-07

The most visible phase in the project. Build spec: [UIUX_DESIGN.md](UIUX_DESIGN.md) §5.

**Build:**

- **Seven JSON endpoints** ([BACKEND_FLOW.md](BACKEND_FLOW.md) §10), each capped at 500 points with
  server-side down-sampling. Note two of them serve Nandan's screens:
  - `…/features/<name>/distribution/` → feeds **his** S14
  - `/runs/<id>/status/` → feeds **his** S15 progress panel
- `static/js/charts.js` — Chart.js factories reading colours from CSS custom properties, shared
  tooltip config, and the "View as table" builder
- Six charts: performance over time · drift over time · distribution comparison · prediction trend
  · alerts over time · health over time
- S2 role-aware dashboard in its **three** compositions ([APP_FLOW.md](APP_FLOW.md) §3)
- S9 Drift · S10 Performance · S11 Data Quality tabs
- Shared time-range control (24h / 7d / 30d / All) applying to every chart on the page

**Non-negotiable chart rules** ([UIUX_DESIGN.md](UIUX_DESIGN.md) §2.4, §5.1). These were validated
with a colour-blindness checker — please don't substitute your own palette:

1. **No dual-axis charts anywhere.** Two measures of different scale = two charts.
2. Categorical palette in **fixed slot order**: blue → orange → aqua → yellow. Never cycle, never
   generate a 5th colour — fold extras into "Other".
3. Status colours (green/amber/red) are **reserved** for drift and health. Never a series colour.
4. **Status is never colour alone** — icon + text label + colour, always. Around 8% of men have
   red-green colour deficiency and this product is built entirely out of traffic lights.
5. Every chart needs a hover tooltip **and** a "View as table" disclosure. The table is a hard
   requirement — two light-mode palette colours sit below 3:1 contrast and the table view is what
   makes that acceptable.
6. Unlabelled runs render as **gaps** — never interpolated, never zero.

**⚠ Depends on Track A:** every chart reads his `MonitoringRun`, `FeatureDriftResult`,
`DataQualityReport`, `PerformanceSnapshot` (contract C3). Until H2 lands, serve hardcoded JSON
from your endpoints and build the entire front end against it (§7.2).

**Acceptance:**
- Theme toggle re-themes live charts via `update()` — no rebuild, no flash
- Unlabelled runs appear as gaps
- Every chart has a tooltip and a working table view
- Dashboard renders in under 3 seconds with 500 runs in the database

---

### Phase 10 — Version comparison and history · 5 points → PRD FR-12, FR-13

**Build:**

- S16 comparison — two versions of the **same** model ([BACKEND_FLOW.md](BACKEND_FLOW.md) §9)
- Schema-compatibility check: if feature schemas differ, show a notice and suppress the drift
  rows, but still compare the metrics
- Mark the better value in each row, with the delta
- Verdict line: *"V2 outperforms V1 on accuracy by 3.1 points across 42 runs."*
- S12 history — filters (date, run status, drift status, trigger source), pagination, CSV export

**Immutability:** historical runs never change. Each run stores the thresholds it was judged under,
so editing a threshold today leaves last week's results exactly as they were. Write a test.

**⚠ Depends on Track A:** reads `MonitoringRun` (C3) and `DataBatch` for the trigger-source filter
(contract C4).

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
- Empty states for every list ([APP_FLOW.md](APP_FLOW.md) §6.3) — no blank screens
- `scripts/seed_demo.py` — users of all three roles, models, grants, threshold profiles
- README: setup, demo script, architecture notes

**⚠ Depends on Track A:** `seed_demo.py` runs *after* his `prepare_datasets.py` and
`train_demo_models.py` (contract C5). Write yours to assume those outputs already exist on disk,
and document the run order in the README.

---

### Phase 12 — REST ingestion endpoint · 4 points · **OPTIONAL**

Only if time allows. Not one of the 14 required features — cut first if effort runs short.

- Per-model API keys, hashed at rest, shown once at creation
- `POST /api/v1/models/<uuid>/batches/` → calls Nandan's `ingest_batch()` (contract C18)
- Rate limit 60/min per key, 10,000-row cap, documented error contract

**⚠ Depends on Track A:** entirely — it is a thin HTTP wrapper over his pipeline. Do not start
before H3.

---

## 7. Dependencies — everything Suhas needs from Nandan

This is the complete list. If it is not here, it is not a dependency.

### 7.1 Contracts

**Track A → Track B — what Suhas consumes**

| # | What | Needed for | Blocks | Ready by |
|---|---|---|---|---|
| **C1** | `datasets.services.get_validation_sample(ml_model, n=50) -> (DataFrame, list[classes])` | Validation gate checks 3 & 5 | Phase 2 | H1 |
| **C2** | `monitoring.services.compute_baseline_prediction_distribution(version) -> dict` | Version activation | Phase 2 | H2 |
| **C3** | ORM models `MonitoringRun`, `FeatureDriftResult`, `DataQualityReport`, `PerformanceSnapshot` | Alert rules, all charts, history, comparison | Phases 7, 9, 10 | **H2 — the big one** |
| **C4** | ORM models `BaselineDataset`, `DataBatch` | History trigger-source filter; version schema comparison | Phase 10 | H2 |
| **C5** | `scripts/prepare_datasets.py`, `scripts/train_demo_models.py` outputs | `seed_demo.py` | Phase 11 | Late |
| **C18** | `monitoring.services.ingest_batch(...)` | Optional REST endpoint | Phase 12 | H3 |

**Track B → Track A — what Suhas must deliver to Nandan**

| # | What | He needs it for | Deliver by |
|---|---|---|---|
| **C6** | `core.constants.*` — all enums | Every model he writes | **Phase 0** |
| **C7** | `registry.models.MLModel`, `ModelVersion` | Foreign keys on his tables | **H1 — push early and thin** |
| **C8** | `core.mixins.RoleRequiredMixin`, `ModelAccessRequiredMixin`, `visible_models()` | His views S8, S13, S14, S15, S20 | Phase 1 |
| **C9** | `core.validators.*` — upload validators | His CSV uploads | Phase 0 |
| **C10** | `templates/base.html` + model-detail tab shell | His templates extend them | Phase 0 |
| **C11** | `static/css/components.css` — badges, tables, cards, empty states | His screens | Phase 0 |
| **C12** | `static/js/charts.js` distribution factory | His S14 chart | Phase 9 |
| **C13** | `static/js/tables.js`, `static/js/polling.js` | His S13 table, S15 progress panel | Phase 0 shell, Phase 9 complete |
| **C14** | `alerts.services.resolve_thresholds(ml_model) -> dict` | **Every monitoring run** | **Phase 7 — early** |
| **C15** | `alerts.services.evaluate(run)` | End of every run | Phase 7 |
| **C16** | `alerts.retrain.evaluate_retrain(run)` | End of every run | Phase 7 |
| **C17** | `alerts.services.sweep()` | Registered on his scheduler | Phase 7 |

**Note the asymmetry:** Nandan depends on Suhas for **12** contracts; Suhas depends on Nandan for
**6**. Track B is upstream. Phase 0 and the early `MLModel` push (H1) are the two moments where
Suhas holds up the whole project — everything else can proceed in parallel.

### 7.1a The unblock sequence — do these three first

**Track A is fully blocked until these land**, and they are far smaller than a whole phase:
roughly a day and a half of work that unlocks about 14 points of Nandan's.

Push each as its own commit, in this order. The order is not negotiable.

| # | Deliverable | Why it must come first |
|---|---|---|
| 1 | **Phase 0** complete (§6) | Nothing exists without it. Read the ⛔ box in task 1 before running `startapp` |
| 2 | **`accounts.User`** + `AUTH_USER_MODEL = "accounts.User"` in settings, migrated | `MLModel.owner` points at it, and `AUTH_USER_MODEL` must be set before **any** migration runs — changing it afterwards means deleting the database and every migration file |
| 3 | **`registry.MLModel` + `ModelVersion`** — model classes and migration only | Nandan's `MonitoringRun`, `DataBatch` and `BaselineDataset` all have foreign keys to these. Django resolves string references lazily, but `makemigrations` still fails if the class does not exist |

**Step 3 means the model classes and nothing else.** No views, no forms, no upload screen, no
validation gate, no admin registration. Those are Phase 2 proper and can wait — get the tables
into the database and go back to Phase 1.

#### The fields Track A actually reads

Full definitions are in [TRD.md](TRD.md) §4.2 and every field there should exist eventually.
These are the subset Nandan's services read, so getting them right in the first migration avoids
a second one:

**`MLModel`**

| Field | Type | Read for |
|---|---|---|
| `name` | CharField | display |
| `slug` | SlugField | URLs |
| `target_column` | CharField | deciding whether a batch carries labels |
| `positive_class` | CharField, nullable | binary precision/recall/F1 |
| `problem_type` | choice `BINARY`/`MULTICLASS` | metric selection |
| `is_active` | Boolean | pipeline pre-flight — a deactivated model accepts no batches |
| `owner` | FK → `accounts.User` | access grants |

**`ModelVersion`**

| Field | Type | Read for |
|---|---|---|
| `ml_model` | FK → `MLModel` | the run's parent |
| `label` | CharField (`V1`, `V2`, …) | display |
| `artifact` | FileField | loading the model to score a batch |
| `status` | choice `INACTIVE`/`ACTIVE`/`ARCHIVED` | finding the version to score with |
| `validation_status` | choice `PENDING`/`PASSED`/`FAILED` | pipeline pre-flight |
| `feature_schema` | JSONField | which columns to monitor and pass to the model |
| `training_accuracy` | FloatField, nullable | the health score's performance reference (§8.1) |
| `baseline_prediction_distribution` | JSONField, nullable | the health score's stability component (§8.2) |

The last two are nullable on purpose — a first run has no reference yet, and the engine treats
that as "not yet established" rather than as a failure.

### 7.2 How to never be blocked — stub everything on day one

Both sides stub what they consume. A function returning a hardcoded value is enough to build an
entire screen against, and when the real one lands, no calling code changes.

```python
# datasets/services.py — Suhas's temporary stub, delete when Nandan's lands
def get_validation_sample(ml_model, n=50):
    import pandas as pd
    return pd.DataFrame({"tenure": [1] * n, "MonthlyCharges": [50.0] * n}), ["Yes", "No"]

# monitoring/services.py — temporary stub
def compute_baseline_prediction_distribution(version):
    return {"Yes": 0.27, "No": 0.73}
```

For C3 (his monitoring models) the stub is different — you need rows, not a function. Two options:

1. **Preferred:** wait for H2, which should land within the first few days, and build your chart
   endpoints returning hardcoded JSON in the meantime. The entire front end can be finished
   against fake JSON.
2. Write the `MonitoringRun` model yourself as a throwaway, build against it, then delete your
   version when his lands. **Only if H2 slips** — two migrations for one table is a mess.

**Rule: put every stub in one commit with `STUB:` in the message, so they are trivial to find and
delete.**

---

## 8. Order of work

```
Day 1  ── Suhas:  Phase 0 foundation
       └─ Nandan: engine/drift.py as plain Python + pytest (needs no Django at all)

H0 ────── Phase 0 pushed to main ─────► Nandan moves the engine into monitoring/engine/

Then, in parallel:
   Suhas:  Phase 1 auth ─► Phase 2 registry ─► Phase 7 alerts ─► Phase 9 charts ─► Phase 10
   Nandan: Phase 4 drift ─► Phase 5 scoring ─► Phase 3 datasets ─► Phase 6 pipeline ─► Phase 8 sim

Handshakes:
   H1  Suhas pushes MLModel + ModelVersion early in Phase 2   → unblocks Nandan's foreign keys
   H2  Nandan pushes MonitoringRun + children early in Phase 6 → unblocks Suhas's charts & alerts
   H3  Nandan's ingest_batch() works end to end                → Suhas's alert evaluation goes live
   H4  Integration checkpoint: upload a batch → see a run → see an alert → see a chart

Finally: both ── Phase 11 polish ── demo rehearsal ([APP_FLOW.md](APP_FLOW.md) §8)
```

**H1 and H2 are the two that matter.** Push those model definitions early and thin — before the
views, before the services. A migration with the right fields unblocks the other person for days.

---

## 9. Git rules

1. **Merge to `main` at least once a day.** Two branches diverging for a week is how this project
   fails. Nothing else on this list matters as much.
2. Short-lived feature branches: `feat/auth`, `feat/drift-engine`. **Not** long-lived `suhas` and
   `nandan` branches.
3. Never push a broken `main`. `pytest` green before every push.
4. Changes to shared files (§3.2) go in small dedicated commits, and tell the other person.
5. Migrations: only create migrations for **your own** apps. On a migration conflict, don't
   hand-merge — talk first, then one person regenerates.
6. Never commit `db.sqlite3`, `.env`, `media/`, or `*.pkl`. `.gitignore` covers these; don't
   force-add past it.

**Pushing:** this repo belongs to the `ns8963038-hub` GitHub account. If `git push` asks for a
password, the wrong account is active — run `gh auth switch --user ns8963038-hub`.

---

## 10. Definition of done (both tracks)

1. Every acceptance criterion in the phase passes
2. Tests written in the same phase, not deferred — Track B: services ≥ 75%, **every view has a
   permission test**
3. `ruff` and `black` clean
4. No `TODO`, no commented-out code, no `print()`, **no leftover `STUB:` code**
5. Migrations apply cleanly from an empty database
6. The relevant document is updated if the phase changed a decision

---

## 11. Questions

If anything in the specification is ambiguous, **ask before assuming**. The six documents exist so
neither developer has to guess, and a wrong assumption discovered in Phase 9 is expensive. If a
document is genuinely wrong or incomplete, say so — it gets fixed and the fix is committed.

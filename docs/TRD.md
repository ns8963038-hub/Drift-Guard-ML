# Technical Requirements Document (TRD)

**Product:** DriftGuard — Multi-User ML Model Monitoring & Data Drift Detection Platform

| Field | Value |
|---|---|
| Document | TRD |
| Version | 1.0 |
| Status | Baselined |
| Depends on | [PRD.md](PRD.md) — product rules, thresholds and formulas are defined there and **not** duplicated here |
| Companions | [APP_FLOW.md](APP_FLOW.md), [UIUX_DESIGN.md](UIUX_DESIGN.md), [BACKEND_FLOW.md](BACKEND_FLOW.md), [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) |

> **Division of labour between documents.** The PRD owns *what the numbers are* (thresholds,
> weights, bands). This TRD owns *how they are computed and stored*. Where a formula is needed
> here it is referenced by PRD section, never restated — one source of truth, so the two can
> never drift apart.

---

## 1. Technology stack — decided

| Layer | Choice | Version | Why this and not the alternative |
|---|---|---|---|
| Language | Python | 3.11 | scipy/sklearn/pandas are non-negotiable for the drift maths; 3.11 is stable and fast |
| Web framework | **Django** | 5.0 LTS-track | Auth, role permissions, admin, ORM, migrations, file handling and CSRF are built in — PRD FR-01 and FR-02 are largely free. Flask/FastAPI would mean hand-building all of it |
| API layer | **Django REST Framework** | 3.15 | Only for ADD-1 (the REST ingestion endpoint) and chart JSON endpoints |
| Templating | Django Templates | built-in | Server-rendered. No SPA, no npm build step, nothing to break on demo day |
| Interactivity | Vanilla JS (ES2020) + **Alpine.js** 3.x | vendored | Alpine covers tabs, dropdowns, theme toggle and polling in ~15 KB without a build pipeline |
| Charts | **Chart.js** 4.x | vendored | Covers every chart in PRD FR-07; no build step; good tooltip API |
| CSS | Handwritten CSS with custom properties | — | Design tokens in [UIUX_DESIGN.md](UIUX_DESIGN.md) §2. No Tailwind build step |
| DB (dev/demo) | **SQLite** | 3.4x | Zero setup on a demo laptop; WAL mode enabled |
| DB (portable) | PostgreSQL 16 / MySQL 8 | — | Reachable by settings change only; ORM-only queries enforce this (PRD NFR-13) |
| Scheduler | **APScheduler** | 3.10 | In-process `BackgroundScheduler`. No Redis, no Celery, no broker to install |
| ML runtime | scikit-learn 1.5, joblib 1.4 | — | Matches the model contract (PRD §4.3) |
| Data | pandas 2.2, numpy 1.26 | — | Profiling, batch handling |
| Statistics | **scipy 1.13** | — | `ks_2samp`, `chi2_contingency`, `entropy` (for JSD) |
| Auth | Django sessions + `AbstractUser` subclass | — | |
| Email | Django email backend | — | `console` in dev, SMTP in prod, both behind one setting |
| Testing | pytest 8 + pytest-django + factory_boy | — | |
| Quality | ruff, black | — | |

**Hard rule (PRD NFR-10):** no CDN references anywhere. Chart.js, Alpine.js and all fonts are
committed under `static/vendor/`. The demo must run on a laptop with the Wi-Fi switched off.

**Explicitly rejected:** Celery + Redis (infrastructure a student cannot install during a viva),
React/Vue (build step, second server), Tailwind (build step), Evidently AI / NannyML (the drift
maths *is* the project — importing a library that does it would hollow out the contribution and
would be the first thing an examiner attacks).

---

## 2. System architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          Browser (single page loads)                  │
│   Django templates · Alpine.js · Chart.js · CSS custom-property theme │
└───────────────┬──────────────────────────────────┬───────────────────┘
                │ HTML over HTTP                   │ JSON (chart data, polling)
┌───────────────▼──────────────────────────────────▼───────────────────┐
│                        Django application (single process)            │
│                                                                       │
│  ┌────────────┬────────────┬───────────┬───────────┬──────────────┐  │
│  │  accounts  │  registry  │ datasets  │ monitoring│    alerts    │  │
│  │  auth,     │  models,   │ baselines,│ runs,     │  rules,      │  │
│  │  roles,    │  versions  │ batches   │ results   │  lifecycle,  │  │
│  │  grants    │            │           │           │  email       │  │
│  └────────────┴────────────┴───────────┴─────┬─────┴──────────────┘  │
│  ┌────────────┬────────────┬───────────┐     │                        │
│  │ simulator  │ dashboard  │  apiv1    │     │                        │
│  └─────┬──────┴────────────┴─────┬─────┘     │                        │
│        │                          │           │                        │
│        │        ┌─────────────────▼───────────▼──────────────────┐    │
│        │        │      monitoring.engine  (pure Python, no ORM)   │    │
│        │        │  profiling · drift · quality · performance ·    │    │
│        │        │  health · explain          ← the project's core │    │
│        │        └────────────────────────────────────────────────┘    │
│        │                                                              │
│  ┌─────▼──────────────────────────────────────────────────────────┐  │
│  │  APScheduler BackgroundScheduler (in-process, single instance)  │  │
│  │  simulator ticks · alert cooldown sweeps · retention cleanup    │  │
│  └────────────────────────────────────────────────────────────────┘  │
└───────────────┬───────────────────────────────────┬───────────────────┘
                │                                   │
     ┌──────────▼──────────┐            ┌───────────▼───────────┐
     │  Relational DB       │            │  MEDIA_ROOT (disk)    │
     │  SQLite (WAL)        │            │  artifacts/ datasets/ │
     └──────────────────────┘            └───────────────────────┘
```

### 2.1 The one architectural rule that matters

`monitoring/engine/` is **pure Python**: it takes DataFrames and dicts, returns dicts, and
imports nothing from Django. Every ingestion path — CSV upload, simulator tick, REST endpoint —
converges on a single orchestrator that calls it.

Consequences, all deliberate:
- The statistical core is unit-testable without a database or an HTTP request
- Adding an ingestion path is adding a caller, never a new pipeline
- The maths can be demonstrated in a notebook during a viva, standalone

---

## 3. Project structure

```
driftguard/
├── manage.py
├── requirements.txt
├── .env.example
├── pytest.ini
├── config/
│   ├── settings/{base,dev,prod}.py
│   ├── urls.py, wsgi.py, asgi.py
├── core/                        # shared, app-agnostic
│   ├── models.py                # TimeStampedModel abstract base
│   ├── mixins.py                # RoleRequiredMixin, ModelAccessRequiredMixin
│   ├── validators.py            # upload validation (extension, size, sniffing)
│   ├── constants.py             # every enum/choice in the system
│   ├── audit.py                 # AuditLog writer
│   └── templatetags/
├── accounts/                    # FR-01
├── registry/                    # FR-02, FR-12
├── datasets/                    # baselines + batches
├── monitoring/                  # FR-03,04,08,09,13,14
│   ├── models.py
│   ├── services.py              # ORM-aware orchestration
│   └── engine/                  # ← PURE PYTHON, NO DJANGO IMPORTS
│       ├── profiling.py
│       ├── drift.py
│       ├── quality.py
│       ├── performance.py
│       ├── health.py
│       ├── explain.py
│       └── pipeline.py
├── alerts/                      # FR-06, FR-10
├── simulator/                   # FR-05
├── dashboard/                   # FR-07
├── apiv1/                       # ADD-1
├── templates/
├── static/{css,js,vendor}/
├── media/{artifacts,baselines,batches}/     # gitignored
├── scripts/
│   ├── prepare_datasets.py      # download/split Telco + Adult
│   ├── train_demo_models.py     # produce V1/V2/V3 artifacts
│   └── seed_demo.py             # users, models, grants, scenarios
└── tests/
```

---

## 4. Data model

Notation: `PK` primary key, `FK` foreign key, `→` relation. All tables inherit
`created_at` / `updated_at` from `TimeStampedModel`.

### 4.1 accounts

**`User`** *(extends `AbstractUser`)*
| Field | Type | Notes |
|---|---|---|
| `role` | choice | `ADMIN` / `DATA_SCIENTIST` / `ML_ENGINEER` |
| `is_active` | bool | deactivation gate (FR-01.3) |
| `failed_login_count` | int | lockout counter (FR-01.8) |
| `locked_until` | datetime? | |

**`LoginActivity`** — `user FK?`, `username_attempted`, `event` (`LOGIN_SUCCESS`/`LOGIN_FAILED`/`LOGOUT`), `ip_address`, `user_agent`, `occurred_at`
> `user` is nullable because a failed login may name a non-existent account. `username_attempted` is always stored.

**`ModelAccess`** — `user FK`, `ml_model FK`, `permission` (`VIEW`/`MANAGE`), `granted_by FK`, `granted_at`
> `unique_together(user, ml_model)`

### 4.2 registry

**`MLModel`** — `name`, `slug`, `description`, `problem_type` (`BINARY`/`MULTICLASS`), `target_column`, `positive_class` (nullable, binary only), `owner FK→User`, `is_active`, `created_at`
> `unique_together(owner, name)`

**`ModelVersion`** — `ml_model FK`, `version_number` (int, auto-increment per model), `label` (`V1`…), `artifact` FileField, `file_hash` (sha256), `file_size`, `algorithm_name`, `changelog`, `training_accuracy` (nullable), `status` (`INACTIVE`/`ACTIVE`/`ARCHIVED`), `validation_status` (`PENDING`/`PASSED`/`FAILED`), `validation_message`, `feature_schema` JSON, `baseline_prediction_distribution` JSON (nullable), `uploaded_by FK`, `uploaded_at`
> **Constraint:** at most one `status=ACTIVE` per `ml_model` — enforced by a partial unique index *and* a transactional service method.

**`ModelAuditLog`** — `ml_model FK`, `actor FK`, `action` (enum), `detail` JSON, `occurred_at` → serves FR-02.7

### 4.3 datasets

**`BaselineDataset`** — `ml_model FK`, `model_version FK`, `file` FileField, `original_filename`, `row_count`, `column_count`, `checksum`, `schema` JSON, `profile` JSON, `reference_sample` FileField, `uploaded_by FK`

- `schema`: `{column: {dtype, is_feature, is_target, is_excluded, role}}`
- `profile`: per column — numeric → `{count, missing, mean, std, min, q1, median, q3, max, bin_edges[], bin_counts[]}`; categorical → `{count, missing, n_unique, categories: {value: count}}`
- `reference_sample`: up to 50,000 rows sampled with `random_state=42`, stored as parquet. **The K-S test needs raw samples, not bins** — this is why it exists. Fixed seed satisfies PRD NFR-14.

**`DataBatch`** — `ml_model FK`, `model_version FK`, `source` (`UPLOAD`/`SIMULATOR`/`API`), `file` FileField?, `row_count`, `has_labels` bool, `status` (`PENDING`/`VALIDATING`/`PROCESSING`/`COMPLETED`/`FAILED`/`REJECTED`), `rejection_reason`, `submitted_by FK?`, `received_at`, `batch_index` int?

### 4.4 monitoring

**`MonitoringRun`** — the central historical record.
| Field | Type | Notes |
|---|---|---|
| `ml_model FK`, `model_version FK`, `data_batch FK` | | |
| `trigger_source` | choice | `MANUAL`/`SCHEDULED`/`UPLOAD`/`API` |
| `status` | choice | `QUEUED`/`RUNNING`/`COMPLETED`/`FAILED` |
| `started_at`, `completed_at`, `duration_ms` | | |
| `overall_drift_status` | choice | `NONE`/`MODERATE`/`HIGH` |
| `features_total`, `features_high`, `features_moderate`, `features_insufficient` | int | denormalised for fast list queries |
| `health_score` | int? | 0–100 |
| `health_band` | choice | `HEALTHY`/`WARNING`/`CRITICAL` |
| `health_components` | JSON | `{performance, drift, quality, stability}` + weights used |
| `labels_available` | bool | |
| `thresholds_snapshot` | JSON | **satisfies PRD FR-13.4 — history is immutable** |
| `error_message` | text | |

**`FeatureDriftResult`** — `run FK`, `feature_name`, `feature_type` (`NUMERIC`/`CATEGORICAL`), `test_name` (`KS`/`CHI2`), `test_statistic`, `p_value`, `psi`, `jsd`, `status` (`NONE`/`MODERATE`/`HIGH`/`INSUFFICIENT_DATA`), `explanation` text, `baseline_summary` JSON, `current_summary` JSON
> `index(run, status)`; `unique_together(run, feature_name)`

**`DataQualityReport`** — `run FK` (1:1), `missing_total`, `missing_pct`, `duplicate_rows`, `duplicate_pct`, `type_mismatch_columns` JSON, `unseen_category_columns` JSON, `out_of_range_columns` JSON, `outlier_counts` JSON, `outlier_pct`, `quality_score`, `per_column` JSON

**`PerformanceSnapshot`** — `run FK` (1:1), `labels_available`, `accuracy?`, `precision_positive?`, `recall_positive?`, `f1_positive?`, `precision_macro?`, `recall_macro?`, `f1_macro?`, `error_rate?`, `confusion_matrix` JSON?, `prediction_distribution` JSON, `sample_count`
> Every metric nullable — PRD FR-04.5 forbids representing "no labels" as zero.

### 4.5 alerts

**`ThresholdProfile`** — `ml_model FK?` (null = global default), all tunables from PRD §7–§10, `email_enabled`, `alert_cooldown_minutes`
> Resolution order: model profile → global profile → code defaults.

**`Alert`** — `ml_model FK`, `run FK?`, `severity`, `category`, `rule_code`, `title`, `message`, `feature_name?`, `status` (`NEW`/`ACKNOWLEDGED`/`RESOLVED`), `occurrence_count` (default 1), `first_seen_at`, `last_seen_at`, `acknowledged_by FK?`, `acknowledged_at?`, `resolved_by FK?`, `resolved_at?`, `email_sent` bool
> `index(ml_model, status, category, feature_name)` — the dedup lookup key (PRD §9.3)

**`RetrainRecommendation`** — `ml_model FK`, `run FK`, `severity` (`ADVISED`/`URGENT`), `triggers` JSON, `message` text, `status` (`OPEN`/`ACKNOWLEDGED`/`DISMISSED`), `actor FK?`, `note`, `created_at`, `resolved_at?`
> At most one `OPEN` per model (PRD FR-10.5).

### 4.6 simulator

**`SimulationScenario`** — `ml_model FK`, `name`, `description`, `interval_seconds`, `batch_size`, `include_labels` bool, `drift_plan` JSON, `status` (`STOPPED`/`RUNNING`/`PAUSED`), `next_batch_index` int, `holdout_file` FileField, `created_by FK`, `last_tick_at?`

`drift_plan` shape:
```json
{
  "phases": [
    { "from_batch": 0,  "transformations": [] },
    { "from_batch": 10, "transformations": [
        {"type": "numeric_shift",       "column": "MonthlyCharges", "mean_delta_sigma": 0.8},
        {"type": "missing_injection",   "column": "TotalCharges",   "rate": 0.05}
    ]},
    { "from_batch": 25, "transformations": [
        {"type": "numeric_shift",       "column": "MonthlyCharges", "mean_delta_sigma": 2.0},
        {"type": "numeric_scale",       "column": "MonthlyCharges", "std_multiplier": 1.4},
        {"type": "category_shift",      "column": "Contract",
         "target_proportions": {"Month-to-month": 0.75, "One year": 0.15, "Two year": 0.10}},
        {"type": "outlier_injection",   "column": "tenure",         "rate": 0.03},
        {"type": "duplicate_injection", "rate": 0.04}
    ]}
  ]
}
```

Supported transformation types (fixed set — PRD FR-05.7): `numeric_shift`, `numeric_scale`,
`category_shift`, `missing_injection`, `duplicate_injection`, `outlier_injection`.

### 4.7 Entity relationships

```
User ──< ModelAccess >── MLModel ──< ModelVersion ──1:1── BaselineDataset
 │                          │              │
 │                          │              └──< DataBatch ──1:1── MonitoringRun
 │                          │                                          │
 │                          ├──< ThresholdProfile                      ├──< FeatureDriftResult
 │                          ├──< SimulationScenario                    ├──1:1─ DataQualityReport
 │                          ├──< Alert ────────────────────────────────┤
 │                          ├──< RetrainRecommendation ────────────────┘
 │                          └──< ModelAuditLog
 └──< LoginActivity
```

---

## 5. The monitoring engine

Pure-Python modules under `monitoring/engine/`. Signatures are contracts.

### 5.1 `profiling.py`

```python
def build_profile(df: DataFrame, schema: dict) -> dict
def infer_schema(df: DataFrame, target_column: str) -> dict
def summarise_column(series: Series, col_type: str) -> dict
```

- Column typing: numeric if pandas dtype is numeric **and** `n_unique > 10`; otherwise
  categorical. Low-cardinality integers (e.g. `SeniorCitizen` ∈ {0,1}) are therefore correctly
  treated as categorical. The inferred type is overridable per column in the UI.
- Numeric binning: 10 quantile-based bins from the baseline, edges stored. Batches are binned
  using **the baseline's edges**, never recomputed — recomputing would hide the very shift being
  measured.

### 5.2 `drift.py` — the core of the project

```python
def ks_test(baseline: ndarray, current: ndarray) -> tuple[float, float]
def chi_square_test(baseline_counts: dict, current_counts: dict) -> tuple[float, float]
def population_stability_index(baseline_pct: ndarray, current_pct: ndarray) -> float
def jensen_shannon_divergence(baseline_pct: ndarray, current_pct: ndarray) -> float
def classify_feature(psi, jsd, p_value, n_base, n_cur, thresholds) -> str
def analyse_features(baseline_profile, ref_sample, batch_df, schema, thresholds) -> list[dict]
def rollup(results: list[dict], thresholds) -> str
```

Implementation notes that prevent real, known failures:

| Concern | Handling |
|---|---|
| `PSI = Σ (a−e)·ln(a/e)` divides by zero on empty bins | Add ε = 0.0001 to every proportion before the ratio; documented in code and in the report |
| Categorical values in the batch absent from the baseline | Treated as a bin with baseline proportion ε; also raises a data-quality `unseen_category` flag |
| Chi-Square needs adequate expected frequencies | Categories with expected count < 5 are merged into `__OTHER__` before the test |
| JSD base | `log2`, so range is exactly 0–1 and the PRD bands are meaningful |
| KS on huge samples | Both sides capped at 50,000 rows with a fixed seed — bounds runtime and satisfies NFR-14 |
| Constant column (zero variance both sides) | Returns PSI 0, JSD 0, status `NONE` — never NaN |
| All-null column in a batch | `INSUFFICIENT_DATA`, plus a quality flag |

Rules implemented: `classify_feature` → PRD §7.3; `rollup` → PRD §7.4.

### 5.3 `quality.py`

```python
def assess(batch_df, baseline_profile, schema, thresholds) -> dict
```
Implements PRD FR-11.1–11.6. Outliers by the IQR rule using **baseline** Q1/Q3, not the batch's —
using batch quartiles would define the drift away.

### 5.4 `performance.py`

```python
def score_batch(model, batch_df, feature_columns) -> ndarray
def compute_metrics(y_true, y_pred, labels, positive_class) -> dict
def prediction_distribution(y_pred, labels) -> dict
```
`zero_division=0` on sklearn metrics; both positive-class and macro averages stored (PRD FR-04.4).

### 5.5 `health.py`

```python
def compute(performance, drift_counts, quality_score, stability_jsd, labels_available) -> dict
```
Returns score, band, per-component scores and the weight set used. Implements PRD §8 exactly.

### 5.6 `explain.py`

```python
def explain_numeric(feature, baseline_summary, current_summary, scores, thresholds) -> str
def explain_categorical(feature, baseline_counts, current_counts, scores, thresholds) -> str
```
Deterministic templates (PRD FR-14.2). Categorical explanations name the top 2 risers and top 2
fallers by percentage-point change. Numbers formatted to 2 decimals; percentages to 1.

### 5.7 `pipeline.py` — the single convergence point

```python
def run_monitoring(
    batch_df: DataFrame,
    baseline_profile: dict,
    reference_sample: DataFrame,
    schema: dict,
    model,                       # loaded sklearn estimator
    thresholds: dict,
    baseline_prediction_dist: dict | None,
) -> dict
```

Returns a single nested result dict — quality, drift results, performance, health. Django-free,
so it is directly unit-testable and demonstrable in a notebook. `monitoring/services.py` is the
only thing that persists it.

---

## 6. Ingestion paths

All three converge on `monitoring.services.ingest_batch(...)`, which persists a `DataBatch`,
validates schema, calls `pipeline.run_monitoring`, writes the run and its children, then invokes
alert evaluation — in that order, inside one transaction per phase.

| Path | Entry point | Auth | Priority |
|---|---|---|---|
| (a) CSV upload | `datasets.views.BatchUploadView` | Session + `ModelAccess` | Core |
| (b) Simulator tick | `simulator.services.tick(scenario_id)` | System (scheduler) | Core |
| (c) REST | `POST /api/v1/models/<uuid>/batches/` | Per-model API key header | **Low — ADD-1** |

Full sequence in [BACKEND_FLOW.md](BACKEND_FLOW.md) §4.

---

## 7. Scheduling

APScheduler `BackgroundScheduler`, started in `simulator/apps.py::ready()`.

| Job | Trigger | Purpose |
|---|---|---|
| `scenario_tick_<id>` | interval, per running scenario | Produce a batch, run the cycle |
| `alert_cooldown_sweep` | every 5 min | Auto-resolve alerts whose condition cleared for N consecutive runs |
| `retention_cleanup` | daily | Delete batch files older than the retention window (DB records retained) |

Correctness guards (PRD R2, NFR-9):
- Start only when `os.environ.get('RUN_MAIN') == 'true'` or the reloader is off — otherwise
  Django's autoreloader starts two schedulers
- `max_instances=1`, `coalesce=True` per job
- Per-model advisory lock in `services.ingest_batch`; a tick that cannot acquire it logs and skips
- Every job body wrapped in try/except — an exception marks the run `FAILED`, raises a `RUN_FAILED`
  alert, and never propagates to the scheduler thread
- `next_batch_index` persisted on every tick, so restarts resume rather than replay

---

## 8. Security

| Area | Control |
|---|---|
| Passwords | Django PBKDF2-SHA256; validators for length and common passwords |
| Sessions | HttpOnly, SameSite=Lax, `SESSION_EXPIRE_AT_BROWSER_CLOSE` off, 8-hour idle expiry |
| CSRF | Django middleware on every POST |
| Authorization | `RoleRequiredMixin` + `ModelAccessRequiredMixin` on every view; querysets always filtered by grant, so object-level access cannot leak via list views |
| Lockout | 5 failures → 15-minute lock (PRD FR-01.8) |
| Upload validation | extension allowlist, 100 MB cap for artifacts / 50 MB for CSV, MIME sniff, SHA-256 recorded |
| Media serving | `MEDIA_ROOT` outside static; artifacts served only through an authenticated view, never by direct URL |
| SQL injection | ORM only; no raw SQL |
| XSS | Django autoescaping; `|safe` is banned outside the two audited explanation templates, whose content is generated by our own templates from numeric values |
| Secrets | `.env`, never committed; `.env.example` documents the keys |
| API keys (ADD-1) | Per-model, hashed at rest, shown once at creation |

### 8.1 The pickle risk — stated, not hidden

`joblib.load` executes arbitrary code during deserialisation. This is inherent to the format and
is **not solved** by this project. Mitigations in place: no public registration; upload restricted
to Admin and Data Scientist; extension, size and MIME validation; SHA-256 recorded for every
artifact; artifacts never served back to browsers.

This is recorded as accepted risk R1 in the PRD and should be stated openly in the project report
— examiners ask about it, and a prepared answer reads far better than being caught out.

---

## 9. Configuration

`.env` keys, all with safe defaults:

```ini
DEBUG=True
SECRET_KEY=
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=sqlite:///db.sqlite3

SCHEDULER_ENABLED=True
SIMULATOR_DEFAULT_INTERVAL_SECONDS=30      # demo default; UI shows production value too

EMAIL_ENABLED=False
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
DEFAULT_FROM_EMAIL=driftguard@localhost

MAX_ARTIFACT_MB=100
MAX_CSV_MB=50
REFERENCE_SAMPLE_MAX_ROWS=50000
BATCH_FILE_RETENTION_DAYS=30
```

Email is off by default and falls back to the console backend, so a demo needs no mail account
(PRD FR-06.6).

---

## 10. Performance

| Concern | Approach |
|---|---|
| Baseline re-profiling per run | Never — profile computed once at upload, stored as JSON |
| List views | `select_related` / `prefetch_related`; denormalised counters on `MonitoringRun` |
| Chart endpoints | Dedicated JSON views returning only plotted columns; capped at 500 points with server-side down-sampling |
| Large CSV | `pd.read_csv` with explicit dtypes from the stored schema |
| SQLite concurrency | WAL mode, short transactions, one background worker |
| Indexes | `(ml_model, started_at)` on runs; `(run, status)` on drift results; `(ml_model, status, category, feature_name)` on alerts |

Targets are PRD NFR-1 … NFR-4.

---

## 11. Testing

| Layer | Tool | Coverage target |
|---|---|---|
| Engine (`monitoring/engine/`) | pytest, no DB | **≥ 90%** — this is the project's core claim |
| Services | pytest-django | ≥ 75% |
| Views & permissions | Django test client | every row of the PRD §5.2 matrix asserted |
| Scheduler | fake ticks | job registration, lock behaviour, restart resume |
| E2E smoke | Django test client | seed → upload → run → alert → dashboard |

Non-negotiable engine tests:
1. Identical baseline and batch → PSI 0, JSD 0, status `NONE`
2. 2σ mean shift → `HIGH`, PSI > 0.25, KS p < 0.05
3. Categorical proportion flip → `HIGH` via Chi-Square + PSI
4. Empty bin present → PSI finite, no `inf`, no `NaN`
5. Unseen category → handled, quality flag raised
6. n < 30 → `INSUFFICIENT_DATA`, excluded from roll-up
7. Large-sample tiny difference → significant p but `NONE` (proves §7.3 is doing its job)
8. Health score with labels absent → weights redistributed and reported correctly
9. Same batch run twice → byte-identical scores (NFR-14)

---

## 12. Deployment

**Demo (primary):**
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python scripts/prepare_datasets.py
python scripts/train_demo_models.py
python scripts/seed_demo.py
python manage.py runserver --noreload      # --noreload: one scheduler only
```

`--noreload` is required, not cosmetic: the autoreloader spawns a second process and a second
scheduler (PRD R2).

**Production-shaped (optional):** gunicorn `--workers 1`, whitenoise for static, PostgreSQL via
`DATABASE_URL`. One worker only, because the scheduler is in-process. Moving to multiple workers
requires extracting the scheduler — noted in [BACKEND_FLOW.md](BACKEND_FLOW.md) §7.4 and out of
scope here.

---

## 13. Traceability

| PRD requirement | Implemented in |
|---|---|
| FR-01 | `accounts/`, `core/mixins.py` |
| FR-02, FR-12 | `registry/` |
| FR-03, FR-08 | `monitoring/engine/drift.py` |
| FR-04 | `monitoring/engine/performance.py` |
| FR-05 | `simulator/`, APScheduler jobs |
| FR-06 | `alerts/services.py` |
| FR-07 | `dashboard/`, `static/js/charts.js` |
| FR-09 | `monitoring/engine/health.py` |
| FR-10 | `alerts/retrain.py` |
| FR-11 | `monitoring/engine/quality.py` |
| FR-13 | `MonitoringRun` + children, `thresholds_snapshot` |
| FR-14 | `monitoring/engine/explain.py` |
| ADD-1 | `apiv1/` |

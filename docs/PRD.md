# Product Requirements Document (PRD)

**Product:** DriftGuard — Multi-User ML Model Monitoring & Data Drift Detection Platform
*(working name; rename is a find-and-replace at any time)*

| Field | Value |
|---|---|
| Document | PRD |
| Version | 1.0 |
| Status | Baselined — changes require a scope-change note in §13 |
| Source of truth | Client brief (14 numbered features + 7 "Extra Innovative Ideas") |
| Companion docs | [TRD.md](TRD.md), [APP_FLOW.md](APP_FLOW.md), [UIUX_DESIGN.md](UIUX_DESIGN.md), [BACKEND_FLOW.md](BACKEND_FLOW.md), [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) |

---

## 1. Product overview

### 1.1 The problem

An ML model is trained once on a fixed snapshot of data, but the world it predicts on keeps
moving. Customers change, prices change, behaviour changes. The model does not know this has
happened — it keeps returning confident predictions while quietly becoming wrong. The gap
between "the model still runs" and "the model is still correct" is invisible without tooling.

### 1.2 What DriftGuard is

A multi-user web platform where a team registers trained ML models along with the data those
models were trained on, then continuously feeds in new production data. For every batch of new
data the platform answers four questions:

1. **Is the incoming data clean?** (data quality)
2. **Does the incoming data still look like the training data?** (data drift, per feature)
3. **Is the model still performing?** (accuracy, precision, recall, F1, error rate)
4. **Given all of the above, how healthy is this model right now?** (0–100 health score)

…then raises alerts when thresholds are breached, explains *why* in plain English, recommends
retraining when warranted, and keeps the full history so trends are visible over time.

### 1.3 What DriftGuard is NOT

Stating this explicitly because it is the most common misreading of the brief:

- **It does not train models.** Models are trained elsewhere and uploaded as artifacts.
- **It does not retrain models.** It *recommends* retraining. (Client brief, feature 10, is
  explicit on this: "implement this as a recommendation system rather than automatically
  retraining the model.")
- **It is not a model-serving platform.** Predictions are computed for monitoring purposes only.
- **It is not a general BI tool.** Every chart exists to answer one of the four questions above.

### 1.4 Product goals

| # | Goal | How it is measured |
|---|---|---|
| G1 | Detect distribution change per feature, not just overall | Every monitored feature gets its own status and score |
| G2 | Make drift explainable to a non-statistician | Every drifted feature carries a plain-English sentence naming what changed and by how much |
| G3 | Reduce "is my model OK?" to one glance | Single 0–100 health score per model, banded 🟢🟡🔴 |
| G4 | Never require someone to be watching | Scheduled monitoring cycles run unattended and raise alerts |
| G5 | Preserve history | Every run, score, metric and alert is retained and trendable |
| G6 | Enforce access boundaries | A user sees only the models they are authorised for |

---

## 2. Scope — locked

### 2.1 In scope: all 14 numbered features from the client brief

| Ref | Feature | PRD section |
|---|---|---|
| 1 | Multi-User Login & Role Management | §5, §6 (FR-01) |
| 2 | ML Model Upload & Management | FR-02 |
| 3 | Data Drift Detection ⭐ | FR-03, §7 |
| 4 | Model Performance Monitoring | FR-04 |
| 5 | Real-Time / Periodic Monitoring | FR-05 |
| 6 | Smart Alert System | FR-06, §9 |
| 7 | Interactive Dashboard | FR-07 |
| 8 | Feature-Level Drift Analysis | FR-08 |
| 9 | Model Health Score ⭐ | FR-09, §8 |
| 10 | Automatic Retraining Recommendation | FR-10 |
| 11 | Data Quality Monitoring | FR-11 |
| 12 | Model Version Comparison | FR-12 |
| 13 | Monitoring History | FR-13 |
| 14 | Explainable Drift Detection | FR-14 |

Plus one agreed addition that is not one of the 14:

| Ref | Item | Priority |
|---|---|---|
| ADD-1 | REST ingestion endpoint (`POST /api/v1/…`) — ingestion path (c) from the agreed plan | **Low.** Built last, after all 14 are complete. Cut without renegotiation if effort runs short. |

### 2.2 Explicitly OUT of scope: the 7 "Extra Innovative Ideas"

Deliberately excluded by client decision. Listed so nobody re-adds them by accident:

| # | Excluded extra | Why the boundary is easy to blur |
|---|---|---|
| E1 | Multi-model comparison on one dashboard | Feature 12 (version comparison) *is* in scope. **V1 vs V2 of the same model: IN. Churn model vs Income model side by side: OUT.** |
| E2 | Automatic anomaly detection (record-level) | Feature 11 outlier detection *is* in scope. **Per-column IQR/z-score outlier counts: IN. Record-level IsolationForest anomaly scoring: OUT.** |
| E3 | Drift heatmap | Feature 8 per-feature drift *table* is IN. **Sortable status table: IN. Feature × time colour-grid heatmap: OUT.** |
| E4 | Prediction drift (statistical) | Feature 4 lists "prediction distribution" and feature 7 lists "prediction trends". **Charting the prediction mix over time: IN. Running a formal PSI/KS test on the prediction column and banding it as drift: OUT** — except as one internal input to the health score (§8), where it is not surfaced as a drift result. |
| E5 | Data drift + model drift as separate tracked concepts | Both signals exist (FR-03, FR-04) and both feed the health score and retrain logic. A distinct "model drift" entity with its own screens: OUT. |
| E6 | Model registry | Feature 2 already delivers upload, versions, activate/deactivate and history. No separate registry product surface, no registry API, no stage promotion workflow. |
| E7 | Admin analytics panel | Admin gets user management, model management, access grants and login activity (FR-01). A fleet-wide analytics dashboard (total users / active models / unhealthy models tiles): OUT. |

**Also out of scope, universally:** automated retraining execution, model serving/production
inference traffic, multi-tenancy or organisations, SSO/OAuth/LDAP, mobile native apps,
notification channels other than in-app and email, non-tabular data (image/text/audio),
non-scikit-learn model frameworks, and horizontal scaling.

---

## 3. Assumptions

Every assumption below is a decision, not a guess. Each one has a stated consequence if it turns
out to be wrong.

| # | Assumption | If wrong |
|---|---|---|
| A1 | Models are **scikit-learn** estimators or `Pipeline` objects, serialised with `joblib` or `pickle` | Supporting TF/PyTorch requires a new loader abstraction — roughly one extra phase |
| A2 | Uploaded artifacts accept **raw feature columns** (i.e. preprocessing is inside the `Pipeline`) — see §4.3 | Bare estimators needing external preprocessing cannot be scored; user must re-export as a Pipeline |
| A3 | Data is **tabular**, CSV, with a header row | Non-tabular is out of scope entirely |
| A4 | Supervised **classification** (binary or multiclass) | Regression needs a different metric set (MAE/RMSE/R²) — additive, ~1 week |
| A5 | Production batches **may or may not** carry the true-label column | Handled natively; no consequence. See FR-04 |
| A6 | Deployment is **single-node**, single web worker, on a laptop or small VM | Multi-worker needs the scheduler moved out of process (see [BACKEND_FLOW.md](BACKEND_FLOW.md) §7) |
| A7 | Dataset volumes are ≤ ~200k rows baseline, ≤ ~50k rows per batch | Larger needs chunked/streaming profiling |
| A8 | Users are trusted internal staff, no public registration | Public signup would make the pickle-loading risk (§11 R1) unacceptable |

---

## 4. Core concepts and glossary

Fixed vocabulary. These exact terms are used in every document, every model name, every screen
label. No synonyms.

| Term | Definition |
|---|---|
| **Model** | A logical monitored entity, e.g. "Customer Churn Model". Owns versions, datasets, thresholds, alerts, history. |
| **Version** | One uploaded artifact of a Model, e.g. V1, V2, V3. Exactly one version per Model may be **active** at a time. |
| **Baseline dataset** | The training/reference data uploaded against a Version. Defines the feature schema and the reference distributions that everything is compared against. |
| **Baseline profile** | Precomputed per-column statistics derived from the baseline dataset (bins, frequencies, mean, std, quantiles). Computed once, stored, reused by every run. |
| **Batch** | One arriving set of production rows. Arrives via CSV upload, the simulator, or the REST endpoint. |
| **Monitoring run** | One full evaluation of one Batch against one Version's baseline profile. Produces quality report + per-feature drift results + performance snapshot + health score + alerts. |
| **Drift** | A statistically and materially significant change in a feature's distribution, batch vs baseline. |
| **Drift status** | `NONE` 🟢 / `MODERATE` 🟡 / `HIGH` 🔴. Applies per feature and, rolled up, per run. |
| **Health score** | Integer 0–100 summarising performance + drift + quality + prediction stability for one run. |
| **Alert** | A record raised when a threshold is breached. Has severity, category, and a lifecycle. |
| **Threshold profile** | The set of tunable numbers governing drift bands, alert firing and retrain triggers. Global defaults, overridable per model. |
| **Scenario** | A simulator configuration that replays held-out rows on a timer, optionally injecting drift and quality faults. |

### 4.3 The model contract (critical — the #1 source of late-stage failure)

An uploaded artifact is accepted only if it satisfies **all** of these, verified at upload time
before the version can be activated:

1. Deserialises via `joblib.load` without error
2. Exposes a callable `.predict(X: DataFrame) -> array`
3. Successfully predicts on a 50-row sample drawn from the baseline dataset's **raw feature
   columns** (target column removed)
4. Output length equals input length
5. Output classes are a subset of the classes present in the baseline target column

If any check fails, the upload is rejected with a specific, actionable message naming the failed
check. **A version that has not passed validation can never be activated**, which guarantees no
monitoring run can fail on a bad artifact.

`.predict_proba()` is optional. When present it is used for prediction-confidence display; when
absent that panel is hidden. Nothing else depends on it.

---

## 5. Users and roles

Three roles, exactly as the brief specifies. Role is a single attribute on the user — a user has
one role.

| Role | Who they are | What they care about |
|---|---|---|
| **Admin** | Platform owner | Users, access grants, the full model list, audit trail |
| **Data Scientist** | Owns the model | Registering models, uploading versions and baselines, tuning thresholds, diagnosing drift, deciding on retraining |
| **ML Engineer** | Operates the model in production | Feeding production data in, watching health, triaging and resolving alerts |

### 5.1 Access model

Two independent layers, both enforced server-side on every request:

1. **Role** — what kind of action the user may perform at all
2. **Model access grant** — which specific models the user may perform it on

An explicit `ModelAccess` grant (`VIEW` or `MANAGE`) links a user to a model. Admin bypasses
grants and sees everything. A Data Scientist automatically receives a `MANAGE` grant on any model
they create. This is the mechanism behind the brief's *"Each user can access only their
authorized models."*

### 5.2 Permission matrix

Authoritative. Every server-side check maps to exactly one row here.

| Capability | Admin | Data Scientist | ML Engineer |
|---|---|---|---|
| Create / edit / deactivate users | ✅ | ❌ | ❌ |
| Grant or revoke model access | ✅ | ❌ | ❌ |
| View login activity (all users) | ✅ | ❌ | ❌ |
| View own login activity | ✅ | ✅ | ✅ |
| Create model | ✅ | ✅ | ❌ |
| Delete model | ✅ | ❌ | ❌ |
| Upload model version | ✅ | ✅ (MANAGE) | ❌ |
| Activate / deactivate model or version | ✅ | ✅ (MANAGE) | ❌ |
| Upload baseline dataset | ✅ | ✅ (MANAGE) | ❌ |
| Upload production batch | ✅ | ✅ (MANAGE) | ✅ (VIEW+) |
| Trigger "Run check now" | ✅ | ✅ (MANAGE) | ✅ (VIEW+) |
| Edit threshold profile | ✅ | ✅ (MANAGE) | ❌ |
| Create / start / stop simulator scenario | ✅ | ✅ (MANAGE) | ❌ |
| View dashboard, drift, performance, quality, history | ✅ all | ✅ granted | ✅ granted |
| Compare versions | ✅ | ✅ granted | ✅ granted |
| Acknowledge / resolve alerts | ✅ | ✅ granted | ✅ granted |
| Dismiss retraining recommendation | ✅ | ✅ (MANAGE) | ❌ |

---

## 6. Functional requirements

Format: `FR-<module>.<n>`. Each has acceptance criteria that are objectively testable.

### FR-01 — User management and roles *(brief feature 1)*

- **FR-01.1** Username/password login. Session-based. Passwords hashed (Django PBKDF2, never plaintext).
- **FR-01.2** Every user has exactly one role: `ADMIN`, `DATA_SCIENTIST`, `ML_ENGINEER`.
- **FR-01.3** Admin can create, edit, deactivate and reactivate users. Deactivated users cannot log in. Users are never hard-deleted (history integrity).
- **FR-01.4** Admin can grant/revoke per-model `VIEW` or `MANAGE` access to any non-admin user.
- **FR-01.5** Every login success, login failure and logout is recorded with username, timestamp, IP and user agent.
- **FR-01.6** Admin can view, filter (by user, by event type, by date) and paginate the login activity log.
- **FR-01.7** Unauthorised access to a model returns HTTP 403 and is not distinguishable in the UI from the model not existing.
- **FR-01.8** Five consecutive failed logins for one username locks that account for 15 minutes.

**Acceptance:** an ML Engineer granted access to Model A and not Model B cannot reach Model B's
detail page, monitoring runs, alerts, or any of its data by direct URL manipulation.

### FR-02 — Model upload and management *(brief feature 2)*

- **FR-02.1** Create a model with name (unique per owner), description, problem type (`BINARY` / `MULTICLASS`), and target column name.
- **FR-02.2** Upload a version: artifact file, version label (auto-incremented `V1`, `V2`, …), changelog note, and optional recorded training accuracy.
- **FR-02.3** Every uploaded artifact runs the §4.3 validation gate. Failures are rejected with the specific reason.
- **FR-02.4** Exactly one version per model may be `ACTIVE`. Activating a version automatically deactivates the previously active one, in a single transaction.
- **FR-02.5** Versions can be `ARCHIVED`. Archived versions keep all history and remain viewable and comparable, but cannot be activated or used for scoring.
- **FR-02.6** A model can be deactivated. Deactivated models run no scheduled monitoring and accept no new batches, but all history remains readable.
- **FR-02.7** Model history shows a chronological audit of every version upload, activation, deactivation, baseline change and threshold change, with actor and timestamp.
- **FR-02.8** Artifact file size limit 100 MB; extensions `.pkl`, `.joblib` only; SHA-256 recorded at upload.

**Acceptance:** uploading a corrupt `.pkl` produces a clear rejection message and creates no version record.

### FR-03 — Data drift detection *(brief feature 3)* ⭐

- **FR-03.1** Numerical features are tested with the **two-sample Kolmogorov–Smirnov test**.
- **FR-03.2** Categorical features are tested with the **Chi-Square test of independence**.
- **FR-03.3** **PSI (Population Stability Index)** is computed for every feature, numeric and categorical.
- **FR-03.4** **Jensen–Shannon Divergence** (base-2, range 0–1) is computed for every feature.
- **FR-03.5** Each feature is assigned `NONE` / `MODERATE` / `HIGH` by the combination rule in §7.3.
- **FR-03.6** The run receives a rolled-up overall drift status by the rule in §7.4.
- **FR-03.7** Every score is stored with the run, permanently.
- **FR-03.8** Features with fewer than 30 non-null values in either baseline or batch are marked `INSUFFICIENT_DATA` and excluded from the roll-up rather than silently reported as `NONE`.

**Acceptance:** given a batch where a numeric feature's mean is shifted by 2σ, that feature is
`HIGH`, its PSI exceeds the high threshold, and the KS p-value is < 0.05.

### FR-04 — Model performance monitoring *(brief feature 4)*

- **FR-04.1** Every batch is scored by the model's active version to produce predictions.
- **FR-04.2** Prediction distribution (count and percentage per predicted class) is computed and stored for **every** run, regardless of labels.
- **FR-04.3** When the batch contains the target column, compute **accuracy, precision, recall, F1** and **error rate** (= 1 − accuracy), plus the confusion matrix.
- **FR-04.4** For binary problems, precision/recall/F1 are reported for the positive class **and** as macro averages. Both are stored; the UI shows positive-class by default with a toggle.
- **FR-04.5** When the batch does **not** contain the target column, performance metrics are recorded as unavailable — never as zero, never as null-rendered-as-0. The UI states "No labels in this batch".
- **FR-04.6** Metrics are plotted over time across runs.
- **FR-04.7** Runs without labels are visibly gapped in performance charts, not interpolated over.

**Acceptance:** a batch with no target column completes successfully with full drift and quality
results, an explicit "labels unavailable" state, and a health score computed on the redistributed
weights of §8.3.

### FR-05 — Periodic monitoring *(brief feature 5)*

- **FR-05.1** A scenario can be configured per model: interval, batch size, label inclusion, and a drift plan.
- **FR-05.2** On each tick the scheduler produces a batch and runs the full monitoring cycle unattended.
- **FR-05.3** Interval is configurable per scenario from 10 seconds to 24 hours. The UI presents both the configured production value and a demo preset.
- **FR-05.4** Scenarios can be started, paused, resumed and stopped. Position (next batch index) survives an application restart.
- **FR-05.5** A **Run check now** action triggers an immediate cycle without waiting for the tick, from any batch or model screen.
- **FR-05.6** Two runs for the same model never execute concurrently; a tick arriving while a run is in progress is skipped and logged.
- **FR-05.7** The drift plan supports phased injection: distribution shift (numeric mean/variance), categorical proportion shift, missing-value injection, duplicate injection and outlier injection, each activating at a configured batch index.

**Acceptance:** starting a scenario configured to shift `MonthlyCharges` from batch 10 produces
runs whose drift status progresses `NONE → MODERATE → HIGH` with no human interaction, and the
progression survives stopping and restarting the server.

### FR-06 — Smart alert system *(brief feature 6)*

- **FR-06.1** Alerts fire on the rules in §9.1.
- **FR-06.2** Each alert has severity (`INFO` / `WARNING` / `CRITICAL`), category (`DRIFT` / `PERFORMANCE` / `QUALITY` / `HEALTH` / `RETRAIN` / `SYSTEM`), title, message, optional feature name, and links to its run.
- **FR-06.3** Lifecycle: `NEW → ACKNOWLEDGED → RESOLVED`. Actor and timestamp recorded at each transition.
- **FR-06.4** Deduplication: an identical (model, category, feature) alert is not re-raised while an unresolved one exists within the cooldown window (default 60 minutes). Instead the existing alert's occurrence counter and last-seen timestamp increment.
- **FR-06.5** Unresolved alert count is visible in the global header at all times.
- **FR-06.6** Email delivery is optional and off by default. When enabled it sends `CRITICAL` alerts only, to the model's granted users. Failure to send is logged and never fails the monitoring run.
- **FR-06.7** Alerts are filterable by model, severity, category and status.

**Acceptance:** a simulator producing 20 consecutive high-drift runs on the same feature yields
one alert with an occurrence count of 20, not 20 alerts.

### FR-07 — Interactive dashboard *(brief feature 7)*

Charts required by the brief, all in scope:

- **FR-07.1** Model performance over time (accuracy / precision / recall / F1, selectable)
- **FR-07.2** Drift score over time
- **FR-07.3** Feature distribution comparison — baseline vs latest batch, per selected feature
- **FR-07.4** Prediction trend over time (predicted class mix)
- **FR-07.5** Alert count over time, split by severity
- **FR-07.6** Model health score over time, with the 🟢🟡🔴 bands shown as background regions
- **FR-07.7** All time-series charts respect a shared range control (last 24h / 7d / 30d / all)
- **FR-07.8** Every chart has a hover tooltip and an accessible table view of the same data
- **FR-07.9** The landing dashboard is role-aware (see [APP_FLOW.md](APP_FLOW.md) §3)

### FR-08 — Feature-level drift analysis *(brief feature 8)*

- **FR-08.1** Every run produces one row per monitored feature: name, type, test used, test statistic, p-value, PSI, JSD, status.
- **FR-08.2** The table is sortable by every column and defaults to worst-drift-first.
- **FR-08.3** Clicking a feature opens a detail view with the baseline-vs-current distribution chart and the full explanation.
- **FR-08.4** A feature can be excluded from monitoring (e.g. IDs, timestamps); excluded features are shown as such and never contribute to the roll-up.
- **FR-08.5** Status is never conveyed by colour alone — every badge carries an icon and a text label.

### FR-09 — Model health score *(brief feature 9)* ⭐

- **FR-09.1** Integer 0–100 computed per run by the formula in §8.
- **FR-09.2** Four weighted components: performance, drift, data quality, prediction stability.
- **FR-09.3** Bands: `HEALTHY` ≥ 80 🟢, `WARNING` 60–79 🟡, `CRITICAL` < 60 🔴.
- **FR-09.4** The UI shows the component breakdown, so the score is never a black box.
- **FR-09.5** When labels are absent, weights are redistributed per §8.3 and the UI states which weighting was used.
- **FR-09.6** Health is trended over time.

### FR-10 — Retraining recommendation *(brief feature 10)*

- **FR-10.1** A recommendation is generated when any trigger in §10 fires.
- **FR-10.2** The recommendation names every trigger that fired, with its measured value against its threshold.
- **FR-10.3** Severity is `ADVISED` or `URGENT`.
- **FR-10.4** Lifecycle `OPEN → ACKNOWLEDGED → DISMISSED`, with actor, timestamp and an optional note.
- **FR-10.5** At most one `OPEN` recommendation exists per model at a time; further triggers update it.
- **FR-10.6** **The platform never retrains anything.** The recommendation is advisory text only.

### FR-11 — Data quality monitoring *(brief feature 11)*

Every check named in the brief:

- **FR-11.1** Missing values — per column count and %, plus overall %
- **FR-11.2** Duplicate records — count and % of exact duplicate rows
- **FR-11.3** Invalid values — values outside the baseline observed range, and categorical values never seen in the baseline
- **FR-11.4** Outliers — per numeric column by the IQR rule (below Q1 − 1.5·IQR or above Q3 + 1.5·IQR), count and %
- **FR-11.5** Incorrect data types — column dtype differing from the baseline schema
- **FR-11.6** A 0–100 quality score by the formula in §8.5
- **FR-11.7** Schema violations (missing required column) **reject** the batch; all other findings are recorded and the run proceeds

### FR-12 — Model version comparison *(brief feature 12)*

- **FR-12.1** Select any two versions of the **same** model and compare side by side.
- **FR-12.2** Compared: recorded training accuracy, latest observed metrics, mean metrics over the compared window, mean health score, drifted-feature counts, total runs, total alerts.
- **FR-12.3** The better value in each row is explicitly marked, with the delta.
- **FR-12.4** An overall verdict line, e.g. *"V2 outperforms V1 on accuracy by 3.1 points across 42 runs."*
- **FR-12.5** Comparison is only meaningful across versions sharing a feature schema; where schemas differ, the UI says so and suppresses the drift comparison rows.

### FR-13 — Monitoring history *(brief feature 13)*

- **FR-13.1** Every monitoring run is retained with its full child records.
- **FR-13.2** History is browsable per model, filterable by date range, status, drift status and trigger source, and paginated.
- **FR-13.3** Any historical run can be reopened in full detail exactly as it appeared when produced.
- **FR-13.4** Historical results are **immutable** — a threshold change does not retroactively alter stored statuses. Each run stores the thresholds it was evaluated under.
- **FR-13.5** History is exportable to CSV.

### FR-14 — Explainable drift detection *(brief feature 14)*

- **FR-14.1** Every feature with `MODERATE` or `HIGH` status receives a generated plain-English explanation.
- **FR-14.2** Explanations are **template-driven and deterministic** — no LLM, no external service, no network call. The same inputs always produce the same sentence.
- **FR-14.3** A numeric explanation names the direction and size of the shift in mean and spread, with real units.
- **FR-14.4** A categorical explanation names the categories whose share rose and fell the most, with before/after percentages.
- **FR-14.5** Every explanation states which threshold was crossed and by how much.
- **FR-14.6** Explanations are stored with the run, not regenerated on read.

Worked examples of the required output shape:

> **Numeric —** High drift detected in `MonthlyCharges`. The average rose from **64.80** in the
> baseline to **89.32** in this batch (**+37.8%**), and the spread widened (std 30.09 → 41.57).
> PSI is **0.34**, above the high-drift threshold of 0.25. The K-S test returns p < 0.001,
> confirming the two distributions differ.

> **Categorical —** Moderate drift detected in `Contract`. The share of *Month-to-month* rose from
> **55.0%** to **71.2%** (+16.2 points) while *Two year* fell from **24.1%** to **9.8%**
> (−14.3 points). PSI is **0.18**, above the moderate threshold of 0.10.

---

## 7. Drift specification — authoritative numbers

All values are defaults in the global threshold profile and are overridable per model. Every
monitoring run stores the values it used (FR-13.4).

### 7.1 Statistical tests

| Feature type | Significance test | Statistic | Default α |
|---|---|---|---|
| Numeric | Two-sample Kolmogorov–Smirnov | D | 0.05 |
| Categorical | Chi-Square test of independence | χ² | 0.05 |

### 7.2 Magnitude bands

| Measure | NONE 🟢 | MODERATE 🟡 | HIGH 🔴 |
|---|---|---|---|
| **PSI** | < 0.10 | 0.10 – 0.25 | > 0.25 |
| **JSD** (base-2) | < 0.10 | 0.10 – 0.20 | > 0.20 |

PSI bands follow the standard credit-risk convention (< 0.1 stable, 0.1–0.25 moderate shift,
> 0.25 significant shift). This is a documented, citable convention — worth stating in the
project report.

### 7.3 Per-feature combination rule

Significance and magnitude are combined deliberately, because **neither alone is trustworthy**:
with large samples a KS test returns p < 0.05 for differences too small to matter, while
magnitude measures alone can over-react on small samples.

```
1. band_psi  := band(PSI)              # NONE / MODERATE / HIGH per §7.2
2. band_jsd  := band(JSD)
3. magnitude := worst(band_psi, band_jsd)
4. significant := (p_value < alpha)
5. if magnitude == NONE          -> status = NONE
   elif significant              -> status = magnitude
   else                          -> status = one level below magnitude
6. if n_baseline < 30 or n_batch < 30 -> status = INSUFFICIENT_DATA
```

Step 5's downgrade is the guard against small-sample false alarms. It is deterministic and easy
to defend in a viva.

### 7.4 Run-level roll-up

Let `H` = count of `HIGH` features, `M` = count of `MODERATE`, `T` = total features evaluated
(excluding `INSUFFICIENT_DATA` and excluded features).

```
HIGH      if H >= 1  OR  (M / T) >= 0.30
MODERATE  else if M >= 1
NONE      otherwise
```

---

## 8. Scoring specification — authoritative formulas

### 8.1 Component: performance (0–100)

```
reference_accuracy := version.training_accuracy
                      (if not recorded, the accuracy of that version's first labelled run)
drop  := max(0, reference_accuracy - current_accuracy)      # in points, 0–1 scale
score := clamp(0, 100, 100 - drop * 200)
```

A 10-point accuracy drop scores 80. A 25-point drop scores 50. A 50-point drop scores 0.

### 8.2 Component: drift, quality, prediction stability (0–100 each)

```
drift_score      := max(0, 100 - (15 * high_count + 6 * moderate_count))
quality_score    := see §8.5
stability_score  := clamp(0, 100, 100 - 200 * JSD(baseline_prediction_dist, batch_prediction_dist))
```

`baseline_prediction_dist` is computed once, when a version is activated, by scoring the baseline
dataset with that version and storing the resulting class distribution.

### 8.3 Weights

| Component | Labels present | Labels absent |
|---|---|---|
| Performance | 40 | — (0) |
| Drift | 30 | 50 |
| Data quality | 20 | 35 |
| Prediction stability | 10 | 15 |

```
health = round( Σ (component_score × weight) / Σ weights )
```

The UI always states which weighting was applied (FR-09.5).

### 8.4 Bands

| Band | Range | Indicator |
|---|---|---|
| HEALTHY | 80 – 100 | 🟢 |
| WARNING | 60 – 79 | 🟡 |
| CRITICAL | 0 – 59 | 🔴 |

### 8.4a Coherence cap

```
if run.overall_drift_status == HIGH:
    health = min(health, 79)     # can never be reported as HEALTHY
```

**Why this exists.** Drift carries only 30 of the 100 weight, so the plain
weighted formula can return a HEALTHY score while several features sit at HIGH
drift. Measured on real Telco data during implementation: 3 of 19 features at
`HIGH`, accuracy down 4 points, quality 87 → **score 81, band HEALTHY**.

That result is self-contradictory in the UI. The run detail page (S13) shows the
drift badge and the health badge side by side, so it would display 🔴 High Drift
next to 🟢 Healthy — while §10 simultaneously raises an **URGENT** retraining
recommendation, because `HIGH` drift is a CRITICAL-tier trigger.

The health score exists so that one glance is enough (goal G3). A number that
disagrees with everything beside it fails that purpose, so the band is capped.

`MODERATE` drift is deliberately **not** capped — it is a signal to weigh against
the other components, not an override.

Both numbers are stored and displayed: `raw_score` (the uncapped formula result)
and `score` (after the cap), plus a `capped` flag. The cap is auditable rather
than invisible.

### 8.5 Data quality score

```
penalty  = min(30, overall_missing_pct   * 1.5)
         + min(20, duplicate_row_pct     * 1.0)
         + min(20, 10 * n_type_mismatched_columns)
         + min(15, 3  * n_columns_with_unseen_categories)
         + min(15, overall_outlier_pct   * 0.5)

quality_score = max(0, 100 - penalty)
```

---

## 9. Alerting specification

### 9.1 Rules

| Rule | Condition | Severity | Category |
|---|---|---|---|
| `DRIFT_HIGH` | any feature `HIGH` | CRITICAL | DRIFT |
| `DRIFT_MODERATE` | any feature `MODERATE`, none `HIGH` | WARNING | DRIFT |
| `PERFORMANCE_DROP_MAJOR` | accuracy ≥ 10 points below reference | CRITICAL | PERFORMANCE |
| `PERFORMANCE_DROP_MINOR` | accuracy 5–10 points below reference | WARNING | PERFORMANCE |
| `QUALITY_POOR` | quality score < 50 | CRITICAL | QUALITY |
| `QUALITY_DEGRADED` | quality score 50–69 | WARNING | QUALITY |
| `HEALTH_CRITICAL` | health score < 60 | CRITICAL | HEALTH |
| `HEALTH_WARNING` | health score 60–79 | WARNING | HEALTH |
| `RETRAIN_RECOMMENDED` | any §10 trigger fires | CRITICAL | RETRAIN |
| `RUN_FAILED` | monitoring run raised an exception | CRITICAL | SYSTEM |
| `BATCH_REJECTED` | batch failed schema validation | WARNING | SYSTEM |

### 9.2 Alert message shape

Matches the brief's example:

```
⚠️  Data Drift Detected
Model:   Customer Churn Model
Feature: Monthly Charges
Drift:   High  (PSI 0.34, threshold 0.25)
Run:     #218 · 16 Aug 2026, 14:05
```

### 9.3 Deduplication

Key = `(model, category, feature_name)`. While an unresolved alert with that key exists and the
cooldown window (default 60 min) has not elapsed, increment `occurrence_count` and
`last_seen_at` instead of creating a new row. This is what stops a fast simulator from generating
hundreds of identical alerts.

---

## 10. Retraining recommendation triggers

A recommendation is raised if **any** trigger fires. Severity is `URGENT` if two or more fire, or
if any single CRITICAL-tier trigger fires; otherwise `ADVISED`.

| Trigger | Default | Tier |
|---|---|---|
| Run-level drift status is `HIGH` | — | CRITICAL |
| Count of `MODERATE`-or-worse features ≥ N | N = 3 | ADVISED |
| Accuracy below reference by ≥ X points | X = 5 | CRITICAL |
| Health score < 60 for K consecutive runs | K = 2 | CRITICAL |
| Quality score < 50 for K consecutive runs | K = 2 | ADVISED |

---

## 11. Non-functional requirements

| Ref | Requirement | Target |
|---|---|---|
| NFR-1 | Page load (non-chart) | < 1.5 s on the demo machine |
| NFR-2 | Dashboard with charts | < 3 s |
| NFR-3 | Monitoring run, 10k-row batch × 20 features | < 15 s |
| NFR-4 | Concurrent users supported | 10 |
| NFR-5 | Passwords | hashed, never logged, never in fixtures as plaintext except seeded demo accounts |
| NFR-6 | Authorisation | enforced server-side on every view and API route; UI hiding is never the only control |
| NFR-7 | CSRF | enabled on every state-changing form |
| NFR-8 | Uploads | extension allowlist, size cap, content sniffing, stored outside the static root |
| NFR-9 | A monitoring run failure | never crashes the scheduler; run marked `FAILED`, alert raised, next tick proceeds |
| NFR-10 | Offline operation | zero CDN dependencies — all JS/CSS/fonts vendored locally so the demo works with no internet |
| NFR-11 | Browser support | current Chrome, Firefox, Edge, Safari |
| NFR-12 | Accessibility | WCAG 2.1 AA contrast; status never colour-alone; full keyboard navigation |
| NFR-13 | Database portability | ORM-only queries; switching SQLite → PostgreSQL/MySQL is a settings change |
| NFR-14 | Reproducibility | all sampling uses a fixed seed; the same batch re-run yields identical scores |

---

## 12. Risks

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| R1 | `joblib.load` on an uploaded file executes arbitrary code | High | No public registration (A8); upload restricted to Admin/Data Scientist; extension + size + hash validation; documented as a known limitation with a prepared viva answer. Accepted, not solved. |
| R2 | Scheduler double-firing under Django's auto-reloader or multiple workers | Medium | Single-worker deployment; `RUN_MAIN` guard; per-model run lock (FR-05.6) |
| R3 | KS test flags trivial differences on large batches | Medium | The §7.3 combination rule — magnitude decides, significance only gates |
| R4 | Alert flooding from a fast simulator | Medium | Deduplication + cooldown (§9.3) |
| R5 | Demo interval of 1 hour makes the demo unwatchable | High | Configurable interval, demo preset, and a "Run check now" button (FR-05.3, FR-05.5) |
| R6 | Uploaded model expects preprocessed input and fails at scoring time | High | The §4.3 validation gate at upload — a version that cannot predict can never be activated |
| R7 | Version comparison across incompatible schemas produces nonsense | Medium | FR-12.5 detects and suppresses |
| R8 | SQLite write contention between scheduler and web requests | Medium | WAL mode, short transactions, single background worker |

---

## 13. Open questions

Both are non-blocking — work proceeds on the stated default, and changing the answer later is
cheap.

| # | Question | Default being built |
|---|---|---|
| Q1 | Does the client want a specific business domain instead of Telco Churn? | Telco Customer Churn (V1/V2/V3) + Adult Income. Swapping the domain is a data-and-fixtures change, not a code change. |
| Q2 | Should the simulator be visible to the examiner, or presented only as "scheduled monitoring"? | Visible, on its own screen, described as a *data feed simulator for demonstration*. It can be hidden behind a settings flag in one line if the guide prefers. |

---

## 14. Demo data shipped with the platform

| Model | Dataset | Rows | Versions | Purpose |
|---|---|---|---|---|
| Customer Churn Model | Telco Customer Churn | ~7,000 | V1 Logistic Regression, V2 Random Forest, V3 Gradient Boosting | Mixed numeric + categorical columns exercise both K-S and Chi-Square. Three versions make FR-12 real. |
| Income Prediction Model | Adult Income (Census) | ~48,000 | V1 Random Forest | Exists to make **role-based access control demonstrable** — one user can be granted this model and denied the other. (Note: with extra E1 out of scope, this model is *not* for cross-model comparison.) |

Split per dataset: **60% baseline** (training/reference), **20% simulator holdout** (replay pool),
**20% test** (used for manual batch upload demos).

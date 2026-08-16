# Backend Flow

**Product:** DriftGuard — Multi-User ML Model Monitoring & Data Drift Detection Platform

| Field | Value |
|---|---|
| Document | BACKEND_FLOW |
| Version | 1.0 |
| Scope | Server-side execution — request lifecycles, the monitoring pipeline, transactions, scheduling, failure handling |
| Depends on | [TRD.md](TRD.md) (stack, data model, engine signatures), [PRD.md](PRD.md) (thresholds, formulas) |

---

## 1. Layering

Strict, one-directional. A layer never calls upward.

```
  views/          HTTP. Parse, authorise, delegate, render. No business logic. No pandas.
      │
      ▼
  services/       ORM-aware orchestration. Owns transactions. The only layer that writes.
      │
      ▼
  engine/         Pure Python. DataFrames in, dicts out. NO Django import, ever.
      │
      ▼
  models/         Django ORM. Persistence only — no computation on model classes.
```

**The rule that keeps the project honest:** `monitoring/engine/` may not import Django. Enforced
by a unit test that walks the package and asserts no module has `django` in its imports. This is
what makes the statistical core testable in isolation and demonstrable in a notebook — the single
most valuable property of the codebase for a viva.

---

## 2. Request lifecycle (every authenticated request)

```
Request
  │
  ├─ SecurityMiddleware / SessionMiddleware / CsrfViewMiddleware
  ├─ AuthenticationMiddleware            → request.user
  ├─ LoginActivityMiddleware             → records login/logout events (FR-01.5)
  │
  ├─ LoginRequiredMixin                  → not authenticated? 302 /login/?next=
  ├─ RoleRequiredMixin                   → role not permitted? 403 (PRD §5.2)
  ├─ ModelAccessRequiredMixin            → no grant on this model? 403 (identical page
  │                                          whether or not the model exists — FR-01.7)
  ├─ View.get_queryset()                 → ALWAYS filtered by grant, so list views
  │                                          cannot leak objects the user may not see
  ├─ Service call                        → business logic, transaction boundary
  └─ Template render / JsonResponse
```

### 2.1 The queryset filter — one helper, used everywhere

```python
def visible_models(user):
    if user.role == Role.ADMIN:
        return MLModel.objects.all()
    return MLModel.objects.filter(access_grants__user=user).distinct()
```

Every model-scoped queryset in the project derives from this. Object-level permission is never
re-implemented per view, which is how object-level checks get forgotten.

---

## 3. Authentication flow

```
POST /login/  {username, password}
  │
  ├─ user exists?  ── no ──► record LOGIN_FAILED (user=None, username_attempted=…)
  │                          generic error, same wording and timing as a wrong password
  │
  ├─ locked_until > now? ──► "Account locked. Try again in N minutes." (FR-01.8)
  │
  ├─ authenticate()
  │    ├─ fail ─► failed_login_count += 1
  │    │          if count >= 5: locked_until = now + 15 min
  │    │          record LOGIN_FAILED
  │    └─ ok   ─► failed_login_count = 0, locked_until = None
  │               is_active false? ─► "Account deactivated." (FR-01.3)
  │               login(request, user)
  │               record LOGIN_SUCCESS (ip, user_agent)
  │               redirect ?next or /
  │
  └─ logout: record LOGOUT, flush session
```

Failure responses are deliberately identical for "no such user" and "wrong password" so the form
cannot be used to enumerate usernames.

---

## 4. The monitoring pipeline — the core flow

Every ingestion path converges here. This is the most important sequence in the system.

### 4.1 Sequence

```
ingest_batch(ml_model, dataframe, source, submitted_by=None, batch_index=None)
│
├─ 1. PRE-FLIGHT
│     ├─ model.is_active?                    else → reject "Model is deactivated"
│     ├─ active_version exists?              else → reject "No active version"
│     ├─ version.validation_status == PASSED else → reject (cannot happen; defence in depth)
│     └─ baseline dataset exists?            else → reject "No baseline dataset"
│
├─ 2. ACQUIRE PER-MODEL LOCK
│     ├─ acquired → continue
│     └─ busy    → log, return SKIPPED  (PRD FR-05.6 — no concurrent runs per model)
│
├─ 3. PERSIST BATCH                          [transaction 1 — short]
│     DataBatch(status=PENDING → VALIDATING), file written to MEDIA_ROOT
│
├─ 4. SCHEMA VALIDATION
│     ├─ required feature column missing
│     │     → batch.status = REJECTED, rejection_reason names the columns
│     │     → raise BATCH_REJECTED alert
│     │     → release lock, return
│     ├─ extra columns          → dropped, noted on the run
│     └─ target column present? → has_labels = True
│
├─ 5. CREATE RUN                             [transaction 2 — short]
│     MonitoringRun(status=QUEUED → RUNNING, thresholds_snapshot=resolved_thresholds)
│     ↑ snapshotting thresholds here is what makes history immutable (PRD FR-13.4)
│
├─ 6. LOAD RESOURCES                         (cached, see §6)
│     ├─ sklearn artifact  (LRU cache keyed by version_id + file_hash)
│     ├─ baseline profile  (JSON from DB)
│     └─ reference sample  (parquet from disk)
│
├─ 7. ENGINE — pipeline.run_monitoring(...)  [NO TRANSACTION — pure computation]
│     │
│     ├─ a. quality.assess(batch, baseline_profile, schema)
│     │        missing · duplicates · type mismatches · unseen categories
│     │        · out-of-range · IQR outliers (baseline quartiles) → quality_score
│     │
│     ├─ b. drift.analyse_features(...)      ← the heart of the project
│     │        for each non-excluded feature:
│     │           numeric     → ks_2samp(reference_sample[col], batch[col])
│     │           categorical → chi2_contingency(baseline_counts, batch_counts)
│     │           both        → PSI and JSD on the BASELINE's bin edges
│     │           classify_feature(...)      → PRD §7.3 combination rule
│     │        rollup(...)                   → PRD §7.4
│     │
│     ├─ c. performance.score_batch(model, batch[feature_columns])
│     │        predictions → prediction_distribution   (always)
│     │        if has_labels → accuracy, precision, recall, F1, error rate,
│     │                        confusion matrix   (positive-class AND macro)
│     │        else          → metrics = None, never 0  (PRD FR-04.5)
│     │
│     ├─ d. health.compute(...)              → PRD §8, weights per labels_available
│     │
│     └─ e. explain.*                        → deterministic sentences for every
│                                               MODERATE/HIGH feature (PRD FR-14)
│
├─ 8. PERSIST RESULTS                        [transaction 3 — atomic, all-or-nothing]
│     MonitoringRun ← summary, health, counters, status=COMPLETED
│     FeatureDriftResult  ← bulk_create, one row per feature
│     DataQualityReport   ← 1:1
│     PerformanceSnapshot ← 1:1
│     DataBatch.status = COMPLETED
│
├─ 9. EVALUATE ALERTS                        [transaction 4 — separate on purpose]
│     alerts.services.evaluate(run)          → §5
│     retrain.evaluate(run)                  → §5.3
│     ↑ separate transaction so an alerting bug can never roll back a valid run
│
├─ 10. DISPATCH EMAIL                        [outside all transactions]
│      CRITICAL alerts only, if enabled; failures logged, never raised (PRD FR-06.6)
│
└─ 11. RELEASE LOCK  (finally — released even on exception)
```

### 4.2 Why the transaction boundaries sit where they do

| Boundary | Reason |
|---|---|
| Batch persisted before computation | A crash mid-run still leaves an auditable batch record |
| Engine runs outside any transaction | Computation can take seconds; holding a write transaction that long would block the web thread under SQLite |
| Results written in one atomic block | A run is never half-written — no run exists with drift results but no health score |
| Alerts in their own transaction | An alerting failure must not destroy a completed, valid monitoring run |
| Email outside everything | SMTP is slow and unreliable; it can never affect data integrity |

### 4.3 Failure handling

```python
try:
    ...steps 4–10...
except SchemaValidationError as e:
    batch.status = REJECTED; batch.rejection_reason = str(e)
    raise_alert(BATCH_REJECTED, WARNING)
except Exception as e:
    logger.exception("monitoring run failed", extra={"run_id": run.id})
    run.status = FAILED; run.error_message = str(e)[:2000]
    batch.status = FAILED
    raise_alert(RUN_FAILED, CRITICAL)
finally:
    release_lock(ml_model.id)
```

The exception is never re-raised to the scheduler thread (PRD NFR-9). A failed run is a visible,
recorded, alerted event — not a silent gap and not a dead scheduler.

---

## 5. Alert evaluation

### 5.1 Flow

```
evaluate(run)
│
├─ collect candidate rules that fire  (PRD §9.1)
│     DRIFT_HIGH · DRIFT_MODERATE · PERFORMANCE_DROP_* · QUALITY_* · HEALTH_*
│
└─ for each fired rule:
      key = (ml_model, category, feature_name)
      existing = Alert.objects.filter(key, status__in=[NEW, ACKNOWLEDGED]).first()
      │
      ├─ existing and (now - existing.last_seen_at) < cooldown
      │     → existing.occurrence_count += 1
      │       existing.last_seen_at = now
      │       NO new row, NO new email          (PRD §9.3)
      │
      └─ else
            → Alert.objects.create(..., status=NEW, occurrence_count=1)
              queue email if severity == CRITICAL and email_enabled
```

Without this, a 30-second simulator generates hundreds of identical alerts in minutes and the
alerts screen becomes useless. The occurrence counter is surfaced in the UI so the mechanism is
visible, not just implemented.

### 5.2 Auto-resolution sweep (every 5 minutes)

```
for each unresolved alert:
    look at the last N runs (default 3) for its model
    if the alert's condition did not fire in ANY of them:
        status = RESOLVED
        resolution_note = "Auto-resolved — condition cleared"
```

### 5.3 Retraining recommendation

```
evaluate_retrain(run)
│
├─ test each trigger (PRD §10), collecting those that fire with measured vs threshold
├─ none fire → return
├─ severity = URGENT if (≥2 triggers) or (any CRITICAL-tier trigger) else ADVISED
│
├─ open = RetrainRecommendation.objects.filter(model, status=OPEN).first()
│     ├─ exists → update triggers, message, severity, run (PRD FR-10.5 — never stack)
│     └─ else   → create, and raise a RETRAIN_RECOMMENDED alert
│
└─ message is generated text naming every trigger with its numbers:
     "Retraining is recommended for Customer Churn Model.
        · Overall drift status is HIGH (1 feature at high drift)
        · Accuracy is 7.2 points below the reference of 0.914
        · Health score has been below 60 for 2 consecutive runs"
```

**Nothing is retrained.** The platform writes a recommendation and stops (PRD FR-10.6).

---

## 6. Resource caching

| Resource | Strategy | Invalidation |
|---|---|---|
| sklearn artifact | Process-level LRU, max 4 entries, keyed `(version_id, file_hash)` | New upload → new hash → new key |
| Baseline profile | Stored as JSON on the row; read with the run's query | Baseline replaced → new row |
| Reference sample | Parquet read per run | Baseline replaced |
| Resolved thresholds | Per-request memo | Threshold edit → next request |
| Chart JSON | No cache | Always live |

Loading a model artifact is the slowest step in a run. The LRU cache means the simulator's second
and subsequent ticks skip it entirely.

---

## 7. Scheduling internals

### 7.1 Startup

```python
# simulator/apps.py
class SimulatorConfig(AppConfig):
    def ready(self):
        if not settings.SCHEDULER_ENABLED:
            return
        # Django's autoreloader runs ready() in BOTH processes.
        # Without this guard, every tick fires twice. (PRD R2)
        if settings.DEBUG and os.environ.get('RUN_MAIN') != 'true':
            return
        from .scheduler import start
        start()
```

### 7.2 Job registry

| Job id | Trigger | Body |
|---|---|---|
| `scenario_tick_<id>` | `IntervalTrigger(seconds=scenario.interval_seconds)` | §7.3 |
| `alert_cooldown_sweep` | `IntervalTrigger(minutes=5)` | §5.2 |
| `retention_cleanup` | `CronTrigger(hour=3)` | delete batch **files** older than the window; DB rows retained forever (PRD FR-13.1) |

Every job: `max_instances=1`, `coalesce=True`, `misfire_grace_time=30`.

### 7.3 Scenario tick

```
tick(scenario_id)
│
├─ reload scenario from DB (never trust the closure — it may be stale)
├─ status != RUNNING → return
│
├─ resolve the active phase for next_batch_index
│     the last phase whose from_batch <= next_batch_index
│
├─ build the batch
│     ├─ sample batch_size rows from the holdout pool (seeded: seed = base + batch_index,
│     │   so a replayed scenario is reproducible — PRD NFR-14)
│     ├─ apply the phase's transformations in declaration order:
│     │     numeric_shift       col += mean_delta_sigma * baseline_std
│     │     numeric_scale       col = mean + (col - mean) * std_multiplier
│     │     category_shift      resample rows to hit target_proportions
│     │     missing_injection   set a random `rate` fraction of the column to NaN
│     │     duplicate_injection append a random `rate` fraction of rows, duplicated
│     │     outlier_injection   set a random `rate` fraction to baseline_q3 + 5*IQR
│     └─ drop the target column if include_labels is False
│
├─ ingest_batch(model, df, source=SIMULATOR, batch_index=next_batch_index)
│
└─ scenario.next_batch_index += 1;  last_tick_at = now;  save()
     ↑ persisted every tick, so a restart resumes rather than replays (PRD FR-05.4)
```

Start/pause/resume/stop add and remove the APScheduler job and update `status`. `next_batch_index`
survives all of them except an explicit, confirmed Stop-and-reset.

### 7.4 Known constraint — single worker

The scheduler lives inside the web process, so **exactly one worker may run**
(`runserver --noreload`, or `gunicorn --workers 1`). Two workers means two schedulers means
duplicate ticks.

Documented escape hatch, deliberately not built: move the scheduler into a separate
`manage.py run_scheduler` process and set `SCHEDULER_ENABLED=False` on the web workers. Roughly
half a day's work, needed only if the deployment ever requires more than one worker. Out of scope
per [PRD.md](PRD.md) §2.2.

---

## 8. Version activation flow

Deceptively important — it is where the baseline prediction distribution comes from.

```
activate_version(version, actor)                         [one transaction]
│
├─ guard: validation_status == PASSED       else → error
├─ guard: status != ARCHIVED                else → error
├─ guard: a baseline dataset exists         else → error
│
├─ demote the current ACTIVE version → INACTIVE
├─ promote this version              → ACTIVE
│
├─ compute the baseline prediction distribution:
│     load artifact → predict on the baseline's feature columns
│     → store class proportions on the version
│     ↑ this is the reference for the health score's stability component (PRD §8.2).
│       Computed once here, never per run.
│
└─ write ModelAuditLog(action=VERSION_ACTIVATED, actor, detail)
```

The partial unique index on `(ml_model, status=ACTIVE)` backstops the demote/promote pair, so even
a concurrent request cannot leave two active versions.

---

## 9. Version comparison (FR-12)

Read-only aggregation, no new computation:

```
compare(model, version_a, version_b, window)
│
├─ schema compatibility: feature_schema keys equal?
│     no → flag incompatible, suppress drift rows, still compare metrics (PRD FR-12.5)
│
├─ per version, aggregate over runs in the window:
│     training_accuracy (recorded at upload)
│     latest run metrics
│     mean accuracy / precision / recall / F1 across labelled runs
│     mean health score
│     mean drifted-feature count
│     run count, alert count
│
└─ per row: mark the better value, compute the delta
   verdict line: "V2 outperforms V1 on accuracy by 3.1 points across 42 runs."
```

Rows where either side has no labelled runs render as "insufficient data" — never as 0.

---

## 10. Chart data endpoints

Thin JSON views under `dashboard/`. Each returns only what its chart plots.

| Endpoint | Returns |
|---|---|
| `GET /api/charts/models/<slug>/health/?range=7d` | `{labels[], scores[], bands[]}` |
| `GET /api/charts/models/<slug>/performance/?range=7d` | `{labels[], accuracy[], precision[], recall[], f1[]}` (nulls where unlabelled — **gaps, not interpolation**, PRD FR-04.7) |
| `GET /api/charts/models/<slug>/drift/?range=7d` | `{labels[], high[], moderate[], none[], max_psi[]}` |
| `GET /api/charts/models/<slug>/predictions/?range=7d` | `{labels[], series: {class: []}}` |
| `GET /api/charts/models/<slug>/alerts/?range=7d` | `{labels[], info[], warning[], critical[]}` |
| `GET /api/charts/runs/<id>/features/<name>/distribution/` | `{type, bins[], baseline[], current[]}` |
| `GET /runs/<id>/status/` | `{status, progress_text}` — the polling endpoint |

All enforce the same access rules as their HTML pages, all cap at 500 points with server-side
down-sampling (TRD §10).

---

## 11. REST ingestion endpoint (ADD-1, low priority)

```
POST /api/v1/models/<uuid>/batches/
Headers: X-API-Key: <key>
Body:    {"rows": [{...}, {...}], "include_predictions": false}

  ├─ resolve key → hashed lookup → model (401 on miss)
  ├─ model active? version active? (409 otherwise)
  ├─ rows → DataFrame
  ├─ ingest_batch(model, df, source=API)      ← the same function, no parallel path
  └─ 202 {"batch_id", "run_id", "status": "queued"}
       optionally {"predictions": [...]} when include_predictions is true
```

Rate limit 60 requests/minute per key. Max 10,000 rows per request. Keys are hashed at rest and
displayed exactly once, at creation.

Built **after** all 14 features are complete, and cut without renegotiation if effort runs short.

---

## 12. Logging

| Logger | Level | Content |
|---|---|---|
| `driftguard.auth` | INFO | login success/failure/logout, lockouts |
| `driftguard.pipeline` | INFO | run start/end, duration, row count, statuses |
| `driftguard.pipeline` | ERROR | full traceback with `run_id` and `batch_id` |
| `driftguard.scheduler` | INFO | job registration, ticks, skips-due-to-lock |
| `driftguard.alerts` | INFO | alerts raised, deduped, auto-resolved |
| `driftguard.email` | WARNING | send failures (never raised) |

Rotating file handler at `logs/driftguard.log`, 10 MB × 5. Never log passwords, session keys or
API keys.

---

## 13. Concurrency summary

| Scenario | Handling |
|---|---|
| Two batches for one model at once | Per-model lock; second is skipped (scheduler) or queued behind (upload) |
| Batches for two different models at once | Runs in parallel; independent locks |
| Threshold edited during a run | The run uses its snapshot; unaffected (PRD FR-13.4) |
| Version activated during a run | The run holds its already-loaded version reference; unaffected |
| Access revoked mid-session | Enforced per request; the next request 403s |
| SQLite writer contention | WAL mode, short transactions, one background worker |

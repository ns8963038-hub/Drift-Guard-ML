# Guided Walkthrough

**A hands-on tour of DriftGuard that doubles as a full test pass.**

Work through this in order. Each part explains *what you are looking at* and
*why it works that way*, then gives you something to verify. By the end you will
have seen every feature, understood the machinery behind it, and confirmed the
whole system works on your machine.

**Time:** about 90 minutes at a steady pace, or 40 if you skip the explanations.

**How to use it:** every step has a ☑ line stating exactly what you should see.
If what you see differs, that is a finding — note it in the results table in
§14 rather than moving on. Exact run numbers and timestamps will differ from
the ones printed here; the *values* should match.

---

## Part 0 — Get it running

### 0.1 Check your Python

```bash
python3.11 --version
```

☑ Prints `Python 3.11.x`.

**Why it must be 3.11.** Django 5.0 supports Python 3.10–3.12 only, and recent
macOS ships 3.14 as the system Python. Installing on 3.14 fails in ways that
look like unrelated errors.

If it is missing: `brew install python@3.11` (macOS) or
`sudo apt install python3.11 python3.11-venv` (Ubuntu).

### 0.2 Install

```bash
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

☑ Finishes without errors. Twenty packages install.

### 0.3 Run the test suite before touching anything

```bash
pytest
```

☑ **324 passed**, in roughly 20 seconds.

**Why start here.** If the tests pass, the statistical engine, the pipeline, the
permissions and the demo script are all verified before you have clicked
anything. If something is wrong with your environment, you find out now rather
than halfway through a walkthrough.

### 0.4 Start the server

```bash
DJANGO_DEBUG=0 python manage.py runserver --noreload
```

> `DJANGO_DEBUG=0` matters as much as `--noreload`. With DEBUG on, Django
> replaces this project's own 403 and 404 pages with its developer pages — and
> the debug 404 lists every URL pattern in the project, which is precisely what
> the access-control demonstration claims a 404 does *not* reveal.


☑ Prints `Starting development server at http://127.0.0.1:8000/`.

**`--noreload` is not optional.** Django's auto-reloader runs the application in
two processes. The batch scheduler lives inside the application, so with the
reloader active it would run twice and every simulated batch would be delivered
twice. There is a guard against this, and `--noreload` is the supported way to
run the project.

Open **http://127.0.0.1:8000/**

---

## Part 1 — What this system is for

Before clicking anything, the idea in one paragraph.

A machine learning model is trained once on a snapshot of data, then deployed.
The world it predicts on keeps moving — customers change, prices change,
behaviour changes. The model does not know this. It keeps returning confident
predictions while quietly becoming wrong. **DriftGuard watches for that.**

For every batch of new data it answers four questions:

| Question | Module |
|---|---|
| Is the incoming data clean? | Data quality |
| Does it still look like the training data? | **Drift detection** |
| Is the model still accurate? | Performance |
| Overall, how healthy is this model? | Health score |

It then raises alerts, explains what changed in plain English, and recommends
retraining. **It never retrains anything** — that is deliberate and stated in
the requirements.

---

## Part 2 — Roles and access control (10 min)

The system has three roles and they genuinely differ. This is worth doing first
because it is the easiest thing to demonstrate and the hardest to fake.

### 2.1 Sign in as the Administrator

Log in with **`admin` / `driftguard123`**.

The sign-in page lists all three demo accounts on the right — click one and it
fills the form for you.

> **Why there is no "log in as…" role dropdown.** A picker that let you choose
> your own role at sign-in would let anyone claim any privilege. The role
> belongs to the account and the server decides; the accounts are simply listed
> so all three are quick to try.

☑ You land on a dashboard showing **Monitored Models 2**, **Registered Users 3**,
an alert count and an open retraining recommendation.

☑ A banner under the heading states what this account may do, beginning
**"You administer this platform."** Each role gets a different sentence there.

☑ The sidebar is grouped into three sections — **Monitoring**, **Administration**
and **Account** — with your username and a red *Admin* chip above them. The
Administration section is the part the other two roles will not have.

☑ A panel titled **Recent sign-in activity** appears under the model list. Only
the Administrator sees it.

### 2.2 Look at what only an Admin can do

Click **Users**, **Access grants** and **Login activity** in the sidebar's
Administration section. (Direct URLs, if you would rather type them:
`/admin-panel/users/`, `/admin-panel/access/`, `/admin-panel/activity/`.)

☑ All three load. The activity log shows your own login just now, with an IP
address and browser string.

> These screens existed from the beginning but nothing linked to them, so they
> could only be reached by typing the URL. The sidebar now links them, and only
> for the role that may use them.

**What is happening.** Every login success, failure and logout is recorded
(requirement FR-01.5). This is the audit trail.

### 2.3 Now sign in as the Analyst — the important test

Log out. Log in as **`mleng` / `driftguard123`**.

☑ The sidebar has **no Administration section at all** — no Users, no Access
grants, no Login activity. The role chip beside your username reads *Analyst*
in green, and the banner now says **"You work the monitoring output."**

☑ Go to http://127.0.0.1:8000/admin-panel/users/ → **403 Forbidden.**

☑ Go to http://127.0.0.1:8000/models/ → you see **only Customer Churn Model**.
The Income Prediction Model is absent.

☑ Now type the Income model's URL directly:
http://127.0.0.1:8000/models/income-prediction-model/ → **404 Not Found.**

**This is the part to understand.** The Analyst is not merely prevented from
*seeing a link* — the object is unreachable by its address. And it returns 404,
not 403, so probing URLs cannot even tell you the model exists. Hiding a button
is not access control; this is.

### 2.4 What the Analyst *can* do

☑ Open Customer Churn Model → **Upload batch** is the only button in the header.

☑ **Edit**, **Train model** and **Upload version** are gone, and so are the
**Baseline**, **Thresholds** and **Simulator** tabs — seven tabs instead of ten.

☑ On the Models screen there is no **+ Register new model** button, and
`/models/new/` returns **403** if you type it.

**Why that split.** Feeding production data in is the Analyst's job. Defining
the reference the model is judged against, and configuring the thresholds, are
Data Scientist decisions. This mirrors how the roles work in a real team.

### 2.5 Sign in as the Data Scientist

Log out, log in as **`dsci` / `driftguard123`**. Stay signed in as this user for
the rest of the walkthrough.

☑ You can see both models and all ten tabs, and **+ Register new model** is
back in the header.

☑ Still no Administration section — creating users is not a Data Scientist's
job. The banner reads **"You own models."**

**Compare the three.** Same code, same templates, three genuinely different
screens: the Admin has 8 sidebar links, the Data Scientist and Analyst 5; the
Admin and Data Scientist get 4 header actions on a model, the Analyst 1.

---

## Part 3 — The model registry (10 min)

Open **Customer Churn Model → Versions**.

☑ You see three versions:

| Version | Algorithm | Training accuracy | Status |
|---|---|---|---|
| V1 | Logistic Regression | 0.7878 | Inactive |
| V2 | Balanced Random Forest | 0.7523 | Inactive |
| V3 | Balanced Gradient Boosting | 0.7587 | **Active** |

### 3.1 Notice something odd

**V1 has the highest accuracy but is not the active version.** That is
deliberate, and it is one of the most interesting things in the project.

The Telco dataset is 26.5% churn — imbalanced. V1 optimises overall accuracy and
achieves it by rarely predicting churn at all: it misses roughly **half** the
customers who actually leave. V2 and V3 handle the imbalance and catch far more
of them, at the cost of a couple of accuracy points.

For a churn model, catching churners is the entire point. You will see this
quantified in Part 11.

**Takeaway:** a monitoring platform that only tracked accuracy would rank these
backwards. That is why the system tracks precision, recall and F1 as well.

### 3.2 The upload gate

Every uploaded model artifact must pass five checks before it can be activated:

1. It deserialises
2. It has a callable `.predict()`
3. It predicts successfully on 50 real baseline rows
4. Its output length matches its input length
5. Its output classes are ones the baseline actually contains

☑ Open **Upload Version**, try uploading any random file (a `.txt` renamed to
`.pkl`, or an image). It is rejected with a specific reason, and **no version
record is created**.

**Why five checks and not one.** A model that deserialises fine but expects
pre-encoded input will fail at *scoring* time — which is during a monitoring
run, possibly mid-demo. Check 3 forces that failure to happen at upload, where
someone can act on it.

---

## Part 4 — Where the data comes from (5 min)

Two kinds of data enter the system.

**The baseline** is the training data. It is uploaded once, profiled once, and
becomes the definition of "normal". Every later comparison is against the stored
profile, never against a re-read of the file.

**Batches** are new production data. They arrive three ways: uploaded manually,
generated by the simulator on a timer, or posted to the REST endpoint.

☑ Open **Upload Batch** on the Churn model. Expand **Required columns**.

☑ It lists 19 columns.

**Why 19 and not 21.** The Telco file has 21 columns. One is the target
(`Churn`) and one is `customerID`, which the system detected as an identifier
and excluded automatically — drift on a customer ID is meaningless. That
detection is a heuristic, and the upload screen lets you override it.

---

## Part 5 — A monitoring run, in detail (15 min)

This is the centre of the whole application.

Open **Customer Churn Model → History**.

☑ 32 runs, newest first. The most recent ones show **High** drift; the oldest
show **No drift**.

Click the **newest** run.

### 5.1 The header

☑ Four tiles: Model health ~**70/100 (Warning)**, Data drift **3 high**,
Data quality **92/100**, Accuracy ~**0.65**.

### 5.2 "How this health score was reached"

☑ A table of four components with their scores and weights:

| Component | Roughly | Weight |
|---|---|---|
| Performance | ~78 | ×40 |
| Drift | ~37 | ×30 |
| Quality | 92 | ×20 |
| Stability | ~91 | ×10 |

**Why this panel exists.** A single number like "70" tells you nothing about
what to fix. The breakdown says: performance has slipped a little, quality is
fine, and *drift is the problem*. The score is never a black box.

☑ It also states **Weighting: With labels**. Remember that — it changes in
Part 8.

### 5.3 The feature drift table

☑ 19 rows, sorted worst-first. The top three:

| Feature | Test | PSI | Status |
|---|---|---|---|
| MonthlyCharges | K-S | ~4.5 | **High** |
| Contract | Chi² | ~0.72 | **High** |
| tenure | K-S | ~0.30 | **High** |

☑ Click any column header to re-sort.

☑ Every status badge has an **icon and a word**, not just a colour — `✕ High`,
`▲ Moderate`, `✓ No drift`.

**Why that matters.** Roughly 8% of men have red–green colour deficiency, and
this entire product is built out of traffic lights. Colour alone would make it
unreadable for them, and unreadable in greyscale or print.

### 5.4 Notice the test column

☑ Numeric features use **K-S**; categorical features use **Chi²**.

**Why two tests.** The Kolmogorov–Smirnov test compares two continuous
distributions — meaningless on a category. Chi-Square compares category
frequencies — meaningless on a continuous variable. The system picks per feature
based on the column's type.

☑ Scroll down. **Performance** and **Data quality** panels, each with a
breakdown rather than a bare score.

---

## Part 6 — Drift detection, the core (15 min)

Click **MonthlyCharges** in the feature table.

### 6.1 The distribution chart

☑ Two series: **Baseline** (blue) and **Current** (orange).

☑ The baseline is spread evenly across all ten bins. The current batch is piled
almost entirely into the top bin.

**What you are seeing.** The baseline bars are even because the bins are
*quantile* bins — each holds 10% of the training data by construction. The
current batch has moved so far right that nearly every row lands in the highest
bin. That is drift, drawn.

☑ Click **View as table** — the same data as numbers.

**Why the table exists.** It is not decoration. Two of the chart colours fall
below the 3:1 contrast standard on a light background, and an accessible table
view is what makes that acceptable.

### 6.2 The four measures

☑ The Scores panel shows:

| Measure | Value | Meaning |
|---|---|---|
| K-S statistic | ~0.71 | The largest gap between the two distributions |
| p-value | < 0.001 | The difference is statistically significant |
| PSI | ~4.5 | How far the distribution moved (industry standard) |
| JSD | ~0.5 | How far it moved (information theory) |

☑ PSI shows `high > 0.25` and JSD shows `high > 0.2` beside them.

### 6.3 The idea worth understanding

**The tests give significance. PSI and JSD give magnitude. Both are needed,
because neither is trustworthy alone.**

- On a large batch, a K-S test returns p < 0.001 for differences far too small
  to matter. Significance alone would flag *every* batch as drifted, forever.
- On a small batch, PSI can look alarming purely from sampling noise. Magnitude
  alone would flag noise as drift.

So the system uses **magnitude to decide the band**, and **significance only to
confirm it**. If a shift is large but the test cannot rule out chance, the
status is *downgraded one level* rather than dropped.

**This is the single best thing to be able to explain in a viva.** There is a
test in the suite that proves it works: two 50,000-row samples differing by
0.05σ produce p < 0.05 — statistically significant — and the system correctly
reports **No drift**, because a 0.05σ shift means nothing operationally.

### 6.4 The explanation — the differentiating feature

☑ Scroll to **Why this is flagged**. You should see something close to:

> High drift detected in `MonthlyCharges`. The average rose from 64.89 in the
> baseline to 140.20 in this batch (+116.1%), and the spread widened (std 30.32
> → 44.40). PSI is 4.502, above the high-drift threshold of 0.25. The K-S test
> returns p < 0.001, confirming the two distributions differ.

**Why this is the standout feature.** "PSI 4.502" is a fact. "The average
monthly charge more than doubled and the spread widened" is something a person
can act on. The text is generated from templates — deterministic, no AI, no
internet — so the same run always produces the same sentence and it can be
stored and re-read years later.

☑ At the bottom: **This feature across the last 30 runs** — a strip of squares
going green → amber → red. That is the drift arriving over time.

### 6.5 Compare against a clean feature

Go back to the run and click **gender** (or any feature marked ✓ No drift).

☑ The two distributions sit almost on top of each other.

☑ The explanation reads roughly: *"No drift in `gender`. Category proportions
are close to the baseline."*

---

## Part 7 — Data quality (5 min)

Back on the run detail page, look at the **Data quality** panel.

☑ Quality score **92/100**, with a breakdown showing the penalties:
duplicates −4.76, outliers −3.56.

☑ Missing values 0 (0.00%), duplicate rows 25 (4.76%).

**What is being checked.** Six things: missing values, duplicate records, values
outside the baseline's observed range, categories never seen before, outliers by
the IQR rule, and columns whose data type changed.

**The important design point:** every threshold comes from the **baseline**, not
from the batch. Outlier bounds use the baseline's quartiles. If they used the
batch's own quartiles, a batch where every value had doubled would look
perfectly normal relative to itself — the drift would define itself away.

☑ Open the **Data Quality** tab from the model's tab bar for the same view
scoped to the latest run.

---

## Part 8 — Performance, and the labels question (10 min)

This part covers the subtlest design decision in the project.

☑ On the run detail page, the Performance panel shows Accuracy, Error rate,
Precision, Recall, F1 (positive class), F1 (macro), and rows scored.

### 8.1 Now do the experiment

You are going to feed the system a batch with **no true labels** — which is what
real production data usually looks like, because the answer has not arrived yet.

Create the file:

```bash
python -c "
import pandas as pd
d = pd.read_csv('data/processed/telco_churn/test.csv').head(400)
d.drop(columns=['Churn']).to_csv('/tmp/no_labels.csv', index=False)
print('wrote', len(d), 'rows with no Churn column')
"
```

Upload `/tmp/no_labels.csv` via **Upload Batch**.

☑ The run **completes successfully**.

☑ The Performance panel says **"No labels in this batch"** — not zeros.

☑ Drift and data quality were still analysed in full, all 19 features.

☑ The health breakdown now says **Weighting: Without labels**, and the
Performance component shows `n/a`.

### 8.2 Why this matters more than it looks

If the system stored accuracy as **0** for an unlabelled batch, then:

- every performance chart would show a cliff to zero
- every average would be dragged down
- the health score would collapse
- alerts would fire about a model that is completely fine

And since most production batches have no labels yet, that would happen
constantly. So unknown accuracy is recorded as **unknown**, and the health score
redistributes its weights across the three components it *can* measure.

☑ Open the **Performance** tab. The unlabelled run appears as a **gap** in the
line — not a drop to zero, not a line drawn straight through it.

---

## Part 9 — The health score (5 min)

Open the **Drift** tab, then look back at a few runs in History.

☑ Health across the seeded runs follows this pattern:

| Batches | Drift | Health | Quality |
|---|---|---|---|
| 0–9 | No drift | 99–100 | 100 |
| 10–24 | Moderate | 98 | 100 |
| 25–31 | **High** | ~70 | 92 |

### 9.1 Notice the jump

Health barely moves during the moderate phase (100 → 98) then falls sharply at
batch 25 (98 → 70).

**That is correct, not a bug.** One feature at moderate drift genuinely is a
minor issue. The health score is a weighted composite, not a copy of the drift
status — it is telling you that moderate drift on one column, with performance
and quality untouched, is not yet a problem worth acting on.

### 9.2 The coherence rule

There is one override worth knowing about. If a run's overall drift is **High**,
the health score is **capped at 79** and can never read "Healthy" — regardless
of what the arithmetic produces.

**Why.** Drift carries only 30 of the 100 weight, so the formula could return a
healthy score while several features sat at high drift. That actually happened
during development: three high-drift features with accuracy down four points
scored **81 — Healthy**, while an *urgent* retraining recommendation was open on
the same model. The run page would have shown a red drift badge beside a green
health badge. A summary that contradicts everything beside it is not a summary.

☑ On a high-drift run, if the cap applied you will see a note reading
*"capped from N — high drift cannot read healthy"*. Both the raw and capped
numbers are stored, so the cap is auditable rather than hidden.

---

## Part 10 — Alerts (10 min)

Open **Alerts** from the sidebar.

☑ Around 12 alerts, of several categories: Drift, Performance, Quality, Health,
Retrain.

### 10.1 The thing to look for

☑ Find the alert for **MonthlyCharges**. It shows **seen ×22** (or similar).

**This is the feature to understand.** Twenty-two runs detected drift on that
feature. A naive implementation would have created twenty-two alerts and the
screen would be useless. Instead there is **one alert with a counter**.

Alerts deduplicate on `(model, category, feature)` within a cooldown window. The
simulator produces a batch every 30 seconds, so without this the alert list
would grow by hundreds per hour.

### 10.2 Work an alert

☑ Click an alert → detail page shows what fired, the measured value against its
threshold, when it was first and last seen, and a link to the run.

☑ Press **Acknowledge** → status changes and records who did it.

☑ Press **Resolve** → status changes again.

**There is also an automatic path:** a background job runs every five minutes
and auto-resolves alerts whose condition has cleared for three consecutive runs,
annotating them *"Auto-resolved — condition cleared."*

---

## Part 11 — Retraining recommendations (5 min)

Open **Alerts → Recommendations** (or the model's Recommendations view).

☑ One **open** recommendation for the Churn model, marked **Urgent**.

☑ It names every trigger that fired, each with its measured value *and* its
threshold. Something like:

> - Overall drift status is HIGH: 3 feature(s) at high drift (threshold: any feature at high drift)
> - Several features have drifted: 6 features at moderate drift or worse (threshold: 3 or more)
> - Accuracy has fallen below its reference: 0.6514 (10.7 points below 0.7587) (threshold: 5 point drop)

☑ It ends with **"This is advisory only — the platform does not retrain
models."**

**Why advisory.** The requirements are explicit: implement this as a
recommendation, not automatic retraining. Retraining is a decision with
consequences and needs a human.

☑ Only **one** recommendation is open at a time. Further triggers update it
rather than stacking near-duplicates.

---

## Part 12 — The simulator: watch it happen live (15 min)

This is the centrepiece. Everything so far was pre-generated; now you will watch
the system detect drift in real time with nobody touching it.

Open **Customer Churn Model → Simulator**.

☑ One scenario, currently **Stopped**, positioned at batch 32.

### 12.1 Reset it so you can watch the whole story

Stop the server (Ctrl+C) and run:

```bash
python -c "
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.dev')
os.environ['SCHEDULER_ENABLED']='False'
django.setup()
from registry.models import MLModel
s = MLModel.objects.get(slug='customer-churn-model').scenarios.first()
s.next_batch_index = 8; s.interval_seconds = 15; s.status='STOPPED'; s.save()
print('reset to batch 8, one batch every 15 seconds')
"
DJANGO_DEBUG=0 python manage.py runserver --noreload
```

### 12.2 Start it and watch

Go back to the Simulator tab and press **Start**.

Now open the **model overview** in a second tab and refresh it every 20 seconds
or so.

☑ **Batches 8–9:** drift stays **No drift**, health ~100.

☑ **Batch 10:** drift becomes **Moderate**. The phase description changes.

☑ **Batches 10–24:** stays Moderate. Health hovers around 98.

☑ **Batch 25:** drift becomes **High**, health drops to ~70, quality drops to
92, and new alerts appear.

**What is actually happening.** The scenario replays real held-out customer
rows — data the model never trained on — and applies controlled transformations
as it progresses. Batches 0–9 are untouched. From batch 10 it shifts
`MonthlyCharges` for 22% of rows. From batch 25 it shifts every row by 2.2
standard deviations, widens the spread, changes the `Contract` mix to 90%
month-to-month, injects outliers and duplicates.

**Why replay real rows instead of generating data?** Generated data looks fake,
the correlations between columns collapse, and the statistics stop being
interesting. Real rows with a controlled shift look exactly like a production
feed going bad.

### 12.3 Do not wait for the timer

☑ Press **Run one batch now**. A batch is processed immediately and you land on
its run detail page.

**Why this button exists.** Nobody waits for a timer during a viva. The
production setting would be hourly — the screen says so — but a demo that
depends on a timer is a demo that can stall.

### 12.4 Pause and resume

☑ Press **Pause**. Note the batch number. Press **Resume** — it continues from
where it stopped, it does not restart.

☑ Press **Stop**, then restart the server, then check the Simulator tab: the
position survived the restart.

**Why.** The position is written to the database on every tick. A restart
resumes the story rather than replaying it.

---

## Part 13 — Version comparison, history and training (15 min)

### 13.1 Compare versions

Open **Customer Churn Model → Compare**. Select **V1** and **V2**.

☑ A table of nine measures, with the better value in each row marked, and a
verdict sentence at the top.

☑ **V1 wins on accuracy. V2 wins on recall and F1.**

**This is the payoff from Part 3.** V1 looks better if you only read accuracy.
V2 catches far more churners. A comparison screen showing only accuracy would
actively mislead the person using it — which is exactly why the system tracks
several metrics.

☑ Rows where a version has no measured runs read **"insufficient data"**, never
0 — the same principle as unlabelled accuracy.

### 13.2 History and immutability

Open **History**.

☑ Filter by drift status **High** → only the drifted runs remain.

☑ Filter by trigger **Scheduled** → only simulator runs.

☑ Press **Export CSV** → downloads and opens in a spreadsheet.

Now the interesting test. Open the **Thresholds** tab and change **PSI —
moderate above** to something extreme like `0.001`. Save.

☑ Go back to History and open an **old, clean** run.

☑ It **still reads "No drift."**

**Why.** Every run stores a snapshot of the thresholds it was judged under.
Changing a threshold today does not rewrite last week's verdicts. Without this,
history would be a lie — every past result would silently re-interpret itself
whenever someone adjusted a setting.

☑ Set the threshold back to `0.10`.

☑ Also try setting **moderate** *above* **high** (e.g. moderate 0.5, high 0.2)
and saving → it is **rejected** with an explanation. That configuration would
make the amber state unreachable.

### 13.3 Train a model inside the platform

Open **Customer Churn Model → Train Model**.

☑ Upload `data/processed/telco_churn/baseline.csv`, target column `Churn`,
algorithm **Decision Tree**, and submit.

☑ After a few seconds: a new version **V4** is created and activated, and the
success message reports its accuracy, precision and recall on held-out rows.

**What just happened.** The file was split into training and held-out portions,
a model was trained, it was measured on the portion it never saw, it was
registered as a version, **and the training split became the new baseline**.

**Why the baseline comes from the same file.** A model must be monitored against
the data it was actually trained on. Deriving both from one upload removes the
commonest way to get that wrong.

☑ Go to **Versions** → V4 is Active, V3 is now Inactive. Only one version is
ever active.

---

## Part 14 — Try to break it (10 min)

Good software fails clearly. Try these and confirm each gives a useful message
rather than a crash.

| Try this | Expected |
|---|---|
| Upload an empty CSV as a batch | Rejected: "The file contains no rows" |
| Upload a batch missing `MonthlyCharges` | Rejected, naming the missing column; **no run is created** |
| Upload an image renamed `.csv` | Rejected with a parse error |
| Train with target column `nonsense` | Rejected: "not in the file", lists the real columns |
| Upload a batch of only 5 rows | **Completes**, and every feature reads "Not enough data" |
| Create a model, then open every tab before adding anything | Every screen renders with an empty state, none crash |

☑ That fifth row is worth pausing on. Five rows is not enough to test a
distribution, so the system reports *"we could not look"* rather than *"we
looked and found nothing"*. Those are different statements and the system does
not conflate them.

☑ Log out and try any URL directly → redirected to login.

---

## Part 15 — Under the bonnet (10 min, optional)

If you want to see the engine without the web application at all.

### 15.1 Run the statistics in a shell

```bash
python -c "
import pandas as pd
from monitoring.engine import profiling, drift

base = pd.read_csv('data/processed/telco_churn/baseline.csv')
batch = pd.read_csv('data/processed/telco_churn/holdout.csv')

schema = profiling.infer_schema(base, 'Churn')
profile = profiling.build_profile(base, schema)

results = drift.analyse_features(profile, base, batch, schema)
print('Same population, so nothing should be flagged:')
print(' overall:', drift.rollup(results))

batch['MonthlyCharges'] += 2 * base['MonthlyCharges'].std()
results = drift.analyse_features(profile, base, batch, schema)
top = results[0]
print()
print('After shifting MonthlyCharges by 2 standard deviations:')
print(' overall:', drift.rollup(results))
print(f' {top[\"feature_name\"]}: PSI {top[\"psi\"]:.3f}, p {top[\"p_value\"]:.2e}, {top[\"status\"]}')
"
```

☑ First result: **NONE**. Second: **HIGH**.

**Why this is worth showing.** The statistical engine imports no Django at all.
It takes DataFrames and returns dictionaries. That means it can be demonstrated
standalone, tested without a database, and reasoned about on its own — and it is
why it has 96% test coverage.

The first result is also the strongest sanity check in the project: the holdout
is a random split of the *same* population as the baseline, so a correct
detector must find nothing. If it invented drift there, every other result would
be worthless.

### 15.2 Check the test suite by area

```bash
pytest tests/test_drift.py -v          # the statistical core
pytest tests/test_permissions.py -v    # all 17 rows of the permission matrix
pytest tests/test_demo.py -v           # the demo script, as a test
```

☑ All pass. Note that `test_demo.py` runs the entire demo walkthrough
automatically — so a broken demo fails a test rather than a viva.

---

## Part 16 — Results table

Fill this in as you go.

| Part | What was checked | ☑ / ✗ | Notes |
|---|---|---|---|
| 0 | 324 tests pass, server starts | | |
| 2 | Admin sees admin panel | | |
| 2 | Analyst gets 403 on admin panel | | |
| 2 | Analyst gets 404 on ungranted model | | |
| 3 | Three versions, one active | | |
| 3 | Bad artifact rejected, no record created | | |
| 4 | 19 required columns, customerID excluded | | |
| 5 | Run detail: header, breakdown, 19 features | | |
| 5 | Badges have icon + text, not colour alone | | |
| 6 | Distribution chart shows both series | | |
| 6 | Four measures with thresholds | | |
| 6 | Plain-English explanation present | | |
| 7 | Quality score with penalty breakdown | | |
| 8 | Unlabelled batch completes, metrics n/a | | |
| 8 | Weighting switches to "Without labels" | | |
| 8 | Performance chart shows a gap, not zero | | |
| 9 | Health follows 100 → 98 → 70 | | |
| 10 | One alert with an occurrence count | | |
| 10 | Acknowledge and resolve work | | |
| 11 | Recommendation names every trigger | | |
| 12 | Simulator runs unattended | | |
| 12 | Green → amber → red observed live | | |
| 12 | "Run one batch now" works | | |
| 12 | Position survives pause and restart | | |
| 13 | V1 beats V2 on accuracy, loses on recall | | |
| 13 | Old run unchanged after threshold edit | | |
| 13 | Invalid threshold ordering rejected | | |
| 13 | In-platform training produces V4 | | |
| 14 | All six failure cases handled cleanly | | |
| 15 | Engine runs standalone in a shell | | |

---

## Part 17 — Questions you will be asked

Having done the walkthrough, these should now be answerable. Each maps to
something you saw.

**"How do you detect drift?"**
Four measures. K-S for numeric features, Chi-Square for categorical, and PSI and
Jensen-Shannon divergence for both. The tests establish significance, PSI and
JSD establish magnitude.

**"Why not just use the p-value?"**
Because on a large batch a p-value is significant for differences too small to
matter — it would flag every batch forever. Magnitude decides the band and
significance confirms it. There is a test proving two 50,000-row samples
differing by 0.05σ give p < 0.05 and are correctly reported as no drift.

**"Why is the moderate band separate from high?"**
Because a warning and an emergency are different. One threshold per measure
would make the amber state unreachable, and the whole green-amber-red
progression impossible.

**"What happens when the new data has no labels?"**
Drift and quality are analysed in full. Accuracy is recorded as unknown, never
as zero, and the health score redistributes its weights. That is the common case
in production, not an edge case.

**"How does the health score work?"**
Weighted composite of performance (40), drift (30), quality (20) and prediction
stability (10), with the breakdown always shown. One override: a run at high
drift cannot report as healthy, because the number must not contradict
everything beside it.

**"Is the drift explanation generated by AI?"**
No. Template-driven and deterministic — same inputs, same sentence, every time.
No external service and no internet, so it works offline and the stored text
stays valid forever.

**"Why does version comparison show nine metrics?"**
Because ranking on accuracy alone puts V1 first, while V2 catches 26 percentage
points more churners. On an imbalanced target, accuracy alone misleads.

**"What are the limitations?"**
Three, stated openly. Uploaded model files execute code when loaded — inherent
to the format, mitigated by restricting uploads to two roles and validating
every file. The scheduler runs in-process, so only one worker may serve the app.
And only tabular scikit-learn classification is supported.

**"What would you add next?"**
Real-time streaming instead of batches, automatic retraining rather than
recommendations, and support for deep learning models — the three items already
listed as future scope.

---

## Troubleshooting

**Tests fail immediately on import**
Wrong Python. Check `python --version` inside the activated virtualenv — it must
be 3.11.

**"disk I/O error" from the database**
SQLite runs in WAL mode and leaves two sidecar files. Delete all three, then
re-seed:
```bash
rm -f db.sqlite3 db.sqlite3-wal db.sqlite3-shm
python manage.py migrate
python scripts/seed_demo.py
```

**The simulator does not tick**
The server must be running with `--noreload`. Check `logs/driftguard.log` for a
line reading `scheduler started`.

**Charts do not appear**
Chart.js is bundled locally, not loaded from the internet. Hard-refresh
(Cmd/Ctrl + Shift + R). If it persists, check the browser console.

**You want to start over completely**
```bash
python scripts/seed_demo.py --reset
```

**Something looked wrong and you want to check it is not just you**
```bash
pytest                                  # 324 tests
python manage.py check                  # configuration
```

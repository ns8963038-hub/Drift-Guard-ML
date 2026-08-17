"""Train the demo model artifacts.

Produces the models the platform monitors:

    telco_churn    V1 Logistic Regression
                   V2 Balanced Random Forest
                   V3 Balanced Gradient Boosting   -> three versions tracing a
                                                      real development arc, so
                                                      version comparison (FR-12)
                                                      has something to compare
    adult_income   V1 Random Forest                -> a second model, so
                                                      role-based access control
                                                      is demonstrable

**Every artifact is a scikit-learn Pipeline that accepts raw feature columns.**
This is not a stylistic choice — it is PRD assumption A2 and implementation risk
I1. A bare estimator expecting pre-encoded input deserialises perfectly, passes
a casual glance, and then fails at scoring time. The upload validation gate
(PRD §4.3) rejects exactly that, so a bare estimator here would make every demo
artifact unusable.

``handle_unknown="ignore"`` on the encoder matters just as much: the simulator
deliberately injects categories the baseline never saw, and without it every
such batch would raise instead of being scored and flagged as drift.

Usage:
    python scripts/train_demo_models.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from monitoring.engine import constants as C  # noqa: E402
from monitoring.engine import profiling  # noqa: E402

RANDOM_STATE = 42

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "processed"
ARTIFACT_DIR = ROOT / "artifacts"

# Tree depth is capped on every forest. Unconstrained trees memorise the
# training set, and they are enormous: an unconstrained Adult forest serialised
# to 157 MB, over the platform's own 100 MB artifact limit (PRD FR-02.8), so it
# could not have been uploaded through the validation gate it exists to
# demonstrate.
#
# The three Telco versions trace a realistic model-development arc rather than
# three arbitrary algorithms. Accuracy on this dataset is capped around 0.79 for
# every reasonable model, so a version story told through accuracy alone would
# be noise. Told through the metrics that matter for churn it is a real one:
#
#   V1  plain logistic regression, optimised for accuracy — and it misses
#       almost half the churners (recall 0.53)
#   V2  handles the 26.5% class imbalance. Recall jumps to 0.79 and F1 rises
#       6 points, paid for with 3.5 points of accuracy. For churn that is
#       unambiguously the better model
#   V3  tightens the trade-off back up: better precision and accuracy than V2
#       while keeping most of the recall gain
#
# This also demonstrates why the platform tracks several metrics instead of
# accuracy alone — a version comparison on accuracy would rank V1 top.
DATASETS = {
    "telco_churn": {
        "target": "Churn",
        "positive_class": "Yes",
        "versions": [
            (
                "V1",
                "Logistic Regression",
                LogisticRegression(max_iter=1000, random_state=RANDOM_STATE),
            ),
            (
                "V2",
                "Balanced Random Forest",
                RandomForestClassifier(
                    n_estimators=200,
                    max_depth=8,
                    min_samples_leaf=15,
                    class_weight="balanced",
                    random_state=RANDOM_STATE,
                ),
            ),
            (
                "V3",
                "Balanced Gradient Boosting",
                HistGradientBoostingClassifier(
                    class_weight="balanced",
                    learning_rate=0.05,
                    max_iter=300,
                    random_state=RANDOM_STATE,
                ),
            ),
        ],
    },
    "adult_income": {
        "target": "income",
        "positive_class": ">50K",
        "versions": [
            (
                "V1",
                "Random Forest",
                RandomForestClassifier(
                    n_estimators=150,
                    max_depth=14,
                    min_samples_leaf=10,
                    random_state=RANDOM_STATE,
                ),
            ),
        ],
    },
}

# PRD FR-02.8. Enforced here so an oversized artifact fails at build time rather
# than at upload time during a demo.
MAX_ARTIFACT_MB = 100


def build_pipeline(estimator, numeric: list[str], categorical: list[str]) -> Pipeline:
    """Wrap an estimator in preprocessing so it accepts raw columns."""
    return Pipeline(
        [
            (
                "preprocess",
                ColumnTransformer(
                    [
                        ("numeric", StandardScaler(), numeric),
                        (
                            "categorical",
                            # handle_unknown="ignore": unseen categories must not
                            # raise. The simulator injects them on purpose; the
                            # platform's job is to score the batch anyway and
                            # report the drift.
                            #
                            # sparse_output=False: HistGradientBoosting cannot
                            # accept sparse input, and ColumnTransformer decides
                            # sparse-vs-dense from a density heuristic — so
                            # leaving it to chance means the pipeline works on
                            # one dataset and raises on the next.
                            OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                            categorical,
                        ),
                    ],
                    remainder="drop",
                ),
            ),
            ("classifier", estimator),
        ]
    )


def validate_artifact(
    path: Path, baseline: pd.DataFrame, features: list[str], target: str
) -> None:
    """Run the PRD §4.3 five-check gate against a freshly written artifact.

    Running it here rather than trusting the upload screen means a broken
    artifact is caught at build time, by this script, instead of during a demo.
    """
    size_mb = path.stat().st_size / 1_000_000
    if size_mb > MAX_ARTIFACT_MB:
        raise SystemExit(
            f"{path.name}: {size_mb:.1f} MB exceeds the {MAX_ARTIFACT_MB} MB upload "
            f"limit (PRD FR-02.8). Constrain the estimator — cap max_depth or "
            f"raise min_samples_leaf."
        )

    model = joblib.load(path)  # 1. deserialises

    if not callable(getattr(model, "predict", None)):  # 2. has predict
        raise SystemExit(f"{path.name}: no callable .predict()")

    sample = baseline[features].head(50)
    predictions = model.predict(sample)  # 3. predicts on raw baseline columns

    if len(predictions) != len(sample):  # 4. length matches
        raise SystemExit(
            f"{path.name}: returned {len(predictions)} rows for {len(sample)}"
        )

    known = set(baseline[target].astype(str))
    produced = set(pd.Series(predictions).astype(str))
    if not produced.issubset(known):  # 5. classes are a subset
        raise SystemExit(f"{path.name}: unexpected classes {produced - known}")


def train_dataset(name: str, config: dict) -> list[dict]:
    baseline = pd.read_csv(DATA_DIR / name / "baseline.csv")
    test = pd.read_csv(DATA_DIR / name / "test.csv")
    target = config["target"]

    schema = profiling.infer_schema(baseline, target)
    features = profiling.feature_columns(schema)
    numeric = [c for c in features if schema[c]["type"] == C.NUMERIC]
    categorical = [c for c in features if schema[c]["type"] == C.CATEGORICAL]

    print(f"\n{name}")
    print(
        f"  {len(baseline):,} training rows · {len(features)} features "
        f"({len(numeric)} numeric, {len(categorical)} categorical)"
    )

    out = ARTIFACT_DIR / name
    out.mkdir(parents=True, exist_ok=True)

    records = []
    for label, algorithm, estimator in config["versions"]:
        model = build_pipeline(estimator, numeric, categorical)
        model.fit(baseline[features], baseline[target])

        predictions = model.predict(test[features])
        positive = config["positive_class"]
        accuracy = float(accuracy_score(test[target], predictions))
        precision = float(
            precision_score(test[target], predictions, pos_label=positive)
        )
        recall = float(recall_score(test[target], predictions, pos_label=positive))
        f1 = float(f1_score(test[target], predictions, pos_label=positive))

        filename = f"{label.lower()}_{algorithm.lower().replace(' ', '_')}.joblib"
        path = out / filename
        joblib.dump(model, path)
        validate_artifact(path, baseline, features, target)

        size_mb = path.stat().st_size / 1_000_000
        print(
            f"  {label} {algorithm:<27} acc {accuracy:.4f}  prec {precision:.4f}  "
            f"rec {recall:.4f}  F1 {f1:.4f}  {size_mb:5.1f} MB  ok"
        )

        records.append(
            {
                "dataset": name,
                "version": label,
                "algorithm": algorithm,
                "artifact": str(path.relative_to(ROOT)),
                "target": target,
                "positive_class": config["positive_class"],
                "training_accuracy": accuracy,
                "training_precision": precision,
                "training_recall": recall,
                "training_f1": f1,
                "feature_count": len(features),
                "classes": sorted(set(baseline[target].astype(str))),
            }
        )

    return records


def main() -> int:
    if not DATA_DIR.exists():
        raise SystemExit("No data found. Run scripts/prepare_datasets.py first.")

    print("Training demo models")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = []
    for name, config in DATASETS.items():
        manifest.extend(train_dataset(name, config))

    manifest_path = ARTIFACT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print(
        f"\nDone. {len(manifest)} artifacts written to {ARTIFACT_DIR.relative_to(ROOT)}/"
    )
    print(f"Manifest: {manifest_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Download, clean and split the two demo datasets.

Produces, for each dataset, a 60/20/20 split:

    baseline.csv   60%  the training/reference data uploaded against a model version.
                        Defines the feature schema and every reference distribution.
    holdout.csv    20%  the simulator's replay pool. Rows are drawn from here and
                        drift transformations are applied on top of them.
    test.csv       20%  clean batches for manual upload demos.

Raw downloads are cached under data/raw/ so this only needs a network connection
once (PRD risk I10). Re-running is safe and produces byte-identical output.

Usage:
    python scripts/prepare_datasets.py
    python scripts/prepare_datasets.py --force-download
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

# Fixed everywhere in this project so results are reproducible (PRD NFR-14).
RANDOM_STATE = 42

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "data" / "processed"

TELCO_URL = (
    "https://raw.githubusercontent.com/IBM/telco-customer-churn-on-icp4d/"
    "master/data/Telco-Customer-Churn.csv"
)
# The Adult dataset ships as two files that together form the full 48,842 rows.
# The canonical split between them is arbitrary for our purposes, so we recombine
# them and do our own stratified split.
ADULT_URLS = {
    "adult.data": "https://archive.ics.uci.edu/ml/machine-learning-databases/adult/adult.data",
    "adult.test": "https://archive.ics.uci.edu/ml/machine-learning-databases/adult/adult.test",
}

ADULT_COLUMNS = [
    "age",
    "workclass",
    "fnlwgt",
    "education",
    "education_num",
    "marital_status",
    "occupation",
    "relationship",
    "race",
    "sex",
    "capital_gain",
    "capital_loss",
    "hours_per_week",
    "native_country",
    "income",
]


def download(url: str, dest: Path, force: bool = False) -> Path:
    """Fetch `url` to `dest`, reusing the cached copy unless `force`."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        print(f"  cached  {dest.relative_to(ROOT)}")
        return dest

    print(f"  downloading {url}")
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            dest.write_bytes(response.read())
    except Exception as exc:  # noqa: BLE001 - surfaced to the user, not swallowed
        raise SystemExit(
            f"\nFailed to download {url}\n  {exc}\n\n"
            f"Fix: download it manually and save it to {dest}, then re-run."
        ) from exc

    print(f"  saved   {dest.relative_to(ROOT)} ({dest.stat().st_size:,} bytes)")
    return dest


def load_telco(force: bool) -> tuple[pd.DataFrame, str]:
    """Telco Customer Churn — 7,043 rows, mixed numeric and categorical.

    Mixed column types are the point: K-S exercises the numeric features and
    Chi-Square the categorical ones.
    """
    path = download(TELCO_URL, RAW_DIR / "telco_churn.csv", force)
    df = pd.read_csv(path)

    # TotalCharges arrives as text because 11 rows (all tenure=0, i.e. brand new
    # customers who have not been billed yet) hold a single space instead of a
    # number. Coerce to numeric, then fill those with 0.0 — a customer with no
    # tenure genuinely has no total charges.
    df["TotalCharges"] = pd.to_numeric(df["TotalCharges"], errors="coerce")
    blank_count = int(df["TotalCharges"].isna().sum())
    df["TotalCharges"] = df["TotalCharges"].fillna(0.0)
    if blank_count:
        print(
            f"  cleaned {blank_count} blank TotalCharges values (tenure=0 rows) -> 0.0"
        )

    # customerID is kept deliberately. It is a perfect example of a column the
    # platform must auto-suggest for exclusion from drift monitoring.
    return df, "Churn"


def load_adult(force: bool) -> tuple[pd.DataFrame, str]:
    """Adult Census Income — ~48,842 rows.

    Second model in the demo. With cross-model comparison out of scope, its job
    is to make role-based access control demonstrable: one user is granted this
    model and denied the other.
    """
    frames = []
    for filename, url in ADULT_URLS.items():
        path = download(url, RAW_DIR / filename, force)
        frames.append(
            pd.read_csv(
                path,
                header=None,
                names=ADULT_COLUMNS,
                skipinitialspace=True,  # the raw file pads every value with a leading space
                na_values=["?"],
                # adult.test opens with a '|1x3 Cross validator' comment line.
                skiprows=1 if filename == "adult.test" else 0,
            )
        )
    df = pd.concat(frames, ignore_index=True)

    # fnlwgt is a census sampling weight, not a property of the person. Keeping it
    # would let a model learn from an artefact of the survey design.
    df = df.drop(columns=["fnlwgt"])

    # Trailing '.' appears in some mirrors of this file but not others; strip it so
    # the two class labels are always exactly '<=50K' and '>50K'.
    df["income"] = df["income"].str.rstrip(".").str.strip()

    before = len(df)
    df = df.dropna().reset_index(drop=True)
    if before != len(df):
        print(f"  dropped {before - len(df):,} rows with missing values")

    return df, "income"


def split_and_write(df: pd.DataFrame, target: str, name: str) -> None:
    """Stratified 60/20/20 split, written to data/processed/<name>/."""
    baseline, remainder = train_test_split(
        df, test_size=0.40, random_state=RANDOM_STATE, stratify=df[target]
    )
    holdout, test = train_test_split(
        remainder, test_size=0.50, random_state=RANDOM_STATE, stratify=remainder[target]
    )

    out = OUT_DIR / name
    out.mkdir(parents=True, exist_ok=True)

    for split_name, frame in (
        ("baseline", baseline),
        ("holdout", holdout),
        ("test", test),
    ):
        # sort_index keeps row order stable across runs, so the files are
        # byte-identical every time (PRD NFR-14).
        frame.sort_index().to_csv(out / f"{split_name}.csv", index=False)

    positive_rate = (df[target] == df[target].value_counts().index[-1]).mean()
    print(
        f"  {name}: {len(df):,} rows, {df.shape[1]} columns, target '{target}'\n"
        f"    baseline {len(baseline):,}  holdout {len(holdout):,}  test {len(test):,}"
        f"  (minority class {positive_rate:.1%})"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="re-download even if a cached copy exists",
    )
    args = parser.parse_args()

    print("Preparing demo datasets\n")

    print("Telco Customer Churn")
    telco, telco_target = load_telco(args.force_download)
    split_and_write(telco, telco_target, "telco_churn")

    print("\nAdult Census Income")
    adult, adult_target = load_adult(args.force_download)
    split_and_write(adult, adult_target, "adult_income")

    print(f"\nDone. Written to {OUT_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Plain-string constants for the engine.

The engine must not import Django (see BACKEND_FLOW.md §1), so it cannot use
``core.constants``. These values are deliberately identical to the *values* of
the corresponding Django ``TextChoices`` members, so a string returned from here
compares equal to the enum on the Django side with no translation layer.

If a value changes here it must change in ``core/constants.py`` too. The mirror
is asserted by ``tests/test_constants_mirror.py`` once Track B's file exists.
"""

from __future__ import annotations

# FeatureType
NUMERIC = "NUMERIC"
CATEGORICAL = "CATEGORICAL"

# DriftStatus
NONE = "NONE"
MODERATE = "MODERATE"
HIGH = "HIGH"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

# TestName
KS = "KS"
CHI2 = "CHI2"

# Ordering used to take the worst of several statuses.
DRIFT_SEVERITY_ORDER: tuple[str, ...] = (NONE, MODERATE, HIGH)

# A feature needs at least this many non-null values on BOTH sides before any
# test is trustworthy (PRD FR-03.8).
MIN_SAMPLES_FOR_TEST = 30

# Number of quantile bins built from the baseline (TRD §5.1).
DEFAULT_BIN_COUNT = 10

# Above this many distinct values, a numeric-dtype column is treated as truly
# numeric; at or below it, it is categorical. Keeps flags like SeniorCitizen
# (0/1) out of the K-S test, where they would be meaningless.
MAX_UNIQUE_FOR_CATEGORICAL = 10

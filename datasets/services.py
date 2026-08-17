import pandas as pd


def get_validation_sample(ml_model, n=50):
    """
    STUB: Contract C1. Temporary stub for dataset validation sample until Track A's implementation lands.
    """
    sample_df = pd.DataFrame({"tenure": [1] * n, "MonthlyCharges": [50.0] * n})
    target_classes = ["Yes", "No"]
    return sample_df, target_classes

def test_pct_and_ratio_are_not_interchangeable():
    """They differ by a factor of 100 and the value cannot tell you which it is.

    ``pct`` is for numbers already in percent (quality rates); ``ratio`` is for
    0-1 fractions (accuracy, recall). Using ``pct`` on accuracy renders a model
    that is 70% accurate as "0.7%".
    """
    from monitoring.templatetags.monitoring_extras import pct, ratio

    assert ratio(0.70) == "70.0%"
    assert ratio(0.8514, 2) == "85.14%"
    assert pct(0.12, 2) == "0.12%"
    assert pct(0.70) == "0.7%", "same input, hundredfold different meaning"
    assert ratio(None) == "—" and pct(None) == "—"
    assert ratio(1.0) == "100.0%"
    assert ratio(0.0) == "0.0%"

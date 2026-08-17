"""Simulated production data feed — TRD §4.6, PRD FR-05.

A scenario replays held-out real rows on a timer, applying drift
transformations as it progresses through its phases. It is what makes the
dashboard change on its own while nobody touches it.
"""

from django.core.exceptions import ValidationError
from django.db import models

from core.constants import ScenarioStatus
from core.models import TimeStampedModel

# "Every hour" is the production value, and it is unwatchable in a demo. The
# interval is configurable down to 10 seconds so a scenario can be seen
# progressing, while the screen still shows what the production setting would be.
MIN_INTERVAL_SECONDS = 10
MAX_INTERVAL_SECONDS = 24 * 60 * 60


class SimulationScenario(TimeStampedModel):
    ml_model = models.ForeignKey(
        "registry.MLModel", on_delete=models.CASCADE, related_name="scenarios"
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    interval_seconds = models.IntegerField(default=30)
    batch_size = models.IntegerField(default=500)
    include_labels = models.BooleanField(default=True)

    # Phases keyed by batch index — see simulator.transforms.
    drift_plan = models.JSONField(default=dict)

    # The pool of real rows to replay. Held out from training, so replaying it
    # is not the same as feeding the model its own training data back.
    holdout_file = models.FileField(
        upload_to="simulator/holdouts/", null=True, blank=True
    )

    status = models.CharField(
        max_length=20, choices=ScenarioStatus.choices, default=ScenarioStatus.STOPPED
    )
    # Persisted on every tick, so restarting the server resumes the scenario
    # rather than replaying it from the beginning (FR-05.4).
    next_batch_index = models.IntegerField(default=0)
    last_tick_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    created_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scenarios",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.ml_model.name})"

    @property
    def job_id(self):
        return f"scenario_tick_{self.pk}"

    @property
    def is_running(self):
        return self.status == ScenarioStatus.RUNNING

    def clean(self):
        if not MIN_INTERVAL_SECONDS <= self.interval_seconds <= MAX_INTERVAL_SECONDS:
            raise ValidationError(
                f"Interval must be between {MIN_INTERVAL_SECONDS} seconds and 24 hours."
            )
        if not 10 <= self.batch_size <= 10_000:
            raise ValidationError("Batch size must be between 10 and 10,000 rows.")

    def current_phase(self):
        from simulator import transforms

        return transforms.resolve_phase(self.drift_plan, self.next_batch_index)

    def phase_description(self):
        from simulator import transforms

        return transforms.describe_phase(self.current_phase())

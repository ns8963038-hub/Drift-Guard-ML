from django.apps import AppConfig


class SimulatorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "simulator"

    def ready(self):
        """Start the in-process scheduler.

        Guarded inside start_scheduler(): Django's autoreloader runs ready() in
        both the reloader and the child process, and without the guard every
        scenario would tick twice.
        """
        from django.conf import settings

        if not getattr(settings, "SCHEDULER_ENABLED", True):
            return
        try:
            from simulator.scheduler import start_scheduler

            start_scheduler()
        except Exception:  # noqa: BLE001
            # A scheduler that cannot start must not stop the site from serving.
            import logging

            logging.getLogger("driftguard.scheduler").exception(
                "scheduler failed to start"
            )

from django.apps import AppConfig


class PredictionsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "predictions"

    def ready(self):
        # Importing signals here (rather than relying on it being imported
        # incidentally elsewhere) is what actually connects the
        # post_save -> create_user_profile receiver. A signals.py file that
        # is never imported registers nothing, and Profile.objects.get_or_create()
        # calls scattered through views.py would then be silently
        # compensating for signals that never fire.
        from . import signals  # noqa: F401
from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Imported for the @register side effect — see core/checks.py.
        from . import checks  # noqa: F401

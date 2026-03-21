from django.apps import AppConfig


class NewsiteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "newsite"

    def ready(self):
        try:
            import ollama
            ollama.list()
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Ollama is not running. LLM features will be unavailable."
            )
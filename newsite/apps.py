from django.apps import AppConfig


class DjangoLlmConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "django_llm"

    def ready(self):
        """
        Runs on Django startup.
        Checks Ollama availability and logs a warning if it's not running.
        """
        try:
            import ollama
            ollama.list()
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Ollama is not running. LLM features will be unavailable. "
                "Start it with: ollama serve"
            )

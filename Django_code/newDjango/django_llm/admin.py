from django.contrib import admin
from .models import new_LLM

# Register your models here.
class llm_admin(admin.ModelAdmin):
    fieldsets = [
        (None, {"fields": ["llm_text"]}),
        ("Date information", {"fields": ["llm_type"]})
    ]

admin.site.register(new_LLM,llm_admin)
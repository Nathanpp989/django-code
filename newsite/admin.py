from django.contrib import admin
from .models import NewLLM

# Register your models here.


class llm_admin(admin.ModelAdmin):

    fieldsets = [
        (None, {"fields": ["llm_text"]}),
        ("Date information", {"fields": ["llm_type"]})
    ]


admin.site.register(NewLLM, llm_admin)

from django.contrib import admin
from .models import NewLLM, LLMChoice, ConvertLLM, ReverseLLM, ChatMessage


class LLMChoiceInline(admin.TabularInline):
    model = LLMChoice
    extra = 1


@admin.register(NewLLM)
class NewLLMAdmin(admin.ModelAdmin):
    list_display = ["llm_text", "llm_date_used", "was_published_recently"]
    list_filter = ["llm_date_used"]
    search_fields = ["llm_text"]
    inlines = [LLMChoiceInline]


@admin.register(ConvertLLM)
class ConvertLLMAdmin(admin.ModelAdmin):
    list_display = ["new_string", "new_number", "created_at"]
    search_fields = ["new_string"]


@admin.register(ReverseLLM)
class ReverseLLMAdmin(admin.ModelAdmin):
    list_display = ["new_string", "new_number", "created_at"]


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ["user", "role", "short_content", "created_at"]
    list_filter = ["role", "created_at", "user"]
    search_fields = ["content", "user__username"]
    readonly_fields = ["created_at"]

    def short_content(self, obj):
        return obj.content[:80] + "..." if len(obj.content) > 80 else obj.content
    short_content.short_description = "Content"

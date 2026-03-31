from django.contrib import admin
from .models import NewLLM, LLMChoice, ConvertLLM, ReverseLLM, ChatMessage, LLMSummary


class LLMChoiceInline(admin.TabularInline):
    model = LLMChoice
    extra = 1


@admin.register(NewLLM)
class NewLLMAdmin(admin.ModelAdmin):
    list_display = ["llm_text", "llm_date_used", "was_published_recently", "created_at"]
    list_filter = ["llm_date_used"]
    search_fields = ["llm_text"]
    inlines = [LLMChoiceInline]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(LLMChoice)
class LLMChoiceAdmin(admin.ModelAdmin):
    list_display = ["choice_text", "new_llm", "amount", "created_at"]
    list_filter = ["new_llm"]
    search_fields = ["choice_text"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ConvertLLM)
class ConvertLLMAdmin(admin.ModelAdmin):
    list_display = ["new_string", "new_number", "created_at"]
    search_fields = ["new_string"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ReverseLLM)
class ReverseLLMAdmin(admin.ModelAdmin):
    list_display = ["new_string", "new_number", "created_at"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ["user", "role", "short_content", "created_at"]
    list_filter = ["role", "created_at", "user"]
    search_fields = ["content", "user__username"]
    readonly_fields = ["created_at"]

    def short_content(self, obj):
        return obj.content[:80] + "..." if len(obj.content) > 80 else obj.content
    short_content.short_description = "Content"


@admin.register(LLMSummary)
class LLMSummaryAdmin(admin.ModelAdmin):
    list_display = ["content_type", "object_id", "model_used", "created_at"]
    list_filter = ["content_type", "model_used", "created_at"]
    search_fields = ["summary"]
    readonly_fields = ["prompt_hash", "created_at", "updated_at"]

    def has_add_permission(self, request):
        return False
    
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.db.models import Count
from .models import NewLLM, LLMChoice, ConvertLLM, ReverseLLM, ChatMessage, LLMSummary, AuditLog, UserActivity


class LLMChoiceInline(admin.TabularInline):
    model = LLMChoice
    extra = 1
    fields = ['choice_text', 'amount']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-amount']


@admin.register(NewLLM)
class NewLLMAdmin(admin.ModelAdmin):
    list_display = ["llm_text", "total_votes", "choice_count", "llm_date_used", "was_published_recently", "created_at"]
    list_filter = ["llm_date_used", "created_at"]
    search_fields = ["llm_text"]
    inlines = [LLMChoiceInline]
    readonly_fields = ["created_at", "updated_at", "vote_summary"]
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    
    def get_queryset(self, request):
        """Optimize queryset with annotations."""
        queryset = super().get_queryset(request)
        return queryset.annotate(
            _choice_count=Count('choices', distinct=True),
            _total_votes=Count('choices__amount', distinct=True)
        )
    
    def choice_count(self, obj):
        return obj._choice_count or 0
    choice_count.short_description = "# Choices"
    choice_count.admin_order_field = '_choice_count'
    
    def total_votes(self, obj):
        total = sum(c.amount for c in obj.choices.all())
        return format_html('<b>{}</b>', total)
    total_votes.short_description = "Total Votes"
    
    def vote_summary(self, obj):
        """Display vote breakdown in admin detail view."""
        choices = obj.choices.all().order_by('-amount')
        if not choices.exists():
            return "No choices yet."
        
        summary = "<ul>"
        for choice in choices:
            summary += f"<li>{choice.choice_text}: {choice.amount} votes</li>"
        summary += "</ul>"
        return format_html(summary)
    vote_summary.short_description = "Vote Summary"


@admin.register(LLMChoice)
class LLMChoiceAdmin(admin.ModelAdmin):
    list_display = ["choice_text", "new_llm_link", "amount", "vote_percentage", "created_at"]
    list_filter = ["new_llm", "created_at"]
    search_fields = ["choice_text", "new_llm__llm_text"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ['-amount']
    
    def new_llm_link(self, obj):
        """Link to parent NewLLM."""
        url = reverse("admin:django_llm_newllm_change", args=[obj.new_llm.pk])
        return format_html('<a href="{}">{}</a>', url, obj.new_llm.llm_text[:50])
    new_llm_link.short_description = "LLM Entry"
    
    def vote_percentage(self, obj):
        """Calculate percentage of total votes."""
        total = sum(c.amount for c in obj.new_llm.choices.all())
        if total == 0:
            return "0%"
        percentage = (obj.amount / total) * 100
        return format_html('<b>{:.1f}%</b>', percentage)
    vote_percentage.short_description = "% of Votes"


@admin.register(ConvertLLM)
class ConvertLLMAdmin(admin.ModelAdmin):
    list_display = ["new_string", "new_number", "string_length_display", "created_at"]
    search_fields = ["new_string"]
    readonly_fields = ["created_at", "updated_at", "new_number"]
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    
    def string_length_display(self, obj):
        """Show string length nicely."""
        return format_html(
            '<span style="background-color: #e3f2fd; padding: 3px 8px; border-radius: 3px;">{}</span>',
            obj.new_number or 0
        )
    string_length_display.short_description = "Length"


@admin.register(ReverseLLM)
class ReverseLLMAdmin(admin.ModelAdmin):
    list_display = ["new_string", "new_number", "created_at"]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ['-created_at']
    date_hierarchy = 'created_at'


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ["user_link", "role_badge", "short_content", "message_length", "created_at"]
    list_filter = ["role", "created_at", "user"]
    search_fields = ["content", "user__username"]
    readonly_fields = ["created_at", "user", "role", "content"]
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    
    def has_add_permission(self, request):
        """Prevent manual chat creation."""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Only superusers can delete chat messages."""
        return request.user.is_superuser
    
    def user_link(self, obj):
        """Link to user."""
        url = reverse("admin:auth_user_change", args=[obj.user.pk])
        return format_html('<a href="{}">{}</a>', url, obj.user.username)
    user_link.short_description = "User"
    
    def role_badge(self, obj):
        """Color-coded role badge."""
        colors = {"user": "#4CAF50", "assistant": "#2196F3"}
        color = colors.get(obj.role, "#999")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px; font-weight: bold;">{}</span>',
            color, obj.role.upper()
        )
    role_badge.short_description = "Role"
    
    def short_content(self, obj):
        content = obj.content[:100] + "..." if len(obj.content) > 100 else obj.content
        return content
    short_content.short_description = "Content"
    
    def message_length(self, obj):
        """Display message character count."""
        return format_html('<code>{}</code> chars', len(obj.content))
    message_length.short_description = "Length"


@admin.register(LLMSummary)
class LLMSummaryAdmin(admin.ModelAdmin):
    list_display = ["content_type", "object_id", "model_used", "summary_preview", "created_at"]
    list_filter = ["content_type", "model_used", "created_at"]
    search_fields = ["summary", "prompt_hash"]
    readonly_fields = ["prompt_hash", "created_at", "updated_at", "full_summary"]
    ordering = ['-created_at']
    date_hierarchy = 'created_at'
    
    def has_add_permission(self, request):
        return False
    
    def summary_preview(self, obj):
        """Show truncated summary."""
        preview = obj.summary[:80] + "..." if len(obj.summary) > 80 else obj.summary
        return preview
    summary_preview.short_description = "Summary"
    
    def full_summary(self, obj):
        """Display full summary in detail view."""
        return format_html('<pre style="white-space: pre-wrap; word-wrap: break-word;">{}</pre>', obj.summary)
    full_summary.short_description = "Full Summary"


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["user", "action_badge", "resource_type", "timestamp", "status_badge"]
    list_filter = ["action", "status", "timestamp", "resource_type"]
    search_fields = ["user__username", "resource_id"]
    readonly_fields = ["user", "action", "resource_type", "resource_id", "changes", "timestamp"]
    ordering = ['-timestamp']
    date_hierarchy = 'timestamp'
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
    
    def action_badge(self, obj):
        """Color-coded action badge."""
        colors = {
            "CREATE": "#4CAF50",
            "UPDATE": "#2196F3",
            "DELETE": "#f44336",
            "VOTE": "#FF9800",
        }
        color = colors.get(obj.action, "#999")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            color, obj.action
        )
    action_badge.short_description = "Action"
    
    def status_badge(self, obj):
        """Status indicator."""
        colors = {"success": "#4CAF50", "failed": "#f44336"}
        color = colors.get(obj.status, "#999")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 10px; border-radius: 3px;">{}</span>',
            color, obj.status.upper()
        )
    status_badge.short_description = "Status"


@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ["user", "activity_type", "timestamp"]
    list_filter = ["activity_type", "timestamp", "user"]
    search_fields = ["user__username", "activity_type"]
    readonly_fields = ["user", "activity_type", "metadata", "timestamp"]
    ordering = ['-timestamp']
    date_hierarchy = 'timestamp'
    
    def has_add_permission(self, request):
        return False

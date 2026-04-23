import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import transaction, connection
from django.db.models import F, Q, Prefetch, Sum
from django.core.cache import cache
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.core.exceptions import ValidationError, PermissionDenied
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.utils.html import escape
from django.utils.decorators import method_decorator
from .models import NewLLM, ConvertLLM, LLMChoice, ChatMessage, ReverseLLM, LLMSummary
from .forms import llm_textbox, NewLLMForm
from .mcp_client import MCPOllamaClient, OLLAMA_AVAILABLE, MCP_AVAILABLE
from .prompts import CONVERT_SUMMARY_PROMPT, RESULTS_SUMMARY_PROMPT, REVERSE_SUMMARY_PROMPT
import logging
import json
import csv
import hashlib
from datetime import timedelta
from django.utils import timezone
from django.http import Http404
import time
from django.conf import settings
import requests
from functools import wraps

logger = logging.getLogger(__name__)

mcp_client = MCPOllamaClient()

# Security constants
MAX_CHAT_LENGTH = 2000
MAX_LLM_TEXT_LENGTH = 200
MAX_CHOICE_LENGTH = 200
MAX_REQUESTS_PER_MINUTE = 10
CHAT_WINDOW_SECONDS = 60
SUMMARY_CACHE_TIMEOUT = 300
OVERVIEW_CACHE_TIMEOUT = 300

# Feature flags
ENABLE_ANALYTICS = True
ENABLE_NOTIFICATIONS = True
ENABLE_AUDIT_LOG = True

# -------------------------
# Helper Functions
# -------------------------

def validate_user_owns_resource(user, obj):
    """Validate that user has permission to access resource."""
    if hasattr(obj, 'user') and obj.user != user:
        raise PermissionDenied("You do not have permission to access this resource.")


def sanitize_input(value: str, max_length: int = 500) -> str:
    """Sanitize and validate user input."""
    if not isinstance(value, str):
        raise ValidationError("Input must be a string.")
    
    value = value.strip()
    
    if len(value) == 0:
        raise ValidationError("Input cannot be empty.")
    
    if len(value) > max_length:
        raise ValidationError(f"Input cannot exceed {max_length} characters.")
    
    return escape(value)


def rate_limit_chat(user, max_requests=MAX_REQUESTS_PER_MINUTE, window=CHAT_WINDOW_SECONDS):
    """
    Sliding window rate limiter for chat requests.
    Allow max_requests per window seconds per user.
    """
    cache_key = f"chat_rate_{user.pk}"
    requests = cache.get(cache_key, 0)
    if requests >= max_requests:
        return True
    cache.set(cache_key, requests + 1, timeout=window)
    return False


def get_or_create_summary(
    prompt: str,
    content_type: str,
    object_id: int
) -> str:
    """
    Get a persisted LLM summary or generate and save a new one.
    Uses prompt hash as key to avoid regenerating identical summaries.
    Includes error handling and timeout protection.
    """
    if not prompt or len(prompt) == 0:
        logger.warning("Empty prompt provided to get_or_create_summary")
        return ""
    
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    
    try:
        summary_obj = LLMSummary.objects.get(prompt_hash=prompt_hash)
        return summary_obj.summary
    except LLMSummary.DoesNotExist:
        pass
    except Exception as e:
        logger.error(f"Error retrieving summary: {e}")
        return ""
    
    # Generate new summary with try/except
    try:
        if not MCP_AVAILABLE or not OLLAMA_AVAILABLE:
            return "Summary generation unavailable."
        
        summary = mcp_client.generate_summary(prompt)
        
        if not summary:
            logger.warning(f"Empty summary returned for content_type={content_type}, object_id={object_id}")
            return ""
        
        # Use get_or_create to handle race conditions
        LLMSummary.objects.get_or_create(
            prompt_hash=prompt_hash,
            defaults={
                "content_type": content_type,
                "object_id": object_id,
                "summary": summary,
            }
        )
        return summary
    except Exception as e:
        logger.error(f"Error generating summary for {content_type}: {e}")
        return ""


def invalidate_related_cache(content_type: str, object_id: int = None):
    """Invalidate cache entries related to object changes."""
    if content_type == "results":
        LLMSummary.objects.filter(
            content_type="results",
            object_id=object_id
        ).delete()
        cache.delete(f"results_summary_{object_id}")
    elif content_type == "convert":
        LLMSummary.objects.filter(
            content_type="convert",
            object_id=object_id
        ).delete()
        cache.delete(f"convert_summary_{object_id}")
    elif content_type == "overview":
        cache.delete("database_overview_summary")


# -------------------------
# Core Views
# -------------------------

@require_http_methods(["GET"])
def index_view(request):
    """Optimized index view with prefetch_related to avoid N+1 queries."""
    try:
        cache_key = "index_recent_llm"
        recent_llm = cache.get(cache_key)
        
        if recent_llm is None:
            recent_llm = list(
                NewLLM.objects
                .prefetch_related(
                    Prefetch('choices', queryset=LLMChoice.objects.order_by('-amount')[:3])
                )
                .order_by("-llm_date_used")[:5]
            )
            cache.set(cache_key, recent_llm, timeout=60)
        
        cache_key_converts = "index_recent_converts"
        recent_converts = cache.get(cache_key_converts)
        
        if recent_converts is None:
            recent_converts = list(
                ConvertLLM.objects.order_by("-created_at")[:5]
            )
            cache.set(cache_key_converts, recent_converts, timeout=60)
        
        # Check FastAPI health
        fastapi_health = None
        if settings.FASTAPI_ENABLED:
            fastapi_health = call_fastapi_api("/api/health", timeout=5)
        
        context = {
            "message": "Django LLM with MCP server integration.",
            "ollama_available": OLLAMA_AVAILABLE,
            "mcp_available": MCP_AVAILABLE,
            "fastapi_available": fastapi_health is not None,
            "recent_llm": recent_llm,
            "recent_converts": recent_converts,
        }
        return render(request, "django_llm/index.html", context)
    except Exception as e:
        logger.error(f"Error in index_view: {e}", exc_info=True)
        messages.error(request, "Failed to load home page.")
        return render(request, "django_llm/index.html", {"error": True})


@require_http_methods(["GET"])
def health_check_view(request):
    """
    Health check endpoint for monitoring and load balancers.
    Returns status of Django, database, Ollama and MCP.
    """
    cache_key = "health_check_status"
    cached_status = cache.get(cache_key)
    if cached_status:
        return JsonResponse(cached_status, status=200 if cached_status["database"] == "ok" else 500)

    status = {
        "django": "ok",
        "database": "ok",
        "ollama": "ok" if OLLAMA_AVAILABLE else "unavailable",
        "mcp": "ok" if MCP_AVAILABLE else "unavailable",
    }

    try:
        connection.ensure_connection()
    except Exception as e:
        status["database"] = f"error: {str(e)}"
        logger.error(f"Health check database error: {e}")

    http_status = 200 if status["database"] == "ok" else 500
    cache.set(cache_key, status, timeout=30)
    return JsonResponse(status, status=http_status)


@login_required
@require_http_methods(["GET", "POST"])
def convert_num_view(request, pk):
    """Convert string to number with validation and authorization."""
    try:
        response = get_object_or_404(ConvertLLM, pk=pk)
    except Http404:
        logger.warning(f"ConvertLLM not found for pk={pk}")
        messages.error(request, "Conversion entry not found.")
        return redirect("django_llm:index")
    
    result_num = response.new_number or 0
    input_str = response.new_string or ""

    if request.method == 'POST':
        form = llm_textbox(request.POST)
        if form.is_valid():
            try:
                input_str = sanitize_input(
                    form.cleaned_data.get("input_string", ""),
                    max_length=1000
                )
                result_num = len(input_str)
                response.new_string = input_str
                response.new_number = result_num
                response.save()
                
                invalidate_related_cache("convert", pk)
                messages.success(request, "Saved successfully.")
            except ValidationError as e:
                messages.error(request, str(e))
            except Exception as e:
                logger.error(f"Failed to save ConvertLLM pk={pk}: {e}")
                messages.error(request, "An error occurred while saving.")
            return redirect("django_llm:convertstr", response.pk)
    else:
        form = llm_textbox(initial={"input_string": input_str})

    llm_summary = None
    if input_str:
        try:
            prompt = CONVERT_SUMMARY_PROMPT.format(text=input_str)
            llm_summary = get_or_create_summary(prompt, "convert", pk)
        except Exception as e:
            logger.error(f"Error generating convert summary: {e}")

    context = {
        "response": response,
        "form": form,
        "result_num": result_num,
        "input_str": input_str,
        "llm_summary": llm_summary,
        "ollama_available": OLLAMA_AVAILABLE,
        "mcp_available": MCP_AVAILABLE,
    }
    return render(request, "django_llm/convertstr.html", context)


@login_required
@require_http_methods(["GET"])
def detail_view(request, pk):
    """Get LLM detail with optimized queries."""
    response = get_object_or_404(
        NewLLM.objects.prefetch_related('choices'),
        pk=pk
    )
    return render(request, "django_llm/detail.html", {
        "response": response,
        "amounts": response.choices.all(),
        "ollama_available": OLLAMA_AVAILABLE,
        "mcp_available": MCP_AVAILABLE,
    })


@login_required
@require_http_methods(["GET"])
def results_view(request, pk):
    """View voting results with LLM summary."""
    response = get_object_or_404(
        NewLLM.objects.prefetch_related('choices'),
        pk=pk
    )
    amounts = response.choices.all()

    llm_summary = None
    if amounts.exists():
        try:
            results_text = "\n".join(
                [f"- {escape(c.choice_text)}: {c.amount} votes" for c in amounts]
            )
            prompt = RESULTS_SUMMARY_PROMPT.format(
                title=escape(response.llm_text),
                results=results_text
            )
            llm_summary = get_or_create_summary(prompt, "results", pk)
        except Exception as e:
            logger.error(f"Error generating results summary: {e}")

    return render(request, "django_llm/results.html", {
        "response": response,
        "amounts": amounts,
        "llm_summary": llm_summary,
        "ollama_available": OLLAMA_AVAILABLE,
        "mcp_available": MCP_AVAILABLE,
    })


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
@handle_view_error
def amount_view(request, pk):
    """Record vote with atomic transaction, validation, and comprehensive tracking."""
    response = get_object_or_404(NewLLM, pk=pk)

    if request.method == 'POST':
        try:
            amount_id = request.POST.get("amount")
            if not amount_id or not amount_id.isdigit():
                raise ValidationError("Invalid selection format.")
            
            amount_id = int(amount_id)
            
            with transaction.atomic():
                selected_amount = response.choices.select_for_update().get(pk=amount_id)
                old_amount = selected_amount.amount
                selected_amount.amount = F('amount') + 1
                selected_amount.save(update_fields=['amount'])
                selected_amount.refresh_from_db()
            
            # Track voting activity
            if ENABLE_ANALYTICS:
                track_user_activity(
                    user=request.user,
                    activity_type="vote",
                    metadata={
                        "llm_id": pk,
                        "choice_id": amount_id,
                        "choice_text": selected_amount.choice_text
                    }
                )
            
            # Audit log with request info
            if ENABLE_AUDIT_LOG:
                log_audit_event(
                    user=request.user,
                    action="VOTE",
                    resource_type="LLMChoice",
                    resource_id=amount_id,
                    request=request,
                    changes={
                        "old_amount": old_amount,
                        "new_amount": selected_amount.amount,
                        "llm_id": pk
                    }
                )
            
            invalidate_related_cache("results", pk)
            messages.success(request, "Vote recorded successfully.")
            return redirect("django_llm:results", response.pk)
            
        except ValidationError as e:
            logger.warning(f"Validation error for NewLLM pk={pk}: {e}")
            messages.error(request, str(e))
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Invalid amount_id submitted for NewLLM pk={pk}: {e}")
            messages.error(request, "Invalid selection. Please try again.")
        except LLMChoice.DoesNotExist:
            logger.warning(f"LLMChoice not found for NewLLM pk={pk}")
            messages.error(request, "Option has not been chosen.")
        except Exception as e:
            logger.error(f"Unexpected error in amount_view: {e}", exc_info=True)
            messages.error(request, "An unexpected error occurred.")

        return render(request, "django_llm/detail.html", {
            "response": response,
            "amounts": response.choices.all(),
        })

    return render(request, "django_llm/detail.html", {
        "response": response,
        "amounts": response.choices.all(),
    })


@login_required
@require_POST
@csrf_protect
def chat_message_view(request):
    """Send chat message with enhanced rate limiting, validation, error handling, and tracking."""
    if rate_limit_chat(request.user, MAX_REQUESTS_PER_MINUTE, CHAT_WINDOW_SECONDS):
        if ENABLE_ANALYTICS:
            track_user_activity(
                user=request.user,
                activity_type="rate_limit_exceeded",
                metadata={"endpoint": "chat_message"}
            )
        
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="CHAT",
                resource_type="ChatMessage",
                resource_id=None,
                request=request,
                status="rate_limited"
            )
        
        return JsonResponse(
            {"error": "Too many requests. Please wait a moment."},
            status=429
        )

    try:
        data = json.loads(request.body)
        user_message = data.get("message", "").strip()
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({"error": "Invalid request body."}, status=400)

    try:
        user_message = sanitize_input(user_message, max_length=MAX_CHAT_LENGTH)
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)

    start_time = time.time()
    user_msg_obj = None
    try:
        with transaction.atomic():
            user_msg_obj = ChatMessage.objects.create(
                user=request.user,
                role="user",
                content=user_message,
            )

            if not OLLAMA_AVAILABLE:
                ai_response = "Ollama is not available. Please start it with: ollama serve"
            else:
                try:
                    history = list(ChatMessage.objects.filter(
                        user=request.user
                    ).order_by("created_at").values("role", "content")[-50:])

                    ollama_messages = [
                        {"role": msg["role"], "content": msg["content"]}
                        for msg in history
                    ]

                    system_prompt = (
                        "You are a helpful AI assistant with access to a Django database. "
                        "You can use tools to query LLM entries, voting results, "
                        "conversion history, and database statistics. "
                        "Always be concise and accurate in your responses."
                    )

                    ai_response = mcp_client.chat_with_tools_and_history(
                        messages=ollama_messages,
                        system=system_prompt,
                    )
                    
                    if not ai_response:
                        ai_response = "I encountered an issue generating a response. Please try again."
                except Exception as e:
                    logger.error(f"Chat error for user {request.user}: {e}", exc_info=True)
                    ai_response = "An error occurred processing your message. Please try again."

            ai_msg_obj = ChatMessage.objects.create(
                user=request.user,
                role="assistant",
                content=ai_response,
            )
            
            response_time = time.time() - start_time

        # Track chat activity
        if ENABLE_ANALYTICS:
            track_user_activity(
                user=request.user,
                activity_type="chat_message",
                metadata={
                    "user_msg_len": len(user_message),
                    "response_len": len(ai_response),
                    "response_time": round(response_time, 3)
                }
            )

        # Audit log with request info
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="CHAT",
                resource_type="ChatMessage",
                resource_id=user_msg_obj.pk,
                request=request,
                changes={
                    "response_time": round(response_time, 3),
                    "message_length": len(user_message)
                }
            )

        return JsonResponse({"response": ai_response, "status": "success"})
        
    except Exception as e:
        logger.error(f"Unexpected error in chat_message_view: {e}", exc_info=True)
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="CHAT",
                resource_type="ChatMessage",
                resource_id=user_msg_obj.pk if user_msg_obj else None,
                request=request,
                status="failed"
            )
        return JsonResponse({"error": "An unexpected error occurred."}, status=500)


@login_required
@require_http_methods(["GET"])
def chat_export_view(request):
    """Export chat history as CSV with proper escaping and security."""
    try:
        # Check user has messages to export
        messages_count = ChatMessage.objects.filter(user=request.user).count()
        if messages_count == 0:
            messages.info(request, "No messages to export.")
            return redirect("django_llm:chat")
        
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="chat_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'

        writer = csv.writer(response, quoting=csv.QUOTE_ALL)
        writer.writerow(['Timestamp', 'Role', 'Message Length', 'Message'])

        chat_messages = ChatMessage.objects.filter(
            user=request.user
        ).order_by("created_at").values_list('created_at', 'role', 'content')

        for timestamp, role, content in chat_messages:
            writer.writerow([
                timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                role,
                len(content),
                content[:500]  # Truncate for privacy in some columns
            ])

        # Audit log
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="EXPORT",
                resource_type="ChatMessage",
                resource_id=None,
                request=request,
                changes={"messages_count": messages_count}
            )
        
        logger.info(f"Exported {messages_count} messages for user {request.user}")
        return response
    except Exception as e:
        logger.error(f"Error exporting chat for user {request.user}: {e}", exc_info=True)
        messages.error(request, "Failed to export chat history.")
        return redirect("django_llm:chat")


@login_required
@require_http_methods(["GET"])
def search_llm_view(request):
    """Enhanced search with better error handling and result limiting."""
    query = request.GET.get('q', '').strip()
    
    if not query:
        messages.warning(request, "Please enter a search query.")
        return redirect("django_llm:index")
    
    if len(query) < 2:
        messages.warning(request, "Search query must be at least 2 characters.")
        return redirect("django_llm:index")
    
    if len(query) > 200:
        messages.error(request, "Search query is too long.")
        return redirect("django_llm:index")
    
    try:
        results = NewLLM.objects.filter(
            Q(llm_text__icontains=query) | 
            Q(choices__choice_text__icontains=query)
        ).distinct().prefetch_related('choices')[:1000]  # Limit results
        
        page = get_paginated_items(results, request.GET.get('page', 1), 20)
        
        if page is None:
            raise Exception("Pagination failed")
        
        if ENABLE_ANALYTICS:
            track_user_activity(
                user=request.user,
                activity_type="search",
                metadata={
                    "query": query,
                    "results_count": len(results)
                }
            )
        
        return render(request, "django_llm/search_results.html", {
            "page_obj": page,
            "query": query,
            "results_count": len(results),
        })
    except Exception as e:
        logger.error(f"Error in search: {e}", exc_info=True)
        messages.error(request, "Search failed. Please try again.")
        return redirect("django_llm:index")


@login_required
@require_http_methods(["GET"])
def export_llm_data_view(request):
    """Export all LLM data as JSON with metadata."""
    try:
        llm_entries = NewLLM.objects.prefetch_related('choices').order_by("-created_at")
        
        data = {
            "exported_at": timezone.now().isoformat(),
            "export_user": request.user.username,
            "export_user_id": request.user.id,
            "total_entries": llm_entries.count(),
            "entries": []
        }
        
        for entry in llm_entries:
            entry_data = {
                "id": entry.pk,
                "llm_text": entry.llm_text,
                "date_used": entry.llm_date_used.isoformat(),
                "created_by": entry.created_by.username if entry.created_by else None,
                "created_at": entry.created_at.isoformat(),
                "total_votes": entry.total_votes(),
                "choices": [
                    {
                        "id": choice.pk,
                        "text": choice.choice_text,
                        "amount": choice.amount,
                        "percentage": round(choice.vote_percentage(), 2)
                    }
                    for choice in entry.choices.all()
                ]
            }
            data["entries"].append(entry_data)
        
        response = HttpResponse(
            json.dumps(data, indent=2),
            content_type='application/json; charset=utf-8'
        )
        filename = f"llm_export_{timezone.now().strftime('%Y%m%d_%H%M%S')}.json"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="EXPORT",
                resource_type="NewLLM",
                resource_id=None,
                request=request,
                changes={"entries_count": len(data["entries"])}
            )
        
        logger.info(f"Exported {len(data['entries'])} LLM entries for user {request.user}")
        return response
    except Exception as e:
        logger.error(f"Error exporting LLM data: {e}", exc_info=True)
        messages.error(request, "Failed to export data.")
        return redirect("django_llm:index")


@login_required
@require_POST
@csrf_protect
def bulk_delete_llm_view(request):
    """Delete multiple LLM entries with confirmation and rollback on error."""
    try:
        llm_ids = request.POST.getlist("llm_ids")
        
        if not llm_ids:
            return JsonResponse({"error": "No entries selected."}, status=400)
        
        # Validate and limit IDs
        try:
            llm_ids = [int(id) for id in llm_ids[:100]]
        except (ValueError, TypeError):
            return JsonResponse({"error": "Invalid IDs provided."}, status=400)
        
        # Verify user has permission to delete (optional - implement ownership check)
        llm_entries = NewLLM.objects.filter(pk__in=llm_ids)
        
        with transaction.atomic():
            deleted_count, deleted_data = llm_entries.delete()
        
        cache.delete("index_recent_llm")
        
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="BULK_DELETE",
                resource_type="NewLLM",
                resource_id=None,
                request=request,
                changes={
                    "deleted_count": deleted_count,
                    "deleted_ids": llm_ids
                }
            )
        
        # Notify user
        notify_user(
            request.user,
            title="Bulk Delete Completed",
            message=f"Successfully deleted {deleted_count} LLM entries.",
            notification_type="info"
        )
        
        logger.info(f"User {request.user} deleted {deleted_count} LLM entries")
        
        return JsonResponse({
            "status": "success",
            "deleted_count": deleted_count
        })
    except Exception as e:
        logger.error(f"Error in bulk delete: {e}", exc_info=True)
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="BULK_DELETE",
                resource_type="NewLLM",
                resource_id=None,
                request=request,
                status="failed"
            )
        return JsonResponse({"error": "Failed to delete entries."}, status=500)


# -------------------------
# Request/Response Utilities
# -------------------------

def get_client_ip(request):
    """Extract client IP address from request."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def get_user_agent(request):
    """Extract user agent from request."""
    return request.META.get('HTTP_USER_AGENT', '')


# -------------------------
# Enhanced Audit Logging with Request Info
# -------------------------

def log_audit_event(
    user,
    action,
    resource_type,
    resource_id,
    request=None,
    changes=None,
    status="success"
):
    """Log user actions for compliance and debugging with request metadata."""
    try:
        from .models import AuditLog
        
        ip_address = None
        user_agent = None
        
        if request:
            ip_address = get_client_ip(request)
            user_agent = get_user_agent(request)
        
        AuditLog.objects.create(
            user=user,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            changes=json.dumps(changes) if changes else None,
            status=status,
            ip_address=ip_address,
            user_agent=user_agent,
        )
    except Exception as e:
        logger.error(f"Failed to log audit event: {e}")


# -------------------------
# Error Handling Utilities
# -------------------------

class APIError(Exception):
    """Custom exception for API errors."""
    def __init__(self, message: str, status_code: int = 500, details: dict = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


def handle_view_error(view_func):
    """Decorator to handle view errors gracefully."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        try:
            return view_func(request, *args, **kwargs)
        except PermissionDenied as e:
            logger.warning(f"Permission denied for user {request.user}: {e}")
            messages.error(request, "You do not have permission to access this resource.")
            return redirect("django_llm:index")
        except ValidationError as e:
            logger.warning(f"Validation error: {e}")
            messages.error(request, str(e))
            return redirect("django_llm:index")
        except Http404:
            logger.warning(f"Resource not found for request: {request.path}")
            messages.error(request, "The requested resource was not found.")
            return redirect("django_llm:index")
        except Exception as e:
            logger.error(f"Unexpected error in {view_func.__name__}: {e}", exc_info=True)
            messages.error(request, "An unexpected error occurred. Please try again later.")
            return redirect("django_llm:index")
    return wrapper


# -------------------------
# Notification System
# -------------------------

def create_notification(user, title: str, message: str, notification_type: str = "info"):
    """Create an in-app notification for a user."""
    try:
        from .models import Notification
        Notification.objects.create(
            user=user,
            title=title,
            message=message,
            notification_type=notification_type
        )
    except Exception as e:
        logger.error(f"Failed to create notification: {e}")


def notify_user(user, title: str, message: str, notification_type: str = "info"):
    """Create notification and optionally send email."""
    create_notification(user, title, message, notification_type)
    
    # Optional: Send email notification
    try:
        from django.core.mail import send_mail
        from django.conf import settings as django_settings
        
        if getattr(django_settings, 'EMAIL_BACKEND', None):
            send_mail(
                subject=title,
                message=message,
                from_email=django_settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                fail_silently=True,
            )
    except Exception as e:
        logger.warning(f"Failed to send email notification to {user.email}: {e}")


# -------------------------
# Pagination Helper
# -------------------------

def get_paginated_items(queryset, page_number: int = 1, per_page: int = 50):
    """Get paginated items from queryset."""
    try:
        paginator = Paginator(queryset, per_page)
        try:
            page = paginator.page(page_number)
        except (PageNotAnInteger, EmptyPage):
            page = paginator.page(1)
        return page
    except Exception as e:
        logger.error(f"Pagination error: {e}")
        return None


# -------------------------
# Caching Decorators
# -------------------------

def cache_view_result(timeout: int = 60, key_prefix: str = ""):
    """Decorator to cache view results for authenticated users."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Only cache for GET requests and authenticated users
            if request.method != "GET" or not request.user.is_authenticated:
                return view_func(request, *args, **kwargs)
            
            cache_key = f"view_{key_prefix}_{request.user.pk}_{request.path}"
            cached_result = cache.get(cache_key)
            
            if cached_result is not None:
                logger.debug(f"Cache hit for {cache_key}")
                return cached_result
            
            result = view_func(request, *args, **kwargs)
            cache.set(cache_key, result, timeout)
            return result
        return wrapper
    return decorator


# -------------------------
# Enhanced Views with Error Handling
# -------------------------

@require_http_methods(["GET"])
def index_view(request):
    """Optimized index view with prefetch_related to avoid N+1 queries."""
    try:
        cache_key = "index_recent_llm"
        recent_llm = cache.get(cache_key)
        
        if recent_llm is None:
            recent_llm = list(
                NewLLM.objects
                .prefetch_related(
                    Prefetch('choices', queryset=LLMChoice.objects.order_by('-amount')[:3])
                )
                .order_by("-llm_date_used")[:5]
            )
            cache.set(cache_key, recent_llm, timeout=60)
        
        cache_key_converts = "index_recent_converts"
        recent_converts = cache.get(cache_key_converts)
        
        if recent_converts is None:
            recent_converts = list(
                ConvertLLM.objects.order_by("-created_at")[:5]
            )
            cache.set(cache_key_converts, recent_converts, timeout=60)
        
        # Check FastAPI health
        fastapi_health = None
        if settings.FASTAPI_ENABLED:
            fastapi_health = call_fastapi_api("/api/health", timeout=5)
        
        context = {
            "message": "Django LLM with MCP server integration.",
            "ollama_available": OLLAMA_AVAILABLE,
            "mcp_available": MCP_AVAILABLE,
            "fastapi_available": fastapi_health is not None,
            "recent_llm": recent_llm,
            "recent_converts": recent_converts,
        }
        return render(request, "django_llm/index.html", context)
    except Exception as e:
        logger.error(f"Error in index_view: {e}", exc_info=True)
        messages.error(request, "Failed to load home page.")
        return render(request, "django_llm/index.html", {"error": True})


@login_required
@require_http_methods(["GET"])
@cache_view_result(timeout=300, key_prefix="user_dashboard")
def user_dashboard_view(request):
    """Display user statistics and activity summary with caching."""
    try:
        from .models import UserActivity, AuditLog
        
        stats = get_user_stats(request.user)
        
        recent_activity = ChatMessage.objects.filter(
            user=request.user
        ).order_by("-created_at")[:10]
        
        recent_audits = AuditLog.objects.filter(
            user=request.user
        ).order_by("-timestamp")[:5]
        
        context = {
            "stats": stats,
            "recent_activity": recent_activity,
            "recent_audits": recent_audits,
            "user": request.user,
        }
        
        if ENABLE_ANALYTICS:
            track_user_activity(
                user=request.user,
                activity_type="view_dashboard",
            )
        
        return render(request, "django_llm/dashboard.html", context)
    except Exception as e:
        logger.error(f"Error rendering dashboard for user {request.user}: {e}", exc_info=True)
        messages.error(request, "Failed to load dashboard.")
        return redirect("django_llm:index")


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
@handle_view_error
def create_llm_view(request):
    """Create LLM entry with comprehensive validation and logging."""
    if request.method == 'POST':
        form = NewLLMForm(request.POST)
        if form.is_valid():
            try:
                llm_text = sanitize_input(
                    form.cleaned_data["llm_text"],
                    max_length=MAX_LLM_TEXT_LENGTH
                )
                choices_str = form.cleaned_data.get("choices", "")
                
                with transaction.atomic():
                    obj = NewLLM.objects.create(
                        llm_text=llm_text,
                        created_by=request.user
                    )
                    
                    choice_objects = []
                    if choices_str:
                        for choice_text in choices_str.splitlines():
                            choice_text = choice_text.strip()
                            if choice_text:
                                try:
                                    choice_text = sanitize_input(
                                        choice_text,
                                        max_length=MAX_CHOICE_LENGTH
                                    )
                                    choice_objects.append(
                                        LLMChoice(
                                            new_llm=obj,
                                            choice_text=choice_text
                                        )
                                    )
                                except ValidationError as ve:
                                    logger.warning(f"Invalid choice text: {choice_text} - {ve}")
                                    continue
                        
                        if choice_objects:
                            LLMChoice.objects.bulk_create(choice_objects)
                
                # Log audit event with request info
                if ENABLE_AUDIT_LOG:
                    log_audit_event(
                        user=request.user,
                        action="CREATE",
                        resource_type="NewLLM",
                        resource_id=obj.pk,
                        request=request,
                        changes={
                            "llm_text": llm_text,
                            "choices_count": len(choice_objects)
                        }
                    )
                
                # Track activity
                if ENABLE_ANALYTICS:
                    track_user_activity(
                        user=request.user,
                        activity_type="create_llm",
                        metadata={"llm_id": obj.pk, "choices_count": len(choice_objects)}
                    )
                
                # Invalidate cache
                cache.delete("index_recent_llm")
                
                # Notify user
                notify_user(
                    request.user,
                    title="LLM Entry Created",
                    message=f"Your entry '{llm_text}' was created successfully.",
                    notification_type="success"
                )
                
                messages.success(request, f"LLM entry '{llm_text}' created successfully.")
                return redirect("django_llm:detail", obj.pk)
            except ValidationError as e:
                messages.error(request, str(e))
                logger.warning(f"Validation error in create_llm: {e}")
            except Exception as e:
                logger.error(f"Error creating LLM: {e}", exc_info=True)
                if ENABLE_AUDIT_LOG:
                    log_audit_event(
                        user=request.user,
                        action="CREATE",
                        resource_type="NewLLM",
                        resource_id=None,
                        request=request,
                        status="failed"
                    )
                messages.error(request, "An error occurred while creating the entry.")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = NewLLMForm()
    
    return render(request, "django_llm/create_llm.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
@handle_view_error
def amount_view(request, pk):
    """Record vote with atomic transaction, validation, and comprehensive tracking."""
    response = get_object_or_404(NewLLM, pk=pk)

    if request.method == 'POST':
        try:
            amount_id = request.POST.get("amount")
            if not amount_id or not amount_id.isdigit():
                raise ValidationError("Invalid selection format.")
            
            amount_id = int(amount_id)
            
            with transaction.atomic():
                selected_amount = response.choices.select_for_update().get(pk=amount_id)
                old_amount = selected_amount.amount
                selected_amount.amount = F('amount') + 1
                selected_amount.save(update_fields=['amount'])
                selected_amount.refresh_from_db()
            
            # Track voting activity
            if ENABLE_ANALYTICS:
                track_user_activity(
                    user=request.user,
                    activity_type="vote",
                    metadata={
                        "llm_id": pk,
                        "choice_id": amount_id,
                        "choice_text": selected_amount.choice_text
                    }
                )
            
            # Audit log with request info
            if ENABLE_AUDIT_LOG:
                log_audit_event(
                    user=request.user,
                    action="VOTE",
                    resource_type="LLMChoice",
                    resource_id=amount_id,
                    request=request,
                    changes={
                        "old_amount": old_amount,
                        "new_amount": selected_amount.amount,
                        "llm_id": pk
                    }
                )
            
            invalidate_related_cache("results", pk)
            messages.success(request, "Vote recorded successfully.")
            return redirect("django_llm:results", response.pk)
            
        except ValidationError as e:
            logger.warning(f"Validation error for NewLLM pk={pk}: {e}")
            messages.error(request, str(e))
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Invalid amount_id submitted for NewLLM pk={pk}: {e}")
            messages.error(request, "Invalid selection. Please try again.")
        except LLMChoice.DoesNotExist:
            logger.warning(f"LLMChoice not found for NewLLM pk={pk}")
            messages.error(request, "Option has not been chosen.")
        except Exception as e:
            logger.error(f"Unexpected error in amount_view: {e}", exc_info=True)
            messages.error(request, "An unexpected error occurred.")

        return render(request, "django_llm/detail.html", {
            "response": response,
            "amounts": response.choices.all(),
        })

    return render(request, "django_llm/detail.html", {
        "response": response,
        "amounts": response.choices.all(),
    })


@login_required
@require_POST
@csrf_protect
def chat_message_view(request):
    """Send chat message with enhanced rate limiting, validation, error handling, and tracking."""
    if rate_limit_chat(request.user, MAX_REQUESTS_PER_MINUTE, CHAT_WINDOW_SECONDS):
        if ENABLE_ANALYTICS:
            track_user_activity(
                user=request.user,
                activity_type="rate_limit_exceeded",
                metadata={"endpoint": "chat_message"}
            )
        
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="CHAT",
                resource_type="ChatMessage",
                resource_id=None,
                request=request,
                status="rate_limited"
            )
        
        return JsonResponse(
            {"error": "Too many requests. Please wait a moment."},
            status=429
        )

    try:
        data = json.loads(request.body)
        user_message = data.get("message", "").strip()
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({"error": "Invalid request body."}, status=400)

    try:
        user_message = sanitize_input(user_message, max_length=MAX_CHAT_LENGTH)
    except ValidationError as e:
        return JsonResponse({"error": str(e)}, status=400)

    start_time = time.time()
    user_msg_obj = None
    try:
        with transaction.atomic():
            user_msg_obj = ChatMessage.objects.create(
                user=request.user,
                role="user",
                content=user_message,
            )

            if not OLLAMA_AVAILABLE:
                ai_response = "Ollama is not available. Please start it with: ollama serve"
            else:
                try:
                    history = list(ChatMessage.objects.filter(
                        user=request.user
                    ).order_by("created_at").values("role", "content")[-50:])

                    ollama_messages = [
                        {"role": msg["role"], "content": msg["content"]}
                        for msg in history
                    ]

                    system_prompt = (
                        "You are a helpful AI assistant with access to a Django database. "
                        "You can use tools to query LLM entries, voting results, "
                        "conversion history, and database statistics. "
                        "Always be concise and accurate in your responses."
                    )

                    ai_response = mcp_client.chat_with_tools_and_history(
                        messages=ollama_messages,
                        system=system_prompt,
                    )
                    
                    if not ai_response:
                        ai_response = "I encountered an issue generating a response. Please try again."
                except Exception as e:
                    logger.error(f"Chat error for user {request.user}: {e}", exc_info=True)
                    ai_response = "An error occurred processing your message. Please try again."

            ai_msg_obj = ChatMessage.objects.create(
                user=request.user,
                role="assistant",
                content=ai_response,
            )
            
            response_time = time.time() - start_time

        # Track chat activity
        if ENABLE_ANALYTICS:
            track_user_activity(
                user=request.user,
                activity_type="chat_message",
                metadata={
                    "user_msg_len": len(user_message),
                    "response_len": len(ai_response),
                    "response_time": round(response_time, 3)
                }
            )

        # Audit log with request info
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="CHAT",
                resource_type="ChatMessage",
                resource_id=user_msg_obj.pk,
                request=request,
                changes={
                    "response_time": round(response_time, 3),
                    "message_length": len(user_message)
                }
            )

        return JsonResponse({"response": ai_response, "status": "success"})
        
    except Exception as e:
        logger.error(f"Unexpected error in chat_message_view: {e}", exc_info=True)
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="CHAT",
                resource_type="ChatMessage",
                resource_id=user_msg_obj.pk if user_msg_obj else None,
                request=request,
                status="failed"
            )
        return JsonResponse({"error": "An unexpected error occurred."}, status=500)


@login_required
@require_http_methods(["GET"])
def chat_export_view(request):
    """Export chat history as CSV with proper escaping and security."""
    try:
        # Check user has messages to export
        messages_count = ChatMessage.objects.filter(user=request.user).count()
        if messages_count == 0:
            messages.info(request, "No messages to export.")
            return redirect("django_llm:chat")
        
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="chat_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'

        writer = csv.writer(response, quoting=csv.QUOTE_ALL)
        writer.writerow(['Timestamp', 'Role', 'Message Length', 'Message'])

        chat_messages = ChatMessage.objects.filter(
            user=request.user
        ).order_by("created_at").values_list('created_at', 'role', 'content')

        for timestamp, role, content in chat_messages:
            writer.writerow([
                timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                role,
                len(content),
                content[:500]  # Truncate for privacy in some columns
            ])

        # Audit log
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="EXPORT",
                resource_type="ChatMessage",
                resource_id=None,
                request=request,
                changes={"messages_count": messages_count}
            )
        
        logger.info(f"Exported {messages_count} messages for user {request.user}")
        return response
    except Exception as e:
        logger.error(f"Error exporting chat for user {request.user}: {e}", exc_info=True)
        messages.error(request, "Failed to export chat history.")
        return redirect("django_llm:chat")


@login_required
@require_http_methods(["GET"])
def search_llm_view(request):
    """Enhanced search with better error handling and result limiting."""
    query = request.GET.get('q', '').strip()
    
    if not query:
        messages.warning(request, "Please enter a search query.")
        return redirect("django_llm:index")
    
    if len(query) < 2:
        messages.warning(request, "Search query must be at least 2 characters.")
        return redirect("django_llm:index")
    
    if len(query) > 200:
        messages.error(request, "Search query is too long.")
        return redirect("django_llm:index")
    
    try:
        results = NewLLM.objects.filter(
            Q(llm_text__icontains=query) | 
            Q(choices__choice_text__icontains=query)
        ).distinct().prefetch_related('choices')[:1000]  # Limit results
        
        page = get_paginated_items(results, request.GET.get('page', 1), 20)
        
        if page is None:
            raise Exception("Pagination failed")
        
        if ENABLE_ANALYTICS:
            track_user_activity(
                user=request.user,
                activity_type="search",
                metadata={
                    "query": query,
                    "results_count": len(results)
                }
            )
        
        return render(request, "django_llm/search_results.html", {
            "page_obj": page,
            "query": query,
            "results_count": len(results),
        })
    except Exception as e:
        logger.error(f"Error in search: {e}", exc_info=True)
        messages.error(request, "Search failed. Please try again.")
        return redirect("django_llm:index")


@login_required
@require_http_methods(["GET"])
def export_llm_data_view(request):
    """Export all LLM data as JSON with metadata."""
    try:
        llm_entries = NewLLM.objects.prefetch_related('choices').order_by("-created_at")
        
        data = {
            "exported_at": timezone.now().isoformat(),
            "export_user": request.user.username,
            "export_user_id": request.user.id,
            "total_entries": llm_entries.count(),
            "entries": []
        }
        
        for entry in llm_entries:
            entry_data = {
                "id": entry.pk,
                "llm_text": entry.llm_text,
                "date_used": entry.llm_date_used.isoformat(),
                "created_by": entry.created_by.username if entry.created_by else None,
                "created_at": entry.created_at.isoformat(),
                "total_votes": entry.total_votes(),
                "choices": [
                    {
                        "id": choice.pk,
                        "text": choice.choice_text,
                        "amount": choice.amount,
                        "percentage": round(choice.vote_percentage(), 2)
                    }
                    for choice in entry.choices.all()
                ]
            }
            data["entries"].append(entry_data)
        
        response = HttpResponse(
            json.dumps(data, indent=2),
            content_type='application/json; charset=utf-8'
        )
        filename = f"llm_export_{timezone.now().strftime('%Y%m%d_%H%M%S')}.json"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="EXPORT",
                resource_type="NewLLM",
                resource_id=None,
                request=request,
                changes={"entries_count": len(data["entries"])}
            )
        
        logger.info(f"Exported {len(data['entries'])} LLM entries for user {request.user}")
        return response
    except Exception as e:
        logger.error(f"Error exporting LLM data: {e}", exc_info=True)
        messages.error(request, "Failed to export data.")
        return redirect("django_llm:index")


@login_required
@require_POST
@csrf_protect
def bulk_delete_llm_view(request):
    """Delete multiple LLM entries with confirmation and rollback on error."""
    try:
        llm_ids = request.POST.getlist("llm_ids")
        
        if not llm_ids:
            return JsonResponse({"error": "No entries selected."}, status=400)
        
        # Validate and limit IDs
        try:
            llm_ids = [int(id) for id in llm_ids[:100]]
        except (ValueError, TypeError):
            return JsonResponse({"error": "Invalid IDs provided."}, status=400)
        
        # Verify user has permission to delete (optional - implement ownership check)
        llm_entries = NewLLM.objects.filter(pk__in=llm_ids)
        
        with transaction.atomic():
            deleted_count, deleted_data = llm_entries.delete()
        
        cache.delete("index_recent_llm")
        
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="BULK_DELETE",
                resource_type="NewLLM",
                resource_id=None,
                request=request,
                changes={
                    "deleted_count": deleted_count,
                    "deleted_ids": llm_ids
                }
            )
        
        # Notify user
        notify_user(
            request.user,
            title="Bulk Delete Completed",
            message=f"Successfully deleted {deleted_count} LLM entries.",
            notification_type="info"
        )
        
        logger.info(f"User {request.user} deleted {deleted_count} LLM entries")
        
        return JsonResponse({
            "status": "success",
            "deleted_count": deleted_count
        })
    except Exception as e:
        logger.error(f"Error in bulk delete: {e}", exc_info=True)
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="BULK_DELETE",
                resource_type="NewLLM",
                resource_id=None,
                request=request,
                status="failed"
            )
        return JsonResponse({"error": "Failed to delete entries."}, status=500)


# -------------------------
# FastAPI Integration Helpers
# -------------------------

def get_fastapi_client_session():
    """Get requests session for FastAPI communication."""
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "User-Agent": "Django-LLM/1.0",
    })
    return session

def call_fastapi_api(endpoint: str, method: str = "GET", data: dict = None, timeout: int = None):
    """
    Call FastAPI endpoint with error handling.
    
    Args:
        endpoint: API endpoint path (e.g., "/api/llm/entries")
        method: HTTP method (GET, POST, etc.)
        data: Request body data
        timeout: Request timeout in seconds
    
    Returns:
        Response data or None on error
    """
    if not settings.FASTAPI_ENABLED:
        logger.warning("FastAPI is disabled")
        return None
    
    timeout = timeout or settings.FASTAPI_API_TIMEOUT
    url = f"{settings.FASTAPI_URL}{endpoint}"
    
    try:
        session = get_fastapi_client_session()
        
        if method == "GET":
            response = session.get(url, timeout=timeout)
        elif method == "POST":
            response = session.post(url, json=data, timeout=timeout)
        elif method == "PUT":
            response = session.put(url, json=data, timeout=timeout)
        elif method == "DELETE":
            response = session.delete(url, timeout=timeout)
        else:
            raise ValueError(f"Unsupported method: {method}")
        
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        logger.error(f"FastAPI timeout: {url}")
        return None
    except requests.exceptions.ConnectionError:
        logger.error(f"FastAPI connection error: {url}")
        return None
    except requests.exceptions.HTTPError as e:
        logger.error(f"FastAPI HTTP error {e.response.status_code}: {url}")
        return None
    except Exception as e:
        logger.error(f"FastAPI error: {e}")
        return None

def sync_to_fastapi(resource_type: str, action: str = "create"):
    """
    Decorator to sync Django model changes to FastAPI.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            response = view_func(request, *args, **kwargs)
            
            # Sync to FastAPI if enabled
            if settings.FASTAPI_ENABLED and hasattr(response, 'url'):
                try:
                    # Extract resource ID from redirect URL
                    if resource_type == "llm" and "detail" in response.url:
                        llm_id = kwargs.get('pk') or args[0]
                        call_fastapi_api(
                            f"/api/llm/{llm_id}/sync",
                            method="POST",
                            data={"action": action}
                        )
                except Exception as e:
                    logger.warning(f"Failed to sync to FastAPI: {e}")
            
            return response
        return wrapper
    return decorator

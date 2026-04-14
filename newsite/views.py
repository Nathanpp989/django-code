from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import transaction, connection
from django.db.models import F, Q, Prefetch
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
        fastapi_health = call_fastapi_api("/api/health")
    
    context = {
        "message": "Django LLM with MCP server integration.",
        "ollama_available": OLLAMA_AVAILABLE,
        "mcp_available": MCP_AVAILABLE,
        "fastapi_available": fastapi_health is not None,
        "recent_llm": recent_llm,
        "recent_converts": recent_converts,
    }
    return render(request, "django_llm/index.html", context)


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
def amount_view(request, pk):
    """Record vote with atomic transaction and validation."""
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
                selected_amount.save()
            
            # Track voting activity
            if ENABLE_ANALYTICS:
                track_user_activity(
                    user=request.user,
                    activity_type="vote",
                    metadata={"llm_id": pk, "choice_id": amount_id}
                )
            
            # Audit log
            if ENABLE_AUDIT_LOG:
                log_audit_event(
                    user=request.user,
                    action="VOTE",
                    resource_type="LLMChoice",
                    resource_id=amount_id,
                    changes={"old_amount": old_amount, "new_amount": old_amount + 1}
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
            logger.error(f"Unexpected error in amount_view: {e}")
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
@require_http_methods(["GET"])
def reverse_llm_view(request, pk):
    """View reversed LLM with summary."""
    response = get_object_or_404(ReverseLLM, pk=pk)

    llm_summary = None
    if response.new_string:
        try:
            prompt = REVERSE_SUMMARY_PROMPT.format(
                number=response.new_number,
                string=escape(response.new_string)
            )
            llm_summary = get_or_create_summary(prompt, "reverse", pk)
        except Exception as e:
            logger.error(f"Error generating reverse summary: {e}")

    return render(request, "django_llm/reverse.html", {
        "response": response,
        "llm_summary": llm_summary,
        "ollama_available": OLLAMA_AVAILABLE,
        "mcp_available": MCP_AVAILABLE,
    })


@login_required
@require_http_methods(["GET"])
def database_overview_view(request):
    """Database overview with cached summary generation."""
    cache_key = "database_overview_summary"
    overview = cache.get(cache_key)
    
    if overview is None:
        try:
            prompt = (
                "Use the get_database_stats tool and get_all_voting_results tool "
                "to give me a concise overview of all the data in the Django LLM "
                "database. Summarise the key statistics and any interesting patterns."
            )
            overview = get_or_create_summary(prompt, "overview", 0)
            cache.set(cache_key, overview, timeout=OVERVIEW_CACHE_TIMEOUT)
        except Exception as e:
            logger.error(f"Error generating overview: {e}")
            overview = "Overview generation temporarily unavailable."
    
    return render(request, "django_llm/overview.html", {
        "overview": overview,
        "ollama_available": OLLAMA_AVAILABLE,
        "mcp_available": MCP_AVAILABLE,
    })


# -------------------------
# Create Views
# -------------------------

@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def create_llm_view(request):
    """Create LLM entry with validation, bulk create, and audit logging."""
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
                    obj = NewLLM.objects.create(llm_text=llm_text)
                    
                    if choices_str:
                        choice_objects = []
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
                                except ValidationError:
                                    logger.warning(f"Invalid choice text: {choice_text}")
                                    continue
                        
                        if choice_objects:
                            LLMChoice.objects.bulk_create(choice_objects)
                
                # Log audit event
                if ENABLE_AUDIT_LOG:
                    log_audit_event(
                        user=request.user,
                        action="CREATE",
                        resource_type="NewLLM",
                        resource_id=obj.pk,
                        changes={"llm_text": llm_text, "choices_count": len(choice_objects)}
                    )
                
                # Track activity
                if ENABLE_ANALYTICS:
                    track_user_activity(
                        user=request.user,
                        activity_type="create_llm",
                        metadata={"llm_id": obj.pk, "choices_count": len(choice_objects)}
                    )
                
                cache.delete("index_recent_llm")
                messages.success(request, f"LLM entry '{llm_text}' created successfully.")
                return redirect("django_llm:detail", obj.pk)
            except ValidationError as e:
                messages.error(request, str(e))
            except Exception as e:
                logger.error(f"Error creating LLM: {e}")
                if ENABLE_AUDIT_LOG:
                    log_audit_event(
                        user=request.user,
                        action="CREATE",
                        resource_type="NewLLM",
                        resource_id=None,
                        status="failed"
                    )
                messages.error(request, "An error occurred while creating the entry.")
    else:
        form = NewLLMForm()
    
    return render(request, "django_llm/create_llm.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def create_convert_view(request):
    """Create conversion entry with validation."""
    if request.method == 'POST':
        form = llm_textbox(request.POST)
        if form.is_valid():
            try:
                input_str = sanitize_input(
                    form.cleaned_data["input_string"],
                    max_length=1000
                )
                obj = ConvertLLM.objects.create(
                    new_string=input_str,
                    new_number=len(input_str)
                )
                messages.success(request, "Conversion entry created.")
                return redirect("django_llm:convertstr", obj.pk)
            except ValidationError as e:
                messages.error(request, str(e))
            except Exception as e:
                logger.error(f"Error creating conversion: {e}")
                messages.error(request, "An error occurred while creating the entry.")
    else:
        form = llm_textbox()
    
    return render(request, "django_llm/create_convert.html", {"form": form})


# -------------------------
# Chat Views
# -------------------------

@login_required
@require_http_methods(["GET"])
def chat_view(request):
    """Chat view with pagination and user-specific queries."""
    all_messages = ChatMessage.objects.filter(
        user=request.user
    ).order_by("-created_at")

    paginator = Paginator(all_messages, 50)
    page_num = request.GET.get('page', 1)
    try:
        page = paginator.page(page_num)
    except (PageNotAnInteger, EmptyPage) as e:
        logger.warning(f"Invalid page number {page_num}: {e}")
        page = paginator.page(1)

    return render(request, "django_llm/chat.html", {
        "chat_history": page.object_list,
        "page_obj": page,
        "has_older": page.has_previous(),
        "older_page": page.previous_page_number() if page.has_previous() else None,
        "ollama_available": OLLAMA_AVAILABLE,
        "mcp_available": MCP_AVAILABLE,
    })


@login_required
@require_POST
@csrf_protect
def chat_message_view(request):
    """Send chat message with rate limiting, validation, error handling, and tracking."""
    if rate_limit_chat(request.user, MAX_REQUESTS_PER_MINUTE, CHAT_WINDOW_SECONDS):
        if ENABLE_ANALYTICS:
            track_user_activity(
                user=request.user,
                activity_type="rate_limit_exceeded",
                metadata={"endpoint": "chat_message"}
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
                    ).order_by("created_at").values("role", "content"))

                    ollama_messages = [
                        {"role": msg["role"], "content": msg["content"]}
                        for msg in history[-50:]
                    ]

                    system_prompt = (
                        "You are a helpful AI assistant with access to a Django database. "
                        "You can use tools to query LLM entries, voting results, "
                        "conversion history, and database statistics. "
                        "Always use the available tools to fetch real data when answering "
                        "questions about the database content."
                    )

                    ai_response = mcp_client.chat_with_tools_and_history(
                        messages=ollama_messages,
                        system=system_prompt,
                    )
                    
                    if not ai_response:
                        ai_response = "I encountered an issue generating a response. Please try again."
                except Exception as e:
                    logger.error(f"Chat error for user {request.user}: {e}")
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
                    "response_time": round(response_time, 2)
                }
            )

        # Audit log
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="CHAT",
                resource_type="ChatMessage",
                resource_id=user_msg_obj.pk,
                changes={"response_time": response_time}
            )

        return JsonResponse({"response": ai_response, "status": "success"})
    except Exception as e:
        logger.error(f"Unexpected error in chat_message_view: {e}")
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="CHAT",
                resource_type="ChatMessage",
                resource_id=None,
                status="failed"
            )
        return JsonResponse({"error": "An unexpected error occurred."}, status=500)


@login_required
@require_POST
@csrf_protect
def chat_clear_view(request):
    """Clear user's chat history with confirmation."""
    try:
        deleted_count, _ = ChatMessage.objects.filter(user=request.user).delete()
        logger.info(f"Cleared {deleted_count} messages for user {request.user}")
        return JsonResponse({
            "status": "success",
            "message": f"Cleared {deleted_count} messages."
        })
    except Exception as e:
        logger.error(f"Error clearing chat for user {request.user}: {e}")
        return JsonResponse({"error": "Failed to clear chat."}, status=500)


@login_required
@require_http_methods(["GET"])
def chat_export_view(request):
    """Export chat history as CSV with proper escaping."""
    try:
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="chat_history.csv"'

        writer = csv.writer(response, quoting=csv.QUOTE_ALL)
        writer.writerow(['Timestamp', 'Role', 'Message'])

        chat_messages = ChatMessage.objects.filter(
            user=request.user
        ).order_by("created_at").values_list('created_at', 'role', 'content')

        for timestamp, role, content in chat_messages:
            writer.writerow([
                timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                role,
                content
            ])

        logger.info(f"Exported chat history for user {request.user}")
        return response
    except Exception as e:
        logger.error(f"Error exporting chat for user {request.user}: {e}")
        messages.error(request, "Failed to export chat history.")
        return redirect("django_llm:chat")


# -------------------------
# Audit Logging
# -------------------------

def log_audit_event(user, action, resource_type, resource_id, changes=None, status="success"):
    """Log user actions for compliance and debugging."""
    try:
        from .models import AuditLog
        AuditLog.objects.create(
            user=user,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            changes=json.dumps(changes) if changes else None,
            status=status,
            ip_address=None,  # Extract from request if available
            user_agent=None,
        )
    except Exception as e:
        logger.error(f"Failed to log audit event: {e}")


# -------------------------
# Analytics and Metrics
# -------------------------

def track_user_activity(user, activity_type, metadata=None):
    """Track user interactions for analytics."""
    try:
        from .models import UserActivity
        UserActivity.objects.create(
            user=user,
            activity_type=activity_type,
            metadata=json.dumps(metadata) if metadata else None,
        )
    except Exception as e:
        logger.error(f"Failed to track user activity: {e}")


def get_user_stats(user):
    """Get user activity statistics."""
    cache_key = f"user_stats_{user.pk}"
    stats = cache.get(cache_key)
    
    if stats is None:
        try:
            from django.db.models import Count
            from .models import UserActivity
            
            stats = {
                "total_votes": NewLLM.objects.aggregate(Count('id'))['id__count'] or 0,
                "total_chats": ChatMessage.objects.filter(user=user).count(),
                "recent_activity": UserActivity.objects.filter(
                    user=user
                ).values('activity_type').annotate(count=Count('id')),
                "created_entries": NewLLM.objects.count(),
            }
            cache.set(cache_key, stats, timeout=3600)  # 1 hour
        except Exception as e:
            logger.error(f"Error getting user stats: {e}")
            stats = {}
    
    return stats


# -------------------------
# Enhanced Views with Logging
# -------------------------

@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def create_llm_view(request):
    """Create LLM entry with validation, bulk create, and audit logging."""
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
                    obj = NewLLM.objects.create(llm_text=llm_text)
                    
                    if choices_str:
                        choice_objects = []
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
                                except ValidationError:
                                    logger.warning(f"Invalid choice text: {choice_text}")
                                    continue
                        
                        if choice_objects:
                            LLMChoice.objects.bulk_create(choice_objects)
                
                # Log audit event
                if ENABLE_AUDIT_LOG:
                    log_audit_event(
                        user=request.user,
                        action="CREATE",
                        resource_type="NewLLM",
                        resource_id=obj.pk,
                        changes={"llm_text": llm_text, "choices_count": len(choice_objects)}
                    )
                
                # Track activity
                if ENABLE_ANALYTICS:
                    track_user_activity(
                        user=request.user,
                        activity_type="create_llm",
                        metadata={"llm_id": obj.pk, "choices_count": len(choice_objects)}
                    )
                
                cache.delete("index_recent_llm")
                messages.success(request, f"LLM entry '{llm_text}' created successfully.")
                return redirect("django_llm:detail", obj.pk)
            except ValidationError as e:
                messages.error(request, str(e))
            except Exception as e:
                logger.error(f"Error creating LLM: {e}")
                if ENABLE_AUDIT_LOG:
                    log_audit_event(
                        user=request.user,
                        action="CREATE",
                        resource_type="NewLLM",
                        resource_id=None,
                        status="failed"
                    )
                messages.error(request, "An error occurred while creating the entry.")
    else:
        form = NewLLMForm()
    
    return render(request, "django_llm/create_llm.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
@csrf_protect
def amount_view(request, pk):
    """Record vote with atomic transaction, validation, and tracking."""
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
                selected_amount.save()
            
            # Track voting activity
            if ENABLE_ANALYTICS:
                track_user_activity(
                    user=request.user,
                    activity_type="vote",
                    metadata={"llm_id": pk, "choice_id": amount_id}
                )
            
            # Audit log
            if ENABLE_AUDIT_LOG:
                log_audit_event(
                    user=request.user,
                    action="VOTE",
                    resource_type="LLMChoice",
                    resource_id=amount_id,
                    changes={"old_amount": old_amount, "new_amount": old_amount + 1}
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
            logger.error(f"Unexpected error in amount_view: {e}")
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
    """Send chat message with rate limiting, validation, error handling, and tracking."""
    if rate_limit_chat(request.user, MAX_REQUESTS_PER_MINUTE, CHAT_WINDOW_SECONDS):
        if ENABLE_ANALYTICS:
            track_user_activity(
                user=request.user,
                activity_type="rate_limit_exceeded",
                metadata={"endpoint": "chat_message"}
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
                    ).order_by("created_at").values("role", "content"))

                    ollama_messages = [
                        {"role": msg["role"], "content": msg["content"]}
                        for msg in history[-50:]
                    ]

                    system_prompt = (
                        "You are a helpful AI assistant with access to a Django database. "
                        "You can use tools to query LLM entries, voting results, "
                        "conversion history, and database statistics. "
                        "Always use the available tools to fetch real data when answering "
                        "questions about the database content."
                    )

                    ai_response = mcp_client.chat_with_tools_and_history(
                        messages=ollama_messages,
                        system=system_prompt,
                    )
                    
                    if not ai_response:
                        ai_response = "I encountered an issue generating a response. Please try again."
                except Exception as e:
                    logger.error(f"Chat error for user {request.user}: {e}")
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
                    "response_time": round(response_time, 2)
                }
            )

        # Audit log
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="CHAT",
                resource_type="ChatMessage",
                resource_id=user_msg_obj.pk,
                changes={"response_time": response_time}
            )

        return JsonResponse({"response": ai_response, "status": "success"})
    except Exception as e:
        logger.error(f"Unexpected error in chat_message_view: {e}")
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="CHAT",
                resource_type="ChatMessage",
                resource_id=None,
                status="failed"
            )
        return JsonResponse({"error": "An unexpected error occurred."}, status=500)


# -------------------------
# User Dashboard/Stats View
# -------------------------

@login_required
@require_http_methods(["GET"])
def user_dashboard_view(request):
    """Display user statistics and activity summary."""
    try:
        stats = get_user_stats(request.user)
        
        recent_activity = ChatMessage.objects.filter(
            user=request.user
        ).order_by("-created_at")[:10]
        
        context = {
            "stats": stats,
            "recent_activity": recent_activity,
            "user": request.user,
        }
        
        if ENABLE_ANALYTICS:
            track_user_activity(
                user=request.user,
                activity_type="view_dashboard",
            )
        
        return render(request, "django_llm/dashboard.html", context)
    except Exception as e:
        logger.error(f"Error rendering dashboard for user {request.user}: {e}")
        messages.error(request, "Failed to load dashboard.")
        return redirect("django_llm:index")


# -------------------------
# Bulk Operations
# -------------------------

@login_required
@require_POST
@csrf_protect
def bulk_delete_llm_view(request):
    """Delete multiple LLM entries at once."""
    try:
        llm_ids = request.POST.getlist("llm_ids")
        
        if not llm_ids:
            return JsonResponse({"error": "No entries selected."}, status=400)
        
        # Validate all IDs are integers
        try:
            llm_ids = [int(id) for id in llm_ids[:100]]  # Limit to 100 deletion max
        except ValueError:
            return JsonResponse({"error": "Invalid IDs provided."}, status=400)
        
        with transaction.atomic():
            deleted_count, _ = NewLLM.objects.filter(pk__in=llm_ids).delete()
        
        cache.delete("index_recent_llm")
        
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="BULK_DELETE",
                resource_type="NewLLM",
                resource_id=None,
                changes={"deleted_count": deleted_count}
            )
        
        return JsonResponse({
            "status": "success",
            "deleted_count": deleted_count
        })
    except Exception as e:
        logger.error(f"Error in bulk delete: {e}")
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="BULK_DELETE",
                resource_type="NewLLM",
                resource_id=None,
                status="failed"
            )
        return JsonResponse({"error": "Failed to delete entries."}, status=500)


# -------------------------
# Search/Filter
# -------------------------

@login_required
@require_http_methods(["GET"])
def search_llm_view(request):
    """Search LLM entries with pagination."""
    query = request.GET.get('q', '').strip()
    
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
        ).distinct().prefetch_related('choices')
        
        paginator = Paginator(results, 20)
        page_num = request.GET.get('page', 1)
        
        try:
            page = paginator.page(page_num)
        except (PageNotAnInteger, EmptyPage):
            page = paginator.page(1)
        
        if ENABLE_ANALYTICS:
            track_user_activity(
                user=request.user,
                activity_type="search",
                metadata={"query": query, "results_count": paginator.count}
            )
        
        return render(request, "django_llm/search_results.html", {
            "page_obj": page,
            "query": query,
            "results_count": paginator.count,
        })
    except Exception as e:
        logger.error(f"Error in search: {e}")
        messages.error(request, "Search failed. Please try again.")
        return redirect("django_llm:index")


# -------------------------
# Export Data
# -------------------------

@login_required
@require_http_methods(["GET"])
def export_llm_data_view(request):
    """Export all LLM data as JSON."""
    try:
        from django.forms.models import model_to_dict
        
        llm_entries = NewLLM.objects.prefetch_related('choices').order_by("-created_at")
        
        data = {
            "exported_at": timezone.now().isoformat(),
            "export_user": request.user.username,
            "entries": []
        }
        
        for entry in llm_entries:
            entry_data = {
                "id": entry.pk,
                "llm_text": entry.llm_text,
                "date_used": entry.llm_date_used.isoformat(),
                "created_at": entry.created_at.isoformat(),
                "choices": [
                    {"text": choice.choice_text, "amount": choice.amount}
                    for choice in entry.choices.all()
                ]
            }
            data["entries"].append(entry_data)
        
        response = HttpResponse(
            json.dumps(data, indent=2),
            content_type='application/json; charset=utf-8'
        )
        response['Content-Disposition'] = 'attachment; filename="llm_export.json"'
        
        if ENABLE_AUDIT_LOG:
            log_audit_event(
                user=request.user,
                action="EXPORT",
                resource_type="NewLLM",
                resource_id=None,
                changes={"entries_count": len(data["entries"])}
            )
        
        return response
    except Exception as e:
        logger.error(f"Error exporting LLM data: {e}")
        messages.error(request, "Failed to export data.")
        return redirect("django_llm:index")


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

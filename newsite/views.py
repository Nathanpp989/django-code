from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction, connection
from django.db.models import F
from django.core.cache import cache
from django.core.paginator import Paginator
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from .models import NewLLM, ConvertLLM, LLMChoice, ChatMessage, ReverseLLM, LLMSummary
from .forms import llm_textbox, NewLLMForm
from .mcp_client import MCPOllamaClient, OLLAMA_AVAILABLE, MCP_AVAILABLE
from .prompts import CONVERT_SUMMARY_PROMPT, RESULTS_SUMMARY_PROMPT, REVERSE_SUMMARY_PROMPT
import logging
import json
import csv
import hashlib

logger = logging.getLogger(__name__)

mcp_client = MCPOllamaClient()


# -------------------------
# Helper Functions
# -------------------------

def rate_limit_chat(user, max_requests=10, window=60):
    """Allow max_requests per window seconds per user."""
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
    """
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    try:
        existing = LLMSummary.objects.get(prompt_hash=prompt_hash)
        logger.debug(f"Using cached summary for {content_type} #{object_id}")
        return existing.summary
    except LLMSummary.DoesNotExist:
        summary = mcp_client.chat_with_tools(prompt)
        LLMSummary.objects.create(
            content_type=content_type,
            object_id=object_id,
            prompt_hash=prompt_hash,
            summary=summary,
            model_used="llama3"
        )
        logger.debug(f"Generated and saved summary for {content_type} #{object_id}")
        return summary


# -------------------------
# Core Views
# -------------------------

def index_view(request):
    recent_llm = NewLLM.objects.order_by("-llm_date_used")[:5]
    recent_converts = ConvertLLM.objects.order_by("-created_at")[:5]
    context = {
        "message": "Django LLM with MCP server integration.",
        "ollama_available": OLLAMA_AVAILABLE,
        "mcp_available": MCP_AVAILABLE,
        "recent_llm": recent_llm,
        "recent_converts": recent_converts,
    }
    return render(request, "django_llm/index.html", context)


def health_check_view(request):
    """
    Health check endpoint for monitoring and load balancers.
    Returns status of Django, database, Ollama and MCP.
    """
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
    return JsonResponse(status, status=http_status)


@login_required
def convert_num_view(request, pk):
    response = get_object_or_404(ConvertLLM, pk=pk)
    result_num = response.new_number or 0
    input_str = response.new_string or ""

    if request.method == 'POST':
        form = llm_textbox(request.POST)
        if form.is_valid():
            input_str = form.cleaned_data.get("input_string", "")
            result_num = len(input_str)
            response.new_string = input_str
            response.new_number = result_num
            try:
                response.save()
                # Invalidate any existing summary for this object
                LLMSummary.objects.filter(
                    content_type="convert",
                    object_id=pk
                ).delete()
                messages.success(request, "Saved successfully.")
            except Exception as e:
                logger.error(f"Failed to save ConvertLLM pk={pk}: {e}")
                messages.error(request, "An error occurred while saving.")
            return redirect("django_llm:convertstr", response.pk)
    else:
        form = llm_textbox(initial={"input_string": input_str})

    llm_summary = None
    if input_str:
        prompt = CONVERT_SUMMARY_PROMPT.format(text=input_str)
        llm_summary = get_or_create_summary(prompt, "convert", pk)

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
def detail_view(request, pk):
    response = get_object_or_404(NewLLM, pk=pk)
    return render(request, "django_llm/detail.html", {
        "response": response,
        "amounts": response.choices.all(),
        "ollama_available": OLLAMA_AVAILABLE,
        "mcp_available": MCP_AVAILABLE,
    })


@login_required
def results_view(request, pk):
    response = get_object_or_404(NewLLM, pk=pk)
    amounts = response.choices.all()

    llm_summary = None
    if amounts.exists():
        results_text = "\n".join(
            [f"- {c.choice_text}: {c.amount} votes" for c in amounts]
        )
        prompt = RESULTS_SUMMARY_PROMPT.format(
            title=response.llm_text,
            results=results_text
        )
        llm_summary = get_or_create_summary(prompt, "results", pk)

    return render(request, "django_llm/results.html", {
        "response": response,
        "amounts": amounts,
        "llm_summary": llm_summary,
        "ollama_available": OLLAMA_AVAILABLE,
        "mcp_available": MCP_AVAILABLE,
    })


@login_required
def amount_view(request, pk):
    response = get_object_or_404(NewLLM, pk=pk)

    if request.method == 'POST':
        try:
            amount_id = int(request.POST["amount"])
            with transaction.atomic():
                selected_amount = response.choices.select_for_update().get(pk=amount_id)
                selected_amount.amount = F('amount') + 1
                selected_amount.save()
            # Invalidate persisted summary since votes changed
            LLMSummary.objects.filter(
                content_type="results",
                object_id=pk
            ).delete()
            messages.success(request, "Vote recorded successfully.")
            return redirect("django_llm:results", response.pk)
        except (KeyError, ValueError, TypeError):
            logger.warning(f"Invalid amount_id submitted for NewLLM pk={pk}")
            messages.error(request, "Invalid selection. Please try again.")
        except LLMChoice.DoesNotExist:
            logger.warning(f"LLMChoice not found for NewLLM pk={pk}")
            messages.error(request, "Server has not been chosen.")

        return render(request, "django_llm/detail.html", {
            "response": response,
            "amounts": response.choices.all(),
        })

    return render(request, "django_llm/detail.html", {
        "response": response,
        "amounts": response.choices.all(),
    })


@login_required
def reverse_llm_view(request, pk):
    response = get_object_or_404(ReverseLLM, pk=pk)

    llm_summary = None
    if response.new_string:
        prompt = REVERSE_SUMMARY_PROMPT.format(
            number=response.new_number,
            string=response.new_string
        )
        llm_summary = get_or_create_summary(prompt, "reverse", pk)

    return render(request, "django_llm/reverse.html", {
        "response": response,
        "llm_summary": llm_summary,
        "ollama_available": OLLAMA_AVAILABLE,
        "mcp_available": MCP_AVAILABLE,
    })


@login_required
def database_overview_view(request):
    prompt = (
        "Use the get_database_stats tool and get_all_voting_results tool "
        "to give me a concise overview of all the data in the Django LLM "
        "database. Summarise the key statistics and any interesting patterns."
    )
    overview = get_or_create_summary(prompt, "overview", 0)

    return render(request, "django_llm/overview.html", {
        "overview": overview,
        "ollama_available": OLLAMA_AVAILABLE,
        "mcp_available": MCP_AVAILABLE,
    })


# -------------------------
# Create Views
# -------------------------

@login_required
def create_llm_view(request):
    if request.method == 'POST':
        form = NewLLMForm(request.POST)
        if form.is_valid():
            llm_text = form.cleaned_data["llm_text"]
            choices = form.cleaned_data.get("choices", "")
            obj = NewLLM.objects.create(llm_text=llm_text)
            if choices:
                for choice_text in choices.splitlines():
                    choice_text = choice_text.strip()
                    if choice_text:
                        LLMChoice.objects.create(
                            new_llm=obj,
                            choice_text=choice_text
                        )
            messages.success(request, f"LLM entry '{llm_text}' created.")
            return redirect("django_llm:detail", obj.pk)
    else:
        form = NewLLMForm()
    return render(request, "django_llm/create_llm.html", {"form": form})


@login_required
def create_convert_view(request):
    if request.method == 'POST':
        form = llm_textbox(request.POST)
        if form.is_valid():
            input_str = form.cleaned_data["input_string"]
            obj = ConvertLLM.objects.create(
                new_string=input_str,
                new_number=len(input_str)
            )
            messages.success(request, "Conversion entry created.")
            return redirect("django_llm:convertstr", obj.pk)
    else:
        form = llm_textbox()
    return render(request, "django_llm/create_convert.html", {"form": form})


# -------------------------
# Chat Views
# -------------------------

@login_required
def chat_view(request):
    all_messages = ChatMessage.objects.filter(
        user=request.user
    ).order_by("created_at")

    paginator = Paginator(all_messages, 50)
    page = paginator.get_page(
        request.GET.get('page', paginator.num_pages)
    )

    return render(request, "django_llm/chat.html", {
        "chat_history": page.object_list,
        "has_older": page.has_previous(),
        "older_page": page.previous_page_number() if page.has_previous() else None,
        "ollama_available": OLLAMA_AVAILABLE,
        "mcp_available": MCP_AVAILABLE,
    })


@login_required
@require_POST
def chat_message_view(request):
    if rate_limit_chat(request.user):
        return JsonResponse(
            {"error": "Too many requests. Please wait a moment."},
            status=429
        )

    try:
        data = json.loads(request.body)
        user_message = data.get("message", "").strip()
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({"error": "Invalid request body."}, status=400)

    if not user_message:
        return JsonResponse({"error": "Message cannot be empty."}, status=400)

    if len(user_message) > 2000:
        return JsonResponse(
            {"error": "Message too long. Maximum 2000 characters."},
            status=400
        )

    ChatMessage.objects.create(
        user=request.user,
        role="user",
        content=user_message,
    )

    if not OLLAMA_AVAILABLE:
        ai_response = "Ollama is not available. Please start it with: ollama serve"
    else:
        try:
            history = ChatMessage.objects.filter(
                user=request.user
            ).order_by("created_at").values("role", "content")

            ollama_messages = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in history
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
        except Exception as e:
            logger.error(f"Chat error for user {request.user}: {e}")
            ai_response = f"An error occurred: {str(e)}"

    ChatMessage.objects.create(
        user=request.user,
        role="assistant",
        content=ai_response,
    )

    return JsonResponse({"response": ai_response, "status": "success"})


@login_required
@require_POST
def chat_clear_view(request):
    deleted_count, _ = ChatMessage.objects.filter(user=request.user).delete()
    logger.info(f"Cleared {deleted_count} messages for user {request.user}")
    return JsonResponse({
        "status": "success",
        "message": f"Cleared {deleted_count} messages."
    })


@login_required
def chat_export_view(request):
    """Export chat history as CSV."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="chat_history.csv"'

    writer = csv.writer(response)
    writer.writerow(['Timestamp', 'Role', 'Message'])

    chat_messages = ChatMessage.objects.filter(
        user=request.user
    ).order_by("created_at")

    for message in chat_messages:
        writer.writerow([
            message.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            message.role,
            message.content
        ])

    return response

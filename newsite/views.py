from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import F
from django.core.cache import cache
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import NewLLM, ConvertLLM, LLMChoice, ChatMessage
from .forms import llm_textbox
from .mcp_client import MCPOllamaClient, OLLAMA_AVAILABLE, MCP_AVAILABLE
from django.core.paginator import Paginator
import logging
import json

logger = logging.getLogger(__name__)

# Single shared client instance
mcp_client = MCPOllamaClient()


def index_view(request):
    context = {
        "message": "Django LLM with MCP server integration.",
        "ollama_available": OLLAMA_AVAILABLE,
        "mcp_available": MCP_AVAILABLE,
    }
    return render(request, "django_llm/index.html", context)

@login_required
def create_llm_view(request):
    if request.method == 'POST':
        llm_text = request.POST.get('llm_text', '').strip()
        if llm_text:
            obj = NewLLM.objects.create(llm_text=llm_text)
            messages.success(request, "LLM entry created.")
            return redirect("django_llm:detail", obj.pk)
        messages.error(request, "Text cannot be empty.")
    return render(request, "django_llm/create_llm.html")

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
            messages.success(request, "Created successfully.")
            return redirect("django_llm:convertstr", obj.pk)
        messages.error(request, "Text cannot be empty.")
    else:
        form = llm_textbox()
    return render(request, "django_llm/create_convert.html", {"form": form})

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
                messages.success(request, "Saved successfully.")
            except Exception as e:
                logger.error(f"Failed to save ConvertLLM pk={pk}: {e}")
                messages.error(request, "An error occurred while saving.")
            return redirect("django_llm:convertstr", response.pk)
    else:
        form = llm_textbox(initial={"input_string": input_str})

    # Generate MCP-powered summary on GET
    llm_summary = None
    if input_str:
        cache_key = f"convert_summary_{pk}_{hash(input_str)}"
        llm_summary = cache.get(cache_key)
        if not llm_summary:
            logger.debug(f"Generating MCP summary for ConvertLLM pk={pk}")
            llm_summary = mcp_client.summarise_convert(input_str)
            cache.set(cache_key, llm_summary, timeout=300)

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
        cache_key = f"results_summary_{pk}"
        llm_summary = cache.get(cache_key)
        if not llm_summary:
            logger.debug(f"Generating MCP voting summary for NewLLM pk={pk}")
            llm_summary = mcp_client.summarise_voting_results(pk, response.llm_text)
            cache.set(cache_key, llm_summary, timeout=300)

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
            cache.delete(f"results_summary_{pk}")
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
def database_overview_view(request):
    cache_key = "database_overview"
    overview = cache.get(cache_key)

    if not overview:
        logger.debug("Generating MCP database overview")
        overview = mcp_client.get_database_overview()
        cache.set(cache_key, overview, timeout=300)

    context = {
        "overview": overview,
        "ollama_available": OLLAMA_AVAILABLE,
        "mcp_available": MCP_AVAILABLE,
    }
    return render(request, "django_llm/overview.html", context)


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

    context = {
        "chat_history": page.object_list,
        "has_older": page.has_previous(),
        "older_page": page.previous_page_number() if page.has_previous() else None,
        "ollama_available": OLLAMA_AVAILABLE,
        "mcp_available": MCP_AVAILABLE,
    }
    return render(request, "django_llm/chat.html", context)


def rate_limit_chat(user, max_requests=10, window=60):
    cache_key = f"chat_rate_{user.pk}"
    requests = cache.get(cache_key, 0)
    if requests >= max_requests:
        return True
    cache.set(cache_key, requests + 1, timeout=window)
    return False

@login_required
@require_POST
def chat_message_view(request):
    """
    AJAX endpoint that receives a user message,
    sends it to Ollama via MCP, saves both messages,
    and returns the AI response as JSON.
    """
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

    # Save user message to database
    ChatMessage.objects.create(
        user=request.user,
        role="user",
        content=user_message,
    )

    # Get AI response via MCP
    if not OLLAMA_AVAILABLE:
        ai_response = "Ollama is not available. Please start it with: ollama serve"
    else:
        try:
            # Build conversation history for context
            history = ChatMessage.objects.filter(
                user=request.user
            ).order_by("created_at").values("role", "content")

            ollama_messages = [
                {"role": msg["role"], "content": msg["content"]}
                for msg in history
            ]

            # Add system prompt with MCP tool awareness
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

    # Save AI response to database
    ChatMessage.objects.create(
        user=request.user,
        role="assistant",
        content=ai_response,
    )

    return JsonResponse({
        "response": ai_response,
        "status": "success",
    })


@login_required
@require_POST
def chat_clear_view(request):
    """
    Clears the chat history for the current user.
    """
    deleted_count, _ = ChatMessage.objects.filter(user=request.user).delete()
    logger.info(f"Cleared {deleted_count} chat messages for user {request.user}")
    return JsonResponse({
        "status": "success",
        "message": f"Cleared {deleted_count} messages."
    })

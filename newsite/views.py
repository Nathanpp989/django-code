from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import F
from django.core.cache import cache
from .models import NewLLM, ConvertLLM, LLMChoice
from .forms import llm_textbox
from .mcp_client import MCPOllamaClient, OLLAMA_AVAILABLE, MCP_AVAILABLE
import logging

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

    # Generate MCP-powered voting summary
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
            # Invalidate cached summary since votes changed
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
    """
    New view that uses MCP to generate a natural language
    overview of the entire database.
    """
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
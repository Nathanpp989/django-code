from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import F
from .models import NewLLM, ConvertLLM, ReverseLLM, LLMChoice
from .forms import llm_textbox
import logging

logger = logging.getLogger(__name__)

try:
    import ollama
    OLLAMA_AVAILABLE = True
except Exception:
    ollama = None
    OLLAMA_AVAILABLE = False


def index_view(request):
    context = {
        "message": "This will eventually use a LLM and MCP server.",
        "ollama_available": OLLAMA_AVAILABLE,
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
                messages.error(request, "An error occurred while saving")
            return redirect("django_llm:convertstr", response.pk)
    else:
        form = llm_textbox(initial={"input_string": input_str})

    context = {
        "response": response,
        "form": form,
        "result_num": result_num,
        "input_str": input_str,
    }
    return render(request, "django_llm/convertstr.html", context)


@login_required
def detail_view(request, pk):
    response = get_object_or_404(NewLLM, pk=pk)
    return render(request, "django_llm/detail.html", {
        "response": response,
        "amounts": response.choices.all(),
    })


@login_required
def results_view(request, pk):
    response = get_object_or_404(NewLLM, pk=pk)
    return render(request, "django_llm/results.html", {
        "response": response,
        "amounts": response.choices.all(),
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
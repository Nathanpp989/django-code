from django.shortcuts import render, get_object_or_404, redirect
from .models import new_LLM, Convert_LLM, Reverse_LLM, LLM_choice
from .forms import llm_textbox
import html

try:
    import ollama
    OLLAMA_AVAILABLE = True
except Exception:
    ollama = None
    OLLAMA_AVAILABLE = False

def index_view(request):
    context = {"message": "This will eventually use a LLM and MCP server."}
    return render(request, "django_llm/index.html", context)

def convert_num_view(request, pk):
    response = get_object_or_404(Convert_LLM, pk=pk)
    result_num = response.new_number
    input_str = getattr(response, "new_string", '')

    if request.method == 'POST':
        form = llm_textbox(request.POST)
        if form.is_valid():
            input_str = form.cleaned_data.get("input_string", "")
            secure_str = html.escape(input_str)
            result_num = len(secure_str)
            response.new_string = input_str
            response.new_number = result_num
            response.save()
            return redirect("django_llm:convertstr", response.pk)
    else:
        form = llm_textbox(initial={"input_string": input_str})

    context = {
        "response": response,
        "form": form,
        "result_num": result_num,
        "input_str": input_str
    }
    return render(request, "django_llm/convertstr.html", context)

def detail_view(request, pk):
    response = get_object_or_404(new_LLM, pk=pk)
    return render(request, "django_llm/detail.html", {
        "response": response,
        "amounts": response.choices.all(),
        })

def results_view(request, pk):
    response = get_object_or_404(new_LLM, pk=pk)
    return render(request, "django_llm/results.html", {"response": response})

def amount_view(request, pk):
    response = get_object_or_404(new_LLM, pk=pk)
    if request.method == 'POST':
        try: 
            amount_id = request.POST["amount"]
            selected_amount = response.choices.get(pk=amount_id)
            with transaction.atomic():
                selected_amount = response.choices.select_for_update().get(pk=amount_id)
                selected_amount.amount = F("amount") + 1
                selected_amount.save()
            return redirect("django_llm:results", response.pk)
        except (KeyError, LLM_choice.DoesNotExist):
            return render(
                request,
                "django_llm/detail.html",
                {
                    "response": response,
                    "error_message": "Server has not been chosen",
                    "amounts": response.choices.all(),
                }
            )
    # If there is no post data, then just return the detail page for the item
    return render(request, "django_llm/detail.html", {
        "response": response,
        "amounts": response.choices.all(),
    })

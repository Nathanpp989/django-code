from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, HttpResponseRedirect
from django.template import loader
from django.urls import reverse
from .models import new_LLM, Convert_LLM, Reverse_LLM, LLM_choice
from .forms import llm_textbox

import ollama

# Create your views here.
def get_llama_response(new_prompt):
    new_response = ollama.generate(model='llama3.2', prompt=new_prompt)
    return new_response['response']

def index_view(request):
    context = {"message": "This will eventually use a LLM and MCP server."}
    return render(request, "django_llm/index.html", context)

def convert_num_view(request, pk):
    response = get_object_or_404(Convert_LLM, pk=pk)
    result_num = getattr(response, "new_number", '')
    input_str = getattr(response, "new_string", '')

    if request.method == 'POST':
        form = llm_textbox(request.POST)
        if form.is_valid():
            input_str = form.cleaned_data.get("input_string", "")
            result_num = len(input_str)
            response.new_string = input_str
            response.new_number = result_num
            response.save()
            return HttpResponseRedirect(reverse("django_llm:convertstr", args=(response.pk,)))
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
    #response = get_object_or_404(new_LLM, pk=pk)
    return HttpResponse("You're looking at the server %s." % pk)

def results_view(request, pk):
    response_text = f"You're looking at the results of server {pk}."
    return render(request, "django_llm/index.html", {"response": response_text})

def amount_view(request, pk):
    response = get_object_or_404(new_LLM, pk=pk)
    if request.method == 'POST':
        try: 
            amount_id = request.POST["amount"]
            selected_amount = response.choices.get(pk=amount_id)
        except (KeyError, LLM_choice.DoesNotExist):
            return render(
                request,
                "django_llm/index.html",
            {
                "response": response,
                "error_message": "Server has not been chosen",
                "amounts": response.choices.all(),
            },
        )
    else:
        selected_amount.amount += 1
        selected_amount.save()
        return HttpResponseRedirect(reverse("django_llm:results", args=(response.id,)))
    # If there is no post data, then just return the page with the form:
    return render(request, "django_llm/index.html", {"response": response})

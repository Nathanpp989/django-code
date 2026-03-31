from django import forms


class llm_textbox(forms.Form):
    input_string = forms.CharField(
        label="Input String",
        max_length=256,
        min_length=1,
        widget=forms.TextInput(attrs={
            "placeholder": "Enter text here...",
            "class": "form-input",
        })
    )


class NewLLMForm(forms.Form):
    llm_text = forms.CharField(
        label="LLM Entry Text",
        max_length=200,
        min_length=1,
        widget=forms.TextInput(attrs={
            "placeholder": "Enter LLM entry name...",
            "class": "form-input",
        })
    )
    choices = forms.CharField(
        label="Choices (one per line)",
        required=False,
        widget=forms.Textarea(attrs={
            "placeholder": "Enter each choice on a new line...",
            "rows": 4,
            "class": "form-input",
        }),
        help_text="Optional. Add one choice per line."
    )

from django import forms

class llm_textbox(forms.Form):
    input_string = forms.CharField(
        label='Input string',
        max_length=256,
        widget=forms.Textarea(attrs={'rows': 3, 'cols': 40}),
        required=True,
    )
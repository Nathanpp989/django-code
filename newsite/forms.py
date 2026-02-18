from django import forms

class llm_textbox(forms.Form):
    name = forms.CharField(
        label='Input_string',
        max_length=256,
        widget=forms.Textarea(attrs={'rows': 3, 'cols': 20})
        )
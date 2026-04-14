from django import forms
from django.core.exceptions import ValidationError


class llm_textbox(forms.Form):
    input_string = forms.CharField(
        label="Input String",
        max_length=1000,
        min_length=1,
        widget=forms.TextInput(attrs={
            "placeholder": "Enter text here...",
            "class": "form-input",
            "autocomplete": "off",
        }),
        error_messages={
            "required": "Input string is required.",
            "max_length": "Input cannot exceed 1000 characters.",
            "min_length": "Input must be at least 1 character.",
        }
    )

    def clean_input_string(self):
        """Sanitize input string."""
        value = self.cleaned_data.get("input_string", "").strip()
        if not value:
            raise ValidationError("Input cannot be empty.")
        
        # Check for suspicious patterns
        if any(char in value for char in ['<', '>', '{', '}', '&']):
            raise ValidationError("Input contains invalid characters.")
        
        return value


class NewLLMForm(forms.Form):
    llm_text = forms.CharField(
        label="LLM Entry Text",
        max_length=200,
        min_length=1,
        widget=forms.TextInput(attrs={
            "placeholder": "Enter LLM entry name...",
            "class": "form-input",
            "autocomplete": "off",
        }),
        error_messages={
            "required": "LLM text is required.",
            "max_length": "LLM text cannot exceed 200 characters.",
            "min_length": "LLM text must be at least 1 character.",
        }
    )
    choices = forms.CharField(
        label="Choices (one per line)",
        required=False,
        widget=forms.Textarea(attrs={
            "placeholder": "Enter each choice on a new line...",
            "rows": 4,
            "class": "form-input",
            "autocomplete": "off",
        }),
        help_text="Optional. Add one choice per line. Max 20 choices, 200 chars each.",
        max_length=5000,
    )

    def clean_llm_text(self):
        """Sanitize LLM text."""
        value = self.cleaned_data.get("llm_text", "").strip()
        if not value:
            raise ValidationError("LLM text cannot be empty.")
        
        if any(char in value for char in ['<', '>', '{', '}', '&']):
            raise ValidationError("LLM text contains invalid characters.")
        
        return value

    def clean_choices(self):
        """Validate and sanitize choices."""
        value = self.cleaned_data.get("choices", "").strip()
        if not value:
            return ""
        
        lines = [line.strip() for line in value.split('\n') if line.strip()]
        
        if len(lines) > 20:
            raise ValidationError("Maximum 20 choices allowed.")
        
        for choice in lines:
            if len(choice) > 200:
                raise ValidationError(f"Choice too long: {choice[:50]}...")
            if any(char in choice for char in ['<', '>', '{', '}', '&']):
                raise ValidationError(f"Choice contains invalid characters: {choice}")
        
        return "\n".join(lines)

    def clean(self):
        """Cross-field validation."""
        cleaned_data = super().clean()
        llm_text = cleaned_data.get("llm_text", "")
        choices = cleaned_data.get("choices", "")
        
        if llm_text and not choices:
            self.add_error("choices", "Please add at least one choice.")
        
        return cleaned_data

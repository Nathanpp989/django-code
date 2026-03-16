from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.core.validators import MinLengthValidator, MinValueValidator
from django.core.exceptions import ValidationError
from datetime import timedelta


class NewLLM(models.Model):
    llm_text = models.CharField(max_length=200)
    llm_date_used = models.DateTimeField("Date used:", default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.llm_text

    def __repr__(self):
        return f"<NewLLM pk={self.pk} text={self.llm_text!r}>"

    def was_published_recently(self):
        now = timezone.now()
        return now - timedelta(days=1) <= self.llm_date_used <= now

    class Meta:
        ordering = ["-llm_date_used"]
        verbose_name = "LLM Entry"
        verbose_name_plural = "LLM Entries"


class LLMChoice(models.Model):
    new_llm = models.ForeignKey(
        NewLLM,
        on_delete=models.CASCADE,
        related_name='choices'
    )
    choice_text = models.CharField(max_length=200)
    amount = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.choice_text

    def __repr__(self):
        return f"<LLMChoice pk={self.pk} text={self.choice_text!r}>"

    class Meta:
        verbose_name = "LLM Choice"
        verbose_name_plural = "LLM Choices"


class ConvertLLM(models.Model):
    new_llm = models.ForeignKey(
        NewLLM,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='conversions'
    )
    new_string = models.CharField(
        max_length=256,
        default="",
        validators=[MinLengthValidator(1)]
    )
    new_number = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(0)]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.new_string or f"ConvertLLM #{self.pk}"

    def __repr__(self):
        return f"<ConvertLLM pk={self.pk} string={self.new_string!r}>"

    def clean(self):
        if self.new_number is not None and self.new_string:
            if self.new_number != len(self.new_string):
                raise ValidationError(
                    "new_number must match the length of new_string"
                )

    class Meta:
        verbose_name = "Convert LLM"
        verbose_name_plural = "Convert LLMs"


class ReverseLLM(models.Model):
    new_llm = models.ForeignKey(
        NewLLM,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reversals'
    )
    new_number = models.IntegerField(null=True, blank=True)
    new_string = models.CharField(max_length=256, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.new_string or f"ReverseLLM #{self.pk}"

    def __repr__(self):
        return f"<ReverseLLM pk={self.pk} string={self.new_string!r}>"

    class Meta:
        verbose_name = "Reverse LLM"
        verbose_name_plural = "Reverse LLMs"


class ChatMessage(models.Model):
    """
    Stores chat history for each user.
    Each message has a role (user or assistant) and content.
    """
    ROLE_CHOICES = [
        ("user", "User"),
        ("assistant", "Assistant"),
        ("system", "System"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="chat_messages"
    )
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default="user"
    )
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} [{self.role}]: {self.content[:50]}"

    def __repr__(self):
        return f"<ChatMessage pk={self.pk} user={self.user.username!r} role={self.role!r}>"

    class Meta:
        ordering = ["created_at"]
        verbose_name = "Chat Message"
        verbose_name_plural = "Chat Messages"

from django.db import models
from django.utils import timezone
from datetime import timedelta

# Create your models here.
class new_LLM(models.Model):
    llm_text = models.CharField(max_length=200)
    llm_type = models.DateTimeField("Model_date_used:")
    def __str__(self):
        return self.llm_text
    def was_published_recently(self):
        return self.llm_type >= timezone.now() - timedelta(days=1)

class LLM_choice(models.Model):
    new_llm = models.ForeignKey(new_LLM, on_delete=models.CASCADE, related_name='choices')
    choice_text = models.CharField(max_length=200)
    amount = models.IntegerField(default=0)
    def __str__(self):
        return self.choice_text
    
#These models will be used to test out the capability of the LLM with django
class Convert_LLM(models.Model):
    new_string = models.CharField(max_length=256)
    new_number = models.IntegerField(null=True, blank=True)
    def __str__(self):
        return self.new_string
    
class Reverse_LLM(models.Model):
    new_number = models.IntegerField()
    new_string= models.CharField(max_length=256, null=True, blank=True)
    def __str__(self):
        return self.new_string

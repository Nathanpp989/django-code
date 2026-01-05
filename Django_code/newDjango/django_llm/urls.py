from django.urls import path
from . import views

app_name = "django_llm"
urlpatterns = [
    path("", views.index_view, name="index"),
    path("<int:pk>/", views.detail_view, name="detail"),
    path("<int:pk>/results/", views.results_view, name="results"),
    path("<int:pk>/amount/", views.amount_view, name="amount"),
    path("<int:pk>/convertstr/", views.convert_num_view, name="convertstr")
]
from django.urls import path
from . import views

app_name = "django_llm"

urlpatterns = [
    # Home
    path("", views.index_view, name="index"),

    # Convert string view
    path("convert/<int:pk>/", views.convert_num_view, name="convertstr"),

    # LLM entry detail and voting
    path("detail/<int:pk>/", views.detail_view, name="detail"),
    path("amount/<int:pk>/", views.amount_view, name="amount"),
    path("results/<int:pk>/", views.results_view, name="results"),

    # MCP database overview
    path("overview/", views.database_overview_view, name="overview"),
]

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
    path("create/", views.create_llm_view, name="create_llm"),
    path("convert/create/", views.create_convert_view, name="create_convert"),

    # MCP database overview
    path("overview/", views.database_overview_view, name="overview"),

    # Chat interface
    path("chat/", views.chat_view, name="chat"),
    path("chat/message/", views.chat_message_view, name="chat_message"),
    path("chat/clear/", views.chat_clear_view, name="chat_clear"),
]

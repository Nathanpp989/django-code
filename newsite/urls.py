from django.urls import path
from . import views
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views

app_name = "django_llm"

urlpatterns = [
    # Home
    path("", views.index_view, name="index"),

    # Convert string views
    path("convert/create/", views.create_convert_view, name="create_convert"),
    path("convert/<int:pk>/", views.convert_num_view, name="convertstr"),

    # LLM entry views
    path("llm/create/", views.create_llm_view, name="create_llm"),
    path("detail/<int:pk>/", views.detail_view, name="detail"),
    path("amount/<int:pk>/", views.amount_view, name="amount"),
    path("results/<int:pk>/", views.results_view, name="results"),

    # MCP database overview
    path("overview/", views.database_overview_view, name="overview"),

    # Chat interface
    path("chat/", views.chat_view, name="chat"),
    path("chat/message/", views.chat_message_view, name="chat_message"),
    path("chat/clear/", views.chat_clear_view, name="chat_clear"),

    # admin views
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("django_llm.urls")),
]

from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django_llm.views import register_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/register/", register_view, name="register"),
    path("", include("django_llm.urls")),
]

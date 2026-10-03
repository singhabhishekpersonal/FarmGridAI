from django.urls import path

from apps.accounts.views import (
    ConsentsView,
    LanguagePreferenceView,
    LoginView,
    LogoutView,
    ProfileView,
    RegisterView,
    TokenRefreshView,
)

urlpatterns = [
    path("register/", RegisterView.as_view(), name="auth-register"),
    path("login/", LoginView.as_view(), name="auth-login"),
    path("login/refresh/", TokenRefreshView.as_view(), name="auth-refresh"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("consents/", ConsentsView.as_view(), name="consents"),
    path("language/", LanguagePreferenceView.as_view(), name="language"),
]
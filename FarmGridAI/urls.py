"""Root URL configuration for FarmGrid AI."""
from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

urlpatterns = [
    # Farmer-facing pages. Mounted last so that the API prefixes below win any
    # overlap, and so a stray /farms/<uuid>/ page URL cannot shadow the API.
    path("", include("apps.web.urls")),

    path("admin/", admin.site.urls),
    path("api/v1/", include("apps.api.urls")),
    path("i18n/", include("django.conf.urls.i18n")),
]

if settings.DEBUG:
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# OpenAPI documentation (only in non-hostile environments).
urlpatterns += [
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]
"""Page routes for the farmer-facing site.

Namespaced as ``web:`` to keep them clearly separate from the versioned API
(``/api/v1/...``). The JavaScript in ``static/js`` hard-codes these paths, so
the list below is the contract - keep it in step with that code.
"""
from django.urls import path

from apps.web import views

app_name = "web"

urlpatterns = [
    # Public
    path("", views.home, name="home"),
    path("login/", views.login, name="login"),
    path("logout/", views.logout, name="logout"),
    path("register/", views.register, name="register"),
    # Full page reload: the whole page copy is server-rendered, so switching
    # language has to re-render it rather than patch it client-side.
    path("lang/<str:code>/", views.set_language, name="set_language"),

    # Farmer area
    path("dashboard/", views.dashboard, name="dashboard"),
    path("profile/", views.profile, name="profile"),
    path("chat/", views.chat, name="chat"),

    # Farms
    path("farms/new/", views.farm_create, name="farm_create"),
    path("farms/<uuid:farm_id>/", views.farm_detail, name="farm_detail"),
    path("farms/<uuid:farm_id>/parcels/new/", views.land_parcel_form, name="land_parcel_form"),
    path("farms/<uuid:farm_id>/crops/", views.farm_crops, name="farm_crops"),

    # Expenses
    path("farms/<uuid:farm_id>/expenses/", views.expense_dashboard, name="expense_dashboard"),
    path("farms/<uuid:farm_id>/expenses/add/", views.expense_entry, name="expense_entry"),

    # Equipment
    path("farms/<uuid:farm_id>/equipment/", views.equipment_list, name="equipment_list"),
    path("farms/<uuid:farm_id>/equipment/new/", views.equipment_upload, name="equipment_create"),
    path("farms/<uuid:farm_id>/equipment/<uuid:equipment_id>/", views.equipment_detail, name="equipment_detail"),
    path(
        "farms/<uuid:farm_id>/equipment/<uuid:equipment_id>/upload/",
        views.equipment_upload,
        name="equipment_upload",
    ),

    # Analytics
    path("farms/<uuid:farm_id>/recommendations/", views.recommendations, name="recommendations"),
    path("farms/<uuid:farm_id>/subsidies/", views.subsidy_recommendations, name="subsidy_recommendations"),
    path("farms/<uuid:farm_id>/energy/solar/", views.solar_comparison, name="solar_comparison"),
    path("farms/<uuid:farm_id>/finance/", views.machinery_decision, name="machinery_decision"),

    # Staff area (gated on is_staff; the API behind it is gated independently)
    path("staff/data-ingestion/", views.staff_data_ingestion, name="staff_data_ingestion"),
]

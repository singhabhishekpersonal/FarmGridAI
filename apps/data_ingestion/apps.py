from django.apps import AppConfig


class DataIngestionConfig(AppConfig):
    name = "apps.data_ingestion"
    label = "data_ingestion"
    verbose_name = "Data ingestion (web compliance & dataset enrichment)"
    default_auto_field = "django.db.models.BigAutoField"
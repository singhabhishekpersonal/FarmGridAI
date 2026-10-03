"""Celery application configuration.

The application keeps working synchronously when ``CELERY_TASK_ALWAYS_EAGER``
is enabled (the default in development) so Redis/Celery is optional locally.
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "FarmGridAI.settings.development")

app = Celery("FarmGridAI")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
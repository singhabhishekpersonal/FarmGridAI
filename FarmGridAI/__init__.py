"""FarmGrid AI package.

Celery is optional locally: tasks run eager when ``CELERY_TASK_ALWAYS_EAGER``
is enabled. Importing settings must never require Celery, so we guard it.
"""
try:
    from FarmGridAI.celery import app as celery_app

    __all__ = ("celery_app",)
except ModuleNotFoundError:
    celery_app = None  # Celery not installed: use eager/local execution
    __all__ = ("celery_app",)
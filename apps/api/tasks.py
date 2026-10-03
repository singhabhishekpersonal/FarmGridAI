"""Background tasks.

Everything here either mirrors a synchronous service or batches work across
farms. Tasks must be idempotent and cheap; heavy ML training stays manual.
"""
import logging

try:  # Celery is optional; always-eager mode is used in development.
    from celery import shared_task
except ModuleNotFoundError:  # pragma: no cover - imports are guarded in dev
    def shared_task(func):
        def _run(*args, **kwargs):
            return func(*args, **kwargs)

        _run.delay = _run
        return _run

logger = logging.getLogger("FarmGrid")


@shared_task
def compute_farm_expense_summary(farm_id, year=None):
    """(Re)build the annual expense summary for a farm."""
    from apps.expenses.services import ExpenseAggregationService

    service = ExpenseAggregationService(farm_id, year=year)
    return service.summarize()


@shared_task
def run_expense_analysis(farm_id, user_id=None):
    from apps.expenses.models import FarmExpenseSummary
    from apps.farms.models import Farm
    from apps.ml_engine.services.expense_analysis import ExpenseAnalysisService

    farm = Farm.objects.filter(pk=farm_id).first()
    if farm is None:
        return {"error": "farm not found"}
    user = None
    if user_id:
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(pk=user_id).first()
    return ExpenseAnalysisService(farm).run_analysis(user=user)


@shared_task
def run_energy_analysis(farm_id, persist=True):
    from apps.energy.services import EnergyAnalysisService
    from apps.farms.models import Farm

    farm = Farm.objects.filter(pk=farm_id).first()
    if farm is None:
        return {"error": "farm not found"}
    return EnergyAnalysisService(farm).run_analysis(persist=persist)


@shared_task
def build_farm_recommendations(farm_id, user_id=None):
    from apps.farms.models import Farm
    from apps.recommendations.services import RecommendationEngine

    farm = Farm.objects.filter(pk=farm_id).first()
    if farm is None:
        return {"error": "farm not found"}
    user = None
    if user_id:
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(pk=user_id).first()
    return RecommendationEngine(farm).run(persist=True, user=user)


@shared_task
def ingest_expense_document(document_id):
    """Heuristic OCR/parse for an uploaded bill (provider pluggable)."""
    from apps.expenses.models import ExpenseDocument

    document = ExpenseDocument.objects.filter(pk=document_id).first()
    if document is None or not document.document:
        return {"error": "document missing"}
    try:
        document.document.open("rb")
        content = document.document.read()
        document.document.close()
    except Exception as exc:  # pragma: no cover
        return {"error": str(exc)}
    # Heuristic: count lines/amounts - never claims accurate extraction.
    text = content.decode("utf-8", errors="ignore")
    return {"lines": len(text.splitlines()), "contains_inr": "Rs" in text or "INR" in text, "needs_user_confirmation": True}
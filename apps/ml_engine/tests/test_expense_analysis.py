import pytest

from apps.expenses.models import FarmExpense, InputExpense
from apps.farms.models import FarmService
from apps.ml_engine.services.expense_analysis import ExpenseAnalysisService


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="green", password="Str0ng!", phone="9876511111")


@pytest.fixture
def farm(user, db):
    return FarmService.create_farm(user, "Green Farm", area=5, unit="acre", state="Uttar Pradesh")


def test_empty_farm_returns_graceful_output(farm):
    out = ExpenseAnalysisService(farm).run_analysis()
    assert out["anomalies"] == []
    assert "No expense records yet." in out["note"]


def test_forecast_with_no_data(farm):
    out = ExpenseAnalysisService(farm).forecast()
    assert out["increasing_trend"] is None
    assert "Not enough data" in out["message"]


def test_anomaly_flag_via_iqr_fallback(farm):
    for month in range(1, 7):
        FarmExpense.objects.create(farm=farm, amount=5000, occurred_on=f"2025-{month:02d}-05")
    FarmExpense.objects.create(farm=farm, amount=50000, occurred_on="2025-07-05")
    out = ExpenseAnalysisService(farm).run_analysis()
    assert out["rows_analysed"] == 7
    flagged = [a for a in out["anomalies"] if a["period"] == "2025-07"]
    assert flagged
    assert flagged[0]["needs_user_confirmation"] is True
    assert "iqr_baseline" in out["models_used"]


def test_ml_anomaly_path_when_sklearn_present(farm):
    import sklearn  # noqa: F401

    from apps.ml_engine.services.expense_analysis import HAVE_SKLEARN

    if not HAVE_SKLEARN:
        pytest.skip("scikit-learn not available")
    for month in range(1, 13):
        FarmExpense.objects.create(farm=farm, amount=4500, occurred_on=f"2025-{month:02d}-05")
    FarmExpense.objects.create(farm=farm, amount=60000, occurred_on="2025-12-10")
    out = ExpenseAnalysisService(farm).run_analysis()
    assert "isolation_forest" in out["models_used"]
    assert any(a["period"] == "2025-12" for a in out["anomalies"])


def test_typed_expenses_included(farm):
    from apps.expenses.models import ExpenseCategory

    cat = ExpenseCategory.objects.create(name="Fertilizer")
    InputExpense.objects.create(farm=farm, category=cat, amount=8000, occurred_on="2025-03-15")
    rows_private = ExpenseAnalysisService(farm)._rows()
    assert any(r["category"] == "fertilizer" and r["amount"] == 8000 for r in rows_private)


def test_input_expense_other_maps_to_other_bucket(farm):
    from apps.expenses.models import ExpenseCategory

    cat = ExpenseCategory.objects.create(name="Other Inputs")
    InputExpense.objects.create(farm=farm, category=cat, input_type="other", amount=3000, occurred_on="2025-04-15")
    rows = ExpenseAnalysisService(farm)._rows()
    assert any(r["category"] == "other" and r["amount"] == 3000 for r in rows)
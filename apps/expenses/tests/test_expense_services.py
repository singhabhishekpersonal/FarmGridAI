"""Regression tests for expense aggregation fixes.

- Generic ``FarmExpense`` rows were previously never bucketed (they leaked
  an ``expense_type`` key that ``summarize`` mapped to itself), so generic
  farm expenses of a known type were double/mis counted. They now bucket into
  the canonical CATEGORY_MAP label or fall back to "other".
- ``expand_typed_expenses`` now includes equipment maintenance-record costs
  so repair spend is not lost from analytics.
"""

import pytest

from apps.equipment.models import EquipmentCategory, EquipmentMaintenanceRecord, FarmerEquipment
from apps.expenses.models import FarmExpense
from apps.expenses.services import ExpenseAggregationService, expand_typed_expenses
from apps.farms.models import FarmService


@pytest.fixture
def user(db):
    from django.contrib.auth import get_user_model

    return get_user_model().objects.create_user(username="spender", password="Str0ng!", phone="9876500401")


@pytest.fixture
def farm(user, db):
    return FarmService.create_farm(user, "Spend Farm", area=5, unit="acre", state="Uttar Pradesh")


def test_generic_expense_bucketed_by_expense_type(farm):
    FarmExpense.objects.create(farm=farm, amount=12000, occurred_on="2025-05-10", expense_type="seed")
    FarmExpense.objects.create(farm=farm, amount=3000, occurred_on="2025-06-10", expense_type="unmapped_type")
    summary = ExpenseAggregationService(farm.id, year=2025).summarize()
    assert summary["by_category"]["seed"]["sum"] == 12000
    assert summary["by_category"]["other"]["sum"] == 3000
    assert summary["by_category"]["seed"]["count"] == 1


def test_expand_typed_expenses_includes_maintenance_costs(farm):
    from apps.expenses.models import ElectricityBill

    ElectricityBill.objects.create(farm=farm, amount=15000, occurred_on="2025-04-01")
    category = EquipmentCategory.objects.create(code="tractor", name="Tractor")
    equipment = FarmerEquipment.objects.create(farm=farm, category=category, is_owned=True)
    EquipmentMaintenanceRecord.objects.create(
        equipment=equipment, occurred_on="2025-07-20", kind="repair", cost=8500
    )
    flat = expand_typed_expenses(farm.id)
    kinds = [row["kind"] for row in flat]
    assert "electricitybill" in kinds
    assert "maintenance_repair" in kinds
    assert any(row["amount"] == 8500 and row["kind"] == "maintenance_repair" for row in flat)
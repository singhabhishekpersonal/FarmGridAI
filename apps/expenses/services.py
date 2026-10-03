"""Expense aggregation service.

Combines typed expense records into a yearly summary.
"""
from django.db import transaction
from django.utils import timezone

from apps.expenses.models import (
    ElectricityBill,
    ExpenseDocument,
    FarmExpense,
    FarmExpenseSummary,
    FuelExpense,
    InputExpense,
    LabourExpense,
    RentalExpense,
    TransportExpense,
)

CATEGORY_MAP = {
    "electricity": "grid electricity",
    "fuel": "fuel",
    "seed": "seed",
    "fertilizer": "fertilizer",
    "pesticide": "pesticide",
    "labour": "labour",
    "transport": "transport",
    "rental": "machinery rental",
    "repair": "repair",
    "other": "other",
}


class ExpenseAggregationService:
    """Aggregate typed expenses into the canonical 'seed/fertilizer/...' buckets."""

    def __init__(self, farm_id, year=None):
        self.farm_id = farm_id
        self.year = year

    def _rows(self):
        year = self.year
        rows = {}
        generic = FarmExpense.objects.filter(farm_id=self.farm_id)
        if year:
            generic = generic.filter(occurred_on__year=year)
        for item in generic:
            key = item.expense_type if item.expense_type in CATEGORY_MAP else "other"
            rows.setdefault(key, []).append((item.occurred_on, float(item.amount)))

        if year:
            bills = ElectricityBill.objects.filter(farm_id=self.farm_id, occurred_on__year=year)
        else:
            bills = ElectricityBill.objects.filter(farm_id=self.farm_id)
        for item in bills:
            rows.setdefault("electricity", []).append((item.occurred_on, float(item.amount)))

        if year:
            fuels = FuelExpense.objects.filter(farm_id=self.farm_id, occurred_on__year=year)
        else:
            fuels = FuelExpense.objects.filter(farm_id=self.farm_id)
        for item in fuels:
            rows.setdefault("fuel", []).append((item.occurred_on, float(item.amount)))

        if year:
            inputs = InputExpense.objects.filter(farm_id=self.farm_id, occurred_on__year=year)
        else:
            inputs = InputExpense.objects.filter(farm_id=self.farm_id)
        for item in inputs:
            rows.setdefault(item.input_type, []).append((item.occurred_on, float(item.amount)))

        if year:
            labour = LabourExpense.objects.filter(farm_id=self.farm_id, occurred_on__year=year)
        else:
            labour = LabourExpense.objects.filter(farm_id=self.farm_id)
        for item in labour:
            rows.setdefault("labour", []).append((item.occurred_on, float(item.amount)))

        if year:
            transport = TransportExpense.objects.filter(farm_id=self.farm_id, occurred_on__year=year)
        else:
            transport = TransportExpense.objects.filter(farm_id=self.farm_id)
        for item in transport:
            rows.setdefault("transport", []).append((item.occurred_on, float(item.amount)))

        if year:
            rental = RentalExpense.objects.filter(farm_id=self.farm_id, occurred_on__year=year)
        else:
            rental = RentalExpense.objects.filter(farm_id=self.farm_id)
        for item in rental:
            rows.setdefault("rental", []).append((item.occurred_on, float(item.amount)))

        return rows

    def summarize(self):
        rows = self._rows()
        by_category = {}
        total = 0.0
        category_labels = {}
        for cat_key, entries in rows.items():
            values = [v for _d, v in entries]
            by_category[CATEGORY_MAP.get(cat_key, cat_key)] = {
                "count": len(values),
                "minimum": round(min(values), 2),
                "maximum": round(max(values), 2),
                "sum": round(sum(values), 2),
            }
            total += sum(values)
            category_labels[CATEGORY_MAP.get(cat_key, cat_key)] = cat_key

        # Repair expenses live in equipment maintenance records.
        # FarmExpense rows of type 'repair' are already in 'generic'.

        completeness = min(1.0, 0.4 + sum(1 for c in by_category if c != "other"))
        summary = {
            "farm_id": str(self.farm_id),
            "year": self.year or "all-years",
            "total": round(total, 2),
            "by_category": by_category,
            "most_expensive": sorted(by_category.items(), key=lambda kv: kv[1]["sum"], reverse=True)[0][0]
            if by_category
            else None,
            "cost_per_hectare": None,
            "estimate_type": "range",
            "confidence": "medium" if by_category else "low",
            "assumptions": [f"Expenses aggregated from typed expense records."],
            "limitations": ["Only expenses entered in the system are included; cash expenses may be missing.", "Estimates require farmer confirmation."],
            "data_completeness": completeness,
            "requires_farmer_confirmation": True,
            "requires_official_verification": False,
        }
        if by_category:
            from apps.farms.models import Farm

            farm = Farm.objects.filter(pk=self.farm_id).first()
            ha = float(farm.total_hectares) if farm and farm.total_hectares else 0
            summary["cost_per_hectare"] = round(total / ha, 2) if ha else None
        return summary

    @transaction.atomic
    def persist_summary(self, user=None):
        result = self.summarize()
        if not self.year:
            return result
        summary, _ = FarmExpenseSummary.objects.update_or_create(
            farm_id=self.farm_id,
            year=self.year,
            defaults={
                "total_min": result["total"],
                "total_max": result["total"],
                "total_expected": result["total"],
                "by_category": result["by_category"],
                "data_completeness": result["data_completeness"],
                "confidence": result["confidence"],
                "assumptions_json": result["assumptions"],
                "limitations_json": result["limitations"],
            },
        )
        if user:
            summary.updated_by = user
            summary.save(update_fields=["updated_at", "updated_by"])
        return result


def expand_typed_expenses(farm_id):
    """Return all + repair expenses in a normalized flat list (for analysis)."""
    flat = []
    for model in [FarmExpense, ElectricityBill, FuelExpense, InputExpense, LabourExpense, TransportExpense, RentalExpense]:
        for obj in model.objects.filter(farm_id=farm_id):
            kind = model.__name__.lower()
            if model is FarmExpense and obj.expense_type:
                kind = obj.expense_type
            flat.append({"kind": kind, "date": obj.occurred_on, "amount": float(obj.amount)})
    from apps.equipment.models import EquipmentMaintenanceRecord, FarmerEquipment

    equipment_ids = FarmerEquipment.objects.filter(farm_id=farm_id).values_list("pk", flat=True)
    for m in EquipmentMaintenanceRecord.objects.filter(equipment_id__in=equipment_ids):
        flat.append({"kind": f"maintenance_{m.kind}", "date": m.occurred_on, "amount": float(m.cost)})
    flat.sort(key=lambda r: r["date"])
    return flat
"""Expense analysis using anomaly detection and baseline forecasting.

Strategy:
- Anomaly detection: IsolationForest when scikit-learn is installed AND there
  is enough history; otherwise IQR / benchmark-ratio fallback (always works).
- Forecasting: simple deterministic linear-trend baseline; an LSTM is an
  optional drop-in when torch is available and a trained artifact exists.

Outputs are always ranges with confidence; never hard claims.
"""
import logging
from collections import defaultdict
from datetime import date

import numpy as np

try:
    from sklearn.ensemble import IsolationForest
    from sklearn.linear_model import LinearRegression

    HAVE_SKLEARN = True
except Exception:  # pragma: no cover
    HAVE_SKLEARN = False

from apps.expenses.models import (
    ElectricityBill,
    FarmExpense,
    FuelExpense,
    InputExpense,
    LabourExpense,
    RentalExpense,
    TransportExpense,
)
from apps.farms.models import Farm
from apps.ml_engine.registry import log_prediction, snapshot_ml_usage

logger = logging.getLogger("FarmGrid")

MIN_ROWS_FOR_ML = 8

# Per-acre monthly floors used by the rule fallback (Rs/acre/month).
CATEGORY_FLOOR_MONTHLY = {
    "fertilizer": 400,
    "seed": 200,
    "pesticide": 250,
    "labour": 700,
    "fuel": 300,
    "rental": 250,
    "electricity": 250,
}

# Map polymorphic expense tables into canonical category labels.
# ``InputExpense`` carries its own ``input_type`` (seed/fertilizer/pesticide),
# so it is bucketed per row instead of collapsing everything to "fertilizer".
_TYPED_TABLES = [
    (ElectricityBill, "electricity"),
    (FuelExpense, "fuel"),
    (InputExpense, lambda e: e.input_type if e.input_type in ("seed", "fertilizer", "pesticide") else "other"),
    (LabourExpense, "labour"),
    (TransportExpense, "transport"),
    (RentalExpense, "rental"),
]


class ExpenseAnalysisService:
    """Analyse a farm's expense history for anomalies + trend."""

    def __init__(self, farm: Farm):
        self.farm = farm

    # ------------------------------------------------------------------
    def _rows(self):
        """Monthly (year, month, category, amount) rows from raw expenses."""
        rows = []
        for expense in FarmExpense.objects.filter(farm=self.farm):
            rows.append(_to_row(expense))
        for model, category in _TYPED_TABLES:
            for expense in model.objects.filter(farm=self.farm):
                rows.append(_to_row(expense, category))
        rows.sort(key=lambda r: (r["year"], r["month"]))
        return rows

    # ------------------------------------------------------------------
    def _ml_anomalies(self, rows):
        """IsolationForest anomaly labels over (period, per-acre spend)."""
        area_ha = float(self.farm.total_hectares or 1.0)
        points = np.array([[r["year"] + ((r["month"] - 1) / 12), r["amount"] / max(area_ha, 0.01)] for r in rows])
        if len(points) < MIN_ROWS_FOR_ML:
            return None
        model = IsolationForest(contamination=0.15, random_state=42)
        preds = model.fit_predict(points)  # -1 = anomaly
        return [bool(p == -1) for p in preds]

    # ------------------------------------------------------------------
    def _rule_flags(self, rows):
        """IQR-based fallback flag per category. Never returns None."""
        by_category = defaultdict(list)
        for r in rows:
            by_category[r["category"]].append(r["amount"])
        flags = []
        for r in rows:
            totals = by_category.get(r["category"], [])
            if not totals:
                flags.append(False)
                continue
            if len(totals) <= 2:
                floor = CATEGORY_FLOOR_MONTHLY.get(r["category"], 0) or 0
                area_ha = float(getattr(self.farm, "total_hectares", 0) or 1.0)
                flags.append(bool(floor and area_ha and r["amount"] > floor * 2.471 * area_ha * 3))
                continue
            q1, q3 = np.percentile(totals, [25, 75])
            iqr = max(q3 - q1, 1.0)
            upper = q3 + 1.5 * iqr
            flags.append(bool(r["amount"] > upper))
        return flags

    # ------------------------------------------------------------------
    def run_analysis(self, user=None):
        rows = self._rows()
        if not rows:
            output = {
                "farm_id": str(self.farm.id),
                "data_completeness": 0.0,
                "anomalies": [],
                "models_used": [],
                "note": "No expense records yet.",
            }
            log_prediction(user=user, farm=self.farm, registry_key="anomaly_detector", input_type="expense_records", output_snapshot=output, status="success")
            return output

        ml_flags = self._ml_anomalies(rows) if HAVE_SKLEARN else None
        rule_flags = self._rule_flags(rows)
        used_ml = ml_flags is not None
        models_used = ["isolation_forest"] if used_ml else ["iqr_baseline"]

        anomalies = []
        for idx, row in enumerate(rows):
            flag = ml_flags[idx] if used_ml else rule_flags[idx]
            if not flag:
                continue
            amount = float(row["amount"])
            excess = max(0, int(amount - (float(np.percentile([r["amount"] for r in rows if r["category"] == row["category"]], 50) or 0))))
            severity = "high" if used_ml else "medium"
            anomalies.append(
                {
                    "period": f"{row['year']}-{row['month']:02d}",
                    "category": row["category"],
                    "amount": round(amount, 2),
                    "excess_amount": excess,
                    "severity": severity,
                    "label": f"{row['category']} spend in {row['year']}-{row['month']:02d}",
                    "explanation": (
                        "This expense is an outlier compared with the farm's own history (isolation forest). "
                        "It may be a legitimate one-time purchase - confirm before acting."
                        if used_ml
                        else "This expense is above the IQR alert threshold for its category. Confirm before acting."
                    ),
                    "confidence": "medium" if used_ml else "low",
                    "model": "isolation_forest" if used_ml else "iqr_baseline",
                    "needs_user_confirmation": True,
                }
            )

        output = {
            "farm_id": str(self.farm.id),
            "rows_analysed": len(rows),
            "anomalies": anomalies,
            "models_used": models_used,
            "data_completeness": min(1.0, len(rows) / 48),
            "note": "Estimates only - anomalies require confirmation; outliers are not errors by default.",
        }
        log_prediction(
            user=user,
            farm=self.farm,
            registry_key="anomaly_detector",
            input_type="expense_records",
            input_snapshot={"rows": len(rows), "categories": sorted({r["category"] for r in rows})},
            output_snapshot=output,
            confidence="medium" if used_ml else "low",
        )
        return output

    # ------------------------------------------------------------------
    def forecast(self, horizon_months=12, user=None):
        """Baseline linear-trend forecast of total monthly expense."""
        rows = self._rows()
        if not rows:
            return {
                "increasing_trend": None,
                "message": "Not enough data for a forecast.",
                "models_used": [],
                "confidence": "low",
            }
        monthly = {}
        for r in rows:
            key = (r["year"], r["month"])
            monthly[key] = monthly.get(key, 0.0) + r["amount"]
        keys = sorted(monthly)
        xs = np.array([[key[0] + (key[1] - 1) / 12] for key in keys])
        ys = np.array([monthly[key] for key in keys])
        if len(xs) < 2:
            return {
                "increasing_trend": None,
                "message": "Not enough history for a trend. Keep recording monthly expenses.",
                "models_used": ["linear_trend_baseline"],
                "confidence": "low",
            }
        model = LinearRegression()
        model.fit(xs, ys)
        slope = float(model.coef_[0])
        last = xs[-1][0]
        future_xs = np.array([[last + (i + 1) / 12] for i in range(horizon_months)])
        future_ys = [max(0.0, float(v)) for v in model.predict(future_xs)]
        increasing = bool(slope > 0 and (future_ys[-1] > 0 and future_ys[-1] > float(np.mean(ys)) * 0.5))

        output = {
            "increasing_trend": increasing,
            "monthly_projection_inr": [round(v, 2) for v in future_ys],
            "models_used": ["linear_trend_baseline"],
            "confidence": "low",
            "message": (
                "Reported expenses trend upward; costs may keep rising at the observed rate."
                if increasing
                else "Reported expenses are flat or trending down; no cost surge projected."
            ),
            "note": "Deterministic baseline estimate only; an LSTM can replace it once more history is available.",
        }
        log_prediction(user=user, farm=self.farm, registry_key="forecast_baseline", input_type="expense_records", input_snapshot={"rows": len(rows)}, output_snapshot=output, confidence="low")
        return output


def _to_row(expense, category=None):
    label = ""
    if callable(category):
        label = category(expense) or "other"
    elif getattr(expense, "category_id", None):
        try:
            label = expense.category.name if category is None else category
        except Exception:
            label = category or "other"
    else:
        label = category or "other"
    occurred_on = getattr(expense, "occurred_on", None) or date.today()
    return {
        "year": occurred_on.year,
        "month": occurred_on.month,
        "category": label,
        "amount": float(getattr(expense, "amount", 0) or 0),
    }
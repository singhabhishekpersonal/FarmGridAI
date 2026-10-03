"""Crop cost estimation service.

Uses benchmark first (rule-based); results are always ranges with
assumptions and confidence.
"""
from apps.crops.models import Crop, CropCostBenchmark, CropInputEstimate, FarmCrop
from apps.core.estimates import EstimateRange


class CropCostEstimationService:
    """Estimate per-input and total cultivation cost ranges for a FarmCrop."""

    def __init__(self, benchmark_queryset=None):
        # Seeded benchmark rows are labelled synthetic and ship with
        # is_verified=False. Filtering them out made every crop estimate zero,
        # so include them but never let them raise confidence above "low".
        self.benchmark_qs = (
            benchmark_queryset
            if benchmark_queryset is not None
            else CropCostBenchmark.objects.all()
        )

    def benchmarks_for(self, farm_crop, state=""):
        qs = self.benchmark_qs.filter(crop=farm_crop.crop)
        if state:
            specific = qs.filter(state=state)
            if specific.exists():
                qs = specific
        return list(qs)

    def estimate_farm_crop(self, farm_crop):
        """Return a dict of EstimateRange-like values for each input type."""
        area_acres = farm_crop.area_acres
        if area_acres <= 0:
            return {"error": "Area must be positive."}

        benchmarks = self.benchmarks_for(farm_crop)
        by_type = {}
        for b in benchmarks:
            by_type.setdefault(b.input_type, []).append(b)

        verified = [b for b in benchmarks if b.is_verified]
        # Only locally verified benchmarks justify "medium"; unverified seed
        # data is a starting range the farmer must confirm.
        confidence = "medium" if verified else ("low" if benchmarks else "low")

        results = {}
        total = EstimateRange(0, 0, 0, confidence=confidence, data_completeness=0.6)
        assumptions = [f"Based on {len(benchmarks)} benchmark records for {farm_crop.crop.name}."]
        if benchmarks and not verified:
            assumptions.append(
                f"All {len(benchmarks)} of these are unverified reference benchmarks, not "
                "confirmed local prices. Replace them with your own rates before budgeting."
            )
        if not benchmarks:
            assumptions.append("No benchmark records found; estimate reflects generic defaults.")
        total.assumptions = assumptions

        for input_type, records in by_type.items():
            minima = [float(r.min_cost) for r in records]
            maxima = [float(r.max_cost) for r in records]
            expected = [float(r.expected_cost) for r in records]
            total_min = min(minima)
            total_max = max(maxima)
            avg = sum(expected) / len(expected)
            # conversion: benchmark.u nit per_hectare -> per_acre
            factor = 1.0
            for r in records:
                if r.unit == "per_hectare":
                    factor = 1.0 / 2.471053814671653
                    break
            low = total_min * factor * area_acres
            high = total_max * factor * area_acres
            mid = avg * factor * area_acres
            results[input_type] = {
                "minimum": round(low, 2),
                "maximum": round(high, 2),
                "expected": round(mid, 2),
                "per_acre_expected": round(avg * factor, 2),
                "confidence": ("medium" if all(r.is_verified for r in records) else confidence),
            }
            total.minimum += low
            total.maximum += high
            total.expected += mid

        CropInputEstimate.objects.filter(farm_crop=farm_crop).delete()
        for input_type, r in results.items():
            CropInputEstimate.objects.create(
                farm_crop=farm_crop,
                input_type=input_type,
                min_cost=r["minimum"],
                max_cost=r["maximum"],
                expected_cost=r["expected"],
                per_acre=r["per_acre_expected"],
                confidence=r["confidence"],
                assumptions_json=assumptions,
            )

        return {
            "farm_crop_id": str(farm_crop.id),
            "crop": farm_crop.crop.name,
            "area_acres": round(area_acres, 3),
            "season": farm_crop.season,
            "year": farm_crop.year,
            "by_input": results,
            "total": {
                "minimum": round(total.minimum, 2),
                "maximum": round(total.maximum, 2),
                "expected": round(total.expected, 2),
                "estimate_type": "range",
                "currency": "INR",
                "confidence": confidence,
                "assumptions": assumptions,
                "limitations": ["Benchmark ranges only; actual costs vary by region, input prices and practices.", "Requires farmer confirmation."],
                "data_completeness": 0.6,
                "requires_farmer_confirmation": True,
                "requires_official_verification": False,
            },
        }


def estimate_farm_crops(farm_id, year=None):
    """Run estimation for all FarmCrops in a farm; return aggregate summary."""
    farm_crops = FarmCrop.objects.filter(farm_id=farm_id)
    service = CropCostEstimationService()
    rows = []
    totals = {"minimum": 0, "maximum": 0, "expected": 0}
    for fc in farm_crops:
        if year and fc.year != year:
            continue
        result = service.estimate_farm_crop(fc)
        rows.append(result)
        if "total" not in result:
            continue
        totals["minimum"] += result["total"]["minimum"]
        totals["maximum"] += result["total"]["maximum"]
        totals["expected"] += result["total"]["expected"]
    return {"crop_estimates": rows, "totals": totals, "farm_id": str(farm_id)}
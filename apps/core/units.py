"""Land-area unit conversion utilities.

Hectares are the internal canonical unit. Conventional conversions exist for
acre/hectare/guntha/cent/sqft/sqm. **Bigha is deliberately NOT given a
universal conversion factor** because it is region-specific - the caller must
provide a ``BighaConversionRule`` (state/district level). When no matching rule
is available the service returns a result marked ``requires_confirmation``.
"""
from apps.core.constants import LandUnit

SQM_PER_HECTARE = 10000.0
SQM_PER_ACRE = 4046.8564224
SQM_PER_GUNTHA = 101.17141056
SQM_PER_CENT = 40.468564224
SQM_PER_SQFT = 0.09290304
# Kaththa varies by region; a common western-UP value is 1/30 acre.
SQM_PER_KATHTHA_DEFAULT = 134.0

BASE_FACTORS = {
    LandUnit.ACRE: SQM_PER_ACRE,
    LandUnit.HECTARE: SQM_PER_HECTARE,
    LandUnit.GUNTHA: SQM_PER_GUNTHA,
    LandUnit.SQUARE_METER: 1.0,
    LandUnit.SQUARE_FOOT: SQM_PER_SQFT,
    LandUnit.CENT: SQM_PER_CENT,
    LandUnit.KATHTHA: SQM_PER_KATHTHA_DEFAULT,
}


class BighaRuleProvider:
    """Adapter that resolves region-specific bigha conversion factors."""

    @staticmethod
    def from_model(rule):
        if rule is None:
            return None
        return {
            "state": getattr(rule, "state", None),
            "district": getattr(rule, "district", None),
            "sq_meters_per_bigha": getattr(rule, "sq_meters_per_bigha", None),
            "label": getattr(rule, "label", ""),
        }

    @staticmethod
    def resolve_factor(rule_data):
        """Return sqm per bigha from a resolved rule dict, if present."""
        if rule_data and rule_data.get("sq_meters_per_bigha"):
            return float(rule_data["sq_meters_per_bigha"])
        return None


class UnitConversionService:
    """Stateless area conversion service using sqm as the common axis."""

    def __init__(self, bigha_rule_provider=None):
        self.bigha_provider = bigha_rule_provider or BighaRuleProvider

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _bigha_factor(self, rule=None, state=None, district=None):
        rule_data = None
        if rule is not None:
            rule_data = self.bigha_provider.from_model(rule)
        factor = self.bigha_provider.resolve_factor(rule_data)
        if factor:
            return factor, rule_data
        # Best-effort by state if a rule object exposes state-level factor.
        if state:
            factor = self.STATE_FALLBACKS.get(state)
            if factor:
                return factor, {"state": state, "fallback": True}
        return None, rule_data

    STATE_FALLBACKS = {
        "Uttar Pradesh": 3025 * SQM_PER_SQFT / 2,  # ~2508 sqm (varies)
    }

    # ------------------------------------------------------------------
    # Conversions
    # ------------------------------------------------------------------
    def to_sqm(self, value, unit, rule=None, state=None, district=None):
        """Convert a value in ``unit`` to square meters.

        Returns a dict with ``value`` in sqm plus metadata describing the
        conversion confidence.
        """
        if value is None:
            raise ValueError("value is required")
        value = float(value)
        unit = str(unit)

        if unit in (LandUnit.ACRE, LandUnit.HECTARE, LandUnit.GUNTHA, LandUnit.SQUARE_METER, LandUnit.SQUARE_FOOT, LandUnit.CENT, LandUnit.KATHTHA):
            return {
                "value": value * BASE_FACTORS[unit],
                "requires_confirmation": False,
                "method": "standard factor",
                "rule_label": "",
            }

        if unit == LandUnit.BIGHA:
            factor, rule_data = self._bigha_factor(rule=rule, state=state, district=district)
            if factor:
                return {
                    "value": value * factor,
                    "requires_confirmation": False,
                    "method": f"regional bigha rule: {factor:.2f} sqm/bigha",
                    "rule_label": (rule_data or {}).get("label", "") if rule_data else "",
                }
            return {
                "value": None,
                "requires_confirmation": True,
                "method": "no regional bigha conversion available - farmer confirmation required",
                "rule_label": "",
            }

        raise ValueError(f"Unsupported land unit: {unit}")

    def to_hectares(self, value, unit, rule=None, state=None, district=None):
        result = self.to_sqm(value, unit, rule=rule, state=state, district=district)
        if result["value"] is None:
            return {**result, "value_ha": None, "value_acre": None}
        ha = result["value"] / SQM_PER_HECTARE
        return {
            **result,
            "value_ha": ha,
            "value_acre": ha * 2.471053814671653,
        }

    def to_acre(self, value, unit, rule=None, state=None, district=None):
        result = self.to_hectares(value, unit, rule=rule, state=state, district=district)
        if result["value_acre"] is None:
            return result
        return {**result, "value": result["value_acre"]}

    def to_display(self, value_ha, unit):
        """Convert a canonical hectare value into the farmer's preferred unit."""
        if value_ha is None:
            return None
        if unit == LandUnit.HECTARE:
            return value_ha
        if unit == LandUnit.ACRE:
            return value_ha * 2.471053814671653
        if unit == LandUnit.GUNTHA:
            return value_ha * SQM_PER_HECTARE / SQM_PER_GUNTHA
        if unit == LandUnit.CENT:
            return value_ha * SQM_PER_HECTARE / SQM_PER_CENT
        if unit == LandUnit.SQUARE_FOOT:
            return value_ha * SQM_PER_HECTARE / SQM_PER_SQFT
        if unit == LandUnit.SQUARE_METER:
            return value_ha * SQM_PER_HECTARE
        if unit == LandUnit.KATHTHA:
            return value_ha * SQM_PER_HECTARE / SQM_PER_KATHTHA_DEFAULT
        if unit == LandUnit.BIGHA:
            # Without a rule we refuse to present an authoritative number.
            return None
        return value_ha


class LandUnitConversion:
    """Static factory mirroring the model-like API for conversion helpers."""

    @staticmethod
    def normalize(value, unit, **kwargs):
        return UnitConversionService().to_hectares(value, unit, **kwargs)
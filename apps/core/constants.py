"""Project-wide enums and constants.

Domain-specific enum constants live here so they can be shared across
multiple apps without circular imports.
"""
from django.db import models

CURRENCY_INR = "INR"


class ConfidenceLevel(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"


class DataSource(models.TextChoices):
    SYNTHETIC = "synthetic", "Synthetic"
    BENCHMARK = "benchmark", "Benchmark"
    OFFICIAL = "official", "Official"
    USER_ENTERED = "user_entered", "User entered"
    MODEL = "model", "Model"
    RULE = "rule", "Rule"
    SCRAPED = "scraped", "Scraped"


class StatusState(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    ARCHIVED = "archived", "Archived"


class LandUnit(models.TextChoices):
    ACRE = "acre", "Acre"
    HECTARE = "hectare", "Hectare"
    BIGHA = "bigha", "Bigha"
    GUNTHA = "guntha", "Guntha"
    SQUARE_METER = "sqm", "Square meter"
    SQUARE_FOOT = "sqft", "Square foot"
    KATHTHA = "kaththa", "Kaththa (local)"
    CENT = "cent", "Cent"


class IrrigationType(models.TextChoices):
    IRRGATED = "irrigated", "Irrigated"
    RAINFED = "rainfed", "Rain-fed"
    # Partial irrigation is common (a partially-bored plot, a canal that runs
    # only part of the season) and is materially different from fully rain-fed,
    # so it is a real state rather than being rounded to one or the other.
    PARTIALLY_IRRIGATED = "partially_irrigated", "Partially irrigated"


# Longest IrrigationType value, so the CharFields that store it cannot silently
# truncate. "partially_irrigated" is the binding constraint at 19 characters.
IRRIGATION_TYPE_MAX_LENGTH = max(len(value) for value, _ in IrrigationType.choices)


class IrrigationSource(models.TextChoices):
    CANAL = "canal", "Canal"
    WELL = "well", "Well"
    BORE_WELL = "borewell", "Bore well"
    POND = "pond", "Pond"
    RIVER = "river", "River"
    TANK = "tank", "Tank"
    DRIP = "drip", "Drip"
    SPRINKLER = "sprinkler", "Sprinkler"
    OTHER = "other", "Other"


class OwnershipStatus(models.TextChoices):
    OWNED = "owned", "Owned"
    LEASED = "leased", "Leased"
    SHARED = "shared", "Shared"
    GOVERNMENT = "government", "Government lease"


class DemandType(models.TextChoices):
    ESTIMATE = "estimate", "Estimate"


class EstimateKind(models.TextChoices):
    RANGE = "range", "Range"
    POINT = "point", "Point"


EQUIPMENT_CLASS_CHOICES = [
    ("tractor", "Tractor"),
    ("power_tiller", "Power tiller"),
    ("water_pump", "Water pump"),
    ("diesel_pump", "Diesel pump"),
    ("solar_pump", "Solar pump"),
    ("rotavator", "Rotavator"),
    ("cultivator", "Cultivator"),
    ("plough", "Plough"),
    ("seed_drill", "Seed drill"),
    ("sprayer", "Sprayer"),
    ("thresher", "Thresher"),
    ("harvester", "Harvester"),
    ("combine_harvester", "Combine harvester"),
    ("trailer", "Trailer"),
    ("irrigation_pipe", "Irrigation pipes"),
    ("drip_irrigation", "Drip irrigation"),
    ("sprinkler_irrigation", "Sprinkler irrigation"),
    ("unknown", "Unknown"),
]

EQUIPMENT_CLASS_NAMES = [code for code, _label in EQUIPMENT_CLASS_CHOICES]
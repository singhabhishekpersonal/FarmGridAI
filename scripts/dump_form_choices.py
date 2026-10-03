"""Print the authoritative choice sets and writable fields for the web forms."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import django  # noqa: E402

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "FarmGridAI.settings.development")
django.setup()

from apps.farms.models import LandParcel  # noqa: E402
from apps.equipment.models import FarmerEquipment  # noqa: E402
from apps.accounts.models import FarmerProfile  # noqa: E402

TARGETS = [
    ("LandParcel.unit", LandParcel._meta.get_field("unit")),
    ("LandParcel.ownership", LandParcel._meta.get_field("ownership")),
    ("LandParcel.irrigation_source", LandParcel._meta.get_field("irrigation_source")),
    ("FarmerProfile.land_unit", FarmerProfile._meta.get_field("land_unit")),
    ("FarmerProfile.land_ownership", FarmerProfile._meta.get_field("land_ownership")),
    ("FarmerProfile.irrigation_source", FarmerProfile._meta.get_field("irrigation_source")),
    ("FarmerEquipment.condition", FarmerEquipment._meta.get_field("condition")),
    ("FarmerEquipment.fuel_type", FarmerEquipment._meta.get_field("fuel_type")),
]

for label, field in TARGETS:
    print("===", label)
    for value, text in field.choices:
        print("    %-16r %s" % (value, text))
    print()

print("=== FarmerEquipment writable (non-read-only) field names")
from apps.equipment.serializers import FarmerEquipmentSerializer  # noqa: E402

s = FarmerEquipmentSerializer()
print("   ", sorted(set(s.fields) - set(s.Meta.read_only_fields)))

print("=== LandParcel writable field names")
from apps.farms.serializers import LandParcelSerializer  # noqa: E402

s = LandParcelSerializer()
print("   ", sorted(set(s.fields) - set(s.Meta.read_only_fields)))

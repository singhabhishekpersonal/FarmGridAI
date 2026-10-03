import json
from datetime import date
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.chatbot.models import KnowledgeArticle, KnowledgeIntent
from apps.crops.models import Crop, CropCostBenchmark
from apps.energy.models import DieselPriceBenchmark, EnergyTariffBenchmark, SolarCostBenchmark
from apps.equipment.models import EquipmentCatalog, EquipmentCategory
from apps.expenses.models import ExpenseCategory
from apps.farms.models import BighaConversionRule
from apps.subsidies.models import SchemeDocumentRequirement, SubsidyEligibilityRule, SubsidyScheme

SEED_DIR = Path(settings.BASE_DIR) / "data" / "seed"

EXPENSE_CATEGORIES = [
    ("electricity", "Electricity bill"),
    ("fuel", "Fuel / diesel"),
    ("input", "Fertiliser, seed & chemicals"),
    ("labour", "Labour wages"),
    ("transport", "Transport & freight"),
    ("rental", "Equipment rental"),
]

IMPLEMENT_KEYWORDS = {
    "seed_drill": ["seed drill", "seed cum fertilizer", "seed-cum-fertilizer", "zero till", "roto seed", "rota seed"],
    "plough": ["plough", "plow", "mouldboard", "mb plough", "disc plough", "chisel", "reversible", "mulcher"],
    "thresher": ["thresher", "thresh"],
    "harvester": ["harvester", "reaper", "combine"],
    "rotavator": ["rotavator", "rotovator", "rotary"],
    "cultivator": ["cultivator", "tiller"],
    "sprayer": ["sprayer", "spray"],
    "trailer": ["trailer", "trolley"],
    "power_tiller": ["power tiller", "walk behind"],
    "water_pump": ["pump", "submersible"],
}


def _infer_category(model_lower, category_key):
    if category_key == "tractor":
        return "tractor"
    for code, keywords in IMPLEMENT_KEYWORDS.items():
        if any(k in model_lower for k in keywords):
            return code
    return "unknown"


class Command(BaseCommand):
    help = "Load curated/benchmark seed data and the scraped tractor catalog. Idempotent."

    def handle(self, *args, **options):
        self._seed_categories()
        self._seed_expense_categories()
        self._seed_catalog()
        self._seed_crops()
        self._seed_bigha_rules()
        self._seed_subsidies()
        self._seed_knowledge_base()
        self._seed_energy()

    # ------------------------------------------------------------------
    def _load(self, filename):
        with open(SEED_DIR / filename, encoding="utf-8") as fh:
            return json.load(fh)

    def _seed_categories(self):
        for row in self._load("equipment_categories.json"):
            _, created = EquipmentCategory.objects.update_or_create(
                code=row["code"],
                defaults=row,
            )
            self.stdout.write(f"  {'created' if created else 'kept'} category {row['code']}")

    def _seed_expense_categories(self):
        """ExpenseCategory rows the document-upload picker files bills against.

        The `code` values are the contract: the receipt upload control posts a
        code, so these strings must not be renamed without updating
        templates/expenses/expense_entry.html.
        """
        for code, name in EXPENSE_CATEGORIES:
            _, created = ExpenseCategory.objects.update_or_create(
                code=code,
                defaults={"name": name, "is_custom": False},
            )
            self.stdout.write(f"  {'created' if created else 'kept'} expense category {code}")

    def _seed_catalog(self):
        rows = self._load("equipment_catalog.json")
        created_count = 0
        missing_categories = set()
        for row in rows:
            code = _infer_category(row["model"].lower(), row["category"])
            try:
                category = EquipmentCategory.objects.get(code=code)
            except EquipmentCategory.DoesNotExist:
                missing_categories.add(code)
                continue
            _, created = EquipmentCatalog.objects.update_or_create(
                category=category,
                brand=row["brand"],
                model=row["model"],
                defaults={
                    "slug": "",
                    "image_url": row.get("image_url", ""),
                    "source_url": row.get("source_url", ""),
                    "source": "scraped",
                    "is_verified": False,
                    "is_synthetic_benchmark": False,
                    "fuel_type": "diesel" if code == "tractor" else "",
                },
            )
            created_count += int(created)
        self.stdout.write(f"  catalog entries '{created_count}' created from {len(rows)} raw rows")
        if missing_categories:
            self.stdout.write(self.style.WARNING(f"    skipped categories missing: {sorted(missing_categories)}"))

    def _seed_crops(self):
        for row in self._load("crop_cost_benchmarks.json"):
            crop, created = Crop.objects.update_or_create(
                slug=row["slug"],
                defaults={
                    "name": row["name"],
                    "local_name": row.get("local_name", ""),
                    "category": row["category"],
                    "primary_season": row["primary_season"],
                    "typical_days_to_harvest": row.get("typical_days_to_harvest"),
                    "typical_yield_qtl_per_acre": row.get("typical_yield_qtl_per_acre"),
                    "is_synthetic_benchmark": row.get("is_synthetic_benchmark", True),
                },
            )
            for b in row["benchmarks"]:
                CropCostBenchmark.objects.update_or_create(
                    crop=crop,
                    input_type=b["input_type"],
                    unit=b["unit"],
                    state=b.get("state", ""),
                    defaults={
                        "min_cost": b["min_cost"],
                        "max_cost": b["max_cost"],
                        "expected_cost": b["expected_cost"],
                        "source": "benchmark",
                        "is_verified": False,
                        "notes": row.get("note", ""),
                    },
                )
            self.stdout.write(f"  {'created' if created else 'kept'} crop {row['name']}")

    def _seed_bigha_rules(self):
        for row in self._load("bigha_rules.json"):
            _, created = BighaConversionRule.objects.update_or_create(
                state=row["state"],
                district=row.get("district", ""),
                defaults={
                    "label": row["label"],
                    "sq_meters_per_bigha": row["sq_meters_per_bigha"],
                    "source": row.get("source", "benchmark"),
                    "is_verified": row.get("is_verified", False),
                    "notes": row.get("notes", ""),
                },
            )
            self.stdout.write(f"  {'created' if created else 'kept'} bigha rule for {row['state']}")

    def _seed_subsidies(self):
        for row in self._load("subsidy_schemes.json"):
            rules = row.pop("rules")
            documents = row.pop("documents")
            row.setdefault("effective_from", None)
            scheme, created = SubsidyScheme.objects.update_or_create(slug=row["slug"], defaults=row)
            for i, rule in enumerate(rules):
                _, _ = SubsidyEligibilityRule.objects.update_or_create(
                    scheme=scheme,
                    sequence=rule["sequence"],
                    defaults={"field": rule["field"], "operator": rule["operator"], "value": rule.get("value", {}), "reason": rule.get("reason", "")},
                )
            for doc in documents:
                _, _ = SchemeDocumentRequirement.objects.update_or_create(
                    scheme=scheme,
                    document_name=doc["document_name"],
                    defaults={"required": doc.get("required", True), "notes": doc.get("notes", "")},
                )
            self.stdout.write(f"  {'created' if created else 'kept'} scheme {row['name']}")

    def _seed_knowledge_base(self):
        kb = self._load("knowledge_base.json")
        for intent in kb["intents"]:
            _, created = KnowledgeIntent.objects.update_or_create(
                key=intent["key"],
                defaults={
                    "patterns": intent["patterns"],
                    "response": intent["response"],
                    "suggestions": intent.get("suggestions", []),
                    "priority": intent.get("priority", 50),
                },
            )
            self.stdout.write(f"  {'created' if created else 'kept'} intent {intent['key']}")
        for article in kb["articles"]:
            _, created = KnowledgeArticle.objects.update_or_create(
                slug=article["slug"],
                defaults={
                    "topic": article["topic"],
                    "title": article["title"],
                    "content": article["content"],
                    "tags": article["tags"],
                    "source": article.get("source", "curated"),
                    "is_active": article.get("is_active", True),
                },
            )
            self.stdout.write(f"  {'created' if created else 'kept'} article {article['slug']}")

    def _seed_energy(self):
        data = self._load("energy_benchmarks.json")
        observed = date(2025, 1, 1)
        for t in data["tariffs"]:
            _, created = EnergyTariffBenchmark.objects.update_or_create(
                state=t["state"],
                provider=t.get("provider", ""),
                slab_name=t.get("slab_name", ""),
                defaults={"per_kwh_inr": t["per_kwh_inr"], "source": t.get("source", "benchmark"), "is_verified": t.get("is_verified", False), "notes": t.get("notes", "")},
            )
            self.stdout.write(f"  {'created' if created else 'kept'} tariff {t['state']}")

        for d in data["diesel"]:
            _, created = DieselPriceBenchmark.objects.update_or_create(
                state=d.get("state", ""),
                district=d.get("district", ""),
                observed_on=observed,
                defaults={"price_per_litre": d["price_per_litre"], "source": d.get("source", "benchmark"), "is_verified": d.get("is_verified", False)},
            )
            self.stdout.write(f"  {'created' if created else 'kept'} diesel benchmark")

        for s in data["solar"]:
            _, created = SolarCostBenchmark.objects.update_or_create(
                state=s.get("state", ""),
                defaults={"min_inr_per_kw": s["min_inr_per_kw"], "max_inr_per_kw": s["max_inr_per_kw"], "source": s.get("source", "benchmark"), "is_verified": s.get("is_verified", False)},
            )
            self.stdout.write(f"  {'created' if created else 'kept'} solar benchmark {s.get('state', 'All states')}")
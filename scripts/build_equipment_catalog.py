"""Build a clean equipment catalog seed file from the scraped tractorgyan dataset.

Reads ``open-tractor/data/tractor_dataset.json`` (huge list of image records with
brand/model) and emits a deduplicated, category-tagged JSON for import into the
EquirementCatalog model. Prices are intentionally NOT invented here.

This is a build-time helper, not a runtime dependency.
"""
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # project root (FarmGridAI)
OPEN_TRACTOR_DATA = ROOT.parent / "open-tractor" / "data" / "tractor_dataset.json"
OUT = ROOT / "data" / "seed" / "equipment_catalog.json"

# Implements (non-tractor attachments) mentioned in captions/models.
IMPLEMENT_MARKERS = [
    "plough", "plow", "thresher", "seed drill", "seed-cum-fertilizer", "reaper",
    "hole digger", "tipper", "trailer", "rotavator", "leveller", "mulcher",
    "transplanter", "sprayer", "harrow", "ridger", "planter",
]

BAD_BRANDS = {"Brands", "Finance-icon", "-icon", "Icon", "logo", "Popular"}


def classify(model_lower, caption_lower):
    if any(m in model_lower or m in caption_lower for m in IMPLEMENT_MARKERS):
        return "implement"
    # Image-only categories (logo/menu etc) are dropped by the caller.
    return "tractor"


def clean_model(model, caption, alt):
    text = model.strip()
    if not text:
        for candidate in (alt, caption):
            if candidate and "tractor" in candidate.lower():
                # strip trailing "tractor" token for readability
                text = re.sub(r"\s*[Tt]ractor\s*$", "", candidate).strip()
                break
    return re.sub(r"\s+", " ", text).strip()[:120]


def main():
    records = json.load(open(OPEN_TRACTOR_DATA, encoding="utf-8"))
    seen = set()
    rows = []
    dropped = Counter()

    for rec in records:
        brand = (rec.get("brand") or "").strip()
        model = (rec.get("model") or "").strip()
        caption = rec.get("caption") or ""
        alt = rec.get("alt") or ""
        if not brand or brand in BAD_BRANDS:
            dropped["no/bad brand"] += 1
            continue
        model = clean_model(model, caption, alt)
        if not model or model.lower() in ("tractor", "icon", "logo"):
            dropped["no model"] += 1
            continue
        key = (brand.lower(), model.lower())
        if key in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(key)
        img = (rec.get("img_url") or "").strip()
        img = img.split(" ")[0].strip()
        if not isinstance(img, str) or not img.startswith("http"):
            img = ""
        model_clean = re.sub(r"\s+[Tt]ractor\s*$", "", model).strip()
        rows.append(
            {
                "brand": brand,
                "model": model_clean,
                "category": classify(model.lower(), caption.lower()),
                "image_url": img if img.startswith("http") else "",
                "source_url": "https://tractorgyan.com" if img else "",
                "source": "scraped",
                "is_verified": False,
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    cats = Counter(r["category"] for r in rows)
    print(f"wrote {len(rows)} rows -> {OUT}")
    print("categories:", dict(cats))
    print("dropped:", dict(dropped))


if __name__ == "__main__":
    main()
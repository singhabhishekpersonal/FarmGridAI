"""Per-page background imagery.

Maps each page in ``apps.web.urls`` to a photograph from
``static/images/field/``. The template layer only needs the resulting URL, so no
page template has to be edited to change its picture.

Only genuinely agricultural imagery is used here: the two solar photographs go
to the energy/solar page, and the field photographs are distributed across the
rest. Pages whose job is dense data entry (forms, chat, the staff console) get a
plain surface instead of a photo, because a busy background behind form fields
and long tables costs legibility for no visual gain.
"""
from django.templatetags.static import static

# Pages that deliberately keep a plain, high-contrast surface. Adding a
# photograph behind these would put texture under form controls and tables.
PLAIN_PAGES = {
    "chat",
    "staff_data_ingestion",
    "farm_create",
    "land_parcel_form",
    "crop_form",
    "expense_entry",
    "profile",
    "equipment_upload",
}

# url_name -> static image path under static/images/field/
PAGE_IMAGES = {
    # Public / entry points
    "home": "field-01.jpg",
    "login": "field-09.jpg",
    "register": "field-12.jpg",
    # Farmer overview
    "dashboard": "field-03.jpg",
    # Farms
    "farm_detail": "field-05.jpg",
    "farm_crops": "field-06.jpg",
    # Money pages
    "expense_dashboard": "field-10.jpg",
    "equipment_list": "field-04.jpg",
    "equipment_detail": "field-02.jpg",
    "recommendations": "field-07.jpg",
    "subsidy_recommendations": "field-11.jpg",
    "machinery_decision": "field-08.jpg",
    # Energy - the only page that gets the solar photographs
    "solar_comparison": "solar-1.jpg",
}

# Secondary picture for the solar page, used for its side-by-side comparison
# panels rather than as a background.
SOLAR_SIDE_IMAGE = "field/solar-2.jpg"


def page_background(request):
    """Expose ``page_bg_image`` (URL or ``None``) to every rendered template."""
    match = getattr(request, "resolver_match", None)
    name = getattr(match, "url_name", None) if match else None
    image = PAGE_IMAGES.get(name)
    if not image or name in PLAIN_PAGES:
        return {"page_bg_image": None, "page_bg_class": ""}
    return {
        "page_bg_image": static(f"images/field/{image}"),
        # Both classes are required. base.css paints the photograph on
        # `body.has-page-bg`, and the per-page `has-page-bg-<name>` hook lets a
        # single page be re-tuned later. Emitting only the per-page class meant
        # the base selector never matched, so every background silently did
        # nothing and the whole site rendered flat.
        "page_bg_class": f"has-page-bg has-page-bg-{name}",
    }